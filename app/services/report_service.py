"""
报表分析服务
- 仪表盘概览
- 出库频次分析
- 部门领料金额分析
- 到货周期分析
- ABC分类
- 消耗趋势
- 库存价值
- 部门对比
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case, text, Integer, String
from datetime import datetime, date, timedelta

from app.models import (
    OutboundOrder, Material, MaterialCategory, InboundOrder,
    Inventory, Warehouse, PurchaseOrder
)
from app.utils.logger import logger


class ReportService:

    @staticmethod
    def get_dashboard_stats(db: Session) -> Dict:
        """仪表盘概览统计"""
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 本月出库次数
        month_outbound_count = db.query(func.count(OutboundOrder.id)).filter(
            OutboundOrder.created_at >= month_start,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).scalar() or 0

        # 本月出库金额（quantity * material unit_price）
        month_cost = db.query(
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0)
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= month_start,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).scalar() or 0

        # 库存总价值
        total_inventory_value = db.query(
            func.coalesce(func.sum(Inventory.quantity * Material.unit_price), 0)
        ).join(Material, Inventory.material_id == Material.id).filter(
            Inventory.quantity > 0
        ).scalar() or 0

        # 待审批数 (outbound pending_approval)
        pending_approvals = db.query(func.count(OutboundOrder.id)).filter(
            OutboundOrder.status == 'pending_approval'
        ).scalar() or 0

        # 待审批采购单
        pending_purchases = db.query(func.count(PurchaseOrder.id)).filter(
            PurchaseOrder.status.in_(['pending_team_leader', 'pending_technical', 'pending_auditor'])
        ).scalar() or 0

        # 库存预警待处理
        from app.models import InventoryAlert
        pending_alerts = db.query(func.count(InventoryAlert.id)).filter(
            InventoryAlert.status == 'pending'
        ).scalar() or 0

        return {
            "month_outbound_count": month_outbound_count,
            "month_cost": round(float(month_cost), 2),
            "total_inventory_value": round(float(total_inventory_value), 2),
            "pending_approvals": pending_approvals,
            "pending_purchases": pending_purchases,
            "pending_alerts": pending_alerts,
        }

    @staticmethod
    def get_outbound_frequency(
        db: Session,
        period: str = 'month',
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        top_n: int = 20,
    ) -> List[Dict]:
        """
        出库频次分析 - 按时间周期统计物料出库次数和数量

        period: month / quarter / year
        """
        if not start_date:
            start_date = date.today().replace(day=1) - timedelta(days=365)
        if not end_date:
            end_date = date.today()

        q = db.query(
            Material.id.label('material_id'),
            Material.code.label('material_code'),
            Material.name.label('material_name'),
            Material.specification.label('specification'),
            Material.unit.label('unit'),
            func.count(OutboundOrder.id).label('outbound_count'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.created_at <= end_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        )

        if period == 'month':
            period_label = func.strftime('%Y-%m', OutboundOrder.created_at)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, Material.id)
            q = q.order_by(period_label.desc(), func.count(OutboundOrder.id).desc())
        elif period == 'quarter':
            # (month-1)//3 + 1 = quarter number
            qtr = (func.strftime('%m', OutboundOrder.created_at).cast(func.Integer) - 1) / 3 + 1
            period_label = func.strftime('%Y', OutboundOrder.created_at) + '-Q' + qtr.cast(func.String)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, Material.id)
            q = q.order_by(period_label.desc(), func.count(OutboundOrder.id).desc())
        elif period == 'year':
            period_label = func.strftime('%Y', OutboundOrder.created_at)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, Material.id)
            q = q.order_by(period_label.desc(), func.count(OutboundOrder.id).desc())
        else:
            # Default: no time grouping, just top N overall
            q = q.group_by(Material.id)
            q = q.order_by(func.count(OutboundOrder.id).desc())

        results = q.limit(top_n).all()

        return [{
            "period": getattr(r, 'period', None),
            "material_id": r.material_id,
            "material_code": r.material_code,
            "material_name": r.material_name,
            "specification": r.specification or '',
            "unit": r.unit or '',
            "outbound_count": r.outbound_count,
            "total_quantity": round(float(r.total_quantity), 2),
            "total_amount": round(float(r.total_amount), 2),
        } for r in results]

    @staticmethod
    def get_department_cost(
        db: Session,
        period: str = 'month',
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        department: Optional[str] = None,
    ) -> List[Dict]:
        """
        部门领料金额分析 - 按时间周期统计各领用部门的物料花费

        period: month / quarter / year
        department: 筛选指定部门（用于下钻）
        """
        if not start_date:
            start_date = date.today().replace(day=1) - timedelta(days=365)
        if not end_date:
            end_date = date.today()

        q = db.query(
            func.coalesce(OutboundOrder.recipient_department, '未指定').label('department'),
            func.count(OutboundOrder.id).label('order_count'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.created_at <= end_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        )

        if department:
            q = q.filter(func.coalesce(OutboundOrder.recipient_department, '未指定') == department)

        if period == 'month':
            period_label = func.strftime('%Y-%m', OutboundOrder.created_at)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, OutboundOrder.recipient_department)
            q = q.order_by(period_label.desc(), func.sum(OutboundOrder.quantity * Material.unit_price).desc())
        elif period == 'quarter':
            qtr = func.round((func.cast(func.strftime('%m', OutboundOrder.created_at), Integer) - 1) / 3 + 1)
            period_label = func.strftime('%Y', OutboundOrder.created_at) + '-Q' + func.cast(qtr, String)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, OutboundOrder.recipient_department)
            q = q.order_by(period_label.desc(), func.sum(OutboundOrder.quantity * Material.unit_price).desc())
        elif period == 'year':
            period_label = func.strftime('%Y', OutboundOrder.created_at)
            q = q.add_columns(period_label.label('period'))
            q = q.group_by(period_label, OutboundOrder.recipient_department)
            q = q.order_by(period_label.desc(), func.sum(OutboundOrder.quantity * Material.unit_price).desc())
        else:
            q = q.group_by(OutboundOrder.recipient_department)
            q = q.order_by(func.sum(OutboundOrder.quantity * Material.unit_price).desc())

        results = q.all()

        return [{
            "period": getattr(r, 'period', None),
            "department": r.department,
            "order_count": r.order_count,
            "total_quantity": round(float(r.total_quantity), 2),
            "total_amount": round(float(r.total_amount), 2),
        } for r in results]

    @staticmethod
    def get_procurement_cycle(
        db: Session,
        material_id: Optional[int] = None,
    ) -> List[Dict]:
        """
        到货周期分析 - 统计物料实际到货与预期到货的天数偏差

        使用 InboundOrder.arrival_confirmed_at - InboundOrder.expected_arrival_date
        """
        q = db.query(
            Material.id.label('material_id'),
            Material.code.label('material_code'),
            Material.name.label('material_name'),
            Material.specification.label('specification'),
            func.count(InboundOrder.id).label('order_count'),
            func.round(func.avg(
                func.julianday(InboundOrder.arrival_confirmed_at) -
                func.julianday(InboundOrder.expected_arrival_date)
            ), 1).label('avg_cycle_days'),
            func.min(
                func.julianday(InboundOrder.arrival_confirmed_at) -
                func.julianday(InboundOrder.expected_arrival_date)
            ).label('min_cycle_days'),
            func.max(
                func.julianday(InboundOrder.arrival_confirmed_at) -
                func.julianday(InboundOrder.expected_arrival_date)
            ).label('max_cycle_days'),
        ).join(Material, InboundOrder.material_id == Material.id).filter(
            InboundOrder.arrival_confirmed_at.isnot(None),
            InboundOrder.expected_arrival_date.isnot(None)
        )

        if material_id:
            q = q.filter(InboundOrder.material_id == material_id)

        q = q.group_by(Material.id).order_by(func.count(InboundOrder.id).desc())

        results = q.all()

        return [{
            "material_id": r.material_id,
            "material_code": r.material_code,
            "material_name": r.material_name,
            "specification": r.specification or '',
            "order_count": r.order_count,
            "avg_cycle_days": float(r.avg_cycle_days) if r.avg_cycle_days else 0,
            "min_cycle_days": float(r.min_cycle_days) if r.min_cycle_days else 0,
            "max_cycle_days": float(r.max_cycle_days) if r.max_cycle_days else 0,
        } for r in results]

    @staticmethod
    def get_abc_analysis(
        db: Session,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict]:
        """
        ABC分类分析 - 按出库金额累计占比分类

        A类: 累计占比 0-70%
        B类: 累计占比 70-90%
        C类: 累计占比 90-100%
        """
        if not start_date:
            start_date = date.today().replace(day=1) - timedelta(days=365)
        if not end_date:
            end_date = date.today()

        items = db.query(
            Material.id.label('material_id'),
            Material.code.label('material_code'),
            Material.name.label('material_name'),
            Material.specification.label('specification'),
            Material.unit.label('unit'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.created_at <= end_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(Material.id).order_by(
            func.sum(OutboundOrder.quantity * Material.unit_price).desc()
        ).all()

        total_amount = sum(float(r.total_amount) for r in items) or 1

        result = []
        cumulative = 0
        for r in items:
            amt = float(r.total_amount)
            cumulative += amt
            pct = cumulative / total_amount * 100
            if pct <= 70:
                cls = 'A'
            elif pct <= 90:
                cls = 'B'
            else:
                cls = 'C'

            result.append({
                "material_id": r.material_id,
                "material_code": r.material_code,
                "material_name": r.material_name,
                "specification": r.specification or '',
                "unit": r.unit or '',
                "total_quantity": round(float(r.total_quantity), 2),
                "total_amount": round(amt, 2),
                "amount_pct": round(amt / total_amount * 100, 2),
                "cumulative_pct": round(pct, 2),
                "abc_class": cls,
            })

        return result

    @staticmethod
    def get_consumption_trend(
        db: Session,
        material_id: Optional[int] = None,
        months: int = 12,
    ) -> Dict:
        """
        消耗趋势 - 最近N个月月度消耗量，及简单线性预测下3个月

        返回: 历史月度数据 + 预测数据
        """
        end_date = date.today().replace(day=1) - timedelta(days=1)
        start_date = (end_date.replace(day=1) - timedelta(days=30 * (months - 1))).replace(day=1)

        q = db.query(
            func.strftime('%Y-%m', OutboundOrder.created_at).label('period'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        )

        if material_id:
            q = q.filter(OutboundOrder.material_id == material_id)

        q = q.group_by(func.strftime('%Y-%m', OutboundOrder.created_at)).order_by('period')
        rows = q.all()

        history = [{
            "period": r.period,
            "total_quantity": round(float(r.total_quantity), 2),
            "total_amount": round(float(r.total_amount), 2),
        } for r in rows]

        # 简单线性趋势预测（基于近6个月）
        recent = history[-6:] if len(history) >= 6 else history
        prediction = []
        trend = "stable"
        if len(recent) >= 3:
            qty_values = [h["total_quantity"] for h in recent]
            n = len(qty_values)
            x_mean = (n - 1) / 2
            y_mean = sum(qty_values) / n
            numerator = sum((i - x_mean) * (qty_values[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
            intercept = y_mean - slope * x_mean

            if slope > 0.5:
                trend = "up"
            elif slope < -0.5:
                trend = "down"

            last_period = datetime.strptime(recent[-1]["period"], '%Y-%m')
            for i in range(1, 4):
                next_month = last_period + timedelta(days=32 * i)
                next_month = next_month.replace(day=1)
                pred = max(0, intercept + slope * (n - 1 + i))
                prediction.append({
                    "period": next_month.strftime('%Y-%m'),
                    "predicted_quantity": round(pred, 2),
                })

        return {
            "history": history,
            "prediction": prediction,
            "trend": trend,
        }

    @staticmethod
    def get_inventory_value(
        db: Session,
        warehouse_id: Optional[int] = None,
        category_id: Optional[int] = None,
    ) -> List[Dict]:
        """库存价值分析 - 按仓库/分类汇总当前库存价值"""
        from app.models import Location
        q = db.query(
            Warehouse.id.label('warehouse_id'),
            Warehouse.name.label('warehouse_name'),
            MaterialCategory.id.label('category_id'),
            MaterialCategory.name.label('category_name'),
            func.count(func.distinct(Inventory.material_id)).label('material_count'),
            func.coalesce(func.sum(Inventory.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(Inventory.quantity * Material.unit_price), 0).label('total_value'),
        ).join(Material, Inventory.material_id == Material.id).join(
            Location, Inventory.location_id == Location.id
        ).join(
            Warehouse, Location.warehouse_id == Warehouse.id
        ).outerjoin(
            MaterialCategory, Material.category_id == MaterialCategory.id
        ).filter(Inventory.quantity > 0)

        if warehouse_id:
            q = q.filter(Location.warehouse_id == warehouse_id)
        if category_id:
            q = q.filter(Material.category_id == category_id)

        q = q.group_by(Warehouse.id, MaterialCategory.id).order_by(
            Warehouse.name, MaterialCategory.name
        )

        results = q.all()
        return [{
            "warehouse_id": r.warehouse_id,
            "warehouse_name": r.warehouse_name,
            "category_id": r.category_id,
            "category_name": r.category_name or '未分类',
            "material_count": r.material_count,
            "total_quantity": round(float(r.total_quantity), 2),
            "total_value": round(float(r.total_value), 2),
        } for r in results]

    @staticmethod
    def get_department_comparison(
        db: Session,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict:
        """部门消耗对比 - 指定时间段内各部门领料金额/数量排名"""
        if not start_date:
            start_date = date.today().replace(day=1) - timedelta(days=365)
        if not end_date:
            end_date = date.today()

        q = db.query(
            func.coalesce(OutboundOrder.recipient_department, '未指定').label('department'),
            func.count(OutboundOrder.id).label('order_count'),
            func.count(func.distinct(OutboundOrder.material_id)).label('material_variety'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_quantity'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.created_at <= end_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(OutboundOrder.recipient_department).order_by(
            func.sum(OutboundOrder.quantity * Material.unit_price).desc()
        )

        results = q.all()
        total_amount = sum(float(r.total_amount) for r in results) or 1

        departments = [{
            "department": r.department,
            "order_count": r.order_count,
            "material_variety": r.material_variety,
            "total_quantity": round(float(r.total_quantity), 2),
            "total_amount": round(float(r.total_amount), 2),
            "amount_pct": round(float(r.total_amount) / total_amount * 100, 2),
        } for r in results]

        return {
            "departments": departments,
            "total_amount": round(total_amount, 2),
            "date_range": {"start": str(start_date), "end": str(end_date)},
        }

    @staticmethod
    def get_sparkline_data(db: Session) -> Dict:
        """迷你图数据 - 近30天每日出库量 + 近7天每日领料金额"""
        today = date.today()
        days_30 = today - timedelta(days=29)
        days_7 = today - timedelta(days=6)

        daily_qty = db.query(
            func.strftime('%m-%d', OutboundOrder.created_at).label('day_label'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('qty'),
        ).filter(
            OutboundOrder.created_at >= days_30,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(func.strftime('%Y-%m-%d', OutboundOrder.created_at)).order_by(
            func.strftime('%Y-%m-%d', OutboundOrder.created_at)
        ).all()

        daily_amount = db.query(
            func.strftime('%m-%d', OutboundOrder.created_at).label('day_label'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('amt'),
        ).join(Material, OutboundOrder.material_id == Material.id).filter(
            OutboundOrder.created_at >= days_7,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(func.strftime('%Y-%m-%d', OutboundOrder.created_at)).order_by(
            func.strftime('%Y-%m-%d', OutboundOrder.created_at)
        ).all()

        return {
            "daily_quantity": [{"day": r.day_label, "qty": round(float(r.qty), 2)} for r in daily_qty],
            "daily_amount": [{"day": r.day_label, "amount": round(float(r.amt), 2)} for r in daily_amount],
        }

    @staticmethod
    def get_calendar_heatmap(
        db: Session, year: int, month: int
    ) -> List[Dict]:
        """日历热力图 - 指定月份按日出库次数"""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)

        rows = db.query(
            func.strftime('%Y-%m-%d', OutboundOrder.created_at).label('date_str'),
            func.count(OutboundOrder.id).label('cnt'),
        ).filter(
            OutboundOrder.created_at >= start,
            OutboundOrder.created_at < end,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(func.strftime('%Y-%m-%d', OutboundOrder.created_at)).all()

        return [{"date": r.date_str, "count": r.cnt} for r in rows]

    @staticmethod
    def get_yoy_mom_growth(db: Session) -> Dict:
        """同比环比 - 本月 vs 上月, 本月 vs 去年同月"""
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        # 去年同月
        last_year_start = month_start.replace(year=month_start.year - 1)
        last_year_end = last_year_start.replace(
            day=1, month=last_year_start.month
        )
        if last_year_start.month == 12:
            last_year_end = last_year_start.replace(year=last_year_start.year + 1, month=1, day=1)
        else:
            last_year_end = last_year_start.replace(month=last_year_start.month + 1, day=1)

        def _month_stats(since, until):
            qty = db.query(
                func.coalesce(func.sum(OutboundOrder.quantity), 0)
            ).filter(
                OutboundOrder.created_at >= since,
                OutboundOrder.created_at < until,
                OutboundOrder.status.in_(['out_of_stock', 'completed'])
            ).scalar() or 0
            amt = db.query(
                func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0)
            ).join(Material, OutboundOrder.material_id == Material.id).filter(
                OutboundOrder.created_at >= since,
                OutboundOrder.created_at < until,
                OutboundOrder.status.in_(['out_of_stock', 'completed'])
            ).scalar() or 0
            return float(qty), float(amt)

        cur_qty, cur_amt = _month_stats(month_start, now)
        lm_qty, lm_amt = _month_stats(last_month_start, month_start)
        ly_qty, ly_amt = _month_stats(last_year_start, last_year_end)

        def _pct(cur, prev):
            if prev == 0:
                return round(cur * 100, 1) if cur > 0 else 0
            return round((cur - prev) / prev * 100, 1)

        return {
            "current": {
                "period": month_start.strftime('%Y-%m'),
                "quantity": round(cur_qty, 2),
                "amount": round(cur_amt, 2),
            },
            "mom": {
                "period": last_month_start.strftime('%Y-%m'),
                "quantity_growth_pct": _pct(cur_qty, lm_qty),
                "amount_growth_pct": _pct(cur_amt, lm_amt),
            },
            "yoy": {
                "period": last_year_start.strftime('%Y-%m'),
                "quantity_growth_pct": _pct(cur_qty, ly_qty),
                "amount_growth_pct": _pct(cur_amt, ly_amt),
            },
        }

    @staticmethod
    def get_procurement_ontime(db: Session) -> Dict:
        """采购准时率 - 按供应商统计到货偏差分布"""
        q = db.query(
            InboundOrder.supplier.label('supplier_name'),
            func.count(InboundOrder.id).label('total_orders'),
            func.round(func.avg(
                func.julianday(InboundOrder.arrival_confirmed_at) -
                func.julianday(InboundOrder.expected_arrival_date)
            ), 1).label('avg_deviation_days'),
            func.sum(
                case(
                    (
                        func.julianday(InboundOrder.arrival_confirmed_at) <=
                        func.julianday(InboundOrder.expected_arrival_date),
                        1
                    ),
                    else_=0
                )
            ).label('ontime_count'),
            func.sum(
                case(
                    (
                        func.julianday(InboundOrder.arrival_confirmed_at) >
                        func.julianday(InboundOrder.expected_arrival_date),
                        1
                    ),
                    else_=0
                )
            ).label('late_count'),
        ).filter(
            InboundOrder.arrival_confirmed_at.isnot(None),
            InboundOrder.expected_arrival_date.isnot(None),
            InboundOrder.supplier.isnot(None),
            InboundOrder.supplier != '',
        ).group_by(InboundOrder.supplier).order_by(func.count(InboundOrder.id).desc())

        results = q.all()
        suppliers = []
        for r in results:
            total = r.total_orders or 1
            suppliers.append({
                "supplier_name": r.supplier_name,
                "total_orders": r.total_orders,
                "ontime_count": r.ontime_count or 0,
                "late_count": r.late_count or 0,
                "ontime_rate": round((r.ontime_count or 0) / total * 100, 1),
                "avg_deviation_days": float(r.avg_deviation_days) if r.avg_deviation_days else 0,
            })

        return {"suppliers": suppliers}

    @staticmethod
    def get_turnover(
        db: Session,
        period_days: int = 30,
        category_id: Optional[int] = None,
    ) -> Dict:
        """
        库存周转率分析

        周转率 = 出库总量 / 平均库存
        周转天数 = period_days / 周转率

        平均库存取期初+期末均值（简化处理：取该周期内入库量来估算）
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=period_days)

        q = db.query(
            Material.id.label('material_id'),
            Material.code.label('material_code'),
            Material.name.label('material_name'),
            Material.specification.label('specification'),
            Material.unit.label('unit'),
            MaterialCategory.name.label('category_name'),
            func.coalesce(func.sum(OutboundOrder.quantity), 0).label('total_outbound_qty'),
            func.coalesce(func.sum(OutboundOrder.quantity * Material.unit_price), 0).label('total_outbound_amount'),
        ).join(Material, OutboundOrder.material_id == Material.id).outerjoin(
            MaterialCategory, Material.category_id == MaterialCategory.id
        ).filter(
            OutboundOrder.created_at >= start_date,
            OutboundOrder.created_at <= end_date,
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        )

        if category_id:
            q = q.filter(Material.category_id == category_id)

        q = q.group_by(Material.id).order_by(
            func.sum(OutboundOrder.quantity * Material.unit_price).desc()
        )

        results = q.all()
        material_ids = [r.material_id for r in results]

        # 批量查询所有物料的当前库存（1次查询）
        inv_rows = db.query(
            Inventory.material_id,
            func.coalesce(func.sum(Inventory.quantity), 0).label('qty')
        ).filter(Inventory.material_id.in_(material_ids)).group_by(Inventory.material_id).all() if material_ids else []
        inv_map = {row.material_id: float(row.qty) for row in inv_rows}

        # 批量查询所有物料的周期内入库量（1次查询）
        inbound_rows = db.query(
            InboundOrder.material_id,
            func.coalesce(func.sum(InboundOrder.quantity), 0).label('qty')
        ).filter(
            InboundOrder.material_id.in_(material_ids),
            InboundOrder.created_at >= start_date,
            InboundOrder.created_at <= end_date,
            InboundOrder.status == 'completed'
        ).group_by(InboundOrder.material_id).all() if material_ids else []
        inbound_map = {row.material_id: float(row.qty) for row in inbound_rows}

        items = []
        for r in results:
            current_inv = inv_map.get(r.material_id, 0)
            inbound_qty = inbound_map.get(r.material_id, 0)

            beginning_inv = max(0, current_inv + float(r.total_outbound_qty) - inbound_qty)
            avg_inventory = (beginning_inv + current_inv) / 2

            if avg_inventory > 0:
                turnover_rate = float(r.total_outbound_qty) / avg_inventory
                turnover_days = period_days / turnover_rate if turnover_rate > 0 else 0
            else:
                turnover_rate = 0
                turnover_days = 0

            items.append({
                "material_id": r.material_id,
                "material_code": r.material_code,
                "material_name": r.material_name,
                "specification": r.specification or '',
                "unit": r.unit or '',
                "category_name": r.category_name or '未分类',
                "total_outbound_qty": round(float(r.total_outbound_qty), 2),
                "total_outbound_amount": round(float(r.total_outbound_amount), 2),
                "avg_inventory": round(avg_inventory, 2),
                "turnover_rate": round(turnover_rate, 4),
                "turnover_days": round(turnover_days, 1),
            })

        return {"items": items}

    @staticmethod
    def get_slow_moving(
        db: Session,
        days: int = 90,
        warehouse_id: Optional[int] = None,
    ) -> List[Dict]:
        """
        呆滞物料分析 - 超过指定天数未出库的库存物料

        逻辑: 对于有库存的物料，查找最后出库日期，计算距今未出库天数
        """
        from app.models import Location

        # 每个物料最后出库日期
        last_out_sub = db.query(
            OutboundOrder.material_id,
            func.max(OutboundOrder.created_at).label('last_out')
        ).filter(
            OutboundOrder.status.in_(['out_of_stock', 'completed'])
        ).group_by(OutboundOrder.material_id).subquery()

        q = db.query(
            Material.id.label('material_id'),
            Material.code.label('material_code'),
            Material.name.label('material_name'),
            Material.specification.label('specification'),
            Material.unit.label('unit'),
            Material.unit_price.label('unit_price'),
            Warehouse.id.label('warehouse_id'),
            Warehouse.name.label('warehouse_name'),
            func.coalesce(func.sum(Inventory.quantity), 0).label('current_stock'),
            last_out_sub.c.last_out.label('last_outbound_date'),
        ).join(Location, Inventory.location_id == Location.id).join(
            Warehouse, Location.warehouse_id == Warehouse.id
        ).outerjoin(
            last_out_sub, Inventory.material_id == last_out_sub.c.material_id
        ).filter(Inventory.quantity > 0)

        if warehouse_id:
            q = q.filter(Location.warehouse_id == warehouse_id)

        q = q.group_by(Material.id, Warehouse.id).order_by(
            last_out_sub.c.last_out.asc().nullsfirst()
        )

        results = q.all()
        today = date.today()

        items = []
        for r in results:
            if r.last_outbound_date:
                last_date = datetime.strptime(r.last_outbound_date[:10], '%Y-%m-%d').date() if isinstance(r.last_outbound_date, str) else (
                    r.last_outbound_date.date() if hasattr(r.last_outbound_date, 'date') else r.last_outbound_date
                )
                days_since = (today - last_date).days
            else:
                days_since = 9999  # 从未出库

            if days_since < days:
                continue

            items.append({
                "material_code": r.material_code,
                "material_name": r.material_name,
                "specification": r.specification or '',
                "unit": r.unit or '',
                "last_outbound_date": r.last_outbound_date[:10] if r.last_outbound_date else None,
                "days_since_last_outbound": days_since,
                "current_stock": round(float(r.current_stock), 2),
                "stock_value": round(float(r.current_stock) * float(r.unit_price or 0), 2),
                "warehouse_name": r.warehouse_name,
            })

        return items
