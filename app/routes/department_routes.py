"""
部门管理API路由
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import Department, User
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.config import SUPER_ADMIN_ROLE
from app.utils.logger import logger

router = APIRouter()


class DepartmentCreateRequest(BaseModel):
    parent_id: Optional[int] = Field(None, description='上级部门ID')
    name: str = Field(..., description='部门名称')
    code: str = Field(..., description='部门编码')
    leader: Optional[str] = Field(None, description='负责人')
    phone: Optional[str] = Field(None, description='联系电话')
    sort: int = Field(0, description='排序')
    status: str = Field('active', description='状态')


class DepartmentUpdateRequest(BaseModel):
    parent_id: Optional[int] = Field(None, description='上级部门ID')
    name: Optional[str] = Field(None, description='部门名称')
    code: Optional[str] = Field(None, description='部门编码')
    leader: Optional[str] = Field(None, description='负责人')
    phone: Optional[str] = Field(None, description='联系电话')
    sort: Optional[int] = Field(None, description='排序')
    status: Optional[str] = Field(None, description='状态')


def _to_tree(dept, all_depts):
    """将部门列表转为树形结构"""
    children = [d for d in all_depts if d.parent_id == dept.id]
    parent = next((d for d in all_depts if d.id == dept.parent_id), None)
    return {
        'id': dept.id,
        'parent_id': dept.parent_id,
        'parent_name': parent.name if parent else None,
        'name': dept.name,
        'code': dept.code,
        'leader': dept.leader,
        'phone': dept.phone,
        'sort': dept.sort,
        'status': dept.status,
        'created_at': dept.created_at.isoformat() if dept.created_at else None,
        'children': [_to_tree(child, all_depts) for child in children],
    }


@router.get('/list', summary='获取部门列表（树形）')
async def list_departments(
    name: Optional[str] = Query(None, description='按名称筛选'),
    code: Optional[str] = Query(None, description='按编码筛选'),
    status: Optional[str] = Query(None, description='按状态筛选'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        q = db.query(Department)
        if name:
            q = q.filter(Department.name.like(f'%{name}%'))
        if code:
            q = q.filter(Department.code.like(f'%{code}%'))
        if status:
            q = q.filter(Department.status == status)
        all_depts = q.order_by(Department.sort).all()
        root_depts = [d for d in all_depts if d.parent_id is None]
        tree = [_to_tree(dept, all_depts) for dept in root_depts]
        return APIResponse(code=0, message='获取成功', data={'list': tree, 'total': len(tree)})
    except Exception as e:
        logger.error(f"获取部门列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'获取部门列表失败: {str(e)}')


@router.post('', summary='创建部门', status_code=status.HTTP_201_CREATED)
async def create_department(
    request: DepartmentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        exists = db.query(Department).filter(Department.code == request.code).first()
        if exists:
            raise HTTPException(status_code=400, detail='部门编码已存在')
        dept = Department(**request.dict())
        db.add(dept)
        db.commit()
        db.refresh(dept)
        return APIResponse(code=0, message='创建成功', data={'id': dept.id})
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建部门失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'创建部门失败: {str(e)}')


@router.put('/{department_id}', summary='更新部门')
async def update_department(
    department_id: int = Path(..., description='部门ID'),
    request: DepartmentUpdateRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail='部门不存在')
        update_data = {k: v for k, v in request.dict().items() if v is not None}
        if 'code' in update_data:
            exists = db.query(Department).filter(Department.code == update_data['code'], Department.id != department_id).first()
            if exists:
                raise HTTPException(status_code=400, detail='部门编码已存在')
        for key, value in update_data.items():
            setattr(dept, key, value)
        db.commit()
        return APIResponse(code=0, message='更新成功')
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新部门失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'更新部门失败: {str(e)}')


@router.delete('/{department_id}', summary='删除部门')
async def delete_department(
    department_id: int = Path(..., description='部门ID'),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail='部门不存在')
        children = db.query(Department).filter(Department.parent_id == department_id).count()
        if children > 0:
            raise HTTPException(status_code=400, detail='该部门存在子部门，无法删除')
        db.delete(dept)
        db.commit()
        return APIResponse(code=0, message='删除成功')
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除部门失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f'删除部门失败: {str(e)}')
