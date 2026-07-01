"""
采购清单模块路由
- 采购清单CRUD
- 审批流转
- 采购执行
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.utils.auth import get_current_user, require_permission
from app.services.purchase_service import PurchaseService
from app.models import User, PURCHASE_STATUS

router = APIRouter(tags=["采购清单"])


# ========== Request Models ==========

class CreatePurchaseRequest(BaseModel):
    """创建采购清单请求"""
    material_id: Optional[int] = Field(None, description="物料ID（与物料名称二选一）")
    material_name: Optional[str] = Field(None, description="物料名称（新增物料时填写）")
    material_spec: Optional[str] = Field(None, description="规格型号")
    material_unit: Optional[str] = Field(None, description="单位")
    material_category_name: Optional[str] = Field(None, description="物料分类名称")
    warehouse_id: int = Field(..., description="仓库ID")
    quantity: float = Field(..., gt=0, description="采购数量")
    source_alert_id: Optional[int] = Field(None, description="关联预警ID")
    remark: Optional[str] = Field(None, description="备注")


class ApprovePurchaseRequest(BaseModel):
    """审批采购请求"""
    action: str = Field('approve', description="审批动作: approve/reject")
    comment: Optional[str] = Field(None, description="审批意见")


class ExecutePurchaseRequest(BaseModel):
    """执行采购请求"""
    remark: Optional[str] = Field(None, description="备注")


# ========== 采购清单管理接口 ==========

@router.post("/purchases", summary="创建采购清单")
def create_purchase(
    request: CreatePurchaseRequest,
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:create'))
):
    """
    创建采购清单

    **权限**: purchase:create

    **说明**:
    - 从库存预警触发时传 source_alert_id
    - 创建后自动进入审批流程（pending_team_leader）
    """
    success, message, order = PurchaseService.create_purchase(
        db=db,
        material_id=request.material_id,
        material_name=request.material_name,
        material_spec=request.material_spec,
        material_unit=request.material_unit,
        material_category_name=request.material_category_name,
        warehouse_id=request.warehouse_id,
        quantity=request.quantity,
        applicant_id=current_user.id,
        source='alert' if request.source_alert_id else 'manual',
        source_alert_id=request.source_alert_id,
        remark=request.remark,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "purchase_no": order.purchase_no,
            "status": order.status,
            "status_name": PURCHASE_STATUS.get(order.status),
        }
    }


@router.get("/purchases", summary="获取采购清单列表")
def get_purchase_list(
    status: Optional[str] = Query(None, description="状态筛选"),
    material_id: Optional[int] = Query(None, description="物料ID筛选"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:list'))
):
    """
    获取采购清单列表

    **权限**: purchase:list
    """
    success, message, data, total = PurchaseService.get_purchase_list(
        db=db,
        status=status,
        material_id=material_id,
        warehouse_id=warehouse_id,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "code": 0,
        "message": message,
        "data": {
            "list": data or [],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    }


@router.get("/purchases/{purchase_id}", summary="获取采购清单详情")
def get_purchase_detail(
    purchase_id: int,
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:detail'))
):
    """
    获取采购清单详情

    **权限**: purchase:detail
    """
    success, message, data = PurchaseService.get_purchase_detail(
        db=db, purchase_id=purchase_id
    )

    if not success:
        raise HTTPException(status_code=404, detail=message)

    return {
        "code": 0,
        "message": message,
        "data": data,
    }


@router.post("/purchases/{purchase_id}/approve", summary="审批采购清单")
def approve_purchase(
    purchase_id: int,
    request: ApprovePurchaseRequest,
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:approve'))
):
    """
    审批采购清单

    **权限**: purchase:approve

    **审批流程**:
    - 班长审批 → pending_technical
    - 技术员审批 → pending_auditor
    - 审核员审批 → approved（推送到采购员）
    """
    success, message, order = PurchaseService.approve_purchase(
        db=db,
        purchase_id=purchase_id,
        reviewer_id=current_user.id,
        action=request.action,
        comment=request.comment,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "status": order.status,
            "status_name": PURCHASE_STATUS.get(order.status),
            "reviewed_at": order.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if order.reviewed_at else None,
        }
    }


@router.post("/purchases/{purchase_id}/execute", summary="执行采购")
def execute_purchase(
    purchase_id: int,
    request: ExecutePurchaseRequest = None,
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:execute'))
):
    """
    执行采购（采购员确认）

    **权限**: purchase:execute

    **说明**: 仅采购员可操作，将状态从 approved 变为 completed
    """
    remark = request.remark if request else None
    success, message, order = PurchaseService.execute_purchase(
        db=db,
        purchase_id=purchase_id,
        purchaser_id=current_user.id,
        remark=remark,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "status": order.status,
            "status_name": PURCHASE_STATUS.get(order.status),
        }
    }


@router.post("/purchases/{purchase_id}/cancel", summary="作废采购清单")
def cancel_purchase(
    purchase_id: int,
    reason: Optional[str] = Query(None, description="作废原因"),
    db=Depends(get_db),
    current_user: User = Depends(require_permission('purchase:cancel')),
):
    """
    作废采购清单

    **权限**: purchase:cancel
    """
    success, message = PurchaseService.cancel_purchase(
        db=db, purchase_id=purchase_id, user_id=current_user.id, reason=reason
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "code": 0,
        "message": message,
    }


# ========== 辅助接口 ==========

@router.get("/purchase-statuses", summary="获取采购状态列表")
def get_purchase_statuses():
    """获取采购状态列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in PURCHASE_STATUS.items()
        ]
    }
