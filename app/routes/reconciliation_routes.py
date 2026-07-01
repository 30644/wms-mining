from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.reconciliation_service import ReconciliationService
from app.utils.logger import logger

router = APIRouter(prefix="/api/report", tags=["报表分析"])


@router.get("/reconciliation", summary="数据对账列表")
async def get_reconciliation(
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    month: Optional[str] = Query(None, description="对账月份 YYYY-MM"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取WMS与NC的库存对账数据"""
    try:
        items = ReconciliationService.get_reconciliation(
            db=db, warehouse_id=warehouse_id, month=month
        )
        return APIResponse(code=0, message="获取成功", data={"list": items})
    except Exception as e:
        logger.error(f"获取对账数据异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-nc", summary="同步库存到NC")
async def sync_nc_data(
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """将当前库存数据同步到NC"""
    try:
        result = ReconciliationService.sync_nc_data(db=db, warehouse_id=warehouse_id)
        return APIResponse(code=0, message=f"同步完成: 成功{result['success']}条, 失败{result['failed']}条", data=result)
    except Exception as e:
        logger.error(f"同步NC数据异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))
