from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from decimal import Decimal

from app.models import Warehouse, Location, Material, Inventory, TransferOrder, TransferOrderItem, User
from app.utils.logger import logger
from app.services.inventory_ledger_service import InventoryLedgerService
from app.database import beijing_now


class TransferService:
    @staticmethod
    def generate_transfer_no(db: Session) -> str:
        prefix = 'DB'
        date_str = beijing_now().strftime('%Y%m%d')
        today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.query(TransferOrder).filter(
            and_(
                TransferOrder.created_at >= today_start,
                TransferOrder.transfer_no.like(f"{prefix}{date_str}%")
            )
        ).count()
        sequence = str(today_count + 1).zfill(3)
        transfer_no = f"{prefix}{date_str}{sequence}"
        return transfer_no

    @staticmethod
    def create_transfer_order(
        from_warehouse_id: int,
        to_warehouse_id: int,
        reason: Optional[str],
        remark: Optional[str],
        items: List[Dict],
        operator_id: int,
        db: Session,
        submit: bool = False,
        from_location_id: Optional[int] = None,
        to_location_id: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[TransferOrder]]:
        try:
            from_wh = db.query(Warehouse).filter(Warehouse.id == from_warehouse_id).first()
            to_wh = db.query(Warehouse).filter(Warehouse.id == to_warehouse_id).first()
            if not from_wh or not to_wh:
                return False, '调出仓库或调入仓库不存在', None
            if from_warehouse_id == to_warehouse_id and from_location_id == to_location_id:
                return False, '调出与调入的仓库和库位不能完全相同', None
            if not items or len(items) == 0:
                return False, '请添加调拨物料明细', None
            order = TransferOrder(
                transfer_no=TransferService.generate_transfer_no(db),
                from_warehouse_id=from_warehouse_id,
                to_warehouse_id=to_warehouse_id,
                from_location_id=from_location_id,
                to_location_id=to_location_id,
                reason=reason,
                remark=remark,
                status='pending_approval' if submit else 'draft',
                created_by=operator_id,
                created_at=beijing_now(),
                updated_at=beijing_now()
            )
            db.add(order)
            db.flush()
            total_quantity = Decimal('0')
            for item in items:
                material = db.query(Material).filter(Material.id == item.get('material_id')).first()
                if not material:
                    db.rollback()
                    return False, f"物料ID {item.get('material_id')} 不存在", None
                if Decimal(str(item.get('quantity', 0))) <= 0:
                    db.rollback()
                    return False, '调拨数量必须大于0', None
                order_item = TransferOrderItem(
                    order_id=order.id,
                    material_id=material.id,
                    quantity=Decimal(str(item.get('quantity'))),
                    created_at=beijing_now()
                )
                total_quantity += order_item.quantity
                db.add(order_item)
            db.commit()
            return True, '调拨单创建成功', order
        except Exception as e:
            db.rollback()
            logger.error(f"创建调拨单失败: {e}")
            return False, f"创建调拨单失败: {str(e)}", None

    @staticmethod
    def list_transfer_orders(
        order_no: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
        db: Session
    ) -> Tuple[List[Dict], int]:
        query = db.query(TransferOrder)
        if order_no:
            query = query.filter(TransferOrder.transfer_no.contains(order_no))
        if status:
            query = query.filter(TransferOrder.status == status)
        total = query.count()
        orders = query.order_by(TransferOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        data = []
        for order in orders:
            data.append({
                'id': order.id,
                'order_no': order.transfer_no,
                'from_warehouse_name': order.from_warehouse.name if order.from_warehouse else None,
                'to_warehouse_name': order.to_warehouse.name if order.to_warehouse else None,
                'total_quantity': float(sum(item.quantity for item in order.items)),
                'status': order.status,
                'creator_name': order.creator.real_name if order.creator else None,
                'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        return data, total

    @staticmethod
    def get_transfer_order_detail(order_id: int, db: Session) -> Optional[Dict]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return None
        return {
            'id': order.id,
            'order_no': order.transfer_no,
            'from_warehouse_id': order.from_warehouse_id,
            'from_warehouse_name': order.from_warehouse.name if order.from_warehouse else None,
            'to_warehouse_id': order.to_warehouse_id,
            'to_warehouse_name': order.to_warehouse.name if order.to_warehouse else None,
            'reason': order.reason,
            'remark': order.remark,
            'status': order.status,
            'total_quantity': float(sum(item.quantity for item in order.items)),
            'items': [
                {
                    'material_id': item.material_id,
                    'material_name': item.material.name if item.material else None,
                    'specification': item.material.specification if item.material else '',
                    'unit': item.material.unit if item.material else '',
                    'quantity': float(item.quantity)
                }
                for item in order.items
            ],
            'creator_name': order.creator.real_name if order.creator else None,
            'created_by': order.created_by,
            'create_time': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def approve_transfer_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return False, '调拨单不存在'
        if order.status != 'pending_approval':
            return False, '调拨单状态不允许审核'
        order.status = 'approved'
        order.updated_at = beijing_now()
        db.commit()
        success, exec_msg = TransferService.execute_transfer_order(order_id, db)
        return True, '调拨单审核通过并已执行' if success else f'审核通过但执行失败: {exec_msg}'

    @staticmethod
    def submit_transfer_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return False, '调拨单不存在'
        if order.status != 'draft':
            return False, '仅草稿状态的调拨单可提交'
        order.status = 'pending_approval'
        order.updated_at = beijing_now()
        db.commit()
        return True, '调拨单提交成功，等待库管审批'

    @staticmethod
    def reject_transfer_order(order_id: int, comment: str, db: Session) -> Tuple[bool, str]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return False, '调拨单不存在'
        if order.status != 'pending_approval':
            return False, '调拨单状态不允许驳回'
        order.status = 'rejected'
        if comment:
            existing_remark = order.remark or ''
            order.remark = f"{existing_remark}\n[驳回原因]: {comment}" if existing_remark else f"[驳回原因]: {comment}"
        order.updated_at = beijing_now()
        db.commit()
        logger.info(f"调拨单 {order.transfer_no} 已驳回，原因: {comment}")
        return True, '调拨单已驳回'

    @staticmethod
    def execute_transfer_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return False, '调拨单不存在'
        if order.status != 'approved':
            return False, '调拨单状态不允许执行'
        # 使用指定库位或自动查找
        to_location = None
        if order.to_location_id:
            to_location = db.query(Location).filter(
                and_(Location.id == order.to_location_id, Location.is_active == True)
            ).first()
        if not to_location:
            to_location = db.query(Location).filter(
                and_(Location.warehouse_id == order.to_warehouse_id, Location.is_active == True)
            ).first()
        if not to_location:
            return False, '目标仓库/库位不可用'
        try:
            for item in order.items:
                remaining = item.quantity
                # 使用指定调出库位或仓库下所有库位
                loc_filter = [Location.warehouse_id == order.from_warehouse_id, Inventory.material_id == item.material_id, Inventory.quantity > 0]
                if order.from_location_id:
                    loc_filter.insert(0, Location.id == order.from_location_id)
                inventory_records = db.query(Inventory, Location).join(Location, Inventory.location_id == Location.id).filter(
                    and_(*loc_filter)
                ).order_by(Inventory.quantity.desc()).all()
                total_available = sum(inv.quantity for inv, _ in inventory_records)
                if total_available < remaining:
                    return False, f"物料 {item.material.name if item.material else item.material_id} 库存不足"
                for inventory, location in inventory_records:
                    if remaining <= 0:
                        break
                    deduct = min(inventory.quantity, remaining)
                    before_src = float(inventory.quantity)
                    inventory.quantity -= deduct
                    after_src = float(inventory.quantity)
                    remaining -= deduct
                    # 创建调拨出库台账
                    InventoryLedgerService.create_ledger(
                        db=db,
                        material_id=item.material_id,
                        location_id=location.id,
                        warehouse_id=order.from_warehouse_id,
                        business_type='transfer_out',
                        business_id=order.id,
                        business_no=order.transfer_no,
                        change_quantity=-float(deduct),
                        before_quantity=before_src,
                        after_quantity=after_src,
                        unit=item.material.unit if item.material else '件',
                        operator_id=order.created_by,
                        remark=f'调拨出库: {order.transfer_no}'
                    )
                dest_inventory = db.query(Inventory).filter(
                    and_(Inventory.material_id == item.material_id, Inventory.location_id == to_location.id)
                ).first()
                if dest_inventory:
                    before_dest = float(dest_inventory.quantity)
                    dest_inventory.quantity += item.quantity
                    after_dest = float(dest_inventory.quantity)
                else:
                    before_dest = 0
                    db.add(Inventory(material_id=item.material_id, location_id=to_location.id, quantity=item.quantity))
                    after_dest = float(item.quantity)
                # 创建调拨入库台账
                InventoryLedgerService.create_ledger(
                    db=db,
                    material_id=item.material_id,
                    location_id=to_location.id,
                    warehouse_id=order.to_warehouse_id,
                    business_type='transfer_in',
                    business_id=order.id,
                    business_no=order.transfer_no,
                    change_quantity=float(item.quantity),
                    before_quantity=before_dest,
                    after_quantity=after_dest,
                    unit=item.material.unit if item.material else '件',
                    operator_id=order.created_by,
                    remark=f'调拨入库: {order.transfer_no}'
                )
            order.status = 'completed'
            order.updated_at = beijing_now()
            db.commit()
            # 自动同步到NC（不阻塞主流程）
            try:
                from app.services.nc_sync_service import NcSyncService
                NcSyncService.sync_transfer_to_nc(order_id, db)
            except Exception:
                pass
            return True, '调拨执行成功'
        except Exception as e:
            db.rollback()
            logger.error(f"执行调拨失败: {e}")
            return False, f"调拨执行失败: {str(e)}"

    @staticmethod
    def cancel_transfer_order(order_id: int, db: Session) -> Tuple[bool, str]:
        order = db.query(TransferOrder).filter(TransferOrder.id == order_id).first()
        if not order:
            return False, '调拨单不存在'
        if order.status not in ['draft', 'pending']:
            return False, '调拨单状态不允许取消'
        order.status = 'cancelled'
        order.updated_at = beijing_now()
        db.commit()
        return True, '调拨单取消成功'
