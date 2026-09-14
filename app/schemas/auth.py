"""
数据验证模型 - 认证相关
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, description="密码")
    
    class Config:
        schema_extra = {
            "example": {
                "username": "admin",
                "password": "Admin@123456"
            }
        }


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    real_name: str = Field(..., description="真实姓名")
    role: str = Field(..., description="用户角色")
    expires_in: int = Field(..., description="令牌过期时间（秒）")
    
    class Config:
        schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user_id": 1,
                "username": "admin",
                "real_name": "系统管理员",
                "role": "super_admin",
                "expires_in": 28800
            }
        }


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求"""
    refresh_token: str = Field(..., description="刷新令牌")


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=8, description="旧密码")
    new_password: str = Field(..., min_length=8, description="新密码")
    confirm_password: str = Field(..., min_length=8, description="确认密码")
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if not any(c.isupper() for c in v):
            raise ValueError('新密码必须包含至少一个大写字母')
        if not any(c.islower() for c in v):
            raise ValueError('新密码必须包含至少一个小写字母')
        if not any(c.isdigit() for c in v):
            raise ValueError('新密码必须包含至少一个数字')
        return v
    
    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('两次输入的密码不一致')
        return v


class CurrentUserResponse(BaseModel):
    """当前用户信息"""
    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    real_name: str = Field(..., description="真实姓名")
    department: str = Field(..., description="部门")
    role: str = Field(..., description="角色")
    email: Optional[str] = Field(None, description="邮箱")
    phone: Optional[str] = Field(None, description="手机号")
    is_active: bool = Field(..., description="是否启用")
    last_login_at: Optional[datetime] = Field(None, description="最后登录时间")
    created_at: datetime = Field(..., description="创建时间")
    
    class Config:
        from_attributes = True
        schema_extra = {
            "example": {
                "id": 1,
                "username": "admin",
                "real_name": "系统管理员",
                "department": "管理部",
                "role": "super_admin",
                "email": "admin@example.com",
                "phone": "13800000000",
                "is_active": True,
                "last_login_at": "2026-04-21T10:30:00",
                "created_at": "2026-04-21T08:00:00"
            }
        }


class VerifyPasswordRequest(BaseModel):
    """验证密码请求"""
    password: str = Field(..., min_length=1, description="密码")
