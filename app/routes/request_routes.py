"""
领料申请和审批流程接口
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import and_
from pydantic import BaseModel
import datetime

from app.database import get_db, beijing_now
from app.models import Request, Material, User, Inventory, Location, OutboundOrder
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user, require_role
from app.utils.business_tools import PermissionService
from app.config import SUPER_ADMIN_ROLE
from app.utils.logger import logger

router = APIRouter()


# ============================================================================
# 领料申请接口
# ============================================================================

class CreateMaterialRequest(BaseModel):
    material_id: int
    quantity: float
    reason: str
    urgency_level: str = "normal"
    project_code: Optional[str] = None
    expected_date: Optional[str] = None

@router.post("/material-requests", summary="提报领料申请")
async def create_material_request(
    request: CreateMaterialRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """班组成员提报领料申请"""
    try:
        # 检查物资是否存在
        material = db.query(Material).filter(
            and_(Material.id == request.material_id, Material.is_active == True)
        ).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资不存在或已禁用")
        
        # 检查申请数量是否超过单次最大限额
        if material.max_per_request and request.quantity > material.max_per_request:
            raise HTTPException(status_code=400, detail=f"申请数量超过单次最大限额({material.max_per_request})")
        
        # 生成申请单号
        request_no = f"MR{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建领料申请（草稿状态）
        material_request = Request(
            request_no=request_no,
            requester_id=current_user.id,
            material_id=request.material_id,
            quantity=request.quantity,
            reason=request.reason,
            urgency_level=request.urgency_level,
            project_code=request.project_code,
            status="draft"
        )
        
        db.add(material_request)
        db.commit()
        db.refresh(material_request)
        
        logger.info(f"用户 {current_user.username} 提报领料申请: {request_no}")
        
        return APIResponse(
            code=0,
            message="领料申请提报成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "material_name": material.name,
                "quantity": float(request.quantity),
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"提报领料申请失败: {str(e)}")


# ============================================================================
# 创建并提交接口
# ============================================================================

@router.post("/material-requests/create-and-submit", summary="创建并提交领料申请")
async def create_and_submit_material_request(
    request: CreateMaterialRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建领料申请并直接提交为待审批状态"""
    try:
        material = db.query(Material).filter(
            and_(Material.id == request.material_id, Material.is_active == True)
        ).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资不存在或已禁用")

        if material.max_per_request and request.quantity > material.max_per_request:
            raise HTTPException(status_code=400, detail=f"申请数量超过单次最大限额({material.max_per_request})")

        request_no = f"MR{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 检查部门是否有班长，决定审批流向
        if current_user.role == "employee":
            team_leader_count = db.query(User).filter(
                User.department == current_user.department,
                User.role == "team_leader",
                User.is_active == True
            ).count()
            target_status = "pending_team_leader" if team_leader_count > 0 else "pending_dept_leader"
        else:
            target_status = "pending_dept_leader"

        material_request = Request(
            request_no=request_no,
            requester_id=current_user.id,
            material_id=request.material_id,
            quantity=request.quantity,
            reason=request.reason,
            urgency_level=request.urgency_level,
            project_code=request.project_code,
            status=target_status
        )

        db.add(material_request)
        db.commit()
        db.refresh(material_request)

        logger.info(f"用户 {current_user.username} 创建并提交领料申请: {request_no}")

        return APIResponse(
            code=0,
            message="领料申请提交成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "material_name": material.name,
                "quantity": float(request.quantity),
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"提交领料申请失败: {str(e)}")


# ============================================================================
# 提交草稿接口
# ============================================================================

@router.post("/material-requests/{request_id}/submit", summary="提交草稿审批")
async def submit_material_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """将草稿状态的领料申请提交为待审批"""
    try:
        material_request = db.query(Request).filter(Request.id == request_id).first()
        if not material_request:
            raise HTTPException(status_code=404, detail="领料申请不存在")

        if material_request.status != "draft":
            raise HTTPException(status_code=400, detail="只有草稿状态的申请才能提交审批")

        # 检查部门是否有班长，决定审批流向
        if current_user.role == "employee":
            team_leader_count = db.query(User).filter(
                User.department == current_user.department,
                User.role == "team_leader",
                User.is_active == True
            ).count()
            material_request.status = "pending_team_leader" if team_leader_count > 0 else "pending_dept_leader"
        else:
            material_request.status = "pending_dept_leader"
        db.commit()

        logger.info(f"用户 {current_user.username} 提交领料申请: {material_request.request_no}")

        return APIResponse(
            code=0,
            message="提交审批成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"提交审批失败: {str(e)}")




# ============================================================================
# 班长审批接口
# ============================================================================

class TeamLeaderApprovalRequest(BaseModel):
    comment: Optional[str] = None

@router.post("/material-requests/{request_id}/team-leader-approval", summary="班长审批领料申请")
async def team_leader_approve_request(
    request_id: int,
    request: TeamLeaderApprovalRequest,
    action: str = Query(..., pattern="^(approve|reject)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    '''班长审批领料申请（班组内的一级审批）'''
    try:
        # 检查用户角色
        if not PermissionService.check_role(current_user.id, "team_leader", db):
            raise HTTPException(status_code=403, detail="无班长审批权限")

        material_request = db.query(Request).filter(Request.id == request_id).first()
        if not material_request:
            raise HTTPException(status_code=404, detail="领料申请不存在")

        # 部门隔离校验
        if current_user.role != "super_admin":
            requester = db.query(User).filter(User.id == material_request.requester_id).first()
            if requester and requester.department != current_user.department:
                raise HTTPException(status_code=403, detail="只能审批本部门的申请")

        if material_request.status != "pending_team_leader":
            raise HTTPException(status_code=400, detail="领料申请状态不允许班长审批")

        # 更新审批信息
        material_request.leader_reviewer_id = current_user.id
        material_request.leader_reviewed_at = datetime.beijing_now()
        material_request.leader_comment = request.comment

        if action == "approve":
            material_request.status = "pending_dept_leader"
        else:
            material_request.status = "leader_rejected"

        db.commit()

        logger.info(f"班长 {current_user.username} {action} 领料申请: {material_request.request_no}")

        return APIResponse(
            code=0,
            message=f"班长审批{action}成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"班长审批失败: {str(e)}")


# ============================================================================
# 领导审批接口
# ============================================================================

class LeaderApprovalRequest(BaseModel):
    comment: Optional[str] = None

@router.post("/material-requests/{request_id}/leader-approval", summary="领导审批领料申请")
async def leader_approve_request(
    request_id: int,
    request: LeaderApprovalRequest,
    action: str = Query(..., pattern="^(approve|reject)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """领导审批领料申请"""
    try:
        # 检查用户角色（部门领导或库管领导均可审批）
        if not PermissionService.check_role(current_user.id, "department_leader", db) and not PermissionService.check_role(current_user.id, "warehouse_manager", db):
            raise HTTPException(status_code=403, detail="无领导审批权限")
        
        material_request = db.query(Request).filter(Request.id == request_id).first()
        if not material_request:
            raise HTTPException(status_code=404, detail="领料申请不存在")
        
        # 部门隔离校验：只能审批本部门的申请
        if current_user.role != "super_admin":
            requester = db.query(User).filter(User.id == material_request.requester_id).first()
            if requester and requester.department != current_user.department:
                raise HTTPException(status_code=403, detail="只能审批本部门的申请")
        
        if material_request.status != "pending_dept_leader":
            raise HTTPException(status_code=400, detail="领料申请状态不允许领导审批")
        
        # 更新审批信息
        material_request.leader_reviewer_id = current_user.id
        material_request.leader_reviewed_at = datetime.beijing_now()
        material_request.leader_comment = request.comment
        
        if action == "approve":
            material_request.status = "pending_warehouse_outbound"
        else:
            material_request.status = "leader_rejected"
        
        db.commit()
        
        logger.info(f"领导 {current_user.username} {action} 领料申请: {material_request.request_no}")
        
        return APIResponse(
            code=0,
            message=f"领导审批{action}成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"领导审批失败: {str(e)}")


# ============================================================================
# 库管出库接口
# ============================================================================

class WarehouseOutboundRequest(BaseModel):
    location_id: int
    comment: Optional[str] = None

@router.post("/material-requests/{request_id}/warehouse-outbound", summary="库管出库")
async def warehouse_outbound(
    request_id: int,
    request: WarehouseOutboundRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """库管执行出库操作"""
    try:
        # 检查用户角色
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db):
            raise HTTPException(status_code=403, detail="无库管出库权限")
        
        material_request = db.query(Request).filter(Request.id == request_id).first()
        if not material_request:
            raise HTTPException(status_code=404, detail="领料申请不存在")
        
        if material_request.status != "pending_warehouse_outbound":
            raise HTTPException(status_code=400, detail="领料申请状态不允许出库")
        
        # 检查库位是否存在
        location = db.query(Location).filter(
            and_(Location.id == request.location_id, Location.is_active == True)
        ).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在或已禁用")
        
        # 检查库存是否充足
        inventory = db.query(Inventory).filter(
            and_(Inventory.material_id == material_request.material_id, Inventory.location_id == request.location_id)
        ).first()
        if not inventory or inventory.quantity < material_request.quantity:
            raise HTTPException(status_code=400, detail="指定库位库存不足")
        
        # 生成出库单号
        outbound_no = f"OUT{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建出库单
        outbound_order = OutboundOrder(
            outbound_no=outbound_no,
            request_id=material_request.id,
            material_id=material_request.material_id,
            location_id=request.location_id,
            quantity=material_request.quantity,
            warehouse_manager_id=current_user.id,
            comment=request.comment,
            status="completed"
        )
        
        # 更新库存
        inventory.quantity -= material_request.quantity
        
        # 更新申请状态
        material_request.status = "completed"
        material_request.warehouse_manager_id = current_user.id
        material_request.outbound_at = datetime.beijing_now()
        
        db.add(outbound_order)
        db.commit()
        
        logger.info(f"库管 {current_user.username} 出库领料申请: {material_request.request_no}")
        
        return APIResponse(
            code=0,
            message="出库成功",
            data={
                "id": material_request.id,
                "request_no": material_request.request_no,
                "outbound_no": outbound_order.outbound_no,
                "location_code": location.code,
                "quantity": float(material_request.quantity),
                "status": material_request.status
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"出库失败: {str(e)}")


# ============================================================================
# 领料申请查询接口
# ============================================================================

@router.get("/material-requests", summary="获取领料申请列表")
async def get_material_requests(
    status: Optional[str] = Query(None),
    requester_id: Optional[int] = Query(None),
    material_id: Optional[int] = Query(None),
    urgency_level: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取领料申请列表"""
    try:
        query = db.query(Request).join(Material).join(User, Request.requester)

        if status:
            query = query.filter(Request.status == status)
        if requester_id:
            query = query.filter(Request.requester_id == requester_id)
        if material_id:
            query = query.filter(Request.material_id == material_id)
        if urgency_level:
            query = query.filter(Request.urgency_level == urgency_level)
        if start_date:
            query = query.filter(Request.created_at >= start_date)
        if end_date:
            query = query.filter(Request.created_at <= end_date)
        if department:
            query = query.filter(User.department == department)
        if search:
            query = query.filter(
                db.or_(
                    Request.request_no.ilike(f"%{search}%"),
                    Material.name.ilike(f"%{search}%"),
                    Material.code.ilike(f"%{search}%")
                )
            )

        requests = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": req.id,
                        "request_no": req.request_no,
                        "order_no": req.request_no,
                        "requester_name": req.requester.real_name if req.requester else None,
                        "department_name": req.requester.department if req.requester else None,
                        "material_name": req.material.name if req.material else None,
                        "material_code": req.material.code if req.material else None,
                        "specification": req.material.specification if req.material else None,
                        "unit": req.material.unit if req.material else None,
                        "quantity": float(req.quantity),
                        "total_quantity": float(req.quantity),
                        "reason": req.reason,
                        "use_purpose": req.reason,
                        "urgency_level": req.urgency_level,
                        "project_code": req.project_code,
                        "status": req.status,
                        "leader_reviewer_name": req.leader_reviewer.real_name if req.leader_reviewer else None,
                        "leader_reviewed_at": req.leader_reviewed_at.isoformat() if req.leader_reviewed_at else None,
                        "leader_comment": req.leader_comment,
                        "warehouse_manager_name": req.warehouse_manager.real_name if req.warehouse_manager else None,
                        "outbound_at": req.outbound_at.isoformat() if req.outbound_at else None,
                        "created_at": req.created_at.isoformat() if req.created_at else None
                    } for req in requests
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取领料申请列表失败: {str(e)}")


@router.get("/material-requests/{request_id}", summary="获取领料申请详情")
async def get_material_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取领料申请详情"""
    try:
        request = db.query(Request).filter(Request.id == request_id).first()
        if not request:
            raise HTTPException(status_code=404, detail="领料申请不存在")
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": request.id,
                "request_no": request.request_no,
                "order_no": request.request_no,
                "requester_id": request.requester_id,
                "requester_name": request.requester.real_name if request.requester else None,
                "department_name": request.requester.department if request.requester else None,
                "material_id": request.material_id,
                "material_name": request.material.name if request.material else None,
                "material_code": request.material.code if request.material else None,
                "specification": request.material.specification if request.material else None,
                "unit": request.material.unit if request.material else None,
                "quantity": float(request.quantity),
                "total_quantity": float(request.quantity),
                "reason": request.reason,
                "use_purpose": request.reason,
                "urgency_level": request.urgency_level,
                "project_code": request.project_code,
                "status": request.status,
                "leader_reviewer_id": request.leader_reviewer_id,
                "leader_reviewer_name": request.leader_reviewer.real_name if request.leader_reviewer else None,
                "leader_reviewed_at": request.leader_reviewed_at.isoformat() if request.leader_reviewed_at else None,
                "leader_comment": request.leader_comment,
                "warehouse_manager_id": request.warehouse_manager_id,
                "warehouse_manager_name": request.warehouse_manager.real_name if request.warehouse_manager else None,
                "outbound_at": request.outbound_at.isoformat() if request.outbound_at else None,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "updated_at": request.updated_at.isoformat() if request.updated_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取领料申请详情失败: {str(e)}")


# ============================================================================
# 出库单查询接口
# ============================================================================

@router.get("/outbound-orders", summary="获取出库单列表")
async def get_outbound_orders(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    warehouse_manager_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取出库单列表"""
    try:
        query = db.query(OutboundOrder).join(Request).join(Material).join(Location).join(User, OutboundOrder.warehouse_manager)
        
        if start_date:
            query = query.filter(OutboundOrder.created_at >= start_date)
        if end_date:
            query = query.filter(OutboundOrder.created_at <= end_date)
        if warehouse_manager_id:
            query = query.filter(OutboundOrder.warehouse_manager_id == warehouse_manager_id)
        
        outbound_orders = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": order.id,
                        "outbound_no": order.outbound_no,
                        "request_no": order.request.request_no if order.request else None,
                        "material_name": order.material.name if order.material else None,
                        "location_code": order.location.code if order.location else None,
                        "quantity": float(order.quantity),
                        "warehouse_manager_name": order.warehouse_manager.real_name if order.warehouse_manager else None,
                        "comment": order.comment,
                        "status": order.status,
                        "created_at": order.created_at.isoformat() if order.created_at else None
                    } for order in outbound_orders
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取出库单列表失败: {str(e)}")