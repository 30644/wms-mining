"""
供应商评估服务
"""
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.models import SupplierEvaluation, Supplier
from app.utils.logger import logger


class SupplierEvaluationService:

    @staticmethod
    def create_evaluation(
        db: Session,
        supplier_id: int,
        score: float,
        evaluator_id: int,
        quality_score: Optional[float] = None,
        delivery_score: Optional[float] = None,
        price_score: Optional[float] = None,
        service_score: Optional[float] = None,
        evaluation_period: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[SupplierEvaluation]]:
        """创建供应商评估"""
        try:
            supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
            if not supplier:
                return False, "供应商不存在", None

            evaluation = SupplierEvaluation(
                supplier_id=supplier_id,
                score=score,
                quality_score=quality_score,
                delivery_score=delivery_score,
                price_score=price_score,
                service_score=service_score,
                evaluation_period=evaluation_period,
                comment=comment,
                evaluator_id=evaluator_id,
            )
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            logger.info(f"供应商评估创建成功 | 供应商ID: {supplier_id} | 评分: {score}")
            return True, "创建成功", evaluation
        except Exception as e:
            db.rollback()
            logger.error(f"创建供应商评估异常 | 错误: {str(e)}")
            return False, f"创建失败: {str(e)}", None

    @staticmethod
    def get_evaluation_list(
        db: Session,
        supplier_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict], int]:
        """获取评估列表"""
        try:
            query = db.query(SupplierEvaluation)
            if supplier_id:
                query = query.filter(SupplierEvaluation.supplier_id == supplier_id)
            total = query.count()
            evaluations = query.order_by(
                desc(SupplierEvaluation.created_at)
            ).offset((page - 1) * page_size).limit(page_size).all()

            result = []
            for ev in evaluations:
                result.append({
                    "id": ev.id,
                    "supplier_id": ev.supplier_id,
                    "supplier_name": ev.supplier.supplier_name if ev.supplier else None,
                    "score": float(ev.score),
                    "quality_score": float(ev.quality_score) if ev.quality_score else None,
                    "delivery_score": float(ev.delivery_score) if ev.delivery_score else None,
                    "price_score": float(ev.price_score) if ev.price_score else None,
                    "service_score": float(ev.service_score) if ev.service_score else None,
                    "evaluation_period": ev.evaluation_period,
                    "comment": ev.comment,
                    "evaluator_name": ev.evaluator.real_name if ev.evaluator else None,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                })
            return result, total
        except Exception as e:
            logger.error(f"获取评估列表异常: {e}")
            return [], 0

    @staticmethod
    def get_supplier_avg_score(db: Session, supplier_id: int) -> Optional[float]:
        """获取供应商平均评分"""
        try:
            from sqlalchemy import func
            result = db.query(func.avg(SupplierEvaluation.score)).filter(
                SupplierEvaluation.supplier_id == supplier_id
            ).scalar()
            return round(float(result), 2) if result else None
        except Exception as e:
            logger.error(f"获取平均评分异常: {e}")
            return None
