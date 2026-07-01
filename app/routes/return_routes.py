from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.return_service import ReturnService
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


class ReturnOrderItemRequest(BaseModel):
    material_id: int = Field(..., description="物料ID")
    quantity: float = Field(..., gt=0, description="退货数量")


class CreateReturnOrderRequest(BaseModel):
    supplier_id: Optional[int] = Field(None, description="供应商ID")
    warehouse_id: int = Field(..., description="仓库ID")
    return_date: Optional[str] = Field(None, description="退货日期，YYYY-MM-DD")
    reason: Optional[str] = Field(None, description="退货原因")
    remark: Optional[str] = Field(None, description="备注")
    items: List[ReturnOrderItemRequest] = Field(..., description="退货明细")


@router.post("", summary="创建退货单", status_code=http_status.HTTP_201_CREATED)
async def create_return_order(
    request: CreateReturnOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = ReturnService.create_return_order(
            supplier_id=request.supplier_id,
            warehouse_id=request.warehouse_id,
            return_date=request.return_date,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=False
        )
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message='退货单创建成功', data={'order_id': order.id, 'order_no': order.return_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建退货单失败: {str(e)}")


@router.post("/create-and-submit", summary="创建并提交退货单", status_code=http_status.HTTP_201_CREATED)
async def create_and_submit_return_order(
    request: CreateReturnOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = ReturnService.create_return_order(
            supplier_id=request.supplier_id,
            warehouse_id=request.warehouse_id,
            return_date=request.return_date,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=True
        )
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message='退货单创建并提交成功', data={'order_id': order.id, 'order_no': order.return_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建并提交退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建并提交退货单失败: {str(e)}")


@router.get("/list", summary="获取退货单列表")
async def list_return_orders(
    order_no: Optional[str] = Query(None, description='单号模糊搜索'),
    status: Optional[str] = Query(None, description='单据状态'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        items, total = ReturnService.list_return_orders(order_no, status, page, page_size, db)
        return APIResponse(code=0, message='获取退货单列表成功', data={'list': items, 'total': total, 'page': page, 'page_size': page_size})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取退货单列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取退货单列表失败: {str(e)}")


@router.get("/{order_id}", summary="获取退货单详情")
async def get_return_order_detail(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        order = ReturnService.get_return_order_detail(order_id, db)
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail='退货单不存在')
        return APIResponse(code=0, message='获取退货单详情成功', data=order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取退货单详情异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取退货单详情失败: {str(e)}")


@router.post("/{order_id}/submit", summary="提交退货单")
async def submit_return_order(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:submit', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ReturnService.submit_return_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交退货单失败: {str(e)}")


@router.post("/{order_id}/approve", summary="审核退货单")
async def approve_return_order(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:approve', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ReturnService.approve_return_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"审核退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"审核退货单失败: {str(e)}")


@router.post("/{order_id}/execute", summary="执行退货单")
async def execute_return_order(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:execute', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ReturnService.execute_return_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行退货单失败: {str(e)}")


@router.post("/{order_id}/cancel", summary="取消退货单")
async def cancel_return_order(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'return:cancel', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ReturnService.cancel_return_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消退货单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消退货单失败: {str(e)}")


@router.post("/{order_id}/sync-to-nc", summary="同步退货单到NC6.5")
async def sync_return_to_nc(
    order_id: int = Path(..., description='退货单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        from app.services.nc_sync_service import NcSyncService
        success, msg = NcSyncService.sync_return_to_nc(order_id, db)
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步退货单到NC异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
