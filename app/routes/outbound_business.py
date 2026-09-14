"""
出库业务完整API层
- 全类型出库业务（物资领用、维修出库、调拨出库、盘亏出库）
- 库存检查、禁止负库存、超量领用拦截
- 单据审核流程、事务控制、状态流转
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime

from app.database import get_db
from app.models import OutboundOrder, OutboundOrderItem, Material
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.outbound_service import OutboundService
from app.services.nc_sync_service import NcSyncService
from app.utils.business_tools import PermissionService, OperationLog
from app.utils.logger import logger

router = APIRouter()


# ============================================================================
# 数据模型定义
# ============================================================================

class OutboundOrderItemRequest(BaseModel):
    """出库单明细"""
    material_id: int = Field(..., description="物资ID")
    quantity: float = Field(..., gt=0, description="出库数量")
    location_id: Optional[int] = Field(None, description="出库库位ID")
    batch_no: Optional[str] = Field(None, description="批次号")


class CreateOutboundOrderRequest(BaseModel):
    """创建出库单请求"""
    outbound_type: str = Field(..., pattern="^(requisition|maintenance|transfer_out|inventory_loss)$", description="出库类型")
    material_id: Optional[int] = Field(None, description="物资ID（单物料兼容）")
    quantity: Optional[float] = Field(None, gt=0, description="出库数量（单物料兼容）")
    location_id: Optional[int] = Field(None, description="出库库位ID（单物料兼容）")
    items: Optional[List[OutboundOrderItemRequest]] = Field(None, description="物料明细列表（多物料）")
    request_id: Optional[int] = Field(None, description="关联申请单ID（领用出库需要）")
    destination_warehouse: Optional[str] = Field(None, description="目标库房（调拨出库需要）", max_length=50)
    recipient_name: Optional[str] = Field(None, description="领用人", max_length=50)
    recipient_department: Optional[str] = Field(None, description="领用部门", max_length=50)
    save_as_draft: Optional[bool] = Field(False, description="是否保存为草稿（默认直接提交审核）")
    reason: Optional[str] = Field(None, description="出库原因", max_length=200)
    emergency: Optional[bool] = Field(False, description="紧急领料（跳过审批直接出库，需事后审批）")

    class Config:
        schema_extra = {
            "example": {
                "outbound_type": "requisition",
                "items": [{"material_id": 1, "quantity": 50.0, "location_id": 1}],
                "reason": "维修设备"
            }
        }


class ApproveOutboundOrderRequest(BaseModel):
    """审核出库单请求"""
    action: str = Field(..., pattern="^(approve|reject)$", description="审核动作")
    comment: Optional[str] = Field(None, description="审核意见", max_length=500)

    class Config:
        schema_extra = {
            "example": {
                "action": "approve",
                "comment": "批准领用"
            }
        }


class CancelOutboundOrderRequest(BaseModel):
    """作废出库单请求"""
    reason: Optional[str] = Field(None, description="作废原因", max_length=200)

    class Config:
        schema_extra = {
            "example": {
                "reason": "领用申请已取消"
            }
        }


# ============================================================================
# 库存检查接口
# ============================================================================

@router.post("/inventory/check", summary="检查库存是否充足")
async def check_inventory(
    material_id: int = Query(..., description="物资ID"),
    required_quantity: float = Query(..., gt=0, description="需求数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    检查物资库存是否充足

    返回库存信息和可用库位
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inventory:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        is_available, available_qty, locations = OutboundService.check_inventory_available(
            material_id=material_id,
            required_quantity=required_quantity,
            db=db
        )

        return APIResponse(
            code=0,
            message="库存检查成功",
            data={
                "material_id": material_id,
                "required_quantity": required_quantity,
                "is_available": is_available,
                "available_quantity": available_qty,
                "locations": locations
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"库存检查异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"库存检查失败: {str(e)}")


@router.get("/fifo-recommend", summary="FIFO库位推荐")
async def fifo_recommend(
    material_id: int = Query(..., description="物料ID"),
    quantity: float = Query(..., gt=0, description="需求数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    根据 FIFO（先进先出）原则推荐出库库位。

    按最早入库时间排序，推荐从最早入库的库位优先出库。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        recommendations = OutboundService.get_fifo_recommendation(
            material_id=material_id,
            required_quantity=quantity,
            db=db
        )

        return APIResponse(
            code=0,
            message="获取FIFO推荐成功",
            data={
                "material_id": material_id,
                "required_quantity": quantity,
                "recommendations": recommendations,
                "total_available": sum(r["available_qty"] for r in recommendations),
                "total_suggested": sum(r["suggested_qty"] for r in recommendations),
                "sufficient": sum(r["available_qty"] for r in recommendations) >= quantity
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FIFO推荐异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"FIFO推荐失败: {str(e)}")


# ============================================================================
# 出库单创建和管理接口
# ============================================================================

@router.post("/orders", summary="创建出库单", status_code=status.HTTP_201_CREATED)
async def create_outbound_order(
    request: CreateOutboundOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    创建出库单

    支持多种类型：
    - requisition: 物资领用（需要审核）
    - maintenance: 维修出库（自动出库）
    - transfer_out: 调拨出库（自动出库）
    - inventory_loss: 盘亏出库（自动出库）

    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            logger.warning(f"无权限创建出库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg, outbound_order = OutboundService.create_outbound_order(
            outbound_type=request.outbound_type,
            material_id=request.material_id,
            quantity=request.quantity,
            location_id=request.location_id,
            operator_id=current_user.id,
            request_id=request.request_id,
            destination_warehouse=request.destination_warehouse,
            reason=request.reason,
            recipient_name=request.recipient_name,
            recipient_department=request.recipient_department,
            save_as_draft=request.save_as_draft,
            items=[item.dict() for item in request.items] if request.items else None,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(
            code=0,
            message="出库单创建成功",
            data=OutboundService.format_outbound_order(outbound_order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建出库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建出库单失败: {str(e)}")


@router.post("/create-and-submit", summary="创建并提交出库单", status_code=status.HTTP_201_CREATED)
async def create_and_submit_outbound_order(
    request: CreateOutboundOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            logger.warning(f"无权限创建并提交出库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        # 直接提交（不保存为草稿）
        request.save_as_draft = False
        success, msg, outbound_order = OutboundService.create_outbound_order(
            outbound_type=request.outbound_type,
            material_id=request.material_id,
            quantity=request.quantity,
            location_id=request.location_id,
            operator_id=current_user.id,
            request_id=request.request_id,
            destination_warehouse=request.destination_warehouse,
            reason=request.reason,
            recipient_name=request.recipient_name,
            recipient_department=request.recipient_department,
            save_as_draft=False,
            items=[item.dict() for item in request.items] if request.items else None,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(
            code=0,
            message="出库单创建并提交成功",
            data=OutboundService.format_outbound_order(outbound_order)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建并提交出库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建并提交出库单失败: {str(e)}")


@router.get("/orders", summary="获取出库单列表")
async def get_outbound_orders(
    outbound_type: Optional[str] = Query(None, pattern="^(requisition|maintenance|transfer_out|inventory_loss|direct_issue)$", description="出库类型"),
    status: Optional[str] = Query(None, description="单据状态"),
    material_id: Optional[int] = Query(None, description="物资ID"),
    order_no: Optional[str] = Query(None, description="出库单号"),
    keyword: Optional[str] = Query(None, description="关键词搜索（单号/物料名称/领用人）"),
    start_date: Optional[str] = Query(None, description="开始日期（YYYY-MM-DD）"),
    end_date: Optional[str] = Query(None, description="结束日期（YYYY-MM-DD）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取出库单列表（分页、多条件筛选）

    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        # 解析日期
        start_datetime = None
        end_datetime = None
        if start_date:
            try:
                start_datetime = datetime.fromisoformat(start_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="开始日期格式不正确")

        if end_date:
            try:
                end_datetime = datetime.fromisoformat(end_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="结束日期格式不正确")

        orders, total = OutboundService.get_outbound_order_list(
            outbound_type=outbound_type,
            status=status,
            material_id=material_id,
            order_no=order_no,
            keyword=keyword,
            start_date=start_datetime,
            end_date=end_datetime,
            page=page,
            page_size=page_size,
            db=db
        )

        return APIResponse(
            code=0,
            message="获取出库单列表成功",
            data={
                "list": orders,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取出库单列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取出库单列表失败: {str(e)}")


@router.get("/orders/{order_id}", summary="获取出库单详情")
async def get_outbound_order_detail(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取出库单详情"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="出库单不存在")

        return APIResponse(
            code=0,
            message="获取出库单详情成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取出库单详情异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取出库单详情失败: {str(e)}")


# ============================================================================
# 出库单审核接口（针对领用出库）
# ============================================================================

@router.post("/orders/{order_id}/approve", summary="批准出库单")
async def approve_outbound_order(
    order_id: int = Path(..., description="出库单ID"),
    request: ApproveOutboundOrderRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    批准出库单

    权限要求：department_leader（批准领用出库）
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:approve", db):
            logger.warning(f"无权限批准出库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = OutboundService.approve_outbound_order(
            outbound_order_id=order_id,
            approver_id=current_user.id,
            action=request.action,
            comment=request.comment,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=f"出库单{request.action}成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批准出库单异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批准失败: {str(e)}")


# ============================================================================
# 执行出库接口（已批准 → 实际出库）
# ============================================================================

@router.post("/orders/{order_id}/execute", summary="执行出库")
async def execute_outbound_order(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    执行出库（已批准的单据实际出库，扣除库存）

    权限要求：warehouse_manager
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            logger.warning(f"无权限执行出库 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = OutboundService.execute_outbound_order(
            outbound_order_id=order_id,
            operator_id=current_user.id,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()

        # 执行出库后自动同步到NC6.5
        if order.status == "out_of_stock":
            sync_success, sync_msg = NcSyncService.sync_outbound_to_nc(order_id, db)
            logger.info(f"自动同步出库单到NC6.5 | 出库单: {order.outbound_no} | 结果: {sync_success}")

        return APIResponse(
            code=0,
            message="出库单执行成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行出库异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行出库失败: {str(e)}")


# ============================================================================
# 出库单作废接口
# ============================================================================

@router.post("/orders/{order_id}/cancel", summary="作废出库单")
async def cancel_outbound_order(
    order_id: int = Path(..., description="出库单ID"),
    request: CancelOutboundOrderRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    作废出库单

    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:cancel", db):
            logger.warning(f"无权限作废出库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = OutboundService.cancel_outbound_order(
            outbound_order_id=order_id,
            cancelled_by=current_user.id,
            reason=request.reason,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message="出库单作废成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"作废出库单异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"作废出库单失败: {str(e)}")


@router.post("/orders/{order_id}/submit", summary="提交出库单审核")
async def submit_outbound_order(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    提交出库单审核（草稿 → 待审核）

    权限要求：warehouse_manager
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = OutboundService.submit_outbound_order(
            outbound_order_id=order_id,
            operator_id=current_user.id,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message="提交审核成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交出库单审核异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交审核失败: {str(e)}")




async def get_picking_orders(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    查询待拣货的出库单（status=approved 或 status=out_of_stock）。

    权限要求：outbound:create
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        query = db.query(OutboundOrder).filter(
            OutboundOrder.status.in_(["approved", "out_of_stock"])
        ).order_by(OutboundOrder.created_at.desc())

        total = query.count()
        orders = query.offset((page - 1) * page_size).limit(page_size).all()

        return APIResponse(
            code=0,
            message="获取待拣货出库单成功",
            data={
                "list": [OutboundService.format_outbound_order(o) for o in orders],
                "total": total,
                "page": page,
                "page_size": page_size
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取待拣货出库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取待拣货出库单失败: {str(e)}")


@router.post("/picking/{order_id}/verify-item", summary="扫码核验拣货项")
async def verify_picking_item(
    order_id: int = Path(..., description="出库单ID"),
    material_code: str = Query(..., description="扫码得到的物料编码"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    扫码核验单个拣货项。

    根据物料编码匹配出库单明细，返回匹配结果。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="出库单不存在")

        items = db.query(OutboundOrderItem).filter(
            OutboundOrderItem.order_id == order_id
        ).all()

        # 查找匹配的物料
        from app.models import Material
        material = db.query(Material).filter(Material.code == material_code).first()
        if not material:
            return APIResponse(code=1, message="未找到该编码对应的物料", data={"matched": False})

        matched_item = None
        for item in items:
            if item.material_id == material.id:
                matched_item = item
                break

        if not matched_item:
            return APIResponse(
                code=1, message="该物料不在当前出库单中", data={"matched": False}
            )

        return APIResponse(
            code=0,
            message="核验成功",
            data={
                "matched": True,
                "material_id": material.id,
                "material_code": material.code,
                "material_name": material.name,
                "expected_quantity": float(matched_item.quantity),
                "location_id": matched_item.location_id
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"扫码核验拣货项异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"核验失败: {str(e)}")


@router.post("/picking/{order_id}/complete", summary="完成拣货")
async def complete_picking(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    完成拣货。

    将出库单状态从 approved 更新为 out_of_stock（已出库）。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="出库单不存在")

        if order.status != "approved":
            raise HTTPException(status_code=400, detail=f"当前状态({order.status})不允许完成拣货，仅 approved 状态可完成拣货")

        success, msg = OutboundService.execute_outbound_order(
            outbound_order_id=order_id,
            operator_id=current_user.id,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        return APIResponse(
            code=0,
            message="拣货完成，出库成功",
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"完成拣货异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"完成拣货失败: {str(e)}")


# ============================================================================
# 拣货路径接口
# ============================================================================

@router.get("/picking/{order_id}/pick-path", summary="获取拣货路径")
async def get_pick_path(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    按最优顺序返回拣货项列表（按库位编码排序，同巷道连续拣货）。

    权限要求：outbound:create
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=403, detail="无权限执行此操作")

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="出库单不存在")

        pick_path = OutboundService.generate_pick_path(order_id, db)

        return APIResponse(
            code=0,
            message="获取拣货路径成功",
            data={
                "order_id": order_id,
                "outbound_no": order.outbound_no,
                "items": pick_path
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取拣货路径异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取拣货路径失败: {str(e)}")


# ============================================================================
# NC6.5同步接口
# ============================================================================

@router.post("/orders/{order_id}/sync-to-nc", summary="同步出库单到NC6.5")
async def sync_outbound_to_nc(
    order_id: int = Path(..., description="出库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    手动同步出库单到用友NC6.5系统

    权限要求：warehouse_manager或super_admin
    """
    try:
        # 权限检查
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = NcSyncService.sync_outbound_to_nc(order_id, db)

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=msg,
            data=OutboundService.format_outbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步出库单到NC6.5异常 | 出库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


# ============================================================================
# 库存操作历史记录接口
# ============================================================================

@router.get("/orders/history/list", summary="获取出库单操作历史")
async def get_outbound_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取出库单操作历史记录"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "outbound:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        logs, total = OperationLog.get_logs(
            action="create_outbound_order",
            module="outbound_management",
            page=page,
            page_size=page_size,
            db=db
        )

        return APIResponse(
            code=0,
            message="获取出库单操作历史成功",
            data={
                "list": logs,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取出库单操作历史异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取出库单操作历史失败: {str(e)}")


# ============================================================================
# 快捷领料接口
# ============================================================================

class QuickRequisitionItem(BaseModel):
    """快捷领料明细"""
    material_id: int = Field(..., description="物料ID")
    quantity: float = Field(..., gt=0, description="数量")
    location_id: Optional[int] = Field(None, description="库位ID")


class QuickRequisitionRequest(BaseModel):
    """快捷领料请求"""
    items: List[QuickRequisitionItem] = Field(..., description="领用物料列表（至少1项）")
    reason: Optional[str] = Field(None, max_length=200, description="领用原因")
    recipient_name: Optional[str] = Field(None, max_length=50, description="领用人")
    recipient_department: Optional[str] = Field(None, max_length=50, description="领用部门")


@router.get("/frequent-materials", summary="获取常用物料列表")
async def get_frequent_materials(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    统计当前用户领用频率最高的物料。
    按领用次数降序排列，返回含最近一次领用数量。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:view", db):
            raise HTTPException(status_code=403, detail="无权限执行此操作")

        from sqlalchemy import func

        items = (
            db.query(
                OutboundOrderItem.material_id,
                func.count(OutboundOrderItem.id).label("use_count"),
                func.sum(OutboundOrderItem.quantity).label("total_qty")
            )
            .join(OutboundOrder, OutboundOrder.id == OutboundOrderItem.order_id)
            .filter(
                OutboundOrder.outbound_type == "requisition",
                OutboundOrder.warehouse_manager_id == current_user.id
            )
            .group_by(OutboundOrderItem.material_id)
            .order_by(func.count(OutboundOrderItem.id).desc())
            .limit(limit)
            .all()
        )

        result = []
        for item in items:
            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if mat:
                last_order = (
                    db.query(OutboundOrderItem.quantity)
                    .filter(OutboundOrderItem.material_id == item.material_id)
                    .order_by(OutboundOrderItem.id.desc())
                    .first()
                )
                result.append({
                    "material_id": mat.id,
                    "material_code": mat.code,
                    "material_name": mat.name,
                    "specification": mat.specification,
                    "unit": mat.unit,
                    "category_name": mat.category.name if mat.category else None,
                    "use_count": item.use_count,
                    "total_quantity": float(item.total_qty),
                    "last_quantity": float(last_order[0]) if last_order else 1
                })

        return APIResponse(code=0, message="获取成功", data=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取常用物料异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取常用物料失败: {str(e)}")


@router.post("/quick-requisition", summary="快捷领用（一键创建+提交）")
async def quick_requisition(
    req: QuickRequisitionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    一步创建并提交多个领用出库单。
    每个物料创建一个独立出库单，直接提交审核。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "outbound:create", db):
            raise HTTPException(status_code=403, detail="无权限执行此操作")

        created_ids = []
        errors = []

        for item in req.items:
            try:
                # 查物料名称（用于错误提示）
                mat = db.query(Material).filter(Material.id == item.material_id).first()
                mat_name = mat.name if mat else f"ID={item.material_id}"

                # 未指定库位时自动推荐
                loc_id = item.location_id
                if loc_id is None:
                    recs = OutboundService.get_fifo_recommendation(
                        material_id=item.material_id,
                        required_quantity=item.quantity,
                        db=db
                    )
                    if recs:
                        loc_id = recs[0].get("location_id") if isinstance(recs[0], dict) else recs[0].location_id if hasattr(recs[0], 'location_id') else None

                if loc_id is None:
                    errors.append({"material_id": item.material_id, "error": f"物料「{mat_name}」库存不足，无法出库"})
                    continue

                ok, msg, order = OutboundService.create_outbound_order(
                    outbound_type="requisition",
                    material_id=item.material_id,
                    quantity=item.quantity,
                    location_id=loc_id,
                    recipient_name=req.recipient_name,
                    recipient_department=req.recipient_department,
                    reason=req.reason or "快捷领用",
                    operator_id=current_user.id,
                    save_as_draft=True,
                    db=db
                )
                if ok and order:
                    submit_ok, submit_msg = OutboundService.submit_outbound_order(
                        order.id, current_user.id, db
                    )
                    if submit_ok:
                        created_ids.append(order.id)
                    else:
                        errors.append({"material_id": item.material_id, "error": submit_msg})
                else:
                    errors.append({"material_id": item.material_id, "error": msg})
            except Exception as e:
                errors.append({"material_id": item.material_id, "error": str(e)})

        return APIResponse(
            code=0 if not errors else 1,
            message=f"成功创建 {len(created_ids)} 个，失败 {len(errors)} 个",
            data={"created_ids": created_ids, "errors": errors}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"快捷领用异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"快捷领用失败: {str(e)}")


# ============================================================================
# 扫码领料接口
# ============================================================================

@router.get("/location-items", summary="查询库位物料清单（扫码用）")
async def get_location_items(
    location_code: str = Query(..., description="库位编码"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """根据库位编码查询该库位所有物料库存"""
    if not PermissionService.check_permission(current_user.id, "inventory:view", db):
        raise HTTPException(status_code=403, detail="无权限")

    from app.models import Location, Inventory

    location = db.query(Location).filter(Location.code == location_code).first()
    if not location:
        raise HTTPException(status_code=404, detail="库位不存在")

    inventories = db.query(Inventory).filter(
        Inventory.location_id == location.id,
        Inventory.quantity > 0
    ).all()

    items = []
    for inv in inventories:
        items.append({
            "material_id": inv.material_id,
            "material_code": inv.material.code if inv.material else None,
            "material_name": inv.material.name if inv.material else None,
            "specification": inv.material.specification if inv.material else None,
            "unit": inv.material.unit if inv.material else None,
            "quantity": float(inv.quantity),
        })

    return APIResponse(code=0, message="查询成功", data={
        "location_id": location.id,
        "location_code": location.code,
        "warehouse_name": location.warehouse.name if location.warehouse else None,
        "shelf_code": location.shelf.code if location.shelf else None,
        "level": location.level,
        "position": location.position,
        "items": items,
        "total_items": len(items)
    })


# ============================================================================
# 事后审批接口
# ============================================================================

class PostApprovalRequest(BaseModel):
    """事后审批请求"""
    action: str = Field(..., pattern="^(acknowledge)$", description="审批动作")
    comment: Optional[str] = Field(None, description="审批意见", max_length=500)


@router.get("/post-approval-list", summary="获取待事后审批列表")
async def get_post_approval_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取紧急领料出库后需要领导悉知的订单列表"""
    query = db.query(OutboundOrder).filter(
        OutboundOrder.needs_post_approval == True,
        OutboundOrder.post_approver_id.is_(None)
    )
    total = query.count()
    orders = query.order_by(OutboundOrder.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return APIResponse(
        code=0, message="获取成功",
        data={
            "list": [OutboundService.format_outbound_order(o) for o in orders],
            "total": total, "page": page, "page_size": page_size
        }
    )


@router.post("/orders/{order_id}/post-approve", summary="领导悉知紧急出库")
async def post_approve_order(
    order_id: int,
    req: PostApprovalRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """领导确认已知悉紧急领料出库单"""
    order = db.query(OutboundOrder).filter(OutboundOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="出库单不存在")
    if not order.needs_post_approval:
        raise HTTPException(status_code=400, detail="该出库单不需要事后审批")
    if order.post_approver_id is not None:
        raise HTTPException(status_code=400, detail="该出库单已完成事后审批")

    order.post_approver_id = current_user.id
    order.post_approved_at = datetime.now()
    order.post_approval_comment = req.comment or '已悉知'
    order.needs_post_approval = False
    db.commit()

    logger.info(f"领导已悉知紧急出库 | 单号: {order.outbound_no} | 领导: {current_user.username}")

    # 通知操作人领导已知悉
    try:
        from app.models.user import Notification
        notif = Notification(
            user_id=order.warehouse_manager_id,
            title="紧急出库已悉知",
            content=f"紧急出库单 {order.outbound_no} 已被 {current_user.real_name or current_user.username} 确认悉知",
            related_type="outbound", related_id=order.id)
        db.add(notif)
        db.commit()
    except Exception:
        pass

    return APIResponse(code=0, message="已知悉", data=OutboundService.format_outbound_order(order))

