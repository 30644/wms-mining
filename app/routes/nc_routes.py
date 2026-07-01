from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.database import get_db
from app.models import NcSyncRecord
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.utils.business_tools import PermissionService
from app.services.nc_config_service import NcConfigService
from app.services.nc_sync_service import NcSyncService
from app.utils.logger import logger

router = APIRouter(prefix="/api/nc", tags=["NC数据同步"])


@router.get("/config", summary="获取NC配置")
async def get_nc_config(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取NC6.5连接配置"""
    try:
        config = NcConfigService.get_config(db)
        return APIResponse(code=0, message="获取成功", data=config)
    except Exception as e:
        logger.error(f"获取NC配置异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config", summary="保存NC配置")
async def save_nc_config(
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """保存NC6.5连接配置"""
    try:
        if not PermissionService.check_permission(current_user.id, "nc:config", db):
            raise HTTPException(status_code=403, detail="无权限执行此操作")

        NcConfigService.save_config(db, data)
        logger.info(f"NC配置已更新 | 用户: {current_user.username}")
        return APIResponse(code=0, message="配置保存成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存NC配置异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-log", summary="获取NC同步记录列表")
async def get_sync_log(
    data_type: Optional[str] = Query(None, alias="data_type"),
    status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取NC同步记录列表"""
    try:
        query = db.query(NcSyncRecord)

        if data_type:
            query = query.filter(NcSyncRecord.sync_type == data_type)
        if status:
            query = query.filter(NcSyncRecord.sync_status == status)

        total = query.count()
        records = (
            query.order_by(NcSyncRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items = []
        for r in records:
            items.append({
                "data_type": r.sync_type,
                "nc_code": r.nc_code or "",
                "name": r.business_no or "",
                "sync_time": r.synced_at.isoformat() if r.synced_at else (r.created_at.isoformat() if r.created_at else ""),
                "status": r.sync_status,
                "error_msg": r.error_message or "",
            })

        return APIResponse(
            code=0,
            message="获取成功",
            data={"list": items, "total": total, "page": page, "page_size": page_size},
        )
    except Exception as e:
        logger.error(f"获取同步日志异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync", summary="触发NC全业务同步")
async def trigger_sync(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """触发NC全业务同步（重试失败的同步记录）"""
    try:
        stats = NcSyncService.retry_failed_syncs(db)
        logger.info(f"手动触发同步 | 用户: {current_user.username} | 结果: {stats}")
        return APIResponse(code=0, message="同步任务已完成", data=stats)
    except Exception as e:
        logger.error(f"触发同步异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-stats", summary="获取NC同步统计概览")
async def get_sync_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取NC同步状态统计：按状态和类型聚合"""
    try:
        # 按状态统计
        status_counts = (
            db.query(NcSyncRecord.sync_status, sqlfunc.count(NcSyncRecord.id))
            .group_by(NcSyncRecord.sync_status)
            .all()
        )
        stats = {"total": 0, "success": 0, "failed": 0, "pending": 0, "retrying": 0}
        for status, count in status_counts:
            stats["total"] += count
            if status in stats:
                stats[status] = count

        # 按类型+状态统计
        type_status = (
            db.query(
                NcSyncRecord.sync_type,
                NcSyncRecord.sync_status,
                sqlfunc.count(NcSyncRecord.id),
            )
            .group_by(NcSyncRecord.sync_type, NcSyncRecord.sync_status)
            .all()
        )
        by_type = {}
        for sync_type, sync_status, count in type_status:
            if sync_type not in by_type:
                by_type[sync_type] = {}
            by_type[sync_type][sync_status] = count

        stats["by_type"] = by_type
        return APIResponse(code=0, message="获取成功", data=stats)
    except Exception as e:
        logger.error(f"获取同步统计异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
