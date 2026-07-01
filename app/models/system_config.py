"""
系统配置参数模型
"""
from sqlalchemy import Column, Integer, String, Text
from app.database import Base


class SystemConfig(Base):
    __tablename__ = 'system_configs'

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, default="")
    description = Column(String(255), default="")
