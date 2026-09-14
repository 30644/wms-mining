from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.slow_moving_service import SlowMovingService
from app.utils.logger import logger

router = APIRouter(prefix="/api/report", tags=["报表分析"])


@router.get("/slow-moving", summary="呆滞物料列表")
async def get_slow_moving(
    days: int = Query(90, ge=30, le=365, description="呆滞判定天数"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取呆滞物料清单"""
    try:
        items = SlowMovingService.get_slow_moving(db=db, days=days, warehouse_id=warehouse_id)
        return APIResponse(code=0, message="获取成功", data={"list": items, "total": len(items)})
    except Exception as e:
        logger.error(f"获取呆滞物料异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slow-moving/generate-alerts", summary="生成呆滞物料预警")
async def generate_alerts(
    days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """为呆滞物料生成预警通知"""
    try:
        count = SlowMovingService.generate_alerts(db=db, days=days)
        return APIResponse(code=0, message=f"已生成 {count} 条预警通知")
    except Exception as e:
        logger.error(f"生成呆滞预警异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
