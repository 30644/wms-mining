from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models.nc_config import NcConfig


class NcConfigService:
    """NC6.5连接配置服务"""

    @staticmethod
    def get_config(db: Session) -> Dict[str, Any]:
        """获取NC配置，不存在则返回默认值"""
        config = db.query(NcConfig).first()
        if not config:
            from app.config import NC_API_URL, NC_API_TIMEOUT, NC_MAX_RETRY
            return {
                "nc_url": NC_API_URL,
                "nc_username": "",
                "nc_password": "",
                "api_token": "your-nc-token",
                "timeout": NC_API_TIMEOUT,
                "max_retry": NC_MAX_RETRY,
                "auto_sync": False,
                "sync_interval": "hourly",
            }
        return {
            "nc_url": config.nc_url,
            "nc_username": config.nc_username,
            "nc_password": config.nc_password,
            "api_token": config.api_token,
            "timeout": config.timeout,
            "max_retry": config.max_retry,
            "auto_sync": config.auto_sync,
            "sync_interval": config.sync_interval,
        }

    @staticmethod
    def save_config(db: Session, data: Dict[str, Any]) -> NcConfig:
        """保存NC配置"""
        config = db.query(NcConfig).first()
        if not config:
            config = NcConfig()
            db.add(config)

        allowed_fields = {
            "nc_url", "nc_username", "nc_password", "api_token",
            "timeout", "max_retry", "auto_sync", "sync_interval",
        }
        for key, value in data.items():
            if key in allowed_fields:
                setattr(config, key, value)

        db.commit()
        db.refresh(config)
        return config
