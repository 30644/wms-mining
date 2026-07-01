from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import Supplier
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


class SupplierRequest(BaseModel):
    supplier_name: str = Field(..., description='供应商名称')
    contact: Optional[str] = Field(None, description='联系人')
    phone: Optional[str] = Field(None, description='联系电话')
    address: Optional[str] = Field(None, description='地址')
    is_active: Optional[bool] = Field(True, description='是否启用')


@router.get('/list', summary='获取供应商列表')
async def list_suppliers(
    search: Optional[str] = Query(None, description='供应商名称模糊搜索'),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'supplier:view', db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        query = db.query(Supplier)
        if search:
            query = query.filter(Supplier.supplier_name.contains(search))
        total = query.count()
        suppliers = query.offset(skip).limit(limit).all()
        return APIResponse(code=0, message='获取供应商列表成功', data={
            'list': [
                {
                    'id': s.id,
                    'supplier_name': s.supplier_name,
                    'contact': s.contact,
                    'phone': s.phone,
                    'address': s.address,
                    'is_active': s.is_active,
                    'created_at': s.created_at.isoformat() if s.created_at else None
                } for s in suppliers
            ],
            'total': total,
            'skip': skip,
            'limit': limit
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'获取供应商列表失败: {str(e)}')
        raise HTTPException(status_code=500, detail=f'获取供应商列表失败: {str(e)}')


@router.post('', summary='创建供应商', status_code=status.HTTP_201_CREATED)
async def create_supplier(
    request: SupplierRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'supplier:create', db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')

        supplier = Supplier(
            supplier_name=request.supplier_name,
            contact=request.contact,
            phone=request.phone,
            address=request.address,
            is_active=request.is_active
        )
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
        return APIResponse(code=0, message='供应商创建成功', data={'id': supplier.id})
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f'创建供应商失败: {str(e)}')
        raise HTTPException(status_code=500, detail=f'创建供应商失败: {str(e)}')


@router.get('/{supplier_id}', summary='获取供应商详情')
async def get_supplier(
    supplier_id: int = Path(..., description='供应商ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'supplier:view', db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')
        supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='供应商不存在')
        return APIResponse(code=0, message='获取供应商详情成功', data={
            'id': supplier.id,
            'supplier_name': supplier.supplier_name,
            'contact': supplier.contact,
            'phone': supplier.phone,
            'address': supplier.address,
            'is_active': supplier.is_active,
            'created_at': supplier.created_at.isoformat() if supplier.created_at else None
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'获取供应商详情失败: {str(e)}')


@router.put('/{supplier_id}', summary='更新供应商')
async def update_supplier(
    supplier_id: int = Path(..., description='供应商ID'),
    request: SupplierRequest = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'supplier:update', db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')
        supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='供应商不存在')
        supplier.supplier_name = request.supplier_name
        supplier.contact = request.contact
        supplier.phone = request.phone
        supplier.address = request.address
        supplier.is_active = request.is_active
        db.commit()
        return APIResponse(code=0, message='供应商更新成功')
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f'更新供应商失败: {str(e)}')


@router.delete('/{supplier_id}', summary='删除供应商')
async def delete_supplier(
    supplier_id: int = Path(..., description='供应商ID'),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, 'supplier:delete', db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无权限执行此操作')
        supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=404, detail='供应商不存在')
        db.delete(supplier)
        db.commit()
        return APIResponse(code=0, message='供应商删除成功')
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f'删除供应商失败: {str(e)}')
