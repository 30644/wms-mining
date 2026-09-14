"""
认证和授权工具模块
"""
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS, SYSTEM_ROLES
)
from app.database import get_db, beijing_now
from app.utils.logger import logger

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ========== OAuth2认证方案 ==========
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ROLE_ALIASES = {
    "approver": "department_leader",
    "viewer": "team_leader",
    "department_leader": "approver",
    "team_leader": "viewer",
    "warehouse_operator": "employee",
    "employee": "warehouse_operator",
    "procurement_officer": "procurement",
    "procurement": "procurement_officer",
    "receiving_inspector": "technical_officer",
    "technical_officer": "receiving_inspector",
}


def resolve_role_alias(role: str) -> str:
    """返回角色别名或标准角色名称，用于支持 approver=department_leader 和 viewer=team_leader"""
    return ROLE_ALIASES.get(role, role)


def get_role_variants(role: str) -> List[str]:
    """返回角色本身和可能的别名变体"""
    variants = {role, resolve_role_alias(role)}
    return list(variants)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码
    
    参数：
    - plain_password: 明文密码
    - hashed_password: 哈希后的密码
    
    返回：验证结果
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"密码验证失败: {str(e)}")
        return False


def get_password_hash(password: str) -> str:
    """
    获取密码哈希值
    
    参数：
    - password: 明文密码
    
    返回：哈希后的密码
    """
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"密码加密失败: {str(e)}")
        raise


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    验证密码强度
    
    参数：
    - password: 要验证的密码
    
    返回：(是否有效, 错误信息)
    """
    from app.config import (
        MIN_PASSWORD_LENGTH, PASSWORD_REQUIRE_UPPERCASE,
        PASSWORD_REQUIRE_LOWERCASE, PASSWORD_REQUIRE_DIGITS,
        PASSWORD_REQUIRE_SPECIAL
    )
    
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"密码长度不能少于{MIN_PASSWORD_LENGTH}个字符"
    
    if PASSWORD_REQUIRE_UPPERCASE and not any(c.isupper() for c in password):
        return False, "密码必须包含至少一个大写字母"
    
    if PASSWORD_REQUIRE_LOWERCASE and not any(c.islower() for c in password):
        return False, "密码必须包含至少一个小写字母"
    
    if PASSWORD_REQUIRE_DIGITS and not any(c.isdigit() for c in password):
        return False, "密码必须包含至少一个数字"

    if PASSWORD_REQUIRE_SPECIAL and not any(not c.isalnum() for c in password):
        return False, "密码必须包含至少一个特殊字符"
    
    return True, ""


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建访问令牌（Access Token）
    
    参数：
    - data: 要编码的数据
    - expires_delta: 过期时间间隔
    
    返回：JWT令牌
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = beijing_now() + expires_delta
    else:
        expire = beijing_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"创建Access Token失败: {str(e)}")
        raise


def create_refresh_token(data: dict) -> str:
    """
    创建刷新令牌（Refresh Token）
    
    参数：
    - data: 要编码的数据
    
    返回：JWT令牌
    """
    to_encode = data.copy()
    expire = beijing_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"创建Refresh Token失败: {str(e)}")
        raise


def decode_token(token: str) -> Optional[Dict]:
    """
    解码JWT令牌
    
    参数：
    - token: JWT令牌
    
    返回：解码后的数据字典，若失败返回None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"令牌验证失败: {str(e)}")
        return None


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    获取当前登录用户（全局依赖）
    
    参数：
    - token: OAuth2令牌
    - db: 数据库会话
    
    返回：当前用户对象
    
    异常：未授权异常
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="令牌无效或已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = decode_token(token)
        if payload is None:
            raise credentials_exception
        
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if username is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # 从数据库查询用户
    from app.models import User
    user = db.query(User).filter(User.username == username).first()
    
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )
    
    return user


def require_role(*roles: str):
    """
    角色权限装饰器工厂
    
    参数：
    - *roles: 允许的角色列表
    
    返回：装饰器函数
    
    使用示例：
    @app.get("/admin")
    @require_role("super_admin", "warehouse_manager")
    async def admin_endpoint(current_user = Depends(get_current_user)):
        pass
    """
    allowed_roles = set()
    for role in roles:
        allowed_roles.add(role)
        allowed_roles.add(resolve_role_alias(role))

    async def role_checker(current_user = Depends(get_current_user)):
        """
        验证用户角色
        """
        # 获取用户角色（支持dict和User对象）
        user_role = current_user.get("role") if isinstance(current_user, dict) else current_user.role
        user_name = current_user.get("username") if isinstance(current_user, dict) else current_user.username
        
        if user_role not in allowed_roles:
            logger.warning(
                f"用户{user_name}(角色:{user_role})尝试访问需要角色{roles}的接口"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要以下角色之一: {', '.join(roles)}"
            )
        return current_user
    
    return role_checker


def require_permission(permission: str):
    """
    权限装饰器工厂
    
    参数：
    - permission: 所需的权限标识
    
    返回：装饰器函数
    
    使用示例：
    @app.post("/users")
    @require_permission("create_user")
    async def create_user(current_user = Depends(get_current_user)):
        pass
    """
    async def permission_checker(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
        """
        验证用户权限
        """
        from app.models import RolePermission
        
        # 超级管理员拥有所有权限
        if current_user.role == "super_admin":
            return current_user
        
        # 检查该角色和别名角色是否有此权限
        candidate_roles = get_role_variants(current_user.role)
        perm = db.query(RolePermission).filter(
            RolePermission.role.in_(candidate_roles),
            RolePermission.permission == permission
        ).first()
        
        if not perm:
            logger.warning(
                f"用户{current_user.username}(角色:{current_user.role})尝试执行需要权限{permission}的操作"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要权限: {permission}"
            )
        
        return current_user
    
    return permission_checker
