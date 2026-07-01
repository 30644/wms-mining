"""
库存盘点模块路由
- 盘点单管理（创建、查询、编辑、审核、作废）
- 盘点数据录入
- 库存调整执行
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from datetime import date

from app.database import get_db
from app.utils.auth import get_current_user, require_permission
from app.services.inventory_check_service import (
    InventoryCheckService, CHECK_ORDER_STATUS, CHECK_TYPE, CHECK_ITEM_STATUS
)
from app.models import User

router = APIRouter(tags=["库存盘点"])


# ========== Request Models ==========

class CreateCheckOrderRequest(BaseModel):
    """创建盘点单请求"""
    check_type: str = Field(..., description="盘点类型：full-全盘, partial-抽盘, warehouse-按仓库, category-按分类, material-按物料")
    check_date: date = Field(..., description="盘点日期")
    warehouse_id: Optional[int] = Field(None, description="仓库ID（按仓库盘点时使用）")
    category_id: Optional[int] = Field(None, description="分类ID（按分类盘点时使用）")
    material_ids: Optional[List[int]] = Field(None, description="物料ID列表（按物料盘点时使用）")
    remark: Optional[str] = Field(None, description="备注")


class InputCheckDataRequest(BaseModel):
    """录入盘点数据请求"""
    check_item_id: int = Field(..., description="盘点明细ID")
    actual_quantity: float = Field(..., description="实盘数量")
    difference_reason: Optional[str] = Field(None, description="差异原因")
    remark: Optional[str] = Field(None, description="备注")


class BatchInputCheckDataRequest(BaseModel):
    """批量录入盘点数据请求"""
    check_order_id: int = Field(..., description="盘点单ID")
    items_data: List[dict] = Field(..., description="盘点数据列表 [{item_id, actual_quantity, difference_reason, remark}, ...]")


class ReviewCheckOrderRequest(BaseModel):
    """审核盘点单请求"""
    approved: bool = Field(..., description="是否通过审核")
    review_comment: Optional[str] = Field(None, description="审核意见")


# ========== 盘点单管理接口 ==========

@router.post("/orders", summary="创建盘点单")
def create_check_order(
    request: CreateCheckOrderRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:create'))
):
    """
    创建盘点单
    
    **权限**: inventory_check:create
    
    **盘点类型**:
    - full: 全盘（所有库存物料）
    - partial: 抽盘（随机抽取部分物料）
    - warehouse: 按仓库（指定仓库的所有物料）
    - category: 按分类（指定分类的所有物料）
    - material: 按物料（指定物料列表）
    """
    success, message, order = InventoryCheckService.create_check_order(
        db=db,
        check_type=request.check_type,
        check_date=request.check_date,
        warehouse_id=request.warehouse_id,
        category_id=request.category_id,
        material_ids=request.material_ids,
        remark=request.remark,
        creator_id=current_user.id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "check_no": order.check_no,
            "check_type": order.check_type,
            "check_type_name": CHECK_TYPE.get(order.check_type),
            "check_date": order.check_date.strftime('%Y-%m-%d') if order.check_date else None,
            "status": order.status,
            "status_name": CHECK_ORDER_STATUS.get(order.status),
            "total_items": order.total_items,
            "expected_total": float(order.expected_total) if order.expected_total else 0,
            "created_at": order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None
        }
    }


@router.get("/orders", summary="获取盘点单列表")
def get_check_order_list(
    status: Optional[str] = Query(None, description="状态筛选：draft/pending_review/approved/completed/cancelled"),
    check_type: Optional[str] = Query(None, description="盘点类型筛选"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取盘点单列表（带分页）
    
    **权限**: inventory_check:list
    
    **状态说明**:
    - draft: 草稿
    - pending_review: 待审核
    - approved: 已审核
    - completed: 已完成
    - cancelled: 已作废
    """
    success, message, data, total = InventoryCheckService.get_check_order_list(
        db=db,
        status=status,
        check_type=check_type,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
        current_user={'id': current_user.id, 'role': current_user.role}
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
            "limit": limit
        }
    }


@router.get("/orders/{check_order_id}", summary="获取盘点单详情")
def get_check_order_detail(
    check_order_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取盘点单详情
    
    **权限**: inventory_check:detail
    """
    success, message, data = InventoryCheckService.get_check_order_detail(
        db=db,
        check_order_id=check_order_id,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": data
    }


@router.post("/orders/{check_order_id}/submit", summary="提交审核")
def submit_for_review(
    check_order_id: int,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:submit'))
):
    """
    提交盘点单审核
    
    **权限**: inventory_check:submit
    
    **前置条件**: 所有盘点明细已录入实盘数量
    """
    success, message, order = InventoryCheckService.submit_for_review(
        db=db,
        check_order_id=check_order_id,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "check_no": order.check_no,
            "status": order.status,
            "status_name": CHECK_ORDER_STATUS.get(order.status)
        }
    }


@router.post("/orders/{check_order_id}/review", summary="审核盘点单")
def review_check_order(
    check_order_id: int,
    request: ReviewCheckOrderRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:review'))
):
    """
    审核盘点单
    
    **权限**: inventory_check:review
    
    **审核结果**:
    - 通过：状态变为"已审核"，可执行库存调整
    - 驳回：状态变为"草稿"，可修改后重新提交
    """
    success, message, order = InventoryCheckService.review_check_order(
        db=db,
        check_order_id=check_order_id,
        approved=request.approved,
        review_comment=request.review_comment,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "check_no": order.check_no,
            "status": order.status,
            "status_name": CHECK_ORDER_STATUS.get(order.status),
            "reviewed_at": order.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if order.reviewed_at else None
        }
    }


@router.post("/orders/{check_order_id}/adjust", summary="执行库存调整")
def execute_inventory_adjustment(
    check_order_id: int,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:adjust'))
):
    """
    执行库存调整
    
    **权限**: inventory_check:adjust
    
    **前置条件**: 盘点单已审核通过
    
    **执行逻辑**:
    1. 根据实盘数量更新库存
    2. 生成库存流水记录（盘盈/盘亏）
    3. 更新盘点单状态为已完成
    """
    success, message, count = InventoryCheckService.execute_inventory_adjustment(
        db=db,
        check_order_id=check_order_id,
        current_user={'id': current_user.id, 'role': current_user.role, 'real_name': current_user.real_name}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "adjusted_count": count
        }
    }


@router.post("/orders/{check_order_id}/cancel", summary="作废盘点单")
def cancel_check_order(
    check_order_id: int,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:cancel'))
):
    """
    作废盘点单
    
    **权限**: inventory_check:cancel
    
    **限制**: 已完成或已作废的盘点单不能作废
    """
    success, message, order = InventoryCheckService.cancel_check_order(
        db=db,
        check_order_id=check_order_id,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": order.id,
            "check_no": order.check_no,
            "status": order.status,
            "status_name": CHECK_ORDER_STATUS.get(order.status)
        }
    }


# ========== 盘点数据录入接口 ==========

@router.post("/items/input", summary="录入盘点数据")
def input_check_data(
    request: InputCheckDataRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:input'))
):
    """
    录入盘点数据
    
    **权限**: inventory_check:input
    
    **说明**: 录入实盘数量，系统自动计算差异
    """
    success, message, item = InventoryCheckService.input_check_data(
        db=db,
        check_item_id=request.check_item_id,
        actual_quantity=request.actual_quantity,
        difference_reason=request.difference_reason,
        remark=request.remark,
        operator_id=current_user.id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": item.id,
            "material_id": item.material_id,
            "expected_quantity": float(item.expected_quantity) if item.expected_quantity else 0,
            "actual_quantity": float(item.actual_quantity) if item.actual_quantity else 0,
            "difference": float(item.difference) if item.difference else 0,
            "status": item.status,
            "status_name": CHECK_ITEM_STATUS.get(item.status)
        }
    }


@router.post("/items/batch-input", summary="批量录入盘点数据")
def batch_input_check_data(
    request: BatchInputCheckDataRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_check:input'))
):
    """
    批量录入盘点数据
    
    **权限**: inventory_check:input
    """
    success, message, count = InventoryCheckService.batch_input_check_data(
        db=db,
        check_order_id=request.check_order_id,
        items_data=request.items_data,
        operator_id=current_user.id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "success_count": count
        }
    }


# ========== 盘点明细接口 ==========

@router.get("/orders/{check_order_id}/items", summary="获取盘点明细列表")
def get_check_order_items(
    check_order_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取盘点明细列表

    **权限**: inventory_check:detail
    """
    from app.models import InventoryCheckItem, Material
    items = db.query(InventoryCheckItem).filter(
        InventoryCheckItem.check_order_id == check_order_id
    ).all()

    result = []
    for item in items:
        material = db.query(Material).filter(Material.id == item.material_id).first()
        result.append({
            "id": item.id,
            "material_id": item.material_id,
            "material_code": material.code if material else "",
            "material_name": material.name if material else "",
            "system_quantity": float(item.expected_quantity) if item.expected_quantity else 0,
            "actual_quantity": float(item.actual_quantity) if item.actual_quantity else 0,
            "difference": float(item.difference) if item.difference else 0,
            "status": item.status,
            "status_name": CHECK_ITEM_STATUS.get(item.status),
            "remark": item.remark or "",
        })

    return {"code": 0, "message": "获取成功", "data": {"list": result}}


# ========== 辅助接口 ==========

@router.get("/types", summary="获取盘点类型列表")
def get_check_types():
    """获取盘点类型列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in CHECK_TYPE.items()
        ]
    }


@router.get("/statuses", summary="获取盘点单状态列表")
def get_check_statuses():
    """获取盘点单状态列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in CHECK_ORDER_STATUS.items()
        ]
    }


@router.get("/item-statuses", summary="获取盘点明细状态列表")
def get_check_item_statuses():
    """获取盘点明细状态列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in CHECK_ITEM_STATUS.items()
        ]
    }