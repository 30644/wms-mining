from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime

from app.models import Material, MaterialCategory, Inventory, InventoryLedger, Location, Warehouse
from app.utils.logger import logger
from app.database import beijing_now


class InventoryAgeService:
    """库龄分析服务"""

    AGE_LEVELS = [
        ("0-30天", 0, 30),
        ("31-90天", 31, 90),
        ("91-180天", 91, 180),
        ("181-365天", 181, 365),
        ("365天以上", 366, 99999),
    ]

    @staticmethod
    def get_age_level(days: int) -> str:
        for label, low, high in InventoryAgeService.AGE_LEVELS:
            if low <= days <= high:
                return label
        return "365天以上"

    @staticmethod
    def get_inventory_age(
        db: Session = None,
        warehouse_id: Optional[int] = None,
        category_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取库龄分析数据"""
        # 查询有库存的物料
        inv_query = (
            db.query(
                Inventory.material_id,
                Inventory.location_id,
                func.sum(Inventory.quantity).label("total_qty"),
            )
            .group_by(Inventory.material_id, Inventory.location_id)
            .having(func.sum(Inventory.quantity) > 0)
        )

        if warehouse_id:
            inv_query = inv_query.join(Location, Inventory.location_id == Location.id).filter(
                Location.warehouse_id == warehouse_id
            )

        inventory_items = inv_query.all()

        items = []
        age_distribution = {label: {"count": 0, "qty": 0.0} for label, _, _ in InventoryAgeService.AGE_LEVELS}
        seen = set()

        for inv in inventory_items:
            if inv.material_id in seen:
                continue
            seen.add(inv.material_id)

            material = db.query(Material).filter(Material.id == inv.material_id).first()
            if not material:
                continue
            if category_id and material.category_id != category_id:
                continue

            # 最早入库时间
            first_in = (
                db.query(func.min(InventoryLedger.created_at))
                .filter(
                    and_(
                        InventoryLedger.material_id == inv.material_id,
                        InventoryLedger.change_quantity > 0,
                    )
                )
                .scalar()
            )

            age_days = (beijing_now() - first_in).days if first_in else 0
            age_level = InventoryAgeService.get_age_level(age_days)

            total_qty = float(
                db.query(func.coalesce(func.sum(Inventory.quantity), 0))
                .filter(Inventory.material_id == inv.material_id)
                .scalar()
            )

            # 仓库名称
            warehouse_name = ""
            loc = db.query(Location).filter(Location.id == inv.location_id).first()
            if loc and loc.warehouse:
                warehouse_name = loc.warehouse.name

            items.append({
                "material_code": material.code or "",
                "material_name": material.name,
                "specification": material.specification or "",
                "unit": material.unit,
                "warehouse_name": warehouse_name,
                "category_name": material.category.name if material.category else "",
                "quantity": round(total_qty, 2),
                "first_inbound_date": first_in.strftime("%Y-%m-%d") if first_in else "",
                "age_days": age_days,
                "age_level": age_level,
            })

            age_distribution[age_level]["count"] += 1
            age_distribution[age_level]["qty"] += total_qty

        # 按库龄降序
        items.sort(key=lambda x: x["age_days"], reverse=True)

        distribution = []
        for label, _, _ in InventoryAgeService.AGE_LEVELS:
            distribution.append({
                "level": label,
                "material_count": age_distribution[label]["count"],
                "total_qty": round(age_distribution[label]["qty"], 2),
            })

        return {"list": items, "distribution": distribution}
