"""
供应商评估API路由
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import SupplierEvaluation
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.utils.business_tools import PermissionService
from app.utils.logger import logger
from app.services.supplier_evaluation_service import SupplierEvaluationService

router = APIRouter(prefix="/api/supplier-evaluation", tags=["供应商评估"])


class CreateEvaluationRequest(BaseModel):
    supplier_id: int = Field(..., description="供应商ID")
    score: float = Field(..., ge=0, le=100, description="综合评分")
    quality_score: Optional[float] = Field(None, ge=0, le=100, description="质量评分")
    delivery_score: Optional[float] = Field(None, ge=0, le=100, description="交期评分")
    price_score: Optional[float] = Field(None, ge=0, le=100, description="价格评分")
    service_score: Optional[float] = Field(None, ge=0, le=100, description="服务评分")
    evaluation_period: Optional[str] = Field(None, description="评估周期")
    comment: Optional[str] = Field(None, description="评估备注")


@router.post("/create", summary="创建供应商评估")
async def create_evaluation(
    request: CreateEvaluationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建供应商评估记录"""
    try:
        if not PermissionService.check_permission(current_user.id, "supplier:manage", db):
            raise HTTPException(status_code=403, detail="无权限执行此操作")

        success, msg, evaluation = SupplierEvaluationService.create_evaluation(
            db=db,
            supplier_id=request.supplier_id,
            score=request.score,
            evaluator_id=current_user.id,
            quality_score=request.quality_score,
            delivery_score=request.delivery_score,
            price_score=request.price_score,
            service_score=request.service_score,
            evaluation_period=request.evaluation_period,
            comment=request.comment,
        )
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        return APIResponse(code=0, message=msg, data={"id": evaluation.id})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建供应商评估异常: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.get("/list", summary="获取供应商评估列表")
async def get_evaluation_list(
    supplier_id: Optional[int] = Query(None, description="供应商ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取供应商评估列表"""
    try:
        items, total = SupplierEvaluationService.get_evaluation_list(
            db=db, supplier_id=supplier_id, page=page, page_size=page_size
        )
        return APIResponse(
            code=0,
            message="获取成功",
            data={"list": items, "total": total, "page": page, "page_size": page_size},
        )
    except Exception as e:
        logger.error(f"获取评估列表异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/avg-score", summary="获取供应商平均评分")
async def get_avg_score(
    supplier_id: int = Query(..., description="供应商ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取指定供应商的平均评分"""
    try:
        avg = SupplierEvaluationService.get_supplier_avg_score(db, supplier_id)
        return APIResponse(code=0, message="获取成功", data={"avg_score": avg})
    except Exception as e:
        logger.error(f"获取平均评分异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")
