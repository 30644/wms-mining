"""
数据验证模型 - 通用响应
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Generic, TypeVar


T = TypeVar('T')


class APIResponse(BaseModel):
    """统一API响应模型"""
    code: int = Field(..., description="业务状态码: 0成功, 其他为失败")
    message: str = Field(..., description="提示信息")
    data: Optional[Any] = Field(None, description="响应数据")
    
    class Config:
        schema_extra = {
            "example": {
                "code": 0,
                "message": "操作成功",
                "data": None
            }
        }


class PaginationParams(BaseModel):
    """分页参数"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(None, description="错误详情")
    
    class Config:
        schema_extra = {
            "example": {
                "code": 400,
                "message": "参数错误",
                "detail": "用户名已存在"
            }
        }


class OperationLog(BaseModel):
    """操作日志"""
    id: int = Field(..., description="日志ID")
    user_id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    action: str = Field(..., description="操作类型")
    module: str = Field(..., description="操作模块")
    related_id: Optional[int] = Field(None, description="相关业务ID")
    related_no: Optional[str] = Field(None, description="相关业务单号")
    ip_address: Optional[str] = Field(None, description="操作IP")
    created_at: str = Field(..., description="操作时间")
    
    class Config:
        from_attributes = True
