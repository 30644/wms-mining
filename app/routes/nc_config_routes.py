"""
NC同步配置管理
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.models.nc_config import NcConfig
from app.utils.logger import logger

router = APIRouter(prefix="/api/nc-config", tags=["NC配置"])


class NcConfigRequest(BaseModel):
    nc_url: str = Field("", description="NC接口地址")
    api_token: str = Field("", description="API Token")
    timeout: int = Field(30, ge=1, le=120)
    max_retry: int = Field(3, ge=0, le=10)


@router.get("", summary="获取NC配置")
async def get_config(db: Session = Depends(get_db), _=Depends(get_current_user)):
    config = db.query(NcConfig).first()
    if not config:
        config = NcConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return APIResponse(code=0, message="获取成功", data={
        "id": config.id,
        "nc_url": config.nc_url,
        "api_token": config.api_token,
        "timeout": config.timeout,
        "max_retry": config.max_retry,
    })


@router.put("", summary="更新NC配置")
async def update_config(req: NcConfigRequest, db: Session = Depends(get_db),
                         _=Depends(get_current_user)):
    config = db.query(NcConfig).first()
    if not config:
        config = NcConfig()
        db.add(config)
    config.nc_url = req.nc_url
    config.api_token = req.api_token
    config.timeout = req.timeout
    config.max_retry = req.max_retry
    db.commit()
    return APIResponse(code=0, message="NC配置已更新")
