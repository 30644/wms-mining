from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class NcConfig(Base):
    """NC6.5连接配置"""
    __tablename__ = 'nc_configs'

    id = Column(Integer, primary_key=True, index=True)
    nc_url = Column(String(255), default="http://localhost:8080/nc-api")
    nc_username = Column(String(100), default="")
    nc_password = Column(String(255), default="")
    api_token = Column(String(255), default="your-nc-token")
    timeout = Column(Integer, default=30)
    max_retry = Column(Integer, default=3)
    auto_sync = Column(Boolean, default=False)
    sync_interval = Column(String(50), default="hourly")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
