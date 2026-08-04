from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from decimal import Decimal

from app.models import Warehouse, Supplier, Material, Location, Inventory, ReturnOrder, ReturnOrderItem
from app.utils.logger import logger
from app.services.inventory_ledger_service import InventoryLedgerService
from app.database import beijing_now


class ReturnService:
    @staticmethod
    def generate_return_no(db: Session) -> str:
        prefix = 'TH'
        date_str = beijing_now().strftime('%Y%m%d')
        today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.query(ReturnOrder).filter(
            and_(
                ReturnOrder.created_at >= today_start,
                ReturnOrder.return_no.like(f"{prefix}{date_str}%")
            )
        ).count()
        sequence = str(today_count + 1).zfill(3)
        return f"{prefix}{date_str}{sequence}"

    @staticmethod
    def create_return_order(
        supplier_id: int,
        warehouse_id: int,
        reason: Optional[str],
        remark: Optional[str],
        items: List[Dict],
        operator_id: int,
        db: Session,
        submit: bool = False,
        return_date: Optional[str] = None
    ) -> Tuple[bool, str, Optional[ReturnOrder]]:
        try:
            warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
            if supplier_id:
                supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
            else:
                supplier = db.query(Supplier).first()
            if not warehouse:
                return False, '仓库不存在', None
            if not supplier:
                supplier_id_actual = supplier_id or 1
            else:
                supplier_id_actual = supplier.id
            if not items or len(items) == 0:
                return False, '请添加退货明细', None
            return_date_dt = datetime.fromisoformat(return_date) if return_date else beijing_now()
            order = ReturnOrder(
                return_no=ReturnService.generate_return_no(db),
                supplier_id=supplier_id_actual,
                warehouse_id=warehouse_id,
                return_date=return_date_dt,
                reason=reason,
                remark=remark,
                status='pending_approval' if submit else 'draft',
                created_by=operator_id,
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
                if quantity <= 0:
                    db.rollback()
                    return False, '退货数量必须大于0', None
                order_item = ReturnOrderItem(
                    order_id=order.id,
                    material_id=material.id,
                    quantity=quantity,
                    created_at=beijing_now()
                )
                db.add(order_item)
            db.commit()
            return True, '退货单创建成功', order
        except Exception as e:
            db.rollback()
            logger.error(f"创建退货单失败: {e}")
            return False, f"创建退货单失败: {str(e)}", None

    @staticmethod
    def list_return_orders(
        order_no: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
        db: Session
    ) -> Tuple[List[Dict], int]:
        query = db.query(ReturnOrder)
        if order_no:
            query = query.filter(ReturnOrder.return_no.contains(order_no))
        if status:
            query = query.filter(ReturnOrder.status == status)
        total = query.count()
        orders = query.order_by(ReturnOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        data = []
        for order in orders:
            data.append({
                'id': order.id,
                'order_no': order.return_no,
                'supplier_name': order.supplier.supplier_name if order.supplier else None,
                'warehouse_name': order.warehouse.name if order.warehouse else None,
                'total_quantity': float(sum(item.quantity for item in order.items)),
                'reason': order.reason,
                'status': order.status,
                'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return data, total

    @staticmethod
    def get_return_order_detail(order_id: int, db: Session) -> Optional[Dict]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return None
        return {
            'id': order.id,
            'order_no': order.return_no,
            'supplier_id': order.supplier_id,
            'warehouse_id': order.warehouse_id,
            'return_date': order.return_date.strftime('%Y-%m-%d'),
            'supplier_name': order.supplier.supplier_name if order.supplier else None,
            'warehouse_name': order.warehouse.name if order.warehouse else None,
            'reason': order.reason,
            'remark': order.remark,
            'status': order.status,
            'total_quantity': float(sum(item.quantity for item in order.items)),
            'creator_name': order.creator.real_name if order.creator else None,
            'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'items': [
                {
                    'material_id': item.material_id,
                    'material_name': item.material.name if item.material else None,
                    'specification': item.material.specification if item.material else '',
                    'unit': item.material.unit if item.material else '',
                    'quantity': float(item.quantity)
                }
                for item in order.items
            ]
        }

    @staticmethod
    def approve_return_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return False, '退货单不存在'
        if order.status != 'pending_approval':
            return False, '退货单状态不允许审核'
        order.status = 'approved'
        order.updated_at = beijing_now()
        db.commit()
        success, exec_msg = ReturnService.execute_return_order(order_id, db)
        return True, '退货单审核通过并已执行' if success else f'审核通过但执行失败: {exec_msg}'

    @staticmethod
    def submit_return_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return False, '退货单不存在'
        if order.status != 'draft':
            return False, '仅草稿状态的退货单可提交'
        order.status = 'pending_approval'
        order.updated_at = beijing_now()
        db.commit()
        return True, '退货单提交成功'

    @staticmethod
    def reject_return_order(order_id: int, comment: str, db: Session) -> Tuple[bool, str]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return False, '退货单不存在'
        if order.status != 'pending_approval':
            return False, '退货单状态不允许驳回'
        order.status = 'rejected'
        if comment:
            existing_remark = order.remark or ''
            order.remark = f"{existing_remark}\n[驳回原因]: {comment}" if existing_remark else f"[驳回原因]: {comment}"
        order.updated_at = beijing_now()
        db.commit()
        logger.info(f"退货单 {order.return_no} 已驳回，原因: {comment}")
        return True, '退货单已驳回'

    @staticmethod
    def execute_return_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return False, '退货单不存在'
        if order.status != 'approved':
            return False, '退货单状态不允许执行'
        location = db.query(Location).filter(
            and_(Location.warehouse_id == order.warehouse_id, Location.is_active == True)
        ).first()
        if not location:
            return False, '目标仓库没有可用库位'
        try:
            for item in order.items:
                inventory = db.query(Inventory).filter(
                    and_(Inventory.material_id == item.material_id, Inventory.location_id == location.id)
                ).first()
                if not inventory or inventory.quantity < item.quantity:
                    mat_name = item.material.name if item.material else item.material_id
                    available = float(inventory.quantity) if inventory else 0
                    return False, f"物料 {mat_name} 库存不足（需要: {float(item.quantity)}, 可用: {available}）"
                before_qty = float(inventory.quantity)
                inventory.quantity -= item.quantity
                after_qty = float(inventory.quantity)
                # 创建退货出库台账
                InventoryLedgerService.create_ledger(
                    db=db,
                    material_id=item.material_id,
                    location_id=location.id,
                    warehouse_id=order.warehouse_id,
                    business_type='outbound',
                    business_id=order.id,
                    business_no=order.return_no,
                    change_quantity=-float(item.quantity),
                    before_quantity=before_qty,
                    after_quantity=after_qty,
                    unit=item.material.unit if item.material else '件',
                    operator_id=order.created_by,
                    remark=f'退货出库: {order.return_no}'
                )
            order.status = 'completed'
            order.updated_at = beijing_now()
            db.commit()
            try:
                from app.services.nc_sync_service import NcSyncService
                NcSyncService.sync_return_to_nc(order_id, db)
            except Exception:
                pass
            return True, '退货执行成功'
        except Exception as e:
            db.rollback()
            logger.error(f"执行退货失败: {e}")
            return False, f"退货执行失败: {str(e)}"

    @staticmethod
    def cancel_return_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(ReturnOrder).filter(ReturnOrder.id == order_id).first()
        if not order:
            return False, '退货单不存在'
        if order.status not in ['draft', 'pending_approval']:
            return False, '退货单状态不允许取消'
        order.status = 'cancelled'
        order.updated_at = beijing_now()
        db.commit()
        return True, '退货单取消成功'
