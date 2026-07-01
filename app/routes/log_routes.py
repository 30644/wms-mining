"""
操作日志查询与导出路由
"""
import csv
import io
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.log_service import LogService
from app.utils.logger import logger

router = APIRouter(prefix="/api/logs", tags=["系统日志"])


@router.get("", summary="操作日志列表")
async def get_logs(
    keyword: Optional[str] = Query(None, description="关键词（空格分隔，匹配人/类型/模块）"),
    username: Optional[str] = Query(None, description="操作人"),
    action: Optional[str] = Query(None, description="操作类型"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分页查询操作日志"""
    try:
        data = LogService.get_logs(
            db, keyword=keyword, username=username, action=action,
            start_date=start_date, end_date=end_date,
            page=page, page_size=page_size,
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"获取操作日志异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/operation", summary="操作日志列表（别名）")
async def get_operation_logs(
    keyword: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """操作日志列表（别名路径）"""
    return await get_logs(keyword=keyword, username=username, action=action,
                           start_date=start_date, end_date=end_date,
                           page=page, page_size=page_size, db=db, current_user=current_user)


@router.get("/export", summary="导出操作日志CSV")
async def export_logs(
    keyword: Optional[str] = Query(None, description="关键词"),
    username: Optional[str] = Query(None, description="操作人"),
    action: Optional[str] = Query(None, description="操作类型"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """导出操作日志为CSV文件"""
    try:
        items = LogService.export_logs(
            db, keyword=keyword, username=username, action=action,
            start_date=start_date, end_date=end_date,
        )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["username", "real_name", "role", "action", "module", "content", "ip", "create_time"])
        writer.writeheader()
        for item in items:
            writer.writerow(item)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": f"attachment; filename=operation_logs_{date.today()}.csv"},
        )
    except Exception as e:
        logger.error(f"导出操作日志异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
