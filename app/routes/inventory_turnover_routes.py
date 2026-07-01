from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.inventory_turnover_service import InventoryTurnoverService
from app.utils.logger import logger

router = APIRouter(prefix="/api/report", tags=["报表分析"])


@router.get("/turnover", summary="库存周转率分析列表")
async def get_turnover_list(
    period_days: int = Query(30, ge=1, le=365, description="分析周期（天）"),
    category_id: Optional[int] = Query(None, description="物料分类ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取库存周转率分析列表"""
    try:
        items, total = InventoryTurnoverService.get_turnover_list(
            db=db,
            period_days=period_days,
            category_id=category_id,
            page=page,
            page_size=page_size,
        )
        # 计算汇总
        avg_rate = 0
        if items:
            avg_rate = round(sum(x.get("turnover_rate", 0) for x in items) / len(items), 2)

        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "summary": {
                    "avg_turnover_rate": avg_rate,
                    "total_materials": total,
                },
            },
        )
    except Exception as e:
        logger.error(f"获取周转率异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/turnover/{material_id}", summary="单个物料周转率详情")
async def get_turnover_detail(
    material_id: int = Path(..., description="物料ID"),
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取单个物料的周转率详情"""
    try:
        result = InventoryTurnoverService.calculate_turnover(material_id, period_days, db)
        return APIResponse(code=0, message="获取成功", data=result)
    except Exception as e:
        logger.error(f"获取物料周转率异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
