from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    real_name = Column(String(50))
    department = Column(String(50))
    role = Column(String(30), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    requests = relationship('Request', back_populates='requester', foreign_keys='Request.requester_id')
    approvals = relationship('Request', back_populates='approver_user', foreign_keys='Request.approver_id')
    leader_reviews = relationship('Request', foreign_keys='Request.leader_reviewer_id', back_populates='leader_reviewer')
    warehouse_operations = relationship('Request', foreign_keys='Request.warehouse_manager_id', back_populates='warehouse_manager')
    inbound_orders = relationship('InboundOrder', back_populates='operator', foreign_keys='InboundOrder.warehouse_manager_id')
    outbound_orders = relationship('OutboundOrder', back_populates='operator', foreign_keys='OutboundOrder.warehouse_manager_id')
    inventory_checks = relationship('InventoryCheck', back_populates='checker')
    operation_logs = relationship('OperationLog', back_populates='user')


class RoleDefinition(Base):
    __tablename__ = 'role_definitions'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(30), unique=True, nullable=False, comment='角色标识')
    display_name = Column(String(50), comment='角色显示名称')
    description = Column(String(200), comment='角色描述')
    is_system = Column(Boolean, default=False, comment='是否系统内置')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)


class RolePermission(Base):
    __tablename__ = 'role_permissions'
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(30), nullable=False)
    permission = Column(String(50), nullable=False)
    description = Column(String(100))
    created_at = Column(DateTime, default=beijing_now)


class Department(Base):
    __tablename__ = 'departments'
    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey('departments.id'), nullable=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    leader = Column(String(50))
    phone = Column(String(20))
    sort = Column(Integer, default=0)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    children = relationship('Department', backref='parent', remote_side=[id])


class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    is_read = Column(Boolean, default=False)
    related_type = Column(String(50), default="")
    related_id = Column(Integer, default=None, nullable=True)
    created_at = Column(DateTime, default=beijing_now)
