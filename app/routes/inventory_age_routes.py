from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.inventory_age_service import InventoryAgeService
from app.utils.logger import logger

router = APIRouter(prefix="/api/report", tags=["报表分析"])


@router.get("/inventory-age", summary="库龄分析")
async def get_inventory_age(
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    category_id: Optional[int] = Query(None, description="物料分类ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取库龄分析数据（含分布统计）"""
    try:
        data = InventoryAgeService.get_inventory_age(
            db=db, warehouse_id=warehouse_id, category_id=category_id
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"获取库龄分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
