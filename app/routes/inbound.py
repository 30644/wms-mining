"""
入库管理和审核接口
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
import datetime

from app.database import get_db
from app.models import InboundOrder, Material, Location, User, Inventory
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user, require_role
from app.utils.business_tools import PermissionService
from app.config import SUPER_ADMIN_ROLE
from app.utils.logger import logger

router = APIRouter()


# ============================================================================
# 扫码入库接口
# ============================================================================

class ScanInboundRequest(BaseModel):
    material_code: str
    location_code: str
    warehouse_id: Optional[int] = None
    quantity: float
    supplier: Optional[str] = None
    batch_info: Optional[str] = None
    procurement_order_no: Optional[str] = None

@router.post("/scan-inbound", summary="扫码入库登记")
async def scan_inbound(
    request: ScanInboundRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """扫码入库，自动回填物资信息"""
    try:
        # 根据编码查找物资
        material = db.query(Material).filter(
            and_(Material.code == request.material_code, Material.is_active == True)
        ).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资编码不存在或已禁用")
        
        # 根据编码查找库位
        location = db.query(Location).filter(
            and_(Location.code == request.location_code, Location.is_active == True)
        ).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位编码不存在或已禁用")

        # 验证仓库是否与库位匹配
        if request.warehouse_id and location.warehouse_id != request.warehouse_id:
            raise HTTPException(status_code=400, detail="库位不属于所选仓库")
        
        # 检查库位容量
        if location.capacity and request.quantity > location.capacity:
            raise HTTPException(status_code=400, detail=f"入库数量超过库位容量({location.capacity})")
        
        # 生成入库单号
        inbound_no = f"IN{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 创建入库单（到货登记）
        inbound_order = InboundOrder(
            inbound_no=inbound_no,
            material_id=material.id,
            location_id=location.id,
            quantity=request.quantity,
            supplier=request.supplier,
            batch_info=request.batch_info,
            procurement_order_no=request.procurement_order_no,
            warehouse_manager_id=current_user.id,
            status="draft"
        )
        
        db.add(inbound_order)
        db.commit()
        db.refresh(inbound_order)
        
        logger.info(f"用户 {current_user.username} 创建入库单: {inbound_no}")
        
        return APIResponse(
            code=0,
            message="入库登记成功，等待审核",
            data={
                "id": inbound_order.id,
                "inbound_no": inbound_order.inbound_no,
                "material_name": material.name,
                "location_code": location.code,
                "quantity": float(request.quantity),
                "status": inbound_order.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"入库登记失败: {str(e)}")


# ============================================================================
# 入库审核接口
# ============================================================================

class ReviewRequest(BaseModel):
    comment: Optional[str] = None

class CancelRequest(BaseModel):
    reason: Optional[str] = None

class ExecuteRequest(BaseModel):
    location_id: Optional[int] = None
    comment: Optional[str] = None


# ============================================================================
# 到货审核接口（到货审核员 receiving_inspector）
# ============================================================================

@router.post("/inbound-orders/{order_id}/receiving-review", summary="到货审核员审核")
async def receiving_review_inbound(
    order_id: int,
    request: ReviewRequest,
    action: str = Query(..., pattern="^(approve|reject)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """到货审核员验收/驳回"""
    try:
        from app.services.inbound_service import InboundService

        # 检查角色：先看订单的 assigned_role，否则检查 receiving_inspector
        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="入库单不存在")

        required_role = order.assigned_role or "receiving_inspector"
        if not PermissionService.check_role(current_user.id, required_role, db):
            raise HTTPException(status_code=403, detail=f"无{required_role}审核权限")

        success, msg = InboundService.review_inbound_order(
            inbound_order_id=order_id,
            review_type="receiving_review",
            action=action,
            reviewer_id=current_user.id,
            comment=request.comment,
            db=db
        )

        if not success:
            raise HTTPException(status_code=400, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message=f"审核{action}成功",
            data={
                "id": order.id,
                "inbound_no": order.inbound_no,
                "status": order.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"审核失败: {str(e)}")


# ============================================================================
# 入库单操作接口（前端调用）
# ============================================================================

@router.post("/{order_id}/submit", summary="提交到货审核")
async def submit_inbound(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """提交到货单，等待到货审核员验收"""
    try:
        from app.services.inbound_service import InboundService

        success, msg = InboundService.submit_inbound_order(
            inbound_order_id=order_id,
            submitter_id=current_user.id,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交失败: {str(e)}")


@router.post("/{order_id}/approve", summary="审核通过（到货审核员）")
async def approve_inbound(
    order_id: int,
    request: ReviewRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """到货审核员审核通过"""
    try:
        from app.services.inbound_service import InboundService

        # 检查角色：先看订单的 assigned_role，否则检查 receiving_inspector
        order_check = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        if not order_check:
            raise HTTPException(status_code=404, detail="入库单不存在")
        required_role = order_check.assigned_role or "receiving_inspector"
        if not PermissionService.check_role(current_user.id, required_role, db):
            raise HTTPException(status_code=403, detail=f"无{required_role}审核权限")

        success, msg = InboundService.review_inbound_order(
            inbound_order_id=order_id,
            review_type="receiving_review",
            action="approve",
            reviewer_id=current_user.id,
            comment=request.comment,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message="审核通过",
            data={"id": order.id, "inbound_no": order.inbound_no, "status": order.status}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"审核失败: {str(e)}")


@router.post("/{order_id}/execute", summary="执行入库")
async def execute_inbound(
    order_id: int,
    request: ExecuteRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """执行入库（可选择库位，更新库存）"""
    try:
        from app.services.inbound_service import InboundService

        success, msg = InboundService.review_inbound_order(
            inbound_order_id=order_id,
            review_type="warehouse_confirm",
            action="approve",
            reviewer_id=current_user.id,
            comment=request.comment,
            location_id=request.location_id,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()

        return APIResponse(
            code=0,
            message="入库成功",
            data={"id": order.id, "inbound_no": order.inbound_no, "status": order.status}
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"入库失败: {str(e)}")


@router.post("/{order_id}/cancel", summary="作废入库单")
async def cancel_inbound(
    order_id: int,
    request: CancelRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """作废入库单"""
    try:
        from app.services.inbound_service import InboundService

        success, msg = InboundService.cancel_inbound_order(
            inbound_order_id=order_id,
            cancelled_by=current_user.id,
            reason=request.reason,
            db=db
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        return APIResponse(code=0, message="作废成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"作废失败: {str(e)}")


# ============================================================================
# 入库单查询接口
# ============================================================================

@router.get("/inbound-orders", summary="获取入库单列表")
async def get_inbound_orders(
    status: Optional[str] = Query(None),
    material_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取入库单列表"""
    try:
        query = db.query(InboundOrder).outerjoin(Material).join(Location).join(User, InboundOrder.operator)
        
        if status:
            query = query.filter(InboundOrder.status == status)
        if material_id:
            query = query.filter(InboundOrder.material_id == material_id)
        if start_date:
            query = query.filter(InboundOrder.created_at >= start_date)
        if end_date:
            query = query.filter(InboundOrder.created_at <= end_date)
        
        inbound_orders = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": order.id,
                        "inbound_no": order.inbound_no,
                        "material_name": order.material.name if order.material else (order.material_name_text or None),
                        "location_code": order.location.code if order.location else None,
                        "quantity": float(order.quantity),
                        "supplier": order.supplier,
                        "batch_info": order.batch_info,
                        "procurement_order_no": order.procurement_order_no,
                        "status": order.status,
                        "operator_name": order.operator.real_name if order.operator else None,
                        "procurement_reviewer_name": order.procurement_reviewer.real_name if order.procurement_reviewer else None,
                        "technical_reviewer_name": order.technical_reviewer.real_name if order.technical_reviewer else None,
                        "created_at": order.created_at.isoformat() if order.created_at else None
                    } for order in inbound_orders
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取入库单列表失败: {str(e)}")


@router.get("/inbound-orders/{order_id}", summary="获取入库单详情")
async def get_inbound_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取入库单详情"""
    try:
        order = db.query(InboundOrder).filter(InboundOrder.id == order_id).first()
        if not order:
            raise HTTPException(status_code=404, detail="入库单不存在")
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": order.id,
                "inbound_no": order.inbound_no,
                "material_id": order.material_id,
                "material_name": order.material.name if order.material else (order.material_name_text or None),
                "material_name_text": order.material_name_text,
                "specification_text": order.specification_text,
                "unit_text": order.unit_text,
                "location_id": order.location_id,
                "location_code": order.location.code if order.location else None,
                "quantity": float(order.quantity),
                "supplier": order.supplier,
                "batch_info": order.batch_info,
                "procurement_order_no": order.procurement_order_no,
                "status": order.status,
                "procurement_reviewer_id": order.procurement_reviewer_id,
                "procurement_reviewer_name": order.procurement_reviewer.real_name if order.procurement_reviewer else None,
                "procurement_reviewed_at": order.procurement_reviewed_at.isoformat() if order.procurement_reviewed_at else None,
                "procurement_comment": order.procurement_comment,
                "technical_reviewer_id": order.technical_reviewer_id,
                "technical_reviewer_name": order.technical_reviewer.real_name if order.technical_reviewer else None,
                "technical_reviewed_at": order.technical_reviewed_at.isoformat() if order.technical_reviewed_at else None,
                "technical_comment": order.technical_comment,
                "operator_name": order.operator.real_name if order.operator else None,
                "created_at": order.created_at.isoformat() if order.created_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取入库单详情失败: {str(e)}")