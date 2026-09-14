"""
全局异常处理
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.utils.logger import logger


async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器
    
    参数：
    - request: 请求对象
    - exc: 异常对象
    """
    logger.error(f"全局异常捕获 | 路径: {request.url.path} | 异常: {str(exc)}")
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "detail": str(exc) if hasattr(exc, '__str__') else "未知错误"
        }
    )


async def http_exception_handler(request: Request, exc: Exception):
    """
    HTTP异常处理器
    """
    logger.warning(f"HTTP异常 | 状态码: {exc.status_code} | 信息: {exc.detail}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    参数验证异常处理器
    """
    errors = exc.errors()
    error_messages = []
    
    for error in errors:
        field = '.'.join(str(x) for x in error['loc'][1:])
        error_messages.append(f"{field}: {error['msg']}")
    
    logger.warning(f"参数验证失败 | 路径: {request.url.path} | 错误: {error_messages}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 422,
            "message": "参数验证失败",
            "detail": error_messages
        }
    )


async def integrity_error_handler(request: Request, exc: IntegrityError):
    """
    数据库完整性异常处理器（如唯一约束冲突）
    """
    logger.warning(f"数据库完整性错误 | {str(exc)}")
    
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "code": 409,
            "message": "数据已存在或违反约束条件",
            "detail": "请检查输入数据是否重复或不符合要求"
        }
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """
    SQLAlchemy异常处理器
    """
    logger.error(f"数据库异常 | {str(exc)}")
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "数据库操作失败",
            "detail": "请稍后重试或联系管理员"
        }
    )
