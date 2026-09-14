"""
认证相关API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import timedelta

from app.database import get_db
from app.schemas.auth import LoginRequest, LoginResponse, ChangePasswordRequest, CurrentUserResponse, VerifyPasswordRequest
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user, verify_password, get_password_hash, validate_password_strength
from app.services.auth_service import AuthService, UserService
from app.models import User
from app.utils.logger import logger
from app.config import UNAUTHENTICATED_PATHS

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=dict, summary="用户登录")
async def login(request: Request, credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    用户登录接口

    获取用户凭证并返回访问令牌。
    """
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"

    logger.info(f"登录尝试 | 用户名: {credentials.username} | IP: {client_ip}")

    # 认证用户
    user = AuthService.authenticate_user(credentials.username, credentials.password, db)
    if not user:
        logger.warning(f"登录失败 | 用户名: {credentials.username} | IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 创建令牌
    access_token, refresh_token, expires_in = AuthService.create_tokens(user)

    return {
        "code": 0,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role,
            "department": user.department,
            "expires_in": expires_in
        }
    }


@router.get("/me", response_model=CurrentUserResponse, summary="获取当前用户信息")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    获取当前登录用户的详细信息
    """
    return CurrentUserResponse.from_orm(current_user)


@router.post("/change-password", response_model=APIResponse, summary="修改密码")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改当前用户的密码

    要求：
    - 提供正确的旧密码
    - 新密码必须符合强度要求
    """
    # 验证旧密码
    if not verify_password(req.old_password, current_user.hashed_password):
        logger.warning(f"修改密码失败: 旧密码错误 | 用户ID: {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="旧密码不正确"
        )

    # 验证新密码强度
    is_valid, error_msg = validate_password_strength(req.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # 更新密码
    try:
        current_user.hashed_password = get_password_hash(req.new_password)
        db.commit()

        logger.info(f"修改密码成功 | 用户ID: {current_user.id}")

        # 记录操作日志
        UserService.log_operation(
            user_id=current_user.id,
            action="change_password",
            module="auth",
            details=f"用户修改了自己的密码",
            db=db
        )

        return APIResponse(code=0, message="密码修改成功")

    except Exception as e:
        db.rollback()
        logger.error(f"修改密码异常 | 用户ID: {current_user.id} | 错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="修改密码失败，请稍后重试"
        )


@router.post("/logout", response_model=APIResponse, summary="用户登出")
async def logout(current_user: User = Depends(get_current_user)):
    """
    用户登出接口

    注：Token基于JWT，服务端无法主动废止。
    建议前端删除本地Token以实现登出。
    """
    logger.info(f"用户登出 | 用户ID: {current_user.id} | 用户名: {current_user.username}")

    return APIResponse(code=0, message="登出成功")


@router.post("/verify-password", response_model=APIResponse, summary="验证当前用户密码")
async def verify_current_password(
    req: VerifyPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    验证当前用户的密码

    用于敏感操作前的二次确认。
    """
    logger.info(f"验证密码 | 用户ID: {current_user.id}")

    user = db.query(User).filter(User.id == current_user.id).first()
    is_valid = verify_password(req.password, user.hashed_password)

    return APIResponse(code=0, message="验证完成", data={"valid": is_valid})
