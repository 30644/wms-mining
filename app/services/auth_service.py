"""
用户认证和管理业务逻辑服务
"""
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from sqlalchemy import desc

from app.models import User, RolePermission, OperationLog
from app.utils.auth import (
    get_password_hash, verify_password, 
    create_access_token, create_refresh_token,
    validate_password_strength
)
from app.utils.logger import logger
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import beijing_now


class AuthService:
    """认证服务"""
    
    @staticmethod
    def authenticate_user(username: str, password: str, db: Session) -> Optional[User]:
        """
        认证用户
        
        参数：
        - username: 用户名
        - password: 密码
        - db: 数据库会话
        
        返回：用户对象或None
        """
        user = db.query(User).filter(User.username == username).first()
        
        if not user:
            logger.warning(f"登录失败: 用户不存在 | 用户名: {username}")
            return None
        
        if not user.is_active:
            logger.warning(f"登录失败: 用户已禁用 | 用户名: {username}")
            return None
        
        if not verify_password(password, user.hashed_password):
            logger.warning(f"登录失败: 密码错误 | 用户名: {username}")
            return None
        
        logger.info(f"用户登录成功 | 用户名: {username} | 角色: {user.role}")
        
        # 更新最后登录时间
        user.last_login_at = beijing_now()
        db.commit()
        
        return user
    
    @staticmethod
    def create_tokens(user: User) -> Tuple[str, str, int]:
        """
        创建访问令牌和刷新令牌
        
        参数：
        - user: 用户对象
        
        返回：(access_token, refresh_token, expires_in)
        """
        access_token_data = {"sub": user.username, "role": user.role}
        refresh_token_data = {"sub": user.username}
        
        access_token = create_access_token(access_token_data)
        refresh_token = create_refresh_token(refresh_token_data)
        
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # 转换为秒
        
        return access_token, refresh_token, expires_in


class UserService:
    """用户管理服务"""
    
    @staticmethod
    def create_user(username: str, password: str, real_name: str, department: str,
                   role: str, email: str = None, phone: str = None,
                   created_by: int = None, db: Session = None) -> Tuple[bool, str, Optional[User]]:
        """
        创建用户
        
        参数：
        - username: 用户名
        - password: 密码
        - real_name: 真实姓名
        - department: 部门
        - role: 角色
        - email: 邮箱
        - phone: 手机号
        - created_by: 创建人ID（用于日志）
        - db: 数据库会话
        
        返回：(成功标志, 错误信息, 用户对象)
        """
        # 检查用户名是否已存在
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            logger.warning(f"创建用户失败: 用户名已存在 | 用户名: {username}")
            return False, "用户名已存在", None
        
        # 验证密码强度
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            return False, error_msg, None
        
        try:
            # 创建新用户
            hashed_password = get_password_hash(password)
            new_user = User(
                username=username,
                hashed_password=hashed_password,
                real_name=real_name,
                department=department,
                role=role,
                email=email,
                phone=phone,
                is_active=True
            )
            
            db.add(new_user)
            db.flush()  # 获取用户ID
            db.commit()
            
            logger.info(f"新增用户成功 | 用户ID: {new_user.id} | 用户名: {username} | 角色: {role}")
            
            # 记录操作日志
            if created_by:
                UserService.log_operation(
                    user_id=created_by,
                    action="create_user",
                    module="user_management",
                    related_id=new_user.id,
                    related_no=username,
                    details=f"创建用户: {real_name}({username}), 角色: {role}",
                    db=db
                )
            
            return True, "用户创建成功", new_user
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建用户异常 | 用户名: {username} | 错误: {str(e)}")
            return False, f"创建用户失败: {str(e)}", None
    
    @staticmethod
    def update_user(user_id: int, real_name: str = None, department: str = None,
                   role: str = None, email: str = None, phone: str = None,
                   updated_by: int = None, db: Session = None) -> Tuple[bool, str, Optional[User]]:
        """
        更新用户信息
        
        参数：
        - user_id: 用户ID
        - real_name: 真实姓名
        - department: 部门
        - role: 角色
        - email: 邮箱
        - phone: 手机号
        - updated_by: 更新人ID（用于日志）
        - db: 数据库会话
        
        返回：(成功标志, 消息, 用户对象)
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False, "用户不存在", None
            
            # 记录修改前的值
            old_values = {}
            
            if real_name is not None:
                old_values['real_name'] = user.real_name
                user.real_name = real_name
            
            if department is not None:
                old_values['department'] = user.department
                user.department = department
            
            if role is not None:
                old_values['role'] = user.role
                user.role = role
            
            if email is not None:
                old_values['email'] = user.email
                user.email = email
            
            if phone is not None:
                old_values['phone'] = user.phone
                user.phone = phone
            
            db.commit()
            
            logger.info(f"编辑用户成功 | 用户ID: {user_id} | 用户名: {user.username}")
            
            # 记录操作日志
            if updated_by:
                details = ", ".join([f"{k}: {old_values.get(k)} -> {getattr(user, k)}" for k in old_values.keys()])
                UserService.log_operation(
                    user_id=updated_by,
                    action="update_user",
                    module="user_management",
                    related_id=user_id,
                    related_no=user.username,
                    details=details,
                    db=db
                )
            
            return True, "用户更新成功", user
        
        except Exception as e:
            db.rollback()
            logger.error(f"编辑用户异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return False, f"编辑用户失败: {str(e)}", None
    
    @staticmethod
    def disable_user(user_id: int, disabled_by: int = None, db: Session = None) -> Tuple[bool, str]:
        """
        禁用用户账户
        
        参数：
        - user_id: 用户ID
        - disabled_by: 禁用人ID（用于日志）
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False, "用户不存在"
            
            if not user.is_active:
                return False, "用户已被禁用"
            
            user.is_active = False
            db.commit()
            
            logger.info(f"禁用用户成功 | 用户ID: {user_id} | 用户名: {user.username}")
            
            # 记录操作日志
            if disabled_by:
                UserService.log_operation(
                    user_id=disabled_by,
                    action="disable_user",
                    module="user_management",
                    related_id=user_id,
                    related_no=user.username,
                    details=f"禁用用户: {user.real_name}({user.username})",
                    db=db
                )
            
            return True, "用户已禁用"
        
        except Exception as e:
            db.rollback()
            logger.error(f"禁用用户异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return False, f"禁用用户失败: {str(e)}"
    
    @staticmethod
    def enable_user(user_id: int, enabled_by: int = None, db: Session = None) -> Tuple[bool, str]:
        """
        启用用户账户
        
        参数：
        - user_id: 用户ID
        - enabled_by: 启用人ID（用于日志）
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False, "用户不存在"
            
            if user.is_active:
                return False, "用户已启用"
            
            user.is_active = True
            db.commit()
            
            logger.info(f"启用用户成功 | 用户ID: {user_id} | 用户名: {user.username}")
            
            # 记录操作日志
            if enabled_by:
                UserService.log_operation(
                    user_id=enabled_by,
                    action="enable_user",
                    module="user_management",
                    related_id=user_id,
                    related_no=user.username,
                    details=f"启用用户: {user.real_name}({user.username})",
                    db=db
                )
            
            return True, "用户已启用"
        
        except Exception as e:
            db.rollback()
            logger.error(f"启用用户异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return False, f"启用用户失败: {str(e)}"
    
    @staticmethod
    def reset_password(user_id: int, new_password: str, reset_by: int = None, db: Session = None) -> Tuple[bool, str]:
        """
        重置用户密码
        
        参数：
        - user_id: 用户ID
        - new_password: 新密码
        - reset_by: 重置人ID（用于日志）
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False, "用户不存在"
            
            # 验证密码强度
            is_valid, error_msg = validate_password_strength(new_password)
            if not is_valid:
                return False, error_msg
            
            hashed_password = get_password_hash(new_password)
            user.hashed_password = hashed_password
            db.commit()
            
            logger.info(f"重置用户密码成功 | 用户ID: {user_id} | 用户名: {user.username}")
            
            # 记录操作日志
            if reset_by:
                UserService.log_operation(
                    user_id=reset_by,
                    action="reset_password",
                    module="user_management",
                    related_id=user_id,
                    related_no=user.username,
                    details=f"重置用户密码: {user.real_name}({user.username})",
                    db=db
                )
            
            return True, "密码重置成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"重置密码异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return False, f"密码重置失败: {str(e)}"
    
    @staticmethod
    def get_user_list(page: int = 1, page_size: int = 20, role: str = None, 
                     department: str = None, is_active: bool = None,
                     db: Session = None) -> Tuple[int, List[User]]:
        """
        获取用户列表
        
        参数：
        - page: 页码
        - page_size: 每页数量
        - role: 按角色筛选
        - department: 按部门筛选
        - is_active: 按启用状态筛选
        - db: 数据库会话
        
        返回：(总数, 用户列表)
        """
        query = db.query(User)
        
        if role:
            query = query.filter(User.role == role)
        
        if department:
            query = query.filter(User.department == department)
        
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        
        total = query.count()
        
        offset = (page - 1) * page_size
        users = query.order_by(desc(User.created_at)).offset(offset).limit(page_size).all()
        
        return total, users
    
    @staticmethod
    def log_operation(user_id: int, action: str, module: str, related_id: int = None,
                     related_no: str = None, details: str = None, db: Session = None):
        """
        记录操作日志
        
        参数：
        - user_id: 操作用户ID
        - action: 操作类型
        - module: 操作模块
        - related_id: 相关业务ID
        - related_no: 相关业务单号
        - details: 操作详情
        - db: 数据库会话
        """
        try:
            import json
            
            log_entry = OperationLog(
                user_id=user_id,
                action=action,
                module=module,
                related_id=related_id,
                related_no=related_no,
                details=json.dumps({"info": details}) if details else None,
                created_at=beijing_now()
            )
            
            db.add(log_entry)
            db.commit()
            
            logger.info(f"操作日志已记录 | 用户ID: {user_id} | 操作: {action}")
        
        except Exception as e:
            db.rollback()
            logger.error(f"记录操作日志异常 | 错误: {str(e)}")
