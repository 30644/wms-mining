"""
入库业务完整API层
- 全类型入库业务（采购入库、调拨入库、退库入库、盘盈入库）
- 单据自动编号、库存实时增加、事务控制、状态流转
- 数据校验、权限控制
"""
from collections import defaultdict
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path, status, UploadFile, File
from fastapi import status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel, Field
from datetime import datetime

from app.database import get_db
from app.models import InboundOrder, Material, Location, Inventory, ScanInboundSession, MaterialCategory
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.inbound_service import InboundService
from app.services.inbound_import_service import InboundImportService
from app.services.nc_sync_service import NcSyncService
from app.utils.business_tools import PermissionService, OperationLog
from app.utils.logger import logger

router = APIRouter()


# ============================================================================
# 数据模型定义
# ============================================================================

class CreateInboundOrderRequest(BaseModel):
    """创建入库单请求"""
    inbound_type: str = Field(..., pattern="^(procurement|transfer_in|return|inventory_gain)$", description="入库类型")
    material_id: Optional[int] = Field(None, description="物资ID（有匹配物料时传入）")
    material_name_text: Optional[str] = Field(None, description="手动输入的物料名称（未匹配时用）", max_length=200)
    specification_text: Optional[str] = Field(None, description="手动输入的规格型号", max_length=200)
    unit_text: Optional[str] = Field(None, description="手动输入的单位", max_length=50)
    location_id: Optional[int] = Field(None, description="入库库位ID（到货登记可选，执行入库时指定）")
    quantity: float = Field(..., gt=0, description="入库数量")
    supplier: Optional[str] = Field(None, description="供应商（采购入库需要）", max_length=100)
    batch_info: Optional[str] = Field(None, description="批次信息", max_length=200)
    procurement_order_no: Optional[str] = Field(None, description="采购订单号", max_length=50)
    source_warehouse: Optional[str] = Field(None, description="源库房（调拨入库需要）", max_length=50)
    reason: Optional[str] = Field(None, description="原因", max_length=200)
    is_direct_issue: bool = Field(False, description="直接领用（不入库直接发给领用部门）")
    direct_issue_quantity: Optional[float] = Field(None, ge=0, description="直接领用数量（不填或0表示全部入库，等于quantity表示全部直领）")
    direct_issue_recipient: Optional[str] = Field(None, description="直接领用人/部门", max_length=100)

    class Config:
        schema_extra = {
            "example": {
                "inbound_type": "procurement",
                "material_id": 1,
                "location_id": 1,
                "quantity": 100.0,
                "supplier": "供应商A",
                "batch_info": "20260421批",
                "procurement_order_no": "PO20260421001"
            }
        }


class ReviewInboundOrderRequest(BaseModel):
    """审核入库单请求"""
    action: str = Field(..., pattern="^(approve|reject)$", description="审核动作")
    comment: Optional[str] = Field(None, description="审核意见", max_length=500)
    
    class Config:
        schema_extra = {
            "example": {
                "action": "approve",
                "comment": "物资检查合格"
            }
        }


class CancelInboundOrderRequest(BaseModel):
    """作废入库单请求"""
    reason: Optional[str] = Field(None, description="作废原因", max_length=200)

    class Config:
        schema_extra = {
            "example": {
                "reason": "采购订单已取消"
            }
        }


class ExecuteInboundRequest(BaseModel):
    """执行入库请求"""
    location_id: Optional[int] = Field(None, description="入库库位ID（留空使用原有的）")
    comment: Optional[str] = Field(None, description="备注", max_length=200)
    direct_issue_quantity: Optional[float] = Field(None, ge=0, description="直接领用数量（不填或0表示全部入库）")
    direct_issue_recipient: Optional[str] = Field(None, description="直接领用人/部门", max_length=100)

class ScanInboundRequest(BaseModel):
    """扫码入库请求（增强版）"""
    material_code: str = Field(..., description="物资编码")
    location_code: str = Field(..., description="库位编码")
    warehouse_id: int = Field(..., description="仓库ID")
    quantity: float = Field(..., gt=0, description="入库数量")
    inbound_type: str = Field("procurement", pattern="^(procurement|transfer_in|return|inventory_gain)$", description="入库类型")
    session_id: Optional[int] = Field(None, description="扫码会话ID（续扫时传入）")
    supplier: Optional[str] = Field(None, description="供应商（采购入库需要）", max_length=100)
    batch_info: Optional[str] = Field(None, description="批次信息", max_length=200)
    procurement_order_no: Optional[str] = Field(None, description="采购订单号", max_length=50)
    source_warehouse: Optional[str] = Field(None, description="源库房（调拨入库需要）", max_length=50)
    reason: Optional[str] = Field(None, description="原因", max_length=200)


# ============================================================================
# 入库单创建和管理接口
# ============================================================================

@router.post("/orders", summary="创建入库单", status_code=http_status.HTTP_201_CREATED)
async def create_inbound_order(
    request: CreateInboundOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    创建入库单
    
    支持多种类型：
    - procurement: 采购入库（需要供应商信息）
    - transfer_in: 调拨入库（需要源库房信息）
    - return: 退库入库
    - inventory_gain: 盘盈入库
    
    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            logger.warning(f"无权限创建入库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg, inbound_order = InboundService.create_inbound_order(
            inbound_type=request.inbound_type,
            material_id=request.material_id,
            material_name_text=request.material_name_text,
            specification_text=request.specification_text,
            unit_text=request.unit_text,
            location_id=request.location_id,
            quantity=request.quantity,
            operator_id=current_user.id,
            supplier=request.supplier,
            batch_info=request.batch_info,
            procurement_order_no=request.procurement_order_no,
            source_warehouse=request.source_warehouse,
            reason=request.reason,
            is_direct_issue=request.is_direct_issue,
            direct_issue_quantity=request.direct_issue_quantity,
            direct_issue_recipient=request.direct_issue_recipient,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        
        return APIResponse(
            code=0,
            message="入库单创建成功",
            data=InboundService.format_inbound_order(inbound_order)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建入库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建入库单失败: {str(e)}")


@router.post("/orders/create-and-submit", summary="创建并提交入库单", status_code=http_status.HTTP_201_CREATED)
async def create_and_submit_inbound_order(
    request: CreateInboundOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            logger.warning(f"无权限创建并提交入库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg, inbound_order = InboundService.create_inbound_order(
            inbound_type=request.inbound_type,
            material_id=request.material_id,
            material_name_text=request.material_name_text,
            specification_text=request.specification_text,
            unit_text=request.unit_text,
            location_id=request.location_id,
            quantity=request.quantity,
            operator_id=current_user.id,
            supplier=request.supplier,
            batch_info=request.batch_info,
            procurement_order_no=request.procurement_order_no,
            source_warehouse=request.source_warehouse,
            reason=request.reason,
            is_direct_issue=request.is_direct_issue,
            direct_issue_quantity=request.direct_issue_quantity,
            direct_issue_recipient=request.direct_issue_recipient,
            db=db
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        # 创建后自动提交审核（draft → pending_review）
        submit_success, submit_msg = InboundService.submit_inbound_order(
            inbound_order_id=inbound_order.id,
            submitter_id=current_user.id,
            db=db
        )
        if not submit_success:
            logger.warning(f"自动提交审核失败 | 入库单ID: {inbound_order.id} | 原因: {submit_msg}")

        return APIResponse(
            code=0,
            message="到货单创建并提交审核成功",
            data=InboundService.format_inbound_order(inbound_order)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建并提交入库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建并提交入库单失败: {str(e)}")


@router.post("/scan-inbound", summary="扫码入库登记", status_code=http_status.HTTP_201_CREATED)
async def scan_inbound(
    request: ScanInboundRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    扫码入库（增强版）
    - 支持多种入库类型
    - 自动创建或续扫到会话
    - 复用 InboundService 生成单号和状态机
    """
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        # 查物资和库位
        material = db.query(Material).filter(
            Material.code == request.material_code, Material.is_active == True
        ).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资编码不存在或已禁用")

        location = db.query(Location).filter(
            Location.code == request.location_code, Location.is_active == True
        ).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位编码不存在或已禁用")

        if location.warehouse_id != request.warehouse_id:
            raise HTTPException(status_code=400, detail="库位不属于所选仓库")

        # 会话管理
        session = None
        if request.session_id:
            session = db.query(ScanInboundSession).filter(
                ScanInboundSession.id == request.session_id,
                ScanInboundSession.status == 'active'
            ).first()
            if not session:
                raise HTTPException(status_code=400, detail="扫码会话不存在或已关闭")
        else:
            success, msg, session = InboundService.start_scan_session(
                warehouse_id=request.warehouse_id,
                operator_id=current_user.id,
                db=db
            )
            if not success:
                raise HTTPException(status_code=500, detail=msg)

        # 调用 InboundService 创建入库单
        success, msg, inbound_order = InboundService.create_inbound_order(
            inbound_type=request.inbound_type,
            material_id=material.id,
            location_id=location.id,
            quantity=request.quantity,
            operator_id=current_user.id,
            supplier=request.supplier,
            batch_info=request.batch_info,
            procurement_order_no=request.procurement_order_no,
            source_warehouse=request.source_warehouse,
            reason=request.reason,
            is_direct_issue=request.is_direct_issue,
            direct_issue_quantity=request.direct_issue_quantity,
            direct_issue_recipient=request.direct_issue_recipient,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        # 标记来源和会话
        inbound_order.source = 'scan'
        inbound_order.scan_session_id = session.id
        session.total_items = (session.total_items or 0) + 1
        db.commit()
        db.refresh(inbound_order)

        logger.info(f"用户 {current_user.username} 扫码入库 | 单号: {inbound_order.inbound_no} | 会话: {session.session_no}")

        return APIResponse(
            code=0,
            message="扫码入库登记成功",
            data={
                "order": InboundService.format_inbound_order(inbound_order),
                "session": InboundService.format_scan_session(session, db)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"扫码入库异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"扫码入库失败: {str(e)}")


@router.get("/orders", summary="获取入库单列表")
async def get_inbound_orders(
    inbound_type: Optional[str] = Query(None, pattern="^(procurement|transfer_in|return|inventory_gain)$", description="入库类型"),
    status: Optional[str] = Query(None, description="单据状态"),
    material_id: Optional[int] = Query(None, description="物资ID"),
    start_date: Optional[str] = Query(None, description="开始日期（YYYY-MM-DD）"),
    end_date: Optional[str] = Query(None, description="结束日期（YYYY-MM-DD）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取入库单列表（分页、多条件筛选）
    
    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inbound:view", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
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
        
        orders, total = InboundService.get_inbound_order_list(
            inbound_type=inbound_type,
            status=status,
            material_id=material_id,
            start_date=start_datetime,
            end_date=end_datetime,
            page=page,
            page_size=page_size,
            db=db
        )
        
        return APIResponse(
            code=0,
            message="获取入库单列表成功",
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
        logger.error(f"获取入库单列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取入库单列表失败: {str(e)}")


@router.post("/orders/import", summary="CSV批量导入入库单")
async def import_inbound_orders(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    从 CSV 文件批量导入入库单。

    CSV 列名（支持中文）:
    - material_code / 物料编码（必填其一）
    - material_name / 物料名称
    - quantity / 数量（必填）
    - location_code / 库位编码
    - supplier / 供应商
    - batch_info / 批次信息
    - specification / 规格型号
    - unit / 单位
    - remark / 备注
    """
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        if not file.filename.lower().endswith(".csv") and file.content_type != "text/csv":
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="仅支持 CSV 文件导入")

        content = await file.read()
        result = InboundImportService.import_from_csv(
            file_content=content,
            operator_id=current_user.id,
            db=db
        )

        return APIResponse(
            code=0,
            message=f"导入完成: 成功 {result['imported']} 条, 失败 {result['failed']} 条",
            data=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CSV导入入库单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/orders/{order_id}", summary="获取入库单详情")
async def get_inbound_order_detail(
    order_id: int = Path(..., description="入库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取入库单详情"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inbound:view", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="入库单不存在")
        
        return APIResponse(
            code=0,
            message="获取入库单详情成功",
            data=InboundService.format_inbound_order(order)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取入库单详情异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取入库单详情失败: {str(e)}")


# ============================================================================
# 入库单审核流程接口
# ============================================================================

@router.post("/orders/{order_id}/receiving-review", summary="到货审核员审核")
async def receiving_review(
    order_id: int = Path(..., description="入库单ID"),
    request: ReviewInboundOrderRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    到货审核员验收/驳回

    权限要求：receiving_inspector
    """
    try:
        if not PermissionService.check_role(current_user.id, "receiving_inspector", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无到货审核权限")

        success, msg = InboundService.review_inbound_order(
            inbound_order_id=order_id,
            review_type="receiving_review",
            action=request.action,
            reviewer_id=current_user.id,
            comment=request.comment,
            db=db
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=f"到货审核{request.action}成功",
            data=InboundService.format_inbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"到货审核入库单异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"到货审核失败: {str(e)}")


@router.post("/orders/{order_id}/submit", summary="提交到货审核")
async def submit_inbound_order(
    order_id: int = Path(..., description="入库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """提交到货单，等待审核"""
    try:
        success, msg = InboundService.submit_inbound_order(
            inbound_order_id=order_id,
            submitter_id=current_user.id,
            db=db
        )
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=msg,
            data=InboundService.format_inbound_order(order)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交到货审核异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交失败: {str(e)}")


@router.post("/orders/{order_id}/warehouse-confirm", summary="库管确认入库（含越库领用）")
async def warehouse_confirm(
    order_id: int = Path(..., description="入库单ID"),
    request: ExecuteInboundRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    库管确认入库/越库领用（可选择/调整库位，物理上架）

    在验收通过后执行，支持：
    - 全部入库：走入库后审核流程
    - 全部越库：直接完成，自动生成出库单
    - 部分入库+部分越库：入库部分待审核，越库部分生成出库单

    权限要求：warehouse_manager
    """
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:confirm", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = InboundService.execute_inbound_with_split(
            inbound_order_id=order_id,
            operator_id=current_user.id,
            location_id=request.location_id,
            direct_issue_quantity=request.direct_issue_quantity,
            direct_issue_recipient=request.direct_issue_recipient,
            comment=request.comment,
            db=db
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        if order.status == "completed":
            sync_success, sync_msg = NcSyncService.sync_inbound_to_nc(order_id, db)
            logger.info(f"自动同步入库单到NC6.5 | 入库单: {order.inbound_no} | 结果: {sync_success}")

        return APIResponse(
            code=0,
            message=msg,
            data=InboundService.format_inbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"库管确认入库异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"库管确认失败: {str(e)}")


@router.post("/orders/{order_id}/inbound-review", summary="入库后审核")
async def inbound_review(
    order_id: int = Path(..., description="入库单ID"),
    request: ReviewInboundOrderRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    入库后审核（pending_inbound_review → completed/rejected）

    库管完成物理入库上架后，由审核人确认入库数据正确后，
    系统才正式更新库存。适用于需要入库后质检/核实的场景。
    """
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:confirm", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = InboundService.process_inbound_review(
            inbound_order_id=order_id,
            action=request.action,
            reviewer_id=current_user.id,
            comment=request.comment,
            db=db
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=msg,
            data=InboundService.format_inbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"入库后审核异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"入库后审核失败: {str(e)}")


# ============================================================================
# 入库单作废接口
# ============================================================================

@router.post("/orders/{order_id}/cancel", summary="作废入库单")
async def cancel_inbound_order(
    order_id: int = Path(..., description="入库单ID"),
    request: CancelInboundOrderRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    作废入库单
    
    权限要求：warehouse_manager
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inbound:cancel", db):
            logger.warning(f"无权限作废入库单 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg = InboundService.cancel_inbound_order(
            inbound_order_id=order_id,
            cancelled_by=current_user.id,
            reason=request.reason,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        
        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        
        return APIResponse(
            code=0,
            message="入库单作废成功",
            data=InboundService.format_inbound_order(order)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"作废入库单异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"作废入库单失败: {str(e)}")


# ============================================================================
# 扫码会话管理接口
# ============================================================================

@router.post("/scan-session/start", summary="开始扫码会话", status_code=http_status.HTTP_201_CREATED)
async def start_scan_session(
    warehouse_id: int = Body(..., embed=True, description="仓库ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """开始一个新的扫码批次会话"""
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg, session = InboundService.start_scan_session(
            warehouse_id=warehouse_id,
            operator_id=current_user.id,
            db=db
        )
        if not success:
            raise HTTPException(status_code=500, detail=msg)

        return APIResponse(code=0, message=msg, data=InboundService.format_scan_session(session, db))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"开始扫码会话异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"开始扫码会话失败: {str(e)}")


@router.post("/scan-session/{session_id}/submit", summary="提交扫码会话")
async def submit_scan_session(
    session_id: int = Path(..., description="扫码会话ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """提交扫码会话（关闭会话，不再接受新扫码）"""
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:create", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        session = db.query(ScanInboundSession).filter(
            ScanInboundSession.id == session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="扫码会话不存在")
        if session.status != 'active':
            raise HTTPException(status_code=400, detail="扫码会话已提交或已取消")

        session.status = 'submitted'
        db.commit()

        logger.info(f"扫码会话已提交 | 会话号: {session.session_no} | 共 {session.total_items} 件")

        return APIResponse(code=0, message="扫码会话提交成功", data=InboundService.format_scan_session(session, db))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交扫码会话异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交扫码会话失败: {str(e)}")


@router.get("/scan-sessions", summary="获取扫码会话列表")
async def get_scan_sessions(
    status: Optional[str] = Query(None, description="状态: active, submitted"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取扫码会话历史列表"""
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:view", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        query = db.query(ScanInboundSession)
        if status:
            query = query.filter(ScanInboundSession.status == status)

        total = query.count()
        sessions = query.order_by(desc(ScanInboundSession.created_at))\
            .offset((page - 1) * page_size).limit(page_size).all()

        return APIResponse(
            code=0, message="获取成功",
            data={
                "list": [InboundService.format_scan_session(s, db) for s in sessions],
                "total": total, "page": page, "page_size": page_size
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取扫码会话列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取扫码会话列表失败: {str(e)}")


@router.get("/scan-session/{session_id}", summary="获取扫码会话详情")
async def get_scan_session_detail(
    session_id: int = Path(..., description="扫码会话ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取扫码会话详情（含所有扫码入库单）"""
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:view", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        session = db.query(ScanInboundSession).filter(
            ScanInboundSession.id == session_id
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="扫码会话不存在")

        return APIResponse(code=0, message="获取成功", data=InboundService.format_scan_session(session, db))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取扫码会话详情异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取扫码会话详情失败: {str(e)}")


@router.get("/orders/{order_id}/receipt", summary="生成入库凭单")
async def get_inbound_receipt(
    order_id: int = Path(..., description="入库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """生成入库凭单信息（可打印）"""
    try:
        if not PermissionService.check_permission(current_user.id, "inbound:view", db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="入库单不存在")

        return APIResponse(
            code=0, message="获取成功",
            data=InboundService.format_inbound_receipt(order, db)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成入库凭单异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成入库凭单失败: {str(e)}")


# ============================================================================
# NC6.5同步接口
# ============================================================================

@router.post("/orders/{order_id}/sync-to-nc", summary="同步入库单到NC6.5")
async def sync_inbound_to_nc(
    order_id: int = Path(..., description="入库单ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    手动同步入库单到用友NC6.5系统
    
    权限要求：warehouse_manager或super_admin
    """
    try:
        # 权限检查
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg = NcSyncService.sync_inbound_to_nc(order_id, db)
        
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        
        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        
        return APIResponse(
            code=0,
            message=msg,
            data=InboundService.format_inbound_order(order)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步入库单到NC6.5异常 | 入库单ID: {order_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")

# ============================================================================
# 库位推荐接口（入库时智能推荐存放库位）
# ============================================================================

@router.get("/location-recommend", summary="智能推荐入库库位")
async def recommend_locations(
    material_id: int = Query(..., description="物料ID"),
    quantity: float = Query(..., gt=0, description="入库数量"),
    warehouse_id: Optional[int] = Query(None, description="目标仓库ID（可选，不传则全仓库推荐）"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    根据以下策略智能推荐入库库位：

    1. **同类优先**：优先推荐已存放同类物料的库位（取同一物料分类）
    2. **空间足够**：库位剩余容量 >= 入库物料体积
    3. **相邻推荐**：同类库位满时，推荐相邻库位（同一货架）
    4. 按综合评分排序返回前 10 条推荐
    """
    try:
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="物料不存在")

        category_id = material.category_id
        unit_vol = float(material.unit_volume or 0)
        volume_unit = material.volume_unit or 'm³'
        required_space = unit_vol * quantity

        # 1. 找到所有有库存的库位，以及它们的物料分类
        inventory_locations = db.query(
            Inventory, Location, Material
        ).join(
            Location, Inventory.location_id == Location.id
        ).join(
            Material, Inventory.material_id == Material.id
        ).filter(
            Location.is_active == True,
            Inventory.quantity > 0
        ).all()

        # 统计每个库位的：已用空间、物料ID、分类
        from collections import defaultdict
        loc_stats = defaultdict(lambda: {
            "used_space": 0.0,
            "capacity": 0.0,
            "material_ids": set(),
            "category_ids": set(),
            "categories": set(),
            "shelf_id": None,
            "warehouse_id": None,
            "warehouse_name": "",
            "code": "",
            "volume_unit": "m³",
        })

        for inv, loc, mat in inventory_locations:
            loc_id = loc.id
            file_vol = float(mat.unit_volume or 0) * float(inv.quantity)
            loc_stats[loc_id]["used_space"] += file_vol
            loc_stats[loc_id]["capacity"] = float(loc.capacity or 0)
            loc_stats[loc_id]["shelf_id"] = loc.shelf_id
            loc_stats[loc_id]["warehouse_id"] = loc.warehouse_id
            loc_stats[loc_id]["warehouse_name"] = loc.warehouse.name if loc.warehouse else ""
            loc_stats[loc_id]["code"] = loc.code
            loc_stats[loc_id]["material_ids"].add(mat.id)
            if mat.category_id:
                loc_stats[loc_id]["category_ids"].add(mat.category_id)
                loc_stats[loc_id]["categories"].add(mat.category.name if mat.category else "")

        # 2. 加入空库位（有容量但无库存的）
        empty_locations = db.query(Location).filter(
            Location.is_active == True,
            Location.capacity > 0
        ).all()
        for loc in empty_locations:
            if loc.id not in loc_stats:
                loc_stats[loc.id] = {
                    "used_space": 0.0,
                    "capacity": float(loc.capacity or 0),
                    "material_ids": set(),
                    "category_ids": set(),
                    "categories": set(),
                    "shelf_id": loc.shelf_id,
                    "warehouse_id": loc.warehouse_id,
                    "warehouse_name": loc.warehouse.name if loc.warehouse else "",
                    "code": loc.code,
                }

        # 3. 找出已有同分类物料的货架（相邻推荐基础）
        same_category_shelf_ids = set()
        same_material_loc_ids = set()
        for loc_id, stats in loc_stats.items():
            if category_id and category_id in stats["category_ids"]:
                same_category_shelf_ids.add(stats["shelf_id"])
            if material_id in stats["material_ids"]:
                same_material_loc_ids.add(loc_id)

        # 4. 过滤 + 评分
        scored = []
        for loc_id, stats in loc_stats.items():
            # 过滤仓库
            if warehouse_id and stats["warehouse_id"] != warehouse_id:
                continue

            # 容量为 0 表示无限制
            available = stats["capacity"] - stats["used_space"]
            if stats["capacity"] > 0 and available <= 0:
                continue

            # 评分逻辑
            score = 0
            reasons = []

            # 同一物料（之前就放这里）+100 → 最高优先
            has_same_material = loc_id in same_material_loc_ids
            if has_same_material:
                score += 100
                reasons.append("曾存放此物料")

            # 同类物料 +50
            has_same_category = category_id and category_id in stats["category_ids"]
            if has_same_category:
                score += 50
                reasons.append("已有同类物料")

            # 相邻货架（同一货架已有同分类物料）+30
            is_adjacent_same_category = (
                stats["shelf_id"] in same_category_shelf_ids
                and not has_same_category
                and not has_same_material
            )
            if is_adjacent_same_category:
                score += 30
                reasons.append("相邻货架有同类物料")

            # 空间足够 +20
            space_sufficient = available >= required_space
            if space_sufficient:
                score += 20
                reasons.append("空间充足")

            # 空库位 +10（全新库位，优先使用）
            if stats["used_space"] == 0 and stats["capacity"] > 0:
                score += 10
                reasons.append("空库位")

            # 空间利用率适中 +5
            usage_rate = stats["used_space"] / stats["capacity"] if stats["capacity"] > 0 else 0
            if stats["capacity"] > 0 and 0 < usage_rate < 0.8:
                score += 5
                reasons.append("空间利用率适中")

            scored.append({
                "location_id": loc_id,
                "location_code": stats["code"],
                "warehouse_id": stats["warehouse_id"],
                "warehouse_name": stats["warehouse_name"],
                "shelf_id": stats["shelf_id"],
                "capacity": stats["capacity"],
                "capacity_unit": stats.get("volume_unit", "m³"),
                "used_space": round(stats["used_space"], 4),
                "available_space": round(available, 4),
                "required_space": round(required_space, 4),
                "space_sufficient": available >= required_space,
                "has_same_category": has_same_category,
                "has_same_material": has_same_material,
                "categories": list(stats["categories"]),
                "score": score,
                "reasons": reasons,
            })

        # 5. 按评分排序
        scored.sort(key=lambda x: x["score"], reverse=True)

        # 6. 取 top 推荐
        top_recommendations = scored[:10]

        # 7. 如果单个库位空间不够，尝试推荐相邻库位组合（优先同分类货架）
        combined_recs = []
        if not any(r["space_sufficient"] for r in top_recommendations):
            shelf_groups = defaultdict(list)
            for r in scored:
                shelf_groups[r["shelf_id"]].append(r)

            for shelf_id, group in shelf_groups.items():
                group.sort(key=lambda x: x["score"], reverse=True)
                total_available = sum(r["available_space"] for r in group)
                if total_available >= required_space:
                    # 取最高分的几个库位（不超过5个）
                    top_locs = group[:5]
                    shelf_has_category = shelf_id in same_category_shelf_ids
                    combined_recs.append({
                        "shelf_id": shelf_id,
                        "locations": [r["location_id"] for r in top_locs],
                        "location_codes": [r["location_code"] for r in top_locs],
                        "total_available": round(total_available, 4),
                        "volume_unit": volume_unit,
                        "required_space": round(required_space, 4),
                        "has_same_category": shelf_has_category,
                        "reason": "单库位空间不足，推荐相邻库位组合存放"
                                   + ("（该货架已有同类物料）" if shelf_has_category else ""),
                    })

            # 按"是否有同分类" + "总分"排序
            combined_recs.sort(key=lambda x: (x["has_same_category"], x["total_available"]), reverse=True)

        return APIResponse(
            code=0,
            message="获取推荐成功",
            data={
                "material_id": material_id,
                "material_name": material.name,
                "material_code": material.code,
                "category_name": material.category.name if material.category else None,
                "volume_unit": volume_unit,
                "required_space": round(required_space, 4),
                "single_recommendations": top_recommendations,
                "combined_recommendations": combined_recs,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"库位推荐异常 | 物料ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"库位推荐失败: {str(e)}")



