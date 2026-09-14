from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta

from app.models import Material, Inventory, InventoryLedger, Warehouse
from app.utils.logger import logger
from app.database import beijing_now


class SlowMovingService:
    """呆滞物料分析服务"""

    @staticmethod
    def get_slow_moving(
        db: Session = None,
        days: int = 90,
        warehouse_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """获取呆滞物料清单"""
        cutoff_date = beijing_now() - timedelta(days=days)

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

        # 按仓库筛选
        if warehouse_id:
            from app.models import Location
            inv_query = inv_query.join(Location, Inventory.location_id == Location.id).filter(
                Location.warehouse_id == warehouse_id
            )

        inventory_items = inv_query.all()

        result = []
        seen = set()

        for inv in inventory_items:
            if inv.material_id in seen:
                continue
            seen.add(inv.material_id)

            material = db.query(Material).filter(Material.id == inv.material_id).first()
            if not material:
                continue

            # 最近一次出库时间
            last_out = (
                db.query(func.max(InventoryLedger.created_at))
                .filter(
                    and_(
                        InventoryLedger.material_id == inv.material_id,
                        InventoryLedger.change_quantity < 0,
                    )
                )
                .scalar()
            )

            if last_out and last_out >= cutoff_date:
                continue  # 最近有出库，不算呆滞

            # 总库存数量
            total_qty = float(
                db.query(func.coalesce(func.sum(Inventory.quantity), 0))
                .filter(Inventory.material_id == inv.material_id)
                .scalar()
            )
            if total_qty <= 0:
                continue

            days_inactive = (beijing_now() - last_out).days if last_out else days + 1

            # 仓库名称
            warehouse_name = ""
            if warehouse_id:
                wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
                warehouse_name = wh.name if wh else ""
            else:
                from app.models import Location
                loc = db.query(Location).filter(Location.id == inv.location_id).first()
                if loc and loc.warehouse:
                    warehouse_name = loc.warehouse.name

            result.append({
                "material_code": material.code or "",
                "material_name": material.name,
                "warehouse_name": warehouse_name,
                "quantity": round(total_qty, 2),
                "last_outbound_date": last_out.strftime("%Y-%m-%d") if last_out else "",
                "days_since_last_outbound": days_inactive,
                "total_value": round(total_qty * float(material.warning_threshold or 0), 2),
            })

        # 按呆滞天数降序
        result.sort(key=lambda x: x["days_since_last_outbound"], reverse=True)
        return result

    @staticmethod
    def generate_alerts(
        db: Session = None,
        days: int = 90,
    ) -> int:
        """生成呆滞物料预警，返回预警条数"""
        items = SlowMovingService.get_slow_moving(db=db, days=days)
        count = len(items)
        logger.info(f"生成呆滞物料预警 {count} 条，阈值={days}天")
        return count


