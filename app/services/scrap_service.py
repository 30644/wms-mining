from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from decimal import Decimal

from app.models import Warehouse, Location, Material, Inventory, ScrapOrder, ScrapOrderItem, User
from app.utils.logger import logger
from app.services.inventory_ledger_service import InventoryLedgerService
from app.database import beijing_now


class ScrapService:
    @staticmethod
    def generate_scrap_no(db: Session) -> str:
        prefix = 'BF'
        date_str = beijing_now().strftime('%Y%m%d')
        today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.query(ScrapOrder).filter(
            and_(
                ScrapOrder.created_at >= today_start,
                ScrapOrder.scrap_no.like(f"{prefix}{date_str}%")
            )
        ).count()
        sequence = str(today_count + 1).zfill(3)
        return f"{prefix}{date_str}{sequence}"

    @staticmethod
    def create_scrap_order(
        warehouse_id: int,
        scrap_date: str,
        reason: Optional[str],
        remark: Optional[str],
        items: List[Dict],
        operator_id: int,
        db: Session,
        submit: bool = False
    ) -> Tuple[bool, str, Optional[ScrapOrder]]:
        try:
            warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
            if not warehouse:
                return False, '仓库不存在', None
            if not items or len(items) == 0:
                return False, '请添加报损明细', None
            scrap_date_dt = datetime.fromisoformat(scrap_date)
            total_amount = Decimal('0')
            order = ScrapOrder(
                scrap_no=ScrapService.generate_scrap_no(db),
                warehouse_id=warehouse_id,
                scrap_date=scrap_date_dt,
                reason=reason,
                remark=remark,
                status='pending_approval' if submit else 'draft',
                created_by=operator_id,
                total_amount=Decimal('0'),
                created_at=beijing_now(),
                updated_at=beijing_now()
            )
            db.add(order)
            db.flush()
            for item in items:
                material = db.query(Material).filter(Material.id == item.get('material_id')).first()
                if not material:
                    db.rollback()
                    return False, f"物料ID {item.get('material_id')} 不存在", None
                quantity = Decimal(str(item.get('quantity', 0)))
                unit_price = Decimal(str(item.get('unit_price', 0)))
                if quantity <= 0:
                    db.rollback()
                    return False, '报损数量必须大于0', None
                total_price = quantity * unit_price
                total_amount += total_price
                order_item = ScrapOrderItem(
                    order_id=order.id,
                    material_id=material.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price,
                    created_at=beijing_now()
                )
                db.add(order_item)
            order.total_amount = total_amount
            db.commit()
            return True, '报损单创建成功', order
        except Exception as e:
            db.rollback()
            logger.error(f"创建报损单失败: {e}")
            return False, f"创建报损单失败: {str(e)}", None

    @staticmethod
    def list_scrap_orders(
        order_no: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
        db: Session
    ) -> Tuple[List[Dict], int]:
        query = db.query(ScrapOrder)
        if order_no:
            query = query.filter(ScrapOrder.scrap_no.contains(order_no))
        if status:
            query = query.filter(ScrapOrder.status == status)
        total = query.count()
        orders = query.order_by(ScrapOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        data = []
        for order in orders:
            data.append({
                'id': order.id,
                'order_no': order.scrap_no,
                'warehouse_name': order.warehouse.name if order.warehouse else None,
                'total_quantity': float(sum(item.quantity for item in order.items)),
                'total_amount': float(order.total_amount or 0),
                'reason': order.reason,
                'status': order.status,
                'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return data, total

    @staticmethod
    def get_scrap_order_detail(order_id: int, db: Session) -> Optional[Dict]:
        order = db.query(ScrapOrder).filter(ScrapOrder.id == order_id).first()
        if not order:
            return None
        return {
            'id': order.id,
            'order_no': order.scrap_no,
            'warehouse_id': order.warehouse_id,
            'warehouse_name': order.warehouse.name if order.warehouse else None,
            'scrap_date': order.scrap_date.strftime('%Y-%m-%d'),
            'reason': order.reason,
            'remark': order.remark,
            'status': order.status,
            'total_amount': float(order.total_amount or 0),
            'total_quantity': float(sum(item.quantity for item in order.items)),
            'creator_name': order.creator.real_name if order.creator else None,
            'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': [
                {
                    'material_id': item.material_id,
                    'material_name': item.material.name if item.material else None,
                    'specification': item.material.specification if item.material else '',
                    'unit': item.material.unit if item.material else '',
                    'quantity': float(item.quantity),
                    'unit_price': float(item.unit_price or 0),
                    'total_price': float(item.total_price or 0)
                }
                for item in order.items
            ]
        }

    @staticmethod
    def approve_scrap_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ScrapOrder).filter(ScrapOrder.id == order_id).first()
        if not order:
            return False, '报损单不存在'
        if order.status != 'pending_approval':
            return False, '报损单状态不允许审核'
        order.status = 'approved'
        order.updated_at = beijing_now()
        db.commit()
        # 审核通过后自动执行
        success, exec_msg = ScrapService.execute_scrap_order(order_id, db)
        return True, '报损单审核通过并已执行' if success else f'审核通过但执行失败: {exec_msg}'

    @staticmethod
    def submit_scrap_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ScrapOrder).filter(ScrapOrder.id == order_id).first()
        if not order:
            return False, '报损单不存在'
        if order.status != 'draft':
            return False, '仅草稿状态的报损单可提交'
        order.status = 'pending_approval'
        order.updated_at = beijing_now()
        db.commit()
        return True, '报损单提交成功'

    @staticmethod
    def execute_scrap_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ScrapOrder).filter(ScrapOrder.id == order_id).first()
        if not order:
            return False, '报损单不存在'
        if order.status != 'approved':
            return False, '报损单状态不允许执行'
        try:
            for item in order.items:
                remaining = item.quantity
                inventory_records = db.query(Inventory, Location).join(Location, Inventory.location_id == Location.id).filter(
                    and_(
                        Inventory.material_id == item.material_id,
                        Location.warehouse_id == order.warehouse_id,
                        Inventory.quantity > 0
                    )
                ).order_by(Inventory.quantity.desc()).all()
                total_available = sum(inv.quantity for inv, _ in inventory_records)
                if total_available < remaining:
                    return False, f"物料 {item.material.name if item.material else item.material_id} 库存不足"
                for inventory, location in inventory_records:
                    if remaining <= 0:
                        break
                    deduct = min(inventory.quantity, remaining)
                    before_qty = float(inventory.quantity)
                    inventory.quantity -= deduct
                    after_qty = float(inventory.quantity)
                    remaining -= deduct
                    # 创建报废出库台账
                    InventoryLedgerService.create_ledger(
                        db=db,
                        material_id=item.material_id,
                        location_id=location.id,
                        warehouse_id=order.warehouse_id,
                        business_type='inventory_loss',
                        business_id=order.id,
                        business_no=order.scrap_no,
                        change_quantity=-float(deduct),
                        before_quantity=before_qty,
                        after_quantity=after_qty,
                        unit=item.material.unit if item.material else '件',
                        operator_id=order.created_by,
                        remark=f'报废出库: {order.scrap_no}'
                    )
            order.status = 'completed'
            order.updated_at = beijing_now()
            db.commit()
            try:
                from app.services.nc_sync_service import NcSyncService
                NcSyncService.sync_scrap_to_nc(order_id, db)
            except Exception:
                pass
            return True, '报损执行成功'
        except Exception as e:
            db.rollback()
            logger.error(f"执行报损失败: {e}")
            return False, f"执行报损失败: {str(e)}"

    @staticmethod
    def cancel_scrap_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ScrapOrder).filter(ScrapOrder.id == order_id).first()
        if not order:
            return False, '报损单不存在'
        if order.status not in ['draft', 'pending_approval']:
            return False, '报损单状态不允许取消'
        order.status = 'cancelled'
        order.updated_at = beijing_now()
        db.commit()
        return True, '报损单取消成功'
