from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.scrap_service import ScrapService
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


class ScrapOrderItemRequest(BaseModel):
    material_id: int = Field(..., description="物料ID")
    quantity: float = Field(..., gt=0, description="报损数量")
    unit_price: float = Field(..., ge=0, description="单价")


class CreateScrapOrderRequest(BaseModel):
    warehouse_id: int = Field(..., description="仓库ID")
    scrap_date: str = Field(..., description="报损日期，YYYY-MM-DD")
    reason: Optional[str] = Field(None, description="报损原因")
    remark: Optional[str] = Field(None, description="备注")
    items: List[ScrapOrderItemRequest] = Field(..., description="报损明细")


@router.post("", summary="创建报废单", status_code=http_status.HTTP_201_CREATED)
async def create_scrap_order(
    request: CreateScrapOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = ScrapService.create_scrap_order(
            warehouse_id=request.warehouse_id,
            scrap_date=request.scrap_date,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=False
        )
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message='报废单创建成功', data={'order_id': order.id, 'order_no': order.scrap_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建报废单失败: {str(e)}")


@router.post("/create-and-submit", summary="创建并提交报废单", status_code=http_status.HTTP_201_CREATED)
async def create_and_submit_scrap_order(
    request: CreateScrapOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:create', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg, order = ScrapService.create_scrap_order(
            warehouse_id=request.warehouse_id,
            scrap_date=request.scrap_date,
            reason=request.reason,
            remark=request.remark,
            items=[item.dict() for item in request.items],
            operator_id=current_user.id,
            db=db,
            submit=True
        )
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message='报废单创建并提交成功', data={'order_id': order.id, 'order_no': order.scrap_no})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建并提交报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建并提交报废单失败: {str(e)}")


@router.get("/list", summary="获取报废单列表")
async def list_scrap_orders(
    order_no: Optional[str] = Query(None, description='单号模糊搜索'),
    status: Optional[str] = Query(None, description='单据状态'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        items, total = ScrapService.list_scrap_orders(order_no, status, page, page_size, db)
        return APIResponse(code=0, message='获取报废单列表成功', data={'list': items, 'total': total, 'page': page, 'page_size': page_size})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取报废单列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取报废单列表失败: {str(e)}")


@router.get("/{order_id}", summary="获取报废单详情")
async def get_scrap_order_detail(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:view', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        order = ScrapService.get_scrap_order_detail(order_id, db)
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail='报废单不存在')
        return APIResponse(code=0, message='获取报废单详情成功', data=order)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取报废单详情异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取报废单详情失败: {str(e)}")


@router.post("/{order_id}/submit", summary="提交报废单")
async def submit_scrap_order(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:submit', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ScrapService.submit_scrap_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"提交报废单失败: {str(e)}")


@router.post("/{order_id}/approve", summary="审核报废单")
async def approve_scrap_order(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:approve', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ScrapService.approve_scrap_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"审核报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"审核报废单失败: {str(e)}")


@router.post("/{order_id}/execute", summary="执行报废单")
async def execute_scrap_order(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:execute', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ScrapService.execute_scrap_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行报废单失败: {str(e)}")


@router.post("/{order_id}/cancel", summary="取消报废单")
async def cancel_scrap_order(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'scrap:cancel', db):
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        success, msg = ScrapService.cancel_scrap_order(order_id, db)
        if not success:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消报废单异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"取消报废单失败: {str(e)}")


@router.post("/{order_id}/sync-to-nc", summary="同步报废单到NC6.5")
async def sync_scrap_to_nc(
    order_id: int = Path(..., description='报废单ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        from app.services.nc_sync_service import NcSyncService
        success, msg = NcSyncService.sync_scrap_to_nc(order_id, db)
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        return APIResponse(code=0, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步报废单到NC异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")
