"""
入库业务核心服务层
- 全类型入库业务实现（采购入库、调拨入库、退库入库、盘盈入库）
- 单据自动编号
- 库存实时增加、事务控制、状态流转
- 数据校验、权限控制
"""
from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_, or_
from datetime import datetime
import json
from decimal import Decimal

from app.models import (
    InboundOrder, Material, Location, Inventory, User,
    OperationLog, NcSyncRecord, ScanInboundSession, Warehouse,
    MaterialCategory
)
from app.utils.logger import logger
from app.services.inventory_ledger_service import InventoryLedgerService
from app.database import beijing_now


# 入库单编号前缀定义
INBOUND_TYPE_CODES = {
    'procurement': 'CG',      # 采购入库
    'transfer_in': 'ZB',      # 调拨入库
    'return': 'TH',           # 退库入库
    'inventory_gain': 'PY',   # 盘盈入库
}

# 入库单状态定义
INBOUND_STATUS = {
    'draft': '到货登记',
    'pending_review': '待审核',
    'approved': '审核通过',
    'pending_inbound_review': '待入库审核',
    'completed': '已入库',
    'rejected': '审核驳回',
    'cancelled': '已作废'
}


class InboundService:
    """入库业务服务"""
    
    @staticmethod
    def generate_inbound_no(inbound_type: str, db: Session) -> str:
        """
        生成入库单号
        
        格式：前缀 + 年月日 + 序号
        例如：CG20260421001（采购入库）、ZB20260421001（调拨入库）
        
        参数：
        - inbound_type: 入库类型（procurement, transfer_in, return, inventory_gain）
        - db: 数据库会话
        
        返回：入库单号
        """
        try:
            prefix = INBOUND_TYPE_CODES.get(inbound_type, 'RK')
            date_str = beijing_now().strftime('%Y%m%d')
            
            # 查询今天已生成的单号数量
            today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(InboundOrder).filter(
                and_(
                    InboundOrder.created_at >= today_start,
                    InboundOrder.inbound_no.like(f"{prefix}{date_str}%")
                )
            ).count()
            
            sequence = str(today_count + 1).zfill(3)
            inbound_no = f"{prefix}{date_str}{sequence}"
            
            logger.info(f"生成入库单号成功 | 类型: {inbound_type} | 单号: {inbound_no}")
            return inbound_no
        
        except Exception as e:
            logger.error(f"生成入库单号异常 | 类型: {inbound_type} | 错误: {str(e)}")
            return f"RK{beijing_now().strftime('%Y%m%d%H%M%S')}"
    
    @staticmethod
    def create_inbound_order(
        inbound_type: str,
        quantity: float,
        operator_id: int,
        material_id: Optional[int] = None,
        material_name_text: Optional[str] = None,
        specification_text: Optional[str] = None,
        unit_text: Optional[str] = None,
        location_id: Optional[int] = None,
        supplier: Optional[str] = None,
        batch_info: Optional[str] = None,
        procurement_order_no: Optional[str] = None,
        source_warehouse: Optional[str] = None,
        reason: Optional[str] = None,
        status: str = 'draft',
        expected_arrival_date: Optional[datetime] = None,
        is_direct_issue: bool = False,
        direct_issue_quantity: Optional[float] = None,
        direct_issue_recipient: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str, Optional[InboundOrder]]:
        """
        创建入库单（到货登记）

        参数：
        - inbound_type: 入库类型（procurement, transfer_in, return, inventory_gain）
        - quantity: 入库数量
        - operator_id: 操作人（库管）ID
        - material_id: 物资ID（可选，有匹配物料时传入）
        - material_name_text: 手动输入的物料名称（未匹配时用）
        - specification_text: 手动输入的规格型号
        - unit_text: 手动输入的单位
        - location_id: 入库库位ID（可选，执行入库时再指定）
        - supplier: 供应商（采购入库需要）
        - batch_info: 批次信息
        - procurement_order_no: 采购订单号
        - source_warehouse: 源库房（调拨入库需要）
        - reason: 原因
        - status: 单据状态（默认 'draft'，采购创建传 'pending_arrival'）
        - expected_arrival_date: 预计到货日期
        - db: 数据库会话

        返回：(成功标志, 消息, 入库单对象)
        """
        try:
            # 数据校验
            if quantity <= 0:
                logger.warning(f"创建入库单失败: 入库数量必须大于0 | 数量: {quantity}")
                return False, "入库数量必须大于0", None

            if not material_id and not material_name_text:
                return False, "请指定物料或输入物料名称", None

            # 检查物资（如果有 material_id）
            material = None
            assigned_role = None
            material_display_name = material_name_text or ""

            if material_id:
                material = db.query(Material).filter(
                    and_(Material.id == material_id, Material.is_active == True)
                ).first()
                if not material:
                    logger.warning(f"创建入库单失败: 物资不存在或已禁用 | 物资ID: {material_id}")
                    return False, "物资不存在或已禁用", None
                material_display_name = material.name or material_name_text

                # 从物料分类获取验收员角色
                if material.category_id:
                    category = db.query(MaterialCategory).filter(
                        MaterialCategory.id == material.category_id
                    ).first()
                    if category and category.inspector_role:
                        assigned_role = category.inspector_role
                        logger.info(f"到货单自动分配验收员角色: {assigned_role} | 物料: {material.name}")

            # 检查库位（到货登记时可选的，执行入库时再指定）
            if location_id:
                location = db.query(Location).filter(
                    and_(Location.id == location_id, Location.is_active == True)
                ).first()
                if not location:
                    logger.warning(f"创建入库单失败: 库位不存在或已禁用 | 库位ID: {location_id}")
                    return False, "库位不存在或已禁用", None
                if location.capacity and Decimal(str(quantity)) > location.capacity:
                    logger.warning(f"创建入库单失败: 入库数量超过库位容量 | 库位: {location.code} | 容量: {location.capacity}")
                    return False, f"入库数量超过库位容量({float(location.capacity)})", None
            else:
                location = None

            # 检查操作人
            operator = db.query(User).filter(User.id == operator_id).first()
            if not operator:
                logger.warning(f"创建入库单失败: 操作人不存在 | 操作人ID: {operator_id}")
                return False, "操作人不存在", None

            # 检查采购员权限（采购入库必须有供应商）
            if inbound_type == 'procurement' and not supplier:
                logger.warning(f"创建采购入库单失败: 必须指定供应商")
                return False, "采购入库必须指定供应商", None

            # 生成入库单号
            inbound_no = InboundService.generate_inbound_no(inbound_type, db)

            # 直接领用不能和采购入库以外的类型混用
            if is_direct_issue and inbound_type != 'procurement':
                return False, "直接领用仅支持采购入库类型", None

            # 如果没有指定库位，自动分配第一个可用库位（执行入库时再调整）
            final_location_id = location_id
            if not final_location_id:
                default_loc = db.query(Location).filter(Location.is_active == True).first()
                if default_loc:
                    final_location_id = default_loc.id
                    location = default_loc
                    logger.info(f"到货单未指定库位，自动分配: {default_loc.code}")
                else:
                    logger.warning(f"创建入库单失败: 没有可用库位")
                    return False, "没有可用库位，请联系管理员创建库位", None

            # 创建入库单
            inbound_order = InboundOrder(
                inbound_no=inbound_no,
                material_id=material_id,
                material_name_text=material_name_text,
                specification_text=specification_text,
                unit_text=unit_text,
                location_id=final_location_id,
                quantity=Decimal(str(quantity)),
                supplier=supplier,
                batch_info=batch_info,
                procurement_order_no=procurement_order_no,
                warehouse_manager_id=operator_id,
                inbound_type=inbound_type,
                source_warehouse=source_warehouse,
                reason=reason,
                assigned_role=assigned_role,
                expected_arrival_date=expected_arrival_date,
                status=status,
                is_direct_issue=is_direct_issue,
                direct_issue_quantity=Decimal(str(direct_issue_quantity)) if direct_issue_quantity else None,
                direct_issue_recipient=direct_issue_recipient,
                created_at=beijing_now()
            )

            db.add(inbound_order)
            db.flush()
            db.commit()

            logger.info(f"入库单创建成功 | 单号: {inbound_no} | 类型: {inbound_type} | 物资: {material_display_name} | 数量: {quantity}")

            # 记录操作日志
            OperationLog.create_log(
                user_id=operator_id,
                action="create_inbound_order",
                module="inbound_management",
                related_id=inbound_order.id,
                related_no=inbound_no,
                details={
                    "inbound_type": inbound_type,
                    "material_id": material_id,
                    "material_name": material_display_name,
                    "quantity": float(quantity),
                    "location_code": location.code if location else None
                },
                db=db
            )

            return True, "入库单创建成功", inbound_order

        except Exception as e:
            db.rollback()
            logger.error(f"创建入库单异常 | 错误: {str(e)}")
            return False, f"创建入库单失败: {str(e)}", None
    
    @staticmethod
    def review_inbound_order(
        inbound_order_id: int,
        review_type: str,
        action: str,
        reviewer_id: int,
        comment: Optional[str] = None,
        location_id: Optional[int] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        审核入库单

        参数：
        - inbound_order_id: 入库单ID
        - review_type: 审核类型（receiving_review, warehouse_confirm）
        - action: 审核动作（approve, reject）
        - reviewer_id: 审核人ID
        - comment: 审核意见
        - location_id: 库位ID（执行入库时指定/调整）
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                logger.warning(f"审核入库单失败: 入库单不存在 | 入库单ID: {inbound_order_id}")
                return False, "入库单不存在"
            
            # 检查当前状态是否允许审核
            allowed_transitions = {
                'receiving_review': 'pending_review',
                'warehouse_confirm': 'approved'
            }

            if inbound_order.status != allowed_transitions.get(review_type):
                logger.warning(f"审核入库单失败: 入库单状态不允许此操作 | 当前状态: {inbound_order.status}")
                return False, f"入库单状态不允许此操作，当前状态: {inbound_order.status}"

            # 更新审核信息
            if review_type == 'receiving_review':
                inbound_order.procurement_reviewer_id = reviewer_id
                inbound_order.procurement_reviewed_at = beijing_now()
                inbound_order.procurement_comment = comment

                if action == 'approve':
                    # 更新操作人
                    inbound_order.warehouse_manager_id = reviewer_id

                    di_qty = inbound_order.direct_issue_quantity
                    if di_qty and float(di_qty) > 0:
                        total_qty = float(inbound_order.quantity)
                        di_float = float(di_qty)
                        storage_qty = total_qty - di_float

                        # 提交时已创建出库单则跳过，否则在此创建
                        if not inbound_order.outbound_order_id:
                            success, msg = InboundService._create_partial_direct_issue(
                                inbound_order=inbound_order,
                                direct_issue_qty=di_float,
                                operator_id=reviewer_id,
                                db=db
                            )
                            if not success:
                                db.rollback()
                                return False, f"自动越库失败: {msg}"

                        if storage_qty > 0:
                            inbound_order.status = 'pending_inbound_review'
                            logger.info(f"验收通过，自动越库: 入库{storage_qty}+直领{di_float}")
                        else:
                            inbound_order.status = 'completed'
                            logger.info(f"验收通过，全部越库: {di_float}")
                    else:
                        # 无直接领用数量，正常进入待入库状态
                        inbound_order.status = 'approved'
                else:
                    inbound_order.status = 'rejected'

            elif review_type == 'warehouse_confirm':
                inbound_order.warehouse_manager_id = reviewer_id

                if action == 'approve':
                    if location_id and location_id != inbound_order.location_id:
                        new_location = db.query(Location).filter(
                            and_(Location.id == location_id, Location.is_active == True)
                        ).first()
                        if not new_location:
                            db.rollback()
                            return False, "库位不存在或已禁用"
                        inbound_order.location_id = location_id
                        logger.info(f"执行入库时更新库位 | 入库单: {inbound_order.inbound_no} | 新库位: {new_location.code}")
                    # 默认全部入库，走入库后审核
                    inbound_order.status = 'pending_inbound_review'
                else:
                    inbound_order.status = 'cancelled'
            
            db.commit()
            
            logger.info(f"入库单审核成功 | 单号: {inbound_order.inbound_no} | 审核类型: {review_type} | 审核结果: {action}")
            
            # 记录操作日志
            OperationLog.create_log(
                user_id=reviewer_id,
                action=f"review_inbound_{action}",
                module="inbound_management",
                related_id=inbound_order_id,
                related_no=inbound_order.inbound_no,
                details={
                    "review_type": review_type,
                    "action": action,
                    "comment": comment,
                    "new_status": inbound_order.status
                },
                db=db
            )
            
            return True, "审核成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"审核入库单异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"审核失败: {str(e)}"

    @staticmethod
    def execute_inbound_with_split(
        inbound_order_id: int,
        operator_id: int,
        location_id: Optional[int] = None,
        direct_issue_quantity: Optional[float] = None,
        direct_issue_recipient: Optional[str] = None,
        comment: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        执行入库（支持部分越库领用）

        在验收通过后执行，支持：
        - 全部入库：走入库后审核 → 库存增加
        - 全部越库：直接完成，生成关联出库单（不进入库存）
        - 部分入库+部分越库：入库部分待审核，越库部分生成出库单

        越库领用部分生成 DI 前缀的出库单作为追溯和财务记账依据。
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).with_for_update().first()
            if not inbound_order:
                return False, "入库单不存在"

            if inbound_order.status != 'approved':
                return False, f"入库单状态不允许执行入库，当前状态: {inbound_order.status}"

            total_qty = float(inbound_order.quantity)
            di_qty = float(direct_issue_quantity) if direct_issue_quantity else 0.0
            storage_qty = total_qty - di_qty

            if di_qty < 0 or di_qty > total_qty:
                return False, f"越库数量超出总数量（{total_qty}）"

            if storage_qty < 0:
                return False, "入库数量不能小于0"

            if di_qty > 0 and not direct_issue_recipient:
                return False, "越库领用必须指定领用人/部门"

            # 更新库位
            if location_id and location_id != inbound_order.location_id:
                new_location = db.query(Location).filter(
                    and_(Location.id == location_id, Location.is_active == True)
                ).first()
                if not new_location:
                    return False, "库位不存在或已禁用"
                inbound_order.location_id = location_id

            # 更新操作人
            inbound_order.warehouse_manager_id = operator_id

            # 保存越库信息到入库单
            inbound_order.direct_issue_quantity = Decimal(str(di_qty))
            inbound_order.direct_issue_recipient = direct_issue_recipient

            # 处理越库领用部分（不入库，生成出库单用于追溯）
            if di_qty > 0:
                success, msg = InboundService._create_partial_direct_issue(
                    inbound_order=inbound_order,
                    direct_issue_qty=di_qty,
                    operator_id=operator_id,
                    db=db
                )
                if not success:
                    db.rollback()
                    return False, msg

            # 处理入库部分
            if storage_qty > 0:
                inbound_order.status = 'pending_inbound_review'
            else:
                # 全部越库，直接完成
                inbound_order.status = 'completed'

            db.commit()

            action_desc = "全部越库" if storage_qty == 0 else ("部分入库+越库" if di_qty > 0 else "全部入库")
            logger.info(f"入库执行成功 | 单号: {inbound_order.inbound_no} | 入库: {storage_qty} | 越库: {di_qty}")

            OperationLog.create_log(
                user_id=operator_id,
                action="execute_inbound_with_split",
                module="inbound_management",
                related_id=inbound_order_id,
                related_no=inbound_order.inbound_no,
                details={
                    "storage_quantity": storage_qty,
                    "direct_issue_quantity": di_qty,
                    "recipient": direct_issue_recipient,
                },
                db=db
            )

            return True, f"入库执行成功（{action_desc}）"

        except Exception as e:
            db.rollback()
            logger.error(f"执行入库异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"执行入库失败: {str(e)}"

    @staticmethod
    def _create_partial_direct_issue(
        inbound_order: InboundOrder,
        direct_issue_qty: float,
        operator_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        创建越库领用出库单（部分或全部越库）
        - 生成 DI 前缀的出库单
        - 创建出库明细
        - 不扣除库存（物料未进入库存）
        - 记录库存台账（变动量为0，仅作追溯）
        """
        try:
            from app.models import OutboundOrder, OutboundOrderItem

            if not inbound_order.material_id:
                # 尝试通过物料名称查找或自动创建
                name_text = getattr(inbound_order, 'material_name_text', None)
                if name_text:
                    matched = db.query(Material).filter(
                        Material.name == name_text,
                        Material.is_active == True
                    ).first()
                    if matched:
                        inbound_order.material_id = matched.id
                        logger.info(f"越库领用自动匹配物料 | 名称: {name_text} → ID: {matched.id}")
                    else:
                        # 自动创建物料
                        unit = getattr(inbound_order, 'unit_text', None) or '件'
                        spec = getattr(inbound_order, 'specification_text', None)
                        # 查找默认分类
                        default_cat = db.query(MaterialCategory).first()
                        if not default_cat:
                            default_cat = MaterialCategory(name='默认分类', is_active=True)
                            db.add(default_cat)
                            db.flush()
                        new_mat = Material(
                            category_id=default_cat.id,
                            name=name_text,
                            specification=spec or '',
                            unit=unit,
                            is_active=True
                        )
                        db.add(new_mat)
                        db.flush()
                        inbound_order.material_id = new_mat.id
                        logger.info(f"越库领用自动创建物料 | 名称: {name_text} → ID: {new_mat.id} | 分类: {default_cat.name}")
                else:
                    return False, "越库领用需要关联物料"

            # 生成出库单号
            date_str = beijing_now().strftime('%Y%m%d')
            outbound_count = db.query(OutboundOrder).filter(
                OutboundOrder.created_at >= beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            ).count()
            outbound_no = f"DI{date_str}{str(outbound_count + 1).zfill(3)}"

            # 越库领用直接完成，无需审批
            recipient = getattr(inbound_order, 'direct_issue_recipient', None) or ''
            # 尝试分隔 领用人/部门
            recipient_name = recipient
            recipient_department = None
            if '/' in recipient:
                parts = recipient.split('/', 1)
                recipient_name = parts[0].strip()
                recipient_department = parts[1].strip()

            outbound_order = OutboundOrder(
                outbound_no=outbound_no,
                outbound_type='direct_issue',
                material_id=inbound_order.material_id,
                location_id=inbound_order.location_id,
                quantity=Decimal(str(direct_issue_qty)),
                reason=getattr(inbound_order, 'direct_issue_reason', None) or '越库领用',
                warehouse_manager_id=operator_id,
                recipient_name=recipient_name or None,
                recipient_department=recipient_department,
                status='out_of_stock',
                approver_id=operator_id,
                approved_at=beijing_now(),
                created_at=beijing_now()
            )
            db.add(outbound_order)
            db.flush()

            # 创建出库单明细
            outbound_item = OutboundOrderItem(
                order_id=outbound_order.id,
                material_id=inbound_order.material_id,
                location_id=inbound_order.location_id,
                quantity=Decimal(str(direct_issue_qty)),
                batch_no=inbound_order.batch_info,
            )
            db.add(outbound_item)

            # 记录库存台账（越库领用：物料不进入库存，记录为0变动）
            loc = db.query(Location).filter(Location.id == inbound_order.location_id).first()
            mat = db.query(Material).filter(Material.id == inbound_order.material_id).first()
            operator = db.query(User).filter(User.id == operator_id).first()

            InventoryLedgerService.create_ledger(
                db=db,
                material_id=inbound_order.material_id,
                location_id=inbound_order.location_id,
                warehouse_id=loc.warehouse_id if loc else None,
                business_type='direct_issue',
                business_id=outbound_order.id,
                business_no=outbound_no,
                change_quantity=0,
                before_quantity=0,
                after_quantity=0,
                unit=mat.unit if mat else '件',
                operator_id=operator_id,
                operator_name=operator.real_name if operator else None,
                remark=f'越库领用: {outbound_no}，直接发往 {getattr(inbound_order, "direct_issue_recipient", "") or ""}'
            )

            # 关联入库单到出库单
            inbound_order.outbound_order_id = outbound_order.id

            logger.info(f"越库领用出库单创建成功 | 出库单号: {outbound_no} | 数量: {direct_issue_qty}")

            return True, "越库领用出库单创建成功"

        except Exception as e:
            logger.error(f"创建越库领用出库单异常 | 错误: {str(e)}")
            return False, f"创建越库领用出库单失败: {str(e)}"

    @staticmethod
    def process_inbound_review(
        inbound_order_id: int,
        action: str,
        reviewer_id: int,
        comment: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        入库后审核（pending_inbound_review → completed/rejected）

        库管完成物理入库后，由审核人确认入库结果。
        approve: 确认入库，更新库存
        reject: 驳回，状态回退到 rejected（需要人工处理已入库的实物）
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                return False, "入库单不存在"

            if inbound_order.status != 'pending_inbound_review':
                return False, f"入库单状态不允许此操作，当前状态: {inbound_order.status}"

            inbound_order.inbound_reviewer_id = reviewer_id
            inbound_order.inbound_reviewed_at = beijing_now()
            inbound_order.inbound_review_comment = comment

            if action == 'approve':
                inbound_order.status = 'completed'
                # 更新库存
                success, msg = InboundService.update_inventory_on_inbound(
                    inbound_order.id, db
                )
                if not success:
                    db.rollback()
                    return False, msg
            else:
                inbound_order.status = 'rejected'

            db.commit()

            logger.info(f"入库后审核成功 | 单号: {inbound_order.inbound_no} | 动作: {action}")

            OperationLog.create_log(
                user_id=reviewer_id,
                action=f"inbound_review_{action}",
                module="inbound_management",
                related_id=inbound_order_id,
                related_no=inbound_order.inbound_no,
                details={"action": action, "comment": comment, "new_status": inbound_order.status},
                db=db
            )

            return True, "入库审核成功" if action == 'approve' else "入库审核驳回"

        except Exception as e:
            db.rollback()
            logger.error(f"入库后审核异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"入库审核失败: {str(e)}"

    @staticmethod
    def create_outbound_for_direct_issue(
        inbound_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        直接领用：为入库单创建关联出库单，完成出库。
        物料到货后直接发给领用部门/人，不进入库存。
        """
        try:
            from app.models import OutboundOrder, OutboundOrderItem

            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                return False, "入库单不存在"

            if not inbound_order.material_id:
                return False, "直接领用需要关联物料"

            # 生成出库单号
            date_str = beijing_now().strftime('%Y%m%d')
            outbound_count = db.query(OutboundOrder).filter(
                OutboundOrder.created_at >= beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            ).count()
            outbound_no = f"DI{date_str}{str(outbound_count + 1).zfill(3)}"

            # 创建出库单
            outbound_order = OutboundOrder(
                outbound_no=outbound_no,
                outbound_type='direct_issue',
                material_id=inbound_order.material_id,
                location_id=inbound_order.location_id,
                quantity=inbound_order.quantity,
                reason=inbound_order.direct_issue_reason or '直接领用',
                warehouse_manager_id=inbound_order.warehouse_manager_id,
                status='completed',
                created_at=beijing_now()
            )
            db.add(outbound_order)
            db.flush()

            # 创建出库单明细
            outbound_item = OutboundOrderItem(
                order_id=outbound_order.id,
                material_id=inbound_order.material_id,
                location_id=inbound_order.location_id,
                quantity=inbound_order.quantity,
                batch_no=inbound_order.batch_info,
            )
            db.add(outbound_item)

            # 扣除库存（出库）
            success, msg = InboundService.update_inventory_on_outbound(
                inbound_order.material_id,
                inbound_order.location_id,
                inbound_order.quantity,
                outbound_order.id,
                outbound_no,
                inbound_order.warehouse_manager_id,
                db
            )
            if not success:
                return False, msg

            # 关联入库单到出库单
            inbound_order.outbound_order_id = outbound_order.id

            db.commit()

            logger.info(f"直接领用出库单创建成功 | 出库单号: {outbound_no} | 入库单: {inbound_order.inbound_no}")

            return True, "直接领用成功"

        except Exception as e:
            db.rollback()
            logger.error(f"直接领用创建出库单异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"直接领用失败: {str(e)}"

    @staticmethod
    def update_inventory_on_outbound(
        material_id: int,
        location_id: int,
        quantity: 'Decimal',
        outbound_order_id: int,
        outbound_no: str,
        operator_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """直接领用：扣除库存"""
        try:
            inventory = db.query(Inventory).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.location_id == location_id
                )
            ).with_for_update().first()

            if not inventory:
                return False, "库存不足：该库位无此物料库存"

            if inventory.quantity < quantity:
                return False, f"库存不足：当前库存 {float(inventory.quantity)}，需要 {float(quantity)}"

            before_qty = float(inventory.quantity)
            inventory.quantity -= quantity
            after_qty = float(inventory.quantity)

            loc = db.query(Location).filter(Location.id == location_id).first()
            operator = db.query(User).filter(User.id == operator_id).first()
            mat = db.query(Material).filter(Material.id == material_id).first()

            InventoryLedgerService.create_ledger(
                db=db,
                material_id=material_id,
                location_id=location_id,
                warehouse_id=loc.warehouse_id if loc else None,
                business_type='outbound',
                business_id=outbound_order_id,
                business_no=outbound_no,
                change_quantity=-float(quantity),
                before_quantity=before_qty,
                after_quantity=after_qty,
                unit=mat.unit if mat else '件',
                operator_id=operator_id,
                operator_name=operator.real_name if operator else None,
                remark=f'直接领用: {outbound_no}'
            )

            return True, "库存扣除成功"

        except Exception as e:
            logger.error(f"直接领用扣库存异常 | 物料ID: {material_id} | 错误: {str(e)}")
            return False, f"库存扣除失败: {str(e)}"

    @staticmethod
    def update_inventory_on_inbound(
        inbound_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        入库审核通过后，更新库存（包含事务控制和并发锁）
        
        参数：
        - inbound_order_id: 入库单ID
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                logger.warning(f"更新库存失败: 入库单不存在 | 入库单ID: {inbound_order_id}")
                return False, "入库单不存在"
            
            # 检查是否已入库（此时 status 已被 review_inbound_order 改为 completed）
            if inbound_order.status not in ('completed', 'approved'):
                logger.warning(f"更新库存失败: 入库单状态不正确 | 状态: {inbound_order.status}")
                return False, f"入库单状态不正确"
            
            material_id = inbound_order.material_id
            location_id = inbound_order.location_id
            total_qty = inbound_order.quantity
            di_qty = inbound_order.direct_issue_quantity or Decimal('0')
            quantity = total_qty - di_qty  # 只入库存储部分，越库部分不入库

            if quantity <= 0:
                # 全部越库，无需更新库存
                return True, "全部越库，无需更新库存"

            # 在库位上加锁，防止并发冲突
            existing_inventory = db.query(Inventory).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.location_id == location_id
                )
            ).with_for_update().first()

            # 记录变动前的库存数量
            before_qty = float(existing_inventory.quantity) if existing_inventory else 0.0

            if existing_inventory:
                # 库存已存在，增加数量
                existing_inventory.quantity += quantity
            else:
                # 库存不存在，创建新库存记录
                new_inventory = Inventory(
                    material_id=material_id,
                    location_id=location_id,
                    quantity=quantity
                )
                db.add(new_inventory)

            after_qty = before_qty + float(quantity)

            db.flush()

            # 创建库存台账记录
            loc = db.query(Location).filter(Location.id == location_id).first()
            operator = db.query(User).filter(User.id == inbound_order.warehouse_manager_id).first()
            mat = db.query(Material).filter(Material.id == material_id).first()
            InventoryLedgerService.create_ledger(
                db=db,
                material_id=material_id,
                location_id=location_id,
                warehouse_id=loc.warehouse_id if loc else None,
                business_type='inbound',
                business_id=inbound_order.id,
                business_no=inbound_order.inbound_no,
                change_quantity=float(quantity),
                before_quantity=before_qty,
                after_quantity=after_qty,
                unit=mat.unit if mat else '件',
                operator_id=inbound_order.warehouse_manager_id,
                operator_name=operator.real_name if operator else None,
                remark=f'入库: {inbound_order.inbound_no}'
            )

            db.commit()
            
            logger.info(f"库存更新成功 | 入库单: {inbound_order.inbound_no} | 物资ID: {material_id} | 增加数量: {quantity}")
            
            return True, "库存更新成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"更新库存异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"更新库存失败: {str(e)}"
    
    @staticmethod
    def cancel_inbound_order(
        inbound_order_id: int,
        cancelled_by: int,
        reason: Optional[str] = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        作废入库单
        
        参数：
        - inbound_order_id: 入库单ID
        - cancelled_by: 作废人ID
        - reason: 作废原因
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                logger.warning(f"作废入库单失败: 入库单不存在 | 入库单ID: {inbound_order_id}")
                return False, "入库单不存在"
            
            # 检查状态是否允许作废
            cannot_cancel_status = ['completed', 'cancelled']
            if inbound_order.status in cannot_cancel_status:
                logger.warning(f"作废入库单失败: 入库单状态不允许作废 | 状态: {inbound_order.status}")
                return False, f"入库单状态不允许作废（当前状态: {inbound_order.status}）"
            
            inbound_order.status = 'cancelled'
            db.commit()
            
            logger.info(f"入库单作废成功 | 单号: {inbound_order.inbound_no} | 作废原因: {reason}")
            
            # 记录操作日志
            OperationLog.create_log(
                user_id=cancelled_by,
                action="cancel_inbound_order",
                module="inbound_management",
                related_id=inbound_order_id,
                related_no=inbound_order.inbound_no,
                details={"reason": reason},
                db=db
            )
            
            return True, "入库单作废成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"作废入库单异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"作废失败: {str(e)}"
    
    @staticmethod
    def submit_inbound_order(
        inbound_order_id: int,
        submitter_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        提交到货单审核（draft → pending_review）

        参数：
        - inbound_order_id: 入库单ID
        - submitter_id: 提交人ID
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            if not inbound_order:
                return False, "入库单不存在"

            if inbound_order.status != 'draft':
                return False, f"入库单状态不允许提交，当前状态: {inbound_order.status}"

            inbound_order.status = 'pending_review'
            db.flush()

            # 如果有越库领用数量，提交时同步创建出库单（走审批中心审批）
            di_qty = inbound_order.direct_issue_quantity
            if di_qty and float(di_qty) > 0:
                success, msg = InboundService._create_partial_direct_issue(
                    inbound_order=inbound_order,
                    direct_issue_qty=float(di_qty),
                    operator_id=submitter_id,
                    db=db
                )
                if not success:
                    db.rollback()
                    return False, f"创建越库出库失败: {msg}"

            # 越库出库无需审批，直接完成
            if inbound_order.outbound_order_id:
                logger.info(f"越库出库单已自动完成 | 入库单: {inbound_order.inbound_no}")

            db.commit()

            logger.info(f"入库单提交审核成功 | 单号: {inbound_order.inbound_no}")

            OperationLog.create_log(
                user_id=submitter_id,
                action="submit_inbound_order",
                module="inbound_management",
                related_id=inbound_order_id,
                related_no=inbound_order.inbound_no,
                details={"new_status": "pending_review"},
                db=db
            )

            return True, "提交审核成功"
        except Exception as e:
            db.rollback()
            logger.error(f"提交入库单审核异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            return False, f"提交审核失败: {str(e)}"

    @staticmethod
    def get_inbound_order_list(
        inbound_type: Optional[str] = None,
        status: Optional[str] = None,
        material_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
        db: Session = None
    ) -> Tuple[List[Dict], int]:
        """
        查询入库单列表
        
        参数：
        - inbound_type: 入库类型
        - status: 状态
        - material_id: 物资ID
        - start_date: 开始日期
        - end_date: 结束日期
        - page: 页码
        - page_size: 每页数量
        - db: 数据库会话
        
        返回：(入库单列表, 总数)
        """
        try:
            query = db.query(InboundOrder)
            
            if inbound_type:
                query = query.filter(InboundOrder.inbound_type == inbound_type)
            
            if status:
                query = query.filter(InboundOrder.status == status)
            
            if material_id:
                query = query.filter(InboundOrder.material_id == material_id)
            
            if start_date:
                query = query.filter(InboundOrder.created_at >= start_date)
            
            if end_date:
                query = query.filter(InboundOrder.created_at <= end_date)
            
            total = query.count()
            
            orders = query.order_by(desc(InboundOrder.created_at)).offset(
                (page - 1) * page_size
            ).limit(page_size).all()
            
            result = []
            for order in orders:
                result.append(InboundService.format_inbound_order(order))
            
            return result, total
        
        except Exception as e:
            logger.error(f"查询入库单列表异常 | 错误: {str(e)}")
            return [], 0
    
    @staticmethod
    def format_inbound_order(order: InboundOrder) -> Dict:
        """格式化入库单数据"""
        material_name = None
        if order.material:
            material_name = order.material.name
        elif order.material_name_text:
            material_name = order.material_name_text
        return {
            "id": order.id,
            "inbound_no": order.inbound_no,
            "inbound_type": order.inbound_type,
            "inbound_type_name": {
                'procurement': '采购入库',
                'transfer_in': '调拨入库',
                'return': '退库入库',
                'inventory_gain': '盘盈入库'
            }.get(order.inbound_type, order.inbound_type),
            "material_id": order.material_id,
            "material_name": material_name,
            "material_name_text": order.material_name_text,
            "specification_text": order.specification_text,
            "unit_text": order.unit_text,
            "location_id": order.location_id,
            "location_code": order.location.code if order.location else None,
            "quantity": float(order.quantity),
            "actual_quantity": float(order.actual_quantity) if order.actual_quantity else None,
            "expected_arrival_date": order.expected_arrival_date.isoformat() if order.expected_arrival_date else None,
            "arrival_confirmed_at": order.arrival_confirmed_at.isoformat() if order.arrival_confirmed_at else None,
            "arrival_confirmed_by": order.arrival_confirmed_by,
            "arrival_confirmer_name": order.arrival_confirmer.real_name if order.arrival_confirmer else None,
            "supplier": order.supplier,
            "batch_info": order.batch_info,
            "procurement_order_no": order.procurement_order_no,
            "source_warehouse": order.source_warehouse,
            "reason": order.reason,
            "status": order.status,
            "status_name": INBOUND_STATUS.get(order.status, order.status),
            "procurement_reviewer_id": order.procurement_reviewer_id,
            "procurement_reviewer_name": order.procurement_reviewer.real_name if order.procurement_reviewer else None,
            "procurement_comment": order.procurement_comment,
            "procurement_reviewed_at": order.procurement_reviewed_at.isoformat() if order.procurement_reviewed_at else None,
            "technical_reviewer_id": order.technical_reviewer_id,
            "technical_reviewed_at": order.technical_reviewed_at.isoformat() if order.technical_reviewed_at else None,
            "warehouse_manager_id": order.warehouse_manager_id,
            "operator_name": order.operator.real_name if order.operator else None,
            "source": getattr(order, 'source', 'manual'),
            "scan_session_id": getattr(order, 'scan_session_id', None),
            "assigned_role": order.assigned_role,
            "is_synced_to_nc": order.is_synced_to_nc,
            "nc_sync_time": order.nc_sync_time.isoformat() if order.nc_sync_time else None,
            "nc_order_no": order.nc_order_no,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "is_direct_issue": getattr(order, 'is_direct_issue', False),
            "direct_issue_quantity": float(order.direct_issue_quantity) if order.direct_issue_quantity else None,
            "direct_issue_recipient": getattr(order, 'direct_issue_recipient', None),
            "direct_issue_reason": getattr(order, 'direct_issue_reason', None),
            "outbound_order_id": getattr(order, 'outbound_order_id', None),
            "inbound_reviewer_id": order.inbound_reviewer_id,
            "inbound_reviewer_name": order.inbound_reviewer.real_name if order.inbound_reviewer else None,
            "inbound_reviewed_at": order.inbound_reviewed_at.isoformat() if order.inbound_reviewed_at else None,
            "inbound_review_comment": order.inbound_review_comment,
            "outbound_order_no": order.outbound_order.outbound_no if order.outbound_order else None,
        }

    @staticmethod
    def generate_scan_session_no(db: Session) -> str:
        """生成扫码会话编号: SN+YYYYMMDD+3位序号"""
        prefix = 'SN'
        date_str = beijing_now().strftime('%Y%m%d')
        today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = db.query(ScanInboundSession).filter(
            ScanInboundSession.created_at >= today_start
        ).count()
        sequence = str(count + 1).zfill(3)
        session_no = f"{prefix}{date_str}{sequence}"
        logger.info(f"生成扫码会话编号成功 | 会话号: {session_no}")
        return session_no

    @staticmethod
    def start_scan_session(warehouse_id: int, operator_id: int, db: Session):
        """创建新的扫码会话"""
        try:
            session_no = InboundService.generate_scan_session_no(db)
            session = ScanInboundSession(
                session_no=session_no,
                warehouse_id=warehouse_id,
                operator_id=operator_id,
                status='active'
            )
            db.add(session)
            db.flush()
            db.commit()
            logger.info(f"扫码会话创建成功 | 会话号: {session_no} | 仓库ID: {warehouse_id}")
            return True, "扫码会话创建成功", session
        except Exception as e:
            db.rollback()
            logger.error(f"创建扫码会话异常 | 错误: {str(e)}")
            return False, f"创建扫码会话失败: {str(e)}", None

    @staticmethod
    def format_scan_session(session: ScanInboundSession, db: Session) -> Dict:
        """格式化扫码会话（含关联入库单）"""
        orders = db.query(InboundOrder).filter(
            InboundOrder.scan_session_id == session.id
        ).all()
        return {
            "id": session.id,
            "session_no": session.session_no,
            "warehouse_id": session.warehouse_id,
            "warehouse_name": session.warehouse.name if session.warehouse else None,
            "operator_id": session.operator_id,
            "operator_name": session.operator.real_name if session.operator else None,
            "total_items": session.total_items or len(orders),
            "status": session.status,
            "status_name": {'active': '进行中', 'submitted': '已完成', 'cancelled': '已取消'}.get(session.status, session.status),
            "orders": [InboundService.format_inbound_order(o) for o in orders],
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        }

    @staticmethod
    def format_inbound_receipt(order: InboundOrder, db: Session) -> Dict:
        """生成入库凭单信息"""
        material = db.query(Material).filter(Material.id == order.material_id).first()
        location = db.query(Location).filter(Location.id == order.location_id).first()
        operator = db.query(User).filter(User.id == order.warehouse_manager_id).first()
        return {
            "receipt_no": f"RC{order.inbound_no}",
            "inbound_no": order.inbound_no,
            "inbound_type": order.inbound_type,
            "inbound_type_name": {
                'procurement': '采购入库', 'transfer_in': '调拨入库',
                'return': '退库入库', 'inventory_gain': '盘盈入库'
            }.get(order.inbound_type, order.inbound_type),
            "material_name": material.name if material else None,
            "material_code": material.code if material else None,
            "material_spec": material.specification if material else None,
            "material_unit": material.unit if material else None,
            "location_code": location.code if location else None,
            "quantity": float(order.quantity),
            "actual_quantity": float(order.actual_quantity) if order.actual_quantity else None,
            "expected_arrival_date": order.expected_arrival_date.isoformat() if order.expected_arrival_date else None,
            "arrival_confirmed_at": order.arrival_confirmed_at.isoformat() if order.arrival_confirmed_at else None,
            "arrival_confirmed_by": order.arrival_confirmed_by,
            "arrival_confirmer_name": order.arrival_confirmer.real_name if order.arrival_confirmer else None,
            "supplier": order.supplier,
            "batch_info": order.batch_info,
            "operator_name": operator.real_name if operator else None,
            "inbound_time": order.created_at.isoformat() if order.created_at else None,
            "status": order.status,
            "status_name": INBOUND_STATUS.get(order.status, order.status)
        }
