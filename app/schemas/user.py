"""
数据验证模型 - 用户管理相关
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime


class CreateUserRequest(BaseModel):
    """创建用户请求"""
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=8, description="初始密码")
    real_name: str = Field(..., min_length=1, max_length=50, description="真实姓名")
    department: str = Field(..., min_length=1, max_length=50, description="部门")
    role: str = Field(..., description="用户角色")
    email: Optional[str] = Field(None, description="邮箱")
    phone: Optional[str] = Field(None, description="手机号")
    
    @validator('password')
    def validate_password_strength(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not any(c.islower() for c in v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not any(c.isdigit() for c in v):
            raise ValueError('密码必须包含至少一个数字')
        return v
    
    @validator('role')
    def validate_role(cls, v):
        if not v or not v.strip():
            raise ValueError('角色不能为空')
        return v.strip()

    class Config:
        schema_extra = {
            "example": {
                "username": "emp001",
                "password": "Employee@2026",
                "real_name": "张三",
                "department": "车间A",
                "role": "employee",
                "email": "emp001@example.com",
                "phone": "13800000001"
            }
        }


class UpdateUserRequest(BaseModel):
    """更新用户请求"""
    real_name: Optional[str] = Field(None, min_length=1, max_length=50, description="真实姓名")
    department: Optional[str] = Field(None, min_length=1, max_length=50, description="部门")
    role: Optional[str] = Field(None, description="用户角色")
    email: Optional[str] = Field(None, description="邮箱")
    phone: Optional[str] = Field(None, description="手机号")
    
    @validator('role')
    def validate_role_not_empty(cls, v):
        if v is not None and not v.strip():
            raise ValueError('角色不能为空')
        return v.strip() if v else v
    
    class Config:
        schema_extra = {
            "example": {
                "real_name": "李四",
                "department": "车间B",
                "role": "team_leader",
                "email": "emp002@example.com",
                "phone": "13800000002"
            }
        }


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    new_password: str = Field(..., min_length=8, description="新密码")
    
    @validator('new_password')
    def validate_password_strength(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('密码必须包含至少一个大写字母')
        if not any(c.islower() for c in v):
            raise ValueError('密码必须包含至少一个小写字母')
        if not any(c.isdigit() for c in v):
            raise ValueError('密码必须包含至少一个数字')
        return v


class UpdateRoleRequest(BaseModel):
    """更新用户角色请求"""
    role: str = Field(..., description="新角色")
    
    @validator('role')
    def validate_role(cls, v):
        from app.config import SYSTEM_ROLES
        if v not in SYSTEM_ROLES:
            raise ValueError(f'角色不存在，允许的角色: {", ".join(SYSTEM_ROLES)}')
        return v


class UserResponse(BaseModel):
    """用户响应"""
    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    real_name: Optional[str] = Field('', description="真实姓名")
    department: Optional[str] = Field('', description="部门")
    role: Optional[str] = Field('', description="角色")
    email: Optional[str] = Field(None, description="邮箱")
    phone: Optional[str] = Field(None, description="手机号")
    description: Optional[str] = Field(None, description="描述")
    is_active: bool = Field(True, description="是否启用")
    last_login_at: Optional[datetime] = Field(None, description="最后登录时间")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    
    class Config:
        from_attributes = True
        schema_extra = {
            "example": {
                "id": 2,
                "username": "emp001",
                "real_name": "张三",
                "department": "车间A",
                "role": "employee",
                "email": "emp001@example.com",
                "phone": "13800000001",
                "is_active": True,
                "last_login_at": None,
                "created_at": "2026-04-21T08:00:00",
                "updated_at": "2026-04-21T08:00:00"
            }
        }


class UserListResponse(BaseModel):
    """用户列表响应"""
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页")
    page_size: int = Field(..., description="每页数量")
    items: List[UserResponse] = Field(..., description="用户列表")
    
    class Config:
        schema_extra = {
            "example": {
                "total": 10,
                "page": 1,
                "page_size": 20,
                "items": []
            }
        }


class LoginLogResponse(BaseModel):
    """登录日志响应"""
    id: int = Field(..., description="日志ID")
    user_id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    login_time: datetime = Field(..., description="登录时间")
    ip_address: Optional[str] = Field(None, description="登录IP")
    user_agent: Optional[str] = Field(None, description="用户代理")
    status: str = Field(..., description="登录状态: success/failed")
    error_message: Optional[str] = Field(None, description="错误信息")
    
    class Config:
        from_attributes = True


class RolePermissionResponse(BaseModel):
    """角色权限响应"""
    role: str = Field(..., description="角色")
    permissions: List[str] = Field(..., description="权限列表")

    class Config:
        schema_extra = {
            "example": {
                "role": "warehouse_manager",
                "permissions": [
                    "material:create",
                    "inbound:create",
                    "inventory:view"
                ]
            }
        }


class RolePermissionUpdateRequest(BaseModel):
    """更新角色权限请求"""
    permissions: List[str] = Field(..., description="角色权限列表")

    @validator('permissions')
    def validate_permissions(cls, v):
        from app.utils.business_tools import PermissionService
        invalid = [perm for perm in v if perm not in PermissionService.PERMISSIONS]
        if invalid:
            raise ValueError(f"无效权限: {', '.join(invalid)}")
        return v


class PermissionListResponse(BaseModel):
    """权限列表响应"""
    permissions: List[str] = Field(..., description="系统权限列表")

    class Config:
        schema_extra = {
            "example": {
                "permissions": [
                    "material:create",
                    "inventory:view",
                    "outbound:approve"
                ]
            }
        }


class PermissionMenuResponse(BaseModel):
    """权限菜单响应"""
    role: str = Field(..., description="角色")
    permissions: List[str] = Field(..., description="权限列表")

    class Config:
        schema_extra = {
            "example": {
                "role": "employee",
                "permissions": [
                    "view_inventory",
                    "view_location",
                    "create_request"
                ]
            }
        }


class CreateRoleRequest(BaseModel):
    """创建角色请求"""
    name: str = Field(..., min_length=1, max_length=30, description="角色标识")
    display_name: str = Field(..., min_length=1, max_length=50, description="角色显示名称")
    description: Optional[str] = Field(None, max_length=200, description="角色描述")
    permissions: List[str] = Field(default=[], description="权限列表")


class UpdateRoleRequest(BaseModel):
    """更新角色请求"""
    display_name: Optional[str] = Field(None, min_length=1, max_length=50, description="角色显示名称")
    description: Optional[str] = Field(None, max_length=200, description="角色描述")


class RoleDefinitionResponse(BaseModel):
    """角色定义响应"""
    role: str = Field(..., description="角色标识")
    display_name: Optional[str] = Field(None, description="角色显示名称")
    description: Optional[str] = Field(None, description="角色描述")
    is_system: bool = Field(False, description="是否系统内置")
    is_active: bool = Field(True, description="是否启用")
    permissions: List[str] = Field(default=[], description="权限列表")
