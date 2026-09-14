from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.transfer_service import TransferService
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


class TransferOrderItemRequest(BaseModel):
    material_id: int = Field(..., description="物料ID")
    quantity: float = Field(..., gt=0, description="调拨数量")


class CreateTransferOrderRequest(BaseModel):
    from_warehouse_id: int = Field(..., description="调出仓库ID")
    to_warehouse_id: int = Field(..., description="调入仓库ID")
    from_location_id: Optional[int] = Field(None, description="调出库位ID")
    to_location_id: Optional[int] = Field(None, description="调入库位ID")
    reason: Optional[str] = Field(None, description="调拨原因")
    remark: Optional[str] = Field(None, description="备注")
    items: List[TransferOrderItemRequest] = Field(..., description="调拨明细")


@router.post("", summary="创建调拨单", status_code=http_status.HTTP_201_CREATED)
async def create_transfer_order(
    request: CreateTransferOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = TransferService.create_transfer_order(
            from_warehouse_id=request.from_warehouse_id,
            to_warehouse_id=request.to_warehouse_id,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=False,
            from_location_id=request.from_location_id,
            to_location_id=request.to_location_id,
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(code=0, message='调拨单创建成功', data={'order_id': order.id, 'order_no': order.transfer_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建调拨单失败: {str(e)}")


@router.post("/create-and-submit", summary="创建并提交调拨单", status_code=http_status.HTTP_201_CREATED)
async def create_and_submit_transfer_order(
    request: CreateTransferOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = TransferService.create_transfer_order(
            from_warehouse_id=request.from_warehouse_id,
            to_warehouse_id=request.to_warehouse_id,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=True,
            from_location_id=request.from_location_id,
            to_location_id=request.to_location_id,
        )

        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(code=0, message='调拨单创建并提交成功', data={'order_id': order.id, 'order_no': order.transfer_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建并提交调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建并提交调拨单失败: {str(e)}")


@router.get("/list", summary="获取调拨单列表")
async def list_transfer_orders(
    order_no: Optional[str] = Query(None, description='单号模糊搜索'),
    status: Optional[str] = Query(None, description='单据状态'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        items, total = TransferService.list_transfer_orders(order_no, status, page, page_size, db)
        return APIResponse(code=0, message='获取调拨单列表成功', data={'list': items, 'total': total, 'page': page, 'page_size': page_size})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取调拨单列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取调拨单列表失败: {str(e)}")


@router.get("/{order_id}", summary="获取调拨单详情")
async def get_transfer_order_detail(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        order = TransferService.get_transfer_order_detail(order_id, db)
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail='调拨单不存在')
        return APIResponse(code=0, message='获取调拨单详情成功', data=order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取调拨单详情异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取调拨单详情失败: {str(e)}")


@router.post("/{order_id}/submit", summary="提交调拨单")
async def submit_transfer_order(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:submit', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = TransferService.submit_transfer_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交调拨单失败: {str(e)}")


@router.post("/{order_id}/approve", summary="审核调拨单")
async def approve_transfer_order(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:approve', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = TransferService.approve_transfer_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"审核调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"审核调拨单失败: {str(e)}")


@router.post("/{order_id}/execute", summary="执行调拨单")
async def execute_transfer_order(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:execute', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = TransferService.execute_transfer_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行调拨单失败: {str(e)}")


@router.post("/{order_id}/cancel", summary="取消调拨单")
async def cancel_transfer_order(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'transfer:cancel', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = TransferService.cancel_transfer_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消调拨单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消调拨单失败: {str(e)}")


@router.post("/{order_id}/sync-to-nc", summary="同步调拨单到NC6.5")
async def sync_transfer_to_nc(
    order_id: int = Path(..., description='调拨单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        from app.services.nc_sync_service import NcSyncService
        success, msg = NcSyncService.sync_transfer_to_nc(order_id, db)
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步调拨单到NC异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
