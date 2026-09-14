"""
采购执行跟踪仪表板服务
"""
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract
from datetime import datetime, timedelta

from app.models import ProcurementRequest, InboundOrder, Material
from app.utils.logger import logger
from app.database import beijing_now


class ProcurementDashboardService:

    @staticmethod
    def get_overview(db: Session) -> Dict:
        """获取采购全链路概览数据"""
        try:
            # 各环节数量
            pending_review = db.query(ProcurementRequest).filter(
                ProcurementRequest.status == 'pending_leader_review'
            ).count()

            pending_procurement = db.query(ProcurementRequest).filter(
                ProcurementRequest.status == 'pending_procurement'
            ).count()

            in_progress = db.query(ProcurementRequest).filter(
                ProcurementRequest.status == 'procurement_in_progress'
            ).count()

            arrival_pending = db.query(ProcurementRequest).filter(
                ProcurementRequest.status == 'arrival_pending'
            ).count()

            completed = db.query(ProcurementRequest).filter(
                ProcurementRequest.status == 'completed'
            ).count()

            # 本月新增采购申请
            month_start = beijing_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            this_month = db.query(ProcurementRequest).filter(
                ProcurementRequest.created_at >= month_start
            ).count()

            # 本月到货入库
            month_inbound = db.query(InboundOrder).filter(
                and_(
                    InboundOrder.inbound_type == 'procurement',
                    InboundOrder.created_at >= month_start,
                    InboundOrder.status == 'completed'
                )
            ).count()

            return {
                "funnel": {
                    "pending_review": pending_review,
                    "pending_procurement": pending_procurement,
                    "in_progress": in_progress,
                    "arrival_pending": arrival_pending,
                    "completed": completed,
                },
                "this_month": {
                    "new_requests": this_month,
                    "completed_inbound": month_inbound,
                }
            }
        except Exception as e:
            logger.error(f"获取采购概览异常: {e}")
            return {"funnel": {}, "this_month": {}}

    @staticmethod
    def get_trend(db: Session, days: int = 30) -> List[Dict]:
        """获取近 N 天采购趋势"""
        try:
            since = beijing_now() - timedelta(days=days)
            rows = db.query(
                func.date(ProcurementRequest.created_at).label('date'),
                func.count(ProcurementRequest.id).label('count'),
            ).filter(
                ProcurementRequest.created_at >= since
            ).group_by(
                func.date(ProcurementRequest.created_at)
            ).order_by('date').all()

            return [{"date": str(r.date), "count": r.count} for r in rows]
        except Exception as e:
            logger.error(f"获取采购趋势异常: {e}")
            return []
