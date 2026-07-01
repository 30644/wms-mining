"""
用户管理相关API路由 - 仅限超级管理员
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.utils.auth import get_current_user, require_role
from app.schemas.user import (
    CreateUserRequest, UpdateUserRequest, UserResponse,
    UserListResponse, ResetPasswordRequest, RolePermissionResponse,
    RolePermissionUpdateRequest, PermissionListResponse,
    CreateRoleRequest, UpdateRoleRequest, RoleDefinitionResponse
)
from app.schemas.common import APIResponse, PaginationParams
from app.services.auth_service import UserService
from app.utils.business_tools import PermissionService
from app.utils.logger import logger
from app.config import SUPER_ADMIN_ROLE

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.post("", response_model=UserResponse, summary="创建用户")
async def create_user(
    user_data: CreateUserRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    创建新用户（仅超级管理员）
    
    要求：
    - 调用者必须是超级管理员
    - 用户名唯一
    - 密码必须满足强度要求
    """
    logger.info(f"创建用户请求 | 操作人: {current_user.username} | 新用户: {user_data.username}")

    # 校验角色存在
    all_roles = PermissionService.get_roles(db)
    if user_data.role not in all_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"角色 '{user_data.role}' 不存在")

    success, message, new_user = UserService.create_user(
        username=user_data.username,
        password=user_data.password,
        real_name=user_data.real_name,
        department=user_data.department,
        role=user_data.role,
        email=user_data.email,
        phone=user_data.phone,
        created_by=current_user.id,
        db=db
    )
    
    if not success:
        logger.warning(f"创建用户失败 | 操作人: {current_user.username} | 原因: {message}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    
    logger.info(f"创建用户成功 | 用户ID: {new_user.id} | 用户名: {new_user.username}")
    return UserResponse.from_orm(new_user)


@router.get("", response_model=APIResponse, summary="获取用户列表")
async def get_users(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=10000, description="每页数量"),
    role: str = Query(None, description="按角色筛选"),
    department: str = Query(None, description="按部门筛选"),
    is_active: bool = Query(None, description="按启用状态筛选"),
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    获取用户列表（仅超级管理员）
    
    支持按角色、部门、启用状态筛选
    """
    logger.info(f"查询用户列表 | 操作人: {current_user.username}")
    
    total, users = UserService.get_user_list(
        page=page,
        page_size=page_size,
        role=role,
        department=department,
        is_active=is_active,
        db=db
    )
    
    items_list = [UserResponse.from_orm(user).dict() for user in users]

    return APIResponse(
        code=0,
        message="获取成功",
        data={
            'list': items_list,
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    )


@router.get("/roles", summary="获取系统角色权限列表")
async def get_role_permissions_list(
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """获取系统所有角色及其权限配置"""
    logger.info(f"查询角色权限列表 | 操作人: {current_user.username}")

    definitions = PermissionService.get_role_definitions(db)
    return definitions


@router.get("/roles/{role}/permissions", response_model=RolePermissionResponse, summary="获取指定角色权限")
async def get_role_permissions(
    role: str,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """获取指定角色的权限配置"""
    all_roles = PermissionService.get_roles(db)
    if role not in all_roles:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")

    permissions = PermissionService.get_role_permissions(role, db)
    return RolePermissionResponse(role=role, permissions=permissions)


@router.put("/roles/{role}/permissions", response_model=APIResponse, summary="更新指定角色权限")
async def update_role_permissions(
    role: str,
    req: RolePermissionUpdateRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """更新指定角色的权限配置"""
    all_roles = PermissionService.get_roles(db)
    if role not in all_roles:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")

    success, message = PermissionService.set_role_permissions(role, req.permissions, current_user.id, db)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    logger.info(f"角色权限更新成功 | 角色: {role} | 操作人: {current_user.username}")
    return APIResponse(code=0, message=message)


@router.post("/roles", response_model=APIResponse, summary="创建自定义角色")
async def create_role(
    req: CreateRoleRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """创建自定义角色（仅超级管理员）"""
    success, message = PermissionService.create_role(
        db=db, name=req.name, display_name=req.display_name,
        description=req.description, permissions=req.permissions,
        created_by=current_user.id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    logger.info(f"创建角色成功 | 角色: {req.name} | 操作人: {current_user.username}")
    return APIResponse(code=0, message=message)


@router.put("/roles/{role}", response_model=APIResponse, summary="更新角色信息")
async def update_role(
    role: str,
    req: UpdateRoleRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """更新角色信息（仅超级管理员）"""
    success, message = PermissionService.update_role(
        db=db, name=role, display_name=req.display_name,
        description=req.description, updated_by=current_user.id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return APIResponse(code=0, message=message)


@router.delete("/roles/{role}", response_model=APIResponse, summary="删除自定义角色")
async def delete_role(
    role: str,
    force: bool = Query(False, description="是否强制删除（同时删除使用该角色的用户）"),
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """删除自定义角色（仅超级管理员，系统角色不可删除）"""
    success, message = PermissionService.delete_role(
        db=db, name=role, deleted_by=current_user.id, force=force,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return APIResponse(code=0, message=message)


@router.get("/permissions", response_model=PermissionListResponse, summary="获取系统权限列表")
async def get_permissions(
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """获取系统中可分配的所有权限"""
    return PermissionListResponse(permissions=list(PermissionService.get_all_permissions().keys()))


@router.get("/{user_id}", response_model=UserResponse, summary="获取用户详情")
async def get_user(
    user_id: int,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    获取指定用户的详细信息（仅超级管理员）
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        logger.warning(f"用户不存在 | 用户ID: {user_id}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    return UserResponse.from_orm(user)


@router.get("/{user_id}/permissions", response_model=PermissionListResponse, summary="获取用户权限")
async def get_user_permissions(
    user_id: int,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """获取指定用户的实际权限列表"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    permissions = PermissionService.get_user_permissions(user_id, db)
    return PermissionListResponse(permissions=permissions)


@router.put("/{user_id}", response_model=UserResponse, summary="编辑用户")
async def update_user(
    user_id: int,
    user_data: UpdateUserRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    编辑用户信息（仅超级管理员）
    
    支持修改：姓名、部门、角色、邮箱、手机号
    """
    logger.info(f"编辑用户请求 | 操作人: {current_user.username} | 目标用户ID: {user_id}")

    # 校验角色存在
    if user_data.role:
        all_roles = PermissionService.get_roles(db)
        if user_data.role not in all_roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"角色 '{user_data.role}' 不存在")

    # 防止修改超级管理员本身
    if user_id == current_user.id:
        logger.warning(f"禁止修改自己的信息 | 用户ID: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能修改自己的信息"
        )
    
    success, message, updated_user = UserService.update_user(
        user_id=user_id,
        real_name=user_data.real_name,
        department=user_data.department,
        role=user_data.role,
        email=user_data.email,
        phone=user_data.phone,
        updated_by=current_user.id,
        db=db
    )
    
    if not success:
        logger.warning(f"编辑用户失败 | 目标用户ID: {user_id} | 原因: {message}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    
    return UserResponse.from_orm(updated_user)


@router.post("/{user_id}/disable", response_model=APIResponse, summary="禁用用户")
async def disable_user(
    user_id: int,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    禁用用户账户（仅超级管理员）
    
    被禁用的用户无法登录
    """
    logger.info(f"禁用用户请求 | 操作人: {current_user.username} | 目标用户ID: {user_id}")
    
    # 防止禁用超级管理员本身
    if user_id == current_user.id:
        logger.warning(f"禁止禁用自己 | 用户ID: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能禁用自己"
        )
    
    success, message = UserService.disable_user(
        user_id=user_id,
        disabled_by=current_user.id,
        db=db
    )
    
    if not success:
        logger.warning(f"禁用用户失败 | 目标用户ID: {user_id} | 原因: {message}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    
    return APIResponse(code=0, message=message)


@router.post("/{user_id}/enable", response_model=APIResponse, summary="启用用户")
async def enable_user(
    user_id: int,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    启用已禁用的用户账户（仅超级管理员）
    """
    logger.info(f"启用用户请求 | 操作人: {current_user.username} | 目标用户ID: {user_id}")
    
    success, message = UserService.enable_user(
        user_id=user_id,
        enabled_by=current_user.id,
        db=db
    )
    
    if not success:
        logger.warning(f"启用用户失败 | 目标用户ID: {user_id} | 原因: {message}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    
    return APIResponse(code=0, message=message)


@router.post("/{user_id}/reset-password", response_model=APIResponse, summary="重置用户密码")
async def reset_password(
    user_id: int,
    password_data: ResetPasswordRequest,
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE)),
    db: Session = Depends(get_db)
):
    """
    重置用户密码为新密码（仅超级管理员）
    
    用户下次登录时需要使用新密码
    """
    logger.info(f"重置密码请求 | 操作人: {current_user.username} | 目标用户ID: {user_id}")
    
    success, message = UserService.reset_password(
        user_id=user_id,
        new_password=password_data.new_password,
        reset_by=current_user.id,
        db=db
    )
    
    if not success:
        logger.warning(f"重置密码失败 | 目标用户ID: {user_id} | 原因: {message}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    
    return APIResponse(code=0, message=message)
