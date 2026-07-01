"""
系统参数配置管理
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.models.system_config import SystemConfig
from app.utils.logger import logger

router = APIRouter(prefix="/api/system-config", tags=["系统配置"])

DEFAULTS = {
    "company_name": ("大红柳滩矿区", "公司名称"),
    "default_safety_stock": ("100", "默认安全库存阈值"),
    "auto_backup_days": ("7", "自动备份周期（天）"),
    "alert_check_hours": ("24", "预警检查间隔（小时）"),
    "session_timeout_minutes": ("480", "登录超时（分钟）"),
}


class ConfigItem(BaseModel):
    config_key: str
    config_value: str


class BatchConfigRequest(BaseModel):
    items: List[ConfigItem]


def _init_defaults(db: Session):
    """初始化未存在的默认配置项"""
    for key, (value, desc) in DEFAULTS.items():
        if not db.query(SystemConfig).filter(SystemConfig.config_key == key).first():
            db.add(SystemConfig(config_key=key, config_value=value, description=desc))
    db.commit()


@router.get("", summary="获取所有系统配置")
async def get_configs(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _init_defaults(db)
    configs = db.query(SystemConfig).all()
    items = {c.config_key: c.config_value for c in configs}
    descs = {c.config_key: c.description for c in configs}
    return APIResponse(code=0, message="获取成功", data={"items": items, "descriptions": descs})


@router.put("", summary="批量更新系统配置")
async def update_configs(req: BatchConfigRequest, db: Session = Depends(get_db),
                          _=Depends(get_current_user)):
    for item in req.items:
        config = db.query(SystemConfig).filter(
            SystemConfig.config_key == item.config_key
        ).first()
        if config:
            config.config_value = item.config_value
        else:
            db.add(SystemConfig(
                config_key=item.config_key,
                config_value=item.config_value,
                description="",
            ))
    db.commit()
    return APIResponse(code=0, message="配置已更新")
