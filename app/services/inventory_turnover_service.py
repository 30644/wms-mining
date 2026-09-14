from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta

from app.models import Material, MaterialCategory, Inventory, InventoryLedger
from app.utils.logger import logger
from app.database import beijing_now


class InventoryTurnoverService:
    """库存周转率分析服务"""

    @staticmethod
    def calculate_turnover(
        material_id: int,
        period_days: int = 30,
        db: Session = None,
    ) -> Dict[str, Any]:
        """计算单个物料的周转率"""
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            return {"material_id": material_id, "error": "物料不存在"}

        start_date = beijing_now() - timedelta(days=period_days)

        # 期间出库总量
        out_qty = (
            db.query(func.coalesce(func.sum(InventoryLedger.change_quantity), 0))
            .filter(
                and_(
                    InventoryLedger.material_id == material_id,
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= start_date,
                )
            )
            .scalar()
        )
        out_qty = abs(float(out_qty))

        # 期初库存（period_days 天前的库存快照）
        period_start = beijing_now() - timedelta(days=period_days)
        # 从台账推算期初库存 = 当前库存 + 期间出库 - 期间入库
        in_qty = float(
            db.query(func.coalesce(func.sum(InventoryLedger.change_quantity), 0))
            .filter(
                and_(
                    InventoryLedger.material_id == material_id,
                    InventoryLedger.change_quantity > 0,
                    InventoryLedger.created_at >= start_date,
                )
            )
            .scalar()
        )

        # 当前库存
        inv = (
            db.query(func.coalesce(func.sum(Inventory.quantity), 0))
            .filter(Inventory.material_id == material_id)
            .scalar()
        )
        current_stock = float(inv)
        beginning_stock = current_stock + out_qty - in_qty
        avg_stock = (beginning_stock + current_stock) / 2 if (beginning_stock + current_stock) > 0 else 1

        turnover_rate = round(out_qty / avg_stock, 2) if avg_stock > 0 else 0
        turnover_days = round(period_days / turnover_rate, 1) if turnover_rate > 0 else 0

        return {
            "material_id": material_id,
            "material_code": material.code,
            "material_name": material.name,
            "category_name": material.category.name if material.category else "",
            "specification": material.specification or "",
            "unit": material.unit,
            "period_days": period_days,
            "beginning_stock": round(beginning_stock, 2),
            "current_stock": round(current_stock, 2),
            "avg_stock": round(avg_stock, 2),
            "out_qty": round(out_qty, 2),
            "turnover_rate": turnover_rate,
            "turnover_days": turnover_days,
        }

    @staticmethod
    def get_turnover_list(
        db: Session = None,
        period_days: int = 30,
        category_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple:
        """获取周转率列表，按周转率升序（越慢的越靠前）"""
        query = db.query(Material)

        if category_id:
            query = query.filter(Material.category_id == category_id)

        total = query.count()
        materials = (
            query.order_by(Material.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items = []
        for m in materials:
            item = InventoryTurnoverService.calculate_turnover(m.id, period_days, db)
            items.append(item)

        # 按周转率升序排序
        items.sort(key=lambda x: x.get("turnover_rate", 0))

        return items, total
