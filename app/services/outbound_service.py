"""
出库业务核心服务层
- 全类型出库业务实现（物资领用、维修出库、调拨出库、盘亏出库）
- 库存检查、禁止负库存、超量领用拦截
- 单据审核流程、事务控制、状态流转
"""
from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_, func
from datetime import datetime
from decimal import Decimal

from app.models import (
    OutboundOrder, OutboundOrderItem, Request, Material, Location, Inventory, User,
    OperationLog, NcSyncRecord, InventoryLedger
)
from app.utils.logger import logger
from app.services.inventory_ledger_service import InventoryLedgerService
from app.database import beijing_now


# 出库单编号前缀定义
OUTBOUND_TYPE_CODES = {
    'requisition': 'LY',      # 物资领用
    'maintenance': 'WX',      # 维修出库
    'transfer_out': 'ZB',     # 调拨出库
    'inventory_loss': 'PK'    # 盘亏出库
}

# 出库单状态定义
OUTBOUND_STATUS = {
    'draft': '草稿',
    'pending_approval': '待审核',
    'approved': '已批准',
    'rejected': '已驳回',
    'out_of_stock': '已出库',
    'cancelled': '已作废'
}


class OutboundService:
    """出库业务服务"""

    @staticmethod
    def generate_outbound_no(outbound_type: str, db: Session) -> str:
        """
        生成出库单号

        格式：前缀 + 年月日 + 序号
        例如：LY20260421001（领用出库）、WX20260421001（维修出库）

        参数：
        - outbound_type: 出库类型
        - db: 数据库会话

        返回：出库单号
        """
        try:
            prefix = OUTBOUND_TYPE_CODES.get(outbound_type, 'CK')
            date_str = beijing_now().strftime('%Y%m%d')

            # 查询今天已生成的单号数量
            today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(OutboundOrder).filter(
                and_(
                    OutboundOrder.created_at >= today_start,
                    OutboundOrder.outbound_no.like(f"{prefix}{date_str}%")
                )
            ).count()

            sequence = str(today_count + 1).zfill(3)
            outbound_no = f"{prefix}{date_str}{sequence}"

            logger.info(f"生成出库单号成功 | 类型: {outbound_type} | 单号: {outbound_no}")
            return outbound_no

        except Exception as e:
            logger.error(f"生成出库单号异常 | 类型: {outbound_type} | 错误: {str(e)}")
            return f"CK{beijing_now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def check_inventory_available(
        material_id: int,
        required_quantity: float,
        exclude_location_id: Optional[int] = None,
        db: Session = None
    ) -> Tuple[bool, float, List[Dict]]:
        """
        检查物资库存是否充足

        参数：
        - material_id: 物资ID
        - required_quantity: 需求数量
        - exclude_location_id: 排除的库位ID（可选）
        - db: 数据库会话

        返回：(是否充足, 实际可用数量, 库位信息列表)
        """
        try:
            query = db.query(Inventory, Location).join(
                Location, Inventory.location_id == Location.id
            ).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.quantity > 0,
                    Location.is_active == True
                )
            )

            if exclude_location_id:
                query = query.filter(Location.id != exclude_location_id)

            inventory_records = query.all()

            total_available = Decimal('0')
            location_list = []

            for inv, loc in inventory_records:
                total_available += inv.quantity
                location_list.append({
                    "location_id": loc.id,
                    "location_code": loc.code,
                    "available_quantity": float(inv.quantity),
                    "warehouse_code": loc.warehouse.code if loc.warehouse else None
                })

            is_available = total_available >= Decimal(str(required_quantity))

            logger.info(f"库存检查完成 | 物资ID: {material_id} | 需求: {required_quantity} | 可用: {float(total_available)} | 充足: {is_available}")

            return is_available, float(total_available), location_list

        except Exception as e:
            logger.error(f"检查库存异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return False, 0.0, []

    @staticmethod
    def get_fifo_recommendation(
        material_id: int,
        required_quantity: float,
        db: Session = None
    ) -> List[Dict]:
        """
        FIFO（先进先出）库位推荐

        根据入库时间排序，推荐最早入库的库位优先出库。

        参数：
        - material_id: 物资ID
        - required_quantity: 需求数量
        - db: 数据库会话

        返回：[{location_id, location_code, available_qty, suggested_qty, last_inbound_date}, ...]
        """
        try:
            logger.info(f"FIFO推荐 | 物资ID: {material_id} | 需求: {required_quantity}")

            # 查询有库存的库位，按最早入库时间排序
            # 1. 先获取该物料所有有库存的库位
            inventory_records = db.query(
                Inventory, Location
            ).join(
                Location, Inventory.location_id == Location.id
            ).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.quantity > 0,
                    Location.is_active == True
                )
            ).all()

            if not inventory_records:
                logger.info(f"FIFO推荐 | 物资ID: {material_id} | 无可用库存")
                return []

            # 2. 对每个库位，查询最早入库时间
            location_data = []
            for inv, loc in inventory_records:
                # 从流水表找该库位该物料最早的入库记录
                earliest_inbound = db.query(
                    func.min(InventoryLedger.created_at)
                ).filter(
                    and_(
                        InventoryLedger.material_id == material_id,
                        InventoryLedger.location_id == loc.id,
                        InventoryLedger.change_quantity > 0
                    )
                ).scalar()

                location_data.append({
                    "location_id": loc.id,
                    "location_code": loc.code,
                    "available_qty": float(inv.quantity),
                    "last_inbound_date": earliest_inbound.isoformat() if earliest_inbound else None
                })

            # 3. 按入库时间排序（最早入库优先出库），无入库记录的排最后
            location_data.sort(key=lambda x: (
                0 if x["last_inbound_date"] else 1,
                x["last_inbound_date"] or ""
            ))

            # 4. 分配建议出库数量
            remaining = required_quantity
            recommendations = []
            for loc in location_data:
                if remaining <= 0:
                    break
                suggested = min(loc["available_qty"], remaining)
                recommendations.append({
                    "location_id": loc["location_id"],
                    "location_code": loc["location_code"],
                    "available_qty": loc["available_qty"],
                    "suggested_qty": suggested,
                    "last_inbound_date": loc["last_inbound_date"]
                })
                remaining -= suggested

            logger.info(
                f"FIFO推荐完成 | 物资ID: {material_id} | "
                f"推荐库位数: {len(recommendations)} | "
                f"已分配: {required_quantity - remaining} / {required_quantity}"
            )
            return recommendations

        except Exception as e:
            logger.error(f"FIFO推荐异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return []

    @staticmethod
    def create_outbound_order(
        outbound_type: str,
        material_id: int,
        quantity: float,
        location_id: int,
        operator_id: int,
        request_id: Optional[int] = None,
        destination_warehouse: Optional[str] = None,
        reason: Optional[str] = None,
        recipient_name: Optional[str] = None,
        recipient_department: Optional[str] = None,
        items: Optional[List[Dict]] = None,
        save_as_draft: bool = False,
        needs_post_approval: bool = False,
        db: Session = None
    ) -> Tuple[bool, str, Optional[OutboundOrder]]:
        """
        创建出库单

        参数：
        - outbound_type: 出库类型（requisition, maintenance, transfer_out, inventory_loss）
        - material_id: 物资ID（单物料兼容，未传items时使用）
        - quantity: 出库数量（单物料兼容）
        - location_id: 出库库位ID（单物料兼容）
        - operator_id: 操作人（库管）ID
        - request_id: 关联的领料申请ID（领用出库需要）
        - destination_warehouse: 目标库房（调拨出库需要）
        - reason: 出库原因（其他类型）
        - recipient_name: 领用人
        - recipient_department: 领用部门
        - items: 物料明细列表，每项含 material_id, quantity, location_id, batch_no
        - save_as_draft: True=保存为草稿，False=直接提交审核
        - db: 数据库会话

        返回：(成功标志, 消息, 出库单对象)
        """
        try:
            # 如果没有传items，用单物料参数构造items
            if items is None or len(items) == 0:
                if material_id is None or quantity is None:
                    return False, "请添加出库物料明细", None
                items = [{
                    'material_id': material_id,
                    'quantity': quantity,
                    'location_id': location_id,
                    'batch_no': None
                }]

            # 校验明细不能为空
            if not items:
                return False, "请添加出库物料明细", None

            # 检查操作人
            operator = db.query(User).filter(User.id == operator_id).first()
            if not operator:
                logger.warning(f"创建出库单失败: 操作人不存在 | 操作人ID: {operator_id}")
                return False, "操作人不存在", None

            # 领用出库需要关联申请单（紧急领料跳过审批状态校验）
            if outbound_type == 'requisition' and request_id:
                request = db.query(Request).filter(Request.id == request_id).first()
                if not request:
                    logger.warning(f"创建出库单失败: 申请单不存在 | 申请单ID: {request_id}")
                    return False, "申请单不存在", None
                if not needs_post_approval and request.status != 'approved':
                    logger.warning(f"创建出库单失败: 申请单未批准 | 申请单ID: {request_id} | 状态: {request.status}")
                    return False, f"申请单未批准（当前状态: {request.status}）", None

            # 校验每个物料
            first_item = items[0]
            fm_id = first_item.get('material_id')
            fm_qty = first_item.get('quantity', 0)
            fm_loc_id = first_item.get('location_id') or location_id

            if fm_loc_id is None:
                return False, "请指定出库库位", None

            for item in items:
                item_material_id = item.get('material_id')
                item_quantity = item.get('quantity') or 0
                if item_quantity <= 0:
                    return False, "出库数量必须大于0", None
                item_material = db.query(Material).filter(
                    and_(Material.id == item_material_id, Material.is_active == True)
                ).first()
                if not item_material:
                    return False, f"物资ID {item_material_id} 不存在或已禁用", None

            # 生成出库单号
            outbound_no = OutboundService.generate_outbound_no(outbound_type, db)

            # 创建出库单（订单级字段用第一个明细的数据填充）
            # 紧急领料：直接 out_of_stock，标记 needs_post_approval
            if needs_post_approval:
                order_status = 'out_of_stock'
            elif outbound_type == 'requisition':
                order_status = 'draft' if save_as_draft else 'pending_approval'
            else:
                order_status = 'out_of_stock'

            outbound_order = OutboundOrder(
                outbound_no=outbound_no,
                outbound_type=outbound_type,
                request_id=request_id,
                material_id=fm_id,
                location_id=fm_loc_id,
                quantity=Decimal(str(fm_qty)),
                warehouse_manager_id=operator_id,
                destination_warehouse=destination_warehouse,
                reason=reason,
                recipient_name=recipient_name,
                recipient_department=recipient_department,
                status=order_status,
                needs_post_approval=needs_post_approval,
                created_at=datetime.now()
            )

            db.add(outbound_order)
            db.flush()

            # 创建出库明细
            for item in items:
                outbound_item = OutboundOrderItem(
                    order_id=outbound_order.id,
                    material_id=item.get('material_id') or fm_id,
                    location_id=item.get('location_id') or fm_loc_id,
                    quantity=Decimal(str(item.get('quantity', 0))),
                    batch_no=item.get('batch_no')
                )
                db.add(outbound_item)

            # 如果是自动出库类型（维修、调拨、盘亏）或紧急领料，立即更新库存
            if outbound_type in ['maintenance', 'transfer_out', 'inventory_loss'] or needs_post_approval:
                success, msg = OutboundService.update_inventory_on_outbound(
                    outbound_order.id,
                    db
                )
                if not success:
                    db.rollback()
                    return False, msg, None

            db.commit()

            logger.info(f"出库单创建成功 | 单号: {outbound_no} | 类型: {outbound_type} | 明细数: {len(items)}")

            # 记录操作日志
            OperationLog.create_log(
                user_id=operator_id,
                action="create_outbound_order",
                module="outbound_management",
                related_id=outbound_order.id,
                related_no=outbound_no,
                details={
                    "outbound_type": outbound_type,
                    "items": [{'material_id': it.get('material_id'), 'quantity': it.get('quantity')} for it in items]
                },
                db=db
            )

            return True, "出库单创建成功", outbound_order

        except Exception as e:
            db.rollback()
            logger.error(f"创建出库单异常 | 错误: {str(e)}")
            return False, f"创建出库单失败: {str(e)}", None

    @staticmethod
    def submit_outbound_order(
        outbound_order_id: int,
        operator_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """提交出库单审核（草稿 → 待审核）"""
        try:
            order = db.query(OutboundOrder).filter(OutboundOrder.id == outbound_order_id).first()
            if not order:
                return False, "出库单不存在"
            if order.status != 'draft':
                return False, f"当前状态({order.status})不允许提交，仅草稿状态可提交"

            order.status = 'pending_approval'
            db.commit()

            logger.info(f"出库单提交审核成功 | 单号: {order.outbound_no}")

            OperationLog.create_log(
                user_id=operator_id,
                action="submit_outbound_order",
                module="outbound_management",
                related_id=order.id,
                related_no=order.outbound_no,
                details={"new_status": "pending_approval"},
                db=db
            )

            return True, "提交审核成功"
        except Exception as e:
            db.rollback()
            logger.error(f"提交出库单审核异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"提交失败: {str(e)}"

    @staticmethod
    def approve_outbound_order(
        outbound_order_id: int,
        approver_id: int,
        action: str,
        comment: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        审核出库单（领用出库需要审核）

        参数：
        - outbound_order_id: 出库单ID
        - approver_id: 审核人ID
        - action: 审核动作（approve, reject）
        - comment: 审核意见
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            outbound_order = db.query(OutboundOrder).filter(
                OutboundOrder.id == outbound_order_id
            ).first()
            if not outbound_order:
                logger.warning(f"审核出库单失败: 出库单不存在 | 出库单ID: {outbound_order_id}")
                return False, "出库单不存在"

            if outbound_order.status != 'pending_approval':
                logger.warning(f"审核出库单失败: 出库单状态不允许审核 | 当前状态: {outbound_order.status}")
                return False, f"出库单状态不允许审核（当前状态: {outbound_order.status}）"

            if action == 'approve':
                # 审核通过（标记为已批准，不立即扣库存）
                outbound_order.status = 'approved'
            else:
                outbound_order.status = 'rejected'

            outbound_order.approver_id = approver_id
            outbound_order.approved_at = beijing_now()
            outbound_order.approval_comment = comment

            db.commit()

            logger.info(f"出库单审核成功 | 单号: {outbound_order.outbound_no} | 审核结果: {action}")

            # 记录操作日志
            OperationLog.create_log(
                user_id=approver_id,
                action=f"approve_outbound_{action}",
                module="outbound_management",
                related_id=outbound_order_id,
                related_no=outbound_order.outbound_no,
                details={
                    "action": action,
                    "comment": comment,
                    "new_status": outbound_order.status
                },
                db=db
            )

            return True, "审核成功"

        except Exception as e:
            db.rollback()
            logger.error(f"审核出库单异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"审核失败: {str(e)}"

    @staticmethod
    def execute_outbound_order(
        outbound_order_id: int,
        operator_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        执行出库（已批准的出库单实际出库，扣除库存）

        参数：
        - outbound_order_id: 出库单ID
        - operator_id: 操作人ID
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            outbound_order = db.query(OutboundOrder).filter(
                OutboundOrder.id == outbound_order_id
            ).first()
            if not outbound_order:
                logger.warning(f"执行出库失败: 出库单不存在 | 出库单ID: {outbound_order_id}")
                return False, "出库单不存在"

            if outbound_order.status != 'approved':
                logger.warning(f"执行出库失败: 出库单状态不允许执行 | 当前状态: {outbound_order.status}")
                return False, f"出库单状态不允许执行（当前状态: {outbound_order.status}）"

            # 执行出库，扣除库存
            success, msg = OutboundService.update_inventory_on_outbound(
                outbound_order_id, db
            )
            if not success:
                return False, msg

            outbound_order.status = 'out_of_stock'

            db.commit()

            logger.info(f"出库单执行成功 | 单号: {outbound_order.outbound_no}")

            OperationLog.create_log(
                user_id=operator_id,
                action="execute_outbound_order",
                module="outbound_management",
                related_id=outbound_order_id,
                related_no=outbound_order.outbound_no,
                details={"new_status": "out_of_stock"},
                db=db
            )

            return True, "出库成功"

        except Exception as e:
            db.rollback()
            logger.error(f"执行出库异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"执行出库失败: {str(e)}"

    @staticmethod
    def post_approve_outbound_order(
        outbound_order_id: int,
        approver_id: int,
        action: str,
        comment: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        事后审批紧急出库单

        参数：
        - outbound_order_id: 出库单ID
        - approver_id: 审批人ID
        - action: approve / reject
        - comment: 审批意见
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            order = db.query(OutboundOrder).filter(OutboundOrder.id == outbound_order_id).first()
            if not order:
                return False, "出库单不存在"
            if not order.needs_post_approval:
                return False, "该出库单不需要事后审批"
            if order.post_approved_at:
                return False, "该出库单已完成事后审批"

            order.post_approver_id = approver_id
            order.post_approved_at = beijing_now()
            order.post_approval_comment = comment or '已悉知'
            order.needs_post_approval = False
            db.commit()

            logger.info(f"事后审批完成 | 单号: {order.outbound_no} | 结果: {action}")

            OperationLog.create_log(
                user_id=approver_id,
                action=f"post_approve_{action}",
                module="outbound_management",
                related_id=order.id,
                related_no=order.outbound_no,
                details={"action": action, "comment": comment},
                db=db
            )

            return True, "事后审批完成"

        except Exception as e:
            db.rollback()
            logger.error(f"事后审批异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"事后审批失败: {str(e)}"

    @staticmethod
    def update_inventory_on_outbound(
        outbound_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        出库单审核通过后，更新库存（包含事务控制和并发锁）

        参数：
        - outbound_order_id: 出库单ID
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            outbound_order = db.query(OutboundOrder).filter(
                OutboundOrder.id == outbound_order_id
            ).first()
            if not outbound_order:
                logger.warning(f"更新库存失败: 出库单不存在 | 出库单ID: {outbound_order_id}")
                return False, "出库单不存在"

            # 获取出库明细
            items = outbound_order.outbound_items or []
            if not items:
                # 向后兼容：没有明细时使用订单级字段
                items_data = [{
                    'material_id': outbound_order.material_id,
                    'quantity': outbound_order.quantity,
                    'location_id': outbound_order.location_id
                }]
            else:
                items_data = [{
                    'material_id': item.material_id,
                    'quantity': item.quantity,
                    'location_id': item.location_id or outbound_order.location_id
                } for item in items]

            for item_data in items_data:
                mid = item_data['material_id']
                qty = item_data['quantity']
                lid = item_data['location_id']

                inventory = db.query(Inventory).filter(
                    and_(
                        Inventory.material_id == mid,
                        Inventory.location_id == lid
                    )
                ).with_for_update().first()

                if not inventory or inventory.quantity < qty:
                    actual_qty = float(inventory.quantity) if inventory else 0.0
                    logger.warning(f"库存不足，无法出库 | 出库单: {outbound_order.outbound_no} | 物料ID: {mid} | 需要: {qty} | 实际: {actual_qty}")
                    return False, f"库存不足（需要: {qty}, 实际: {actual_qty}）"

                before_qty = float(inventory.quantity)
                inventory.quantity -= qty
                if inventory.quantity < 0:
                    inventory.quantity = 0
                after_qty = float(inventory.quantity)

                loc = db.query(Location).filter(Location.id == lid).first()
                mat = db.query(Material).filter(Material.id == mid).first()
                operator = db.query(User).filter(User.id == outbound_order.warehouse_manager_id).first()
                InventoryLedgerService.create_ledger(
                    db=db,
                    material_id=mid,
                    location_id=lid,
                    warehouse_id=loc.warehouse_id if loc else None,
                    business_type='outbound',
                    business_id=outbound_order.id,
                    business_no=outbound_order.outbound_no,
                    change_quantity=-float(qty),
                    before_quantity=before_qty,
                    after_quantity=after_qty,
                    unit=mat.unit if mat else '件',
                    operator_id=outbound_order.warehouse_manager_id,
                    operator_name=operator.real_name if operator else None,
                    remark=f'出库: {outbound_order.outbound_no}'
                )

            db.commit()

            logger.info(f"库存更新成功 | 出库单: {outbound_order.outbound_no} | 明细数: {len(items_data)}")

            return True, "库存更新成功"

        except Exception as e:
            db.rollback()
            logger.error(f"更新库存异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"更新库存失败: {str(e)}"

    @staticmethod
    def cancel_outbound_order(
        outbound_order_id: int,
        cancelled_by: int,
        reason: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        作废出库单

        参数：
        - outbound_order_id: 出库单ID
        - cancelled_by: 作废人ID
        - reason: 作废原因
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            outbound_order = db.query(OutboundOrder).filter(
                OutboundOrder.id == outbound_order_id
            ).first()
            if not outbound_order:
                logger.warning(f"作废出库单失败: 出库单不存在 | 出库单ID: {outbound_order_id}")
                return False, "出库单不存在"

            # 检查状态是否允许作废
            cannot_cancel_status = ['out_of_stock', 'cancelled']
            if outbound_order.status in cannot_cancel_status:
                logger.warning(f"作废出库单失败: 出库单状态不允许作废 | 状态: {outbound_order.status}")
                return False, f"出库单状态不允许作废（当前状态: {outbound_order.status}）"

            # 如果已出库，需要恢复库存
            if outbound_order.status == 'out_of_stock':
                items = outbound_order.outbound_items or []
                if not items:
                    # 向后兼容：使用订单级字段
                    inventory = db.query(Inventory).filter(
                        and_(
                            Inventory.material_id == outbound_order.material_id,
                            Inventory.location_id == outbound_order.location_id
                        )
                    ).with_for_update().first()
                    if inventory:
                        inventory.quantity += outbound_order.quantity
                else:
                    for item in items:
                        inventory = db.query(Inventory).filter(
                            and_(
                                Inventory.material_id == item.material_id,
                                Inventory.location_id == item.location_id
                            )
                        ).with_for_update().first()
                        if inventory:
                            inventory.quantity += item.quantity

            outbound_order.status = 'cancelled'
            db.commit()

            logger.info(f"出库单作废成功 | 单号: {outbound_order.outbound_no} | 作废原因: {reason}")

            # 记录操作日志
            OperationLog.create_log(
                user_id=cancelled_by,
                action="cancel_outbound_order",
                module="outbound_management",
                related_id=outbound_order_id,
                related_no=outbound_order.outbound_no,
                details={"reason": reason},
                db=db
            )

            return True, "出库单作废成功"

        except Exception as e:
            db.rollback()
            logger.error(f"作废出库单异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            return False, f"作废失败: {str(e)}"

    @staticmethod
    def get_outbound_order_list(
        outbound_type: Optional[str] = None,
        status: Optional[str] = None,
        material_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        order_no: Optional[str] = None,
        keyword: Optional[str] = None,
        needs_post_approval: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
        db: Session = None
    ) -> Tuple[List[Dict], int]:
        """
        查询出库单列表

        参数：
        - outbound_type: 出库类型
        - status: 状态
        - material_id: 物资ID
        - start_date: 开始日期
        - end_date: 结束日期
        - order_no: 出库单号（模糊搜索）
        - needs_post_approval: 是否需要事后审批（True=查询待事后审批的紧急领料单）
        - page: 页码
        - page_size: 每页数量
        - db: 数据库会话

        返回：(出库单列表, 总数)
        """
        try:
            query = db.query(OutboundOrder)

            if outbound_type:
                query = query.filter(OutboundOrder.outbound_type == outbound_type)

            if status:
                query = query.filter(OutboundOrder.status == status)

            if material_id:
                query = query.filter(OutboundOrder.material_id == material_id)

            if needs_post_approval is not None:
                if needs_post_approval:
                    query = query.filter(and_(
                        OutboundOrder.needs_post_approval == True,
                        OutboundOrder.post_approved_at == None
                    ))
                else:
                    query = query.filter(OutboundOrder.needs_post_approval == False)

            if order_no:
                query = query.filter(OutboundOrder.outbound_no.like(f"%{order_no}%"))

            if keyword:
                kw = f"%{keyword}%"
                query = query.join(Material, OutboundOrder.material_id == Material.id)
                query = query.filter(or_(
                    OutboundOrder.outbound_no.like(kw),
                    OutboundOrder.recipient_name.like(kw),
                    Material.name.like(kw)
                ))

            if start_date:
                query = query.filter(OutboundOrder.created_at >= start_date)

            if end_date:
                query = query.filter(OutboundOrder.created_at <= end_date)

            total = query.count()

            orders = query.order_by(desc(OutboundOrder.created_at)).offset(
                (page - 1) * page_size
            ).limit(page_size).all()

            result = []
            for order in orders:
                result.append(OutboundService.format_outbound_order(order))

            return result, total

        except Exception as e:
            logger.error(f"查询出库单列表异常 | 错误: {str(e)}")
            return [], 0

    @staticmethod
    def format_outbound_order(order: OutboundOrder) -> Dict:
        """格式化出库单数据"""
        outbound_items = []
        if order.outbound_items:
            for item in order.outbound_items:
                outbound_items.append({
                    "id": item.id,
                    "material_id": item.material_id,
                    "material_name": item.material.name if item.material else None,
                    "location_id": item.location_id,
                    "location_code": item.location.code if item.location else None,
                    "quantity": float(item.quantity),
                    "batch_no": item.batch_no
                })
        return {
            "id": order.id,
            "outbound_no": order.outbound_no,
            "outbound_type": order.outbound_type,
            "outbound_type_name": {
                'requisition': '物资领用',
                'maintenance': '维修出库',
                'transfer_out': '调拨出库',
                'inventory_loss': '盘亏出库',
                'direct_issue': '越库领用'
            }.get(order.outbound_type, order.outbound_type),
            "request_id": order.request_id,
            "material_id": order.material_id,
            "material_name": order.material.name if order.material else None,
            "material_code": order.material.code if order.material else None,
            "unit": order.material.unit if order.material else None,
            "specification": order.material.specification if order.material else None,
            "location_id": order.location_id,
            "location_code": order.location.code if order.location else None,
            "quantity": float(order.quantity),
            "destination_warehouse": order.destination_warehouse,
            "reason": order.reason,
            "status": order.status,
            "status_name": OUTBOUND_STATUS.get(order.status, order.status),
            "approver_id": order.approver_id,
            "approver_name": order.approver.real_name if order.approver else None,
            "approved_at": order.approved_at.isoformat() if order.approved_at else None,
            "approval_comment": order.approval_comment,
            "warehouse_manager_id": order.warehouse_manager_id,
            "creator_name": order.operator.real_name if order.operator else None,
            "recipient_name": order.recipient_name,
            "recipient_department": order.recipient_department,
            "is_synced_to_nc": order.is_synced_to_nc,
            "nc_sync_time": order.nc_sync_time.isoformat() if order.nc_sync_time else None,
            "nc_order_no": order.nc_order_no,
            "outbound_items": outbound_items,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "needs_post_approval": order.needs_post_approval if hasattr(order, 'needs_post_approval') else False,
            "post_approver_id": order.post_approver_id if hasattr(order, 'post_approver_id') else None,
            "post_approved_at": order.post_approved_at.isoformat() if hasattr(order, 'post_approved_at') and order.post_approved_at else None,
            "post_approval_comment": order.post_approval_comment if hasattr(order, 'post_approval_comment') else None,
        }
