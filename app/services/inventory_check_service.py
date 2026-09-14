"""
库存盘点业务服务层
- 盘点单创建、编辑、审核、作废
- 盘点数据录入、盘盈盘亏计算
- 库存调整执行
- 盘点历史查询
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func
from datetime import datetime, date
import json
from decimal import Decimal

from app.models import (
    InventoryCheckOrder, InventoryCheckItem, Inventory, Material, Location,
    Warehouse, User, OperationLog, InventoryLedger
)
from app.utils.logger import logger
from app.config import SUPER_ADMIN_ROLE
from app.database import beijing_now


# 盘点单状态定义
CHECK_ORDER_STATUS = {
    'draft': '草稿',
    'pending_review': '待审核',
    'approved': '已审核',
    'completed': '已完成',
    'cancelled': '已作废'
}

# 盘点类型定义
CHECK_TYPE = {
    'full': '全盘',
    'partial': '抽盘',
    'warehouse': '按仓库',
    'category': '按分类',
    'material': '按物料'
}

# 盘点明细状态
CHECK_ITEM_STATUS = {
    'pending': '待盘点',
    'recorded': '已录入',
    'reviewed': '已审核',
    'adjusted': '已调整'
}


class InventoryCheckService:
    """库存盘点业务服务"""

    @staticmethod
    def generate_check_no(db: Session) -> str:
        """
        生成盘点单号
        
        格式：PD + 年月日 + 序号
        例如：PD20260423001
        """
        try:
            date_str = beijing_now().strftime('%Y%m%d')
            
            # 查询今天已生成的盘点单数量
            today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(InventoryCheckOrder).filter(
                and_(
                    InventoryCheckOrder.created_at >= today_start,
                    InventoryCheckOrder.check_no.like(f"PD{date_str}%")
                )
            ).count()
            
            sequence = str(today_count + 1).zfill(3)
            check_no = f"PD{date_str}{sequence}"
            
            logger.info(f"生成盘点单号成功 | 单号: {check_no}")
            return check_no
        
        except Exception as e:
            logger.error(f"生成盘点单号异常 | 错误: {str(e)}")
            return f"PD{beijing_now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def create_check_order(
        db: Session,
        check_type: str,
        check_date: date,
        warehouse_id: Optional[int] = None,
        category_id: Optional[int] = None,
        material_ids: Optional[List[int]] = None,
        remark: Optional[str] = None,
        creator_id: int = None
    ) -> Tuple[bool, str, Optional[InventoryCheckOrder]]:
        """
        创建盘点单
        
        参数：
        - db: 数据库会话
        - check_type: 盘点类型（full/partial/warehouse/category/material）
        - check_date: 盘点日期
        - warehouse_id: 仓库ID（按仓库盘点时使用）
        - category_id: 分类ID（按分类盘点时使用）
        - material_ids: 物料ID列表（按物料盘点时使用）
        - remark: 备注
        - creator_id: 创建人ID
        
        返回：(是否成功, 消息, 盘点单对象)
        """
        try:
            # 验证盘点类型
            if check_type not in CHECK_TYPE:
                return False, f"无效的盘点类型: {check_type}", None
            
            # 验证仓库
            if warehouse_id:
                warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
                if not warehouse:
                    return False, "仓库不存在", None
            
            # 生成盘点单号
            check_no = InventoryCheckService.generate_check_no(db)
            
            # 创建盘点主单
            check_order = InventoryCheckOrder(
                check_no=check_no,
                check_type=check_type,
                warehouse_id=warehouse_id,
                category_id=category_id,
                material_ids=json.dumps(material_ids) if material_ids else None,
                check_date=check_date,
                status='draft',
                creator_id=creator_id,
                remark=remark
            )
            
            db.add(check_order)
            db.flush()  # 获取ID
            
            # 根据盘点类型生成盘点明细
            items_created = InventoryCheckService._generate_check_items(
                db=db,
                check_order_id=check_order.id,
                check_type=check_type,
                warehouse_id=warehouse_id,
                category_id=category_id,
                material_ids=material_ids
            )
            
            # 更新盘点单统计
            check_order.total_items = items_created
            
            # 计算账面库存总量
            total_expected = db.query(func.sum(InventoryCheckItem.expected_quantity)).filter(
                InventoryCheckItem.check_order_id == check_order.id
            ).scalar() or 0
            check_order.expected_total = total_expected
            
            db.commit()
            db.refresh(check_order)
            
            logger.info(f"创建盘点单成功 | 单号: {check_no} | 物料项数: {items_created}")
            return True, "盘点单创建成功", check_order
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建盘点单异常 | 错误: {str(e)}")
            return False, f"创建盘点单失败: {str(e)}", None

    @staticmethod
    def _generate_check_items(
        db: Session,
        check_order_id: int,
        check_type: str,
        warehouse_id: Optional[int] = None,
        category_id: Optional[int] = None,
        material_ids: Optional[List[int]] = None
    ) -> int:
        """
        根据盘点类型生成盘点明细
        
        返回：生成的物料项数
        """
        # 查询库存记录
        query = db.query(Inventory).join(Material).join(Location)
        
        if check_type == 'warehouse' and warehouse_id:
            query = query.filter(Location.warehouse_id == warehouse_id)
        elif check_type == 'category' and category_id:
            query = query.filter(Material.category_id == category_id)
        elif check_type == 'material' and material_ids:
            query = query.filter(Inventory.material_id.in_(material_ids))
        # full 和 partial 查询所有有库存的记录
        
        inventories = query.all()
        
        items_count = 0
        for inv in inventories:
            # 检查是否已存在相同物料和库位的盘点记录
            existing = db.query(InventoryCheckItem).filter(
                and_(
                    InventoryCheckItem.check_order_id == check_order_id,
                    InventoryCheckItem.material_id == inv.material_id,
                    InventoryCheckItem.location_id == inv.location_id
                )
            ).first()
            
            if not existing:
                item = InventoryCheckItem(
                    check_order_id=check_order_id,
                    material_id=inv.material_id,
                    location_id=inv.location_id,
                    expected_quantity=inv.quantity,
                    actual_quantity=0,
                    difference=0,
                    status='pending'
                )
                db.add(item)
                items_count += 1
        
        db.flush()
        return items_count

    @staticmethod
    def get_check_order_list(
        db: Session,
        status: Optional[str] = None,
        check_type: Optional[str] = None,
        warehouse_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 20,
        current_user: dict = None
    ) -> Tuple[bool, str, List[Dict], int]:
        """
        获取盘点单列表（带分页）
        
        参数：
        - db: 数据库会话
        - status: 状态筛选
        - check_type: 盘点类型筛选
        - warehouse_id: 仓库筛选
        - start_date: 开始日期
        - end_date: 结束日期
        - skip: 跳过记录数
        - limit: 每页数量
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 列表数据, 总数)
        """
        try:
            query = db.query(InventoryCheckOrder)
            
            # 权限过滤：库管只能看自己创建的
            if current_user and current_user.get('role') == 'warehouse_manager':
                query = query.filter(InventoryCheckOrder.creator_id == current_user.get('id'))
            
            # 条件筛选
            if status:
                query = query.filter(InventoryCheckOrder.status == status)
            if check_type:
                query = query.filter(InventoryCheckOrder.check_type == check_type)
            if warehouse_id:
                query = query.filter(InventoryCheckOrder.warehouse_id == warehouse_id)
            if start_date:
                query = query.filter(InventoryCheckOrder.check_date >= start_date)
            if end_date:
                query = query.filter(InventoryCheckOrder.check_date <= end_date)
            
            # 排序
            query = query.order_by(desc(InventoryCheckOrder.created_at))
            
            # 分页
            total = query.count()
            orders = query.offset(skip).limit(limit).all()
            
            # 转换为字典
            result = []
            for order in orders:
                result.append({
                    'id': order.id,
                    'check_no': order.check_no,
                    'check_type': order.check_type,
                    'check_type_name': CHECK_TYPE.get(order.check_type, order.check_type),
                    'check_date': order.check_date.strftime('%Y-%m-%d') if order.check_date else None,
                    'status': order.status,
                    'status_name': CHECK_ORDER_STATUS.get(order.status, order.status),
                    'total_items': order.total_items,
                    'expected_total': float(order.expected_total) if order.expected_total else 0,
                    'actual_total': float(order.actual_total) if order.actual_total else 0,
                    'profit_total': float(order.profit_total) if order.profit_total else 0,
                    'loss_total': float(order.loss_total) if order.loss_total else 0,
                    'warehouse_id': order.warehouse_id,
                    'warehouse_name': order.warehouse.name if order.warehouse else None,
                    'creator_id': order.creator_id,
                    'creator_name': order.creator.real_name if order.creator else None,
                    'reviewer_id': order.reviewer_id,
                    'reviewer_name': order.reviewer.real_name if order.reviewer else None,
                    'reviewed_at': order.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if order.reviewed_at else None,
                    'remark': order.remark,
                    'created_at': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None
                })
            
            return True, "获取成功", result, total
        
        except Exception as e:
            logger.error(f"获取盘点单列表异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", [], 0

    @staticmethod
    def get_check_order_detail(
        db: Session,
        check_order_id: int,
        current_user: dict = None
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        获取盘点单详情
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 详情数据)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", None
            
            # 权限检查
            if current_user and current_user.get('role') == 'warehouse_manager':
                if order.creator_id != current_user.get('id'):
                    return False, "无权限查看此盘点单", None
            
            # 获取明细
            items = db.query(InventoryCheckItem).filter(
                InventoryCheckItem.check_order_id == check_order_id
            ).all()
            
            items_data = []
            for item in items:
                items_data.append({
                    'id': item.id,
                    'material_id': item.material_id,
                    'material_code': item.material.code if item.material else None,
                    'material_name': item.material.name if item.material else None,
                    'material_spec': item.material.specification if item.material else None,
                    'material_unit': item.material.unit if item.material else None,
                    'location_id': item.location_id,
                    'location_code': item.location.code if item.location else None,
                    'expected_quantity': float(item.expected_quantity) if item.expected_quantity else 0,
                    'actual_quantity': float(item.actual_quantity) if item.actual_quantity else 0,
                    'difference': float(item.difference) if item.difference else 0,
                    'difference_reason': item.difference_reason,
                    'status': item.status,
                    'status_name': CHECK_ITEM_STATUS.get(item.status, item.status),
                    'adjusted_quantity': float(item.adjusted_quantity) if item.adjusted_quantity else None,
                    'adjusted_at': item.adjusted_at.strftime('%Y-%m-%d %H:%M:%S') if item.adjusted_at else None,
                    'remark': item.remark
                })
            
            result = {
                'id': order.id,
                'check_no': order.check_no,
                'check_type': order.check_type,
                'check_type_name': CHECK_TYPE.get(order.check_type, order.check_type),
                'check_date': order.check_date.strftime('%Y-%m-%d') if order.check_date else None,
                'status': order.status,
                'status_name': CHECK_ORDER_STATUS.get(order.status, order.status),
                'total_items': order.total_items,
                'expected_total': float(order.expected_total) if order.expected_total else 0,
                'actual_total': float(order.actual_total) if order.actual_total else 0,
                'profit_total': float(order.profit_total) if order.profit_total else 0,
                'loss_total': float(order.loss_total) if order.loss_total else 0,
                'warehouse_id': order.warehouse_id,
                'warehouse_name': order.warehouse.name if order.warehouse else None,
                'category_id': order.category_id,
                'category_name': order.category.name if order.category else None,
                'creator_id': order.creator_id,
                'creator_name': order.creator.real_name if order.creator else None,
                'reviewer_id': order.reviewer_id,
                'reviewer_name': order.reviewer.real_name if order.reviewer else None,
                'reviewed_at': order.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if order.reviewed_at else None,
                'review_comment': order.review_comment,
                'remark': order.remark,
                'created_at': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None,
                'items': items_data
            }
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取盘点单详情异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", None

    @staticmethod
    def input_check_data(
        db: Session,
        check_item_id: int,
        actual_quantity: float,
        difference_reason: Optional[str] = None,
        remark: Optional[str] = None,
        operator_id: int = None
    ) -> Tuple[bool, str, Optional[InventoryCheckItem]]:
        """
        录入盘点数据
        
        参数：
        - db: 数据库会话
        - check_item_id: 盘点明细ID
        - actual_quantity: 实盘数量
        - difference_reason: 差异原因
        - remark: 备注
        - operator_id: 操作人ID
        
        返回：(是否成功, 消息, 盘点明细对象)
        """
        try:
            item = db.query(InventoryCheckItem).filter(
                InventoryCheckItem.id == check_item_id
            ).first()
            
            if not item:
                return False, "盘点明细不存在", None
            
            # 检查盘点单状态
            if item.check_order.status not in ['draft', 'pending_review']:
                return False, f"盘点单当前状态不允许录入数据: {CHECK_ORDER_STATUS.get(item.check_order.status)}", None
            
            # 更新实盘数据
            item.actual_quantity = actual_quantity
            item.difference = Decimal(str(actual_quantity)) - (item.expected_quantity or 0)
            item.difference_reason = difference_reason
            item.remark = remark
            item.status = 'recorded'
            
            db.commit()
            db.refresh(item)
            
            # 更新盘点单汇总
            InventoryCheckService._update_check_order_summary(db, item.check_order_id)
            
            logger.info(f"录入盘点数据成功 | 明细ID: {check_item_id} | 实盘数量: {actual_quantity}")
            return True, "录入成功", item
        
        except Exception as e:
            db.rollback()
            logger.error(f"录入盘点数据异常 | 错误: {str(e)}")
            return False, f"录入失败: {str(e)}", None

    @staticmethod
    def batch_input_check_data(
        db: Session,
        check_order_id: int,
        items_data: List[Dict],
        operator_id: int = None
    ) -> Tuple[bool, str, int]:
        """
        批量录入盘点数据
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - items_data: 盘点数据列表 [{item_id, actual_quantity, difference_reason, remark}, ...]
        - operator_id: 操作人ID
        
        返回：(是否成功, 消息, 成功数量)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", 0
            
            if order.status not in ['draft', 'pending_review']:
                return False, f"盘点单当前状态不允许录入数据: {CHECK_ORDER_STATUS.get(order.status)}", 0
            
            success_count = 0
            for item_data in items_data:
                item_id = item_data.get('item_id')
                actual_quantity = item_data.get('actual_quantity')
                difference_reason = item_data.get('difference_reason')
                remark = item_data.get('remark')
                
                item = db.query(InventoryCheckItem).filter(
                    InventoryCheckItem.id == item_id
                ).first()
                
                if item:
                    item.actual_quantity = actual_quantity
                    item.difference = Decimal(str(actual_quantity)) - (item.expected_quantity or 0)
                    item.difference_reason = difference_reason
                    item.remark = remark
                    item.status = 'recorded'
                    success_count += 1
            
            db.commit()
            
            # 更新盘点单汇总
            InventoryCheckService._update_check_order_summary(db, check_order_id)
            
            logger.info(f"批量录入盘点数据成功 | 盘点单: {order.check_no} | 成功数量: {success_count}")
            return True, f"成功录入{success_count}条数据", success_count
        
        except Exception as e:
            db.rollback()
            logger.error(f"批量录入盘点数据异常 | 错误: {str(e)}")
            return False, f"录入失败: {str(e)}", 0

    @staticmethod
    def _update_check_order_summary(db: Session, check_order_id: int):
        """更新盘点单汇总数据"""
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return
            
            # 统计实盘总量
            actual_total = db.query(func.sum(InventoryCheckItem.actual_quantity)).filter(
                InventoryCheckItem.check_order_id == check_order_id
            ).scalar() or 0
            
            order.actual_total = actual_total
            
            # 统计盘盈盘亏
            # 盘盈：difference > 0
            profit_total = db.query(func.sum(InventoryCheckItem.difference)).filter(
                and_(
                    InventoryCheckItem.check_order_id == check_order_id,
                    InventoryCheckItem.difference > 0
                )
            ).scalar() or 0
            
            # 盘亏：difference < 0
            loss_total = db.query(func.sum(InventoryCheckItem.difference)).filter(
                and_(
                    InventoryCheckItem.check_order_id == check_order_id,
                    InventoryCheckItem.difference < 0
                )
            ).scalar() or 0
            
            order.profit_total = abs(profit_total)
            order.loss_total = abs(loss_total)
            
            db.commit()
        
        except Exception as e:
            logger.error(f"更新盘点单汇总异常 | 错误: {str(e)}")

    @staticmethod
    def submit_for_review(
        db: Session,
        check_order_id: int,
        current_user: dict = None
    ) -> Tuple[bool, str, Optional[InventoryCheckOrder]]:
        """
        提交盘点单审核
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 盘点单对象)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", None
            
            if order.status != 'draft':
                return False, f"只有草稿状态的盘点单可以提交审核，当前状态: {CHECK_ORDER_STATUS.get(order.status)}", None
            
            # 检查是否所有明细都已录入
            unrecorded_count = db.query(InventoryCheckItem).filter(
                and_(
                    InventoryCheckItem.check_order_id == check_order_id,
                    InventoryCheckItem.status == 'pending'
                )
            ).count()
            
            if unrecorded_count > 0:
                return False, f"还有{unrecorded_count}项未录入盘点数据", None
            
            order.status = 'pending_review'
            db.commit()
            db.refresh(order)
            
            # 记录操作日志
            InventoryCheckService._create_operation_log(
                db=db,
                user_id=current_user.get('id') if current_user else None,
                action='submit_review',
                module='inventory_check',
                related_id=order.id,
                related_no=order.check_no,
                details={'status': 'pending_review'}
            )
            
            logger.info(f"提交盘点单审核成功 | 单号: {order.check_no}")
            return True, "提交审核成功", order
        
        except Exception as e:
            db.rollback()
            logger.error(f"提交审核异常 | 错误: {str(e)}")
            return False, f"提交失败: {str(e)}", None

    @staticmethod
    def review_check_order(
        db: Session,
        check_order_id: int,
        approved: bool,
        review_comment: Optional[str] = None,
        current_user: dict = None
    ) -> Tuple[bool, str, Optional[InventoryCheckOrder]]:
        """
        审核盘点单
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - approved: 是否通过
        - review_comment: 审核意见
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 盘点单对象)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", None
            
            if order.status != 'pending_review':
                return False, f"只有待审核状态的盘点单可以审核，当前状态: {CHECK_ORDER_STATUS.get(order.status)}", None
            
            # 检查是否重复审核
            if order.reviewer_id and order.reviewed_at:
                return False, "该盘点单已审核，不能重复审核", None
            
            order.reviewer_id = current_user.get('id') if current_user else None
            order.reviewed_at = beijing_now()
            order.review_comment = review_comment
            
            if approved:
                order.status = 'approved'
                # 更新明细状态为已审核
                db.query(InventoryCheckItem).filter(
                    InventoryCheckItem.check_order_id == check_order_id
                ).update({'status': 'reviewed'})
            else:
                order.status = 'draft'
            
            db.commit()
            db.refresh(order)
            
            # 记录操作日志
            InventoryCheckService._create_operation_log(
                db=db,
                user_id=current_user.get('id') if current_user else None,
                action='review' if approved else 'reject',
                module='inventory_check',
                related_id=order.id,
                related_no=order.check_no,
                details={'approved': approved, 'comment': review_comment}
            )
            
            logger.info(f"审核盘点单{'通过' if approved else '驳回'} | 单号: {order.check_no}")
            return True, f"{'审核通过' if approved else '审核驳回'}", order
        
        except Exception as e:
            db.rollback()
            logger.error(f"审核盘点单异常 | 错误: {str(e)}")
            return False, f"审核失败: {str(e)}", None

    @staticmethod
    def execute_inventory_adjustment(
        db: Session,
        check_order_id: int,
        current_user: dict = None
    ) -> Tuple[bool, str, int]:
        """
        执行库存调整
        
        审核通过后，根据盘点差异调整库存，并生成流水记录
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 调整数量)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", 0
            
            if order.status != 'approved':
                return False, f"只有已审核状态的盘点单可以执行库存调整，当前状态: {CHECK_ORDER_STATUS.get(order.status)}", 0
            
            # 获取所有已审核的盘点明细
            items = db.query(InventoryCheckItem).filter(
                and_(
                    InventoryCheckItem.check_order_id == check_order_id,
                    InventoryCheckItem.status == 'reviewed',
                    InventoryCheckItem.difference != 0
                )
            ).all()
            
            if not items:
                return True, "无需调整的物料", 0
            
            adjusted_count = 0
            
            for item in items:
                # 获取当前库存
                inventory = db.query(Inventory).filter(
                    and_(
                        Inventory.material_id == item.material_id,
                        Inventory.location_id == item.location_id
                    )
                ).first()
                
                before_quantity = inventory.quantity if inventory else 0
                # 调整后数量 = 实盘数量
                after_quantity = item.actual_quantity
                change_quantity = after_quantity - before_quantity
                
                if inventory:
                    # 更新库存
                    inventory.quantity = after_quantity
                else:
                    # 创建库存记录
                    inventory = Inventory(
                        material_id=item.material_id,
                        location_id=item.location_id,
                        quantity=after_quantity
                    )
                    db.add(inventory)
                
                # 更新盘点明细状态
                item.status = 'adjusted'
                item.adjusted_quantity = after_quantity
                item.adjusted_at = beijing_now()
                item.adjusted_by = current_user.get('id') if current_user else None
                
                # 生成库存流水记录
                ledger = InventoryLedger(
                    ledger_no=InventoryCheckService._generate_ledger_no(db),
                    material_id=item.material_id,
                    location_id=item.location_id,
                    warehouse_id=item.location.warehouse_id if item.location else None,
                    business_type='inventory_gain' if change_quantity > 0 else 'inventory_loss',
                    business_id=order.id,
                    business_no=order.check_no,
                    change_quantity=change_quantity,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    unit=item.material.unit if item.material else '件',
                    operator_id=current_user.get('id') if current_user else None,
                    operator_name=current_user.get('real_name') if current_user else None,
                    remark=f"盘点调整：{item.difference_reason or '无'}"
                )
                db.add(ledger)
                
                adjusted_count += 1
            
            # 更新盘点单状态
            order.status = 'completed'
            
            db.commit()
            
            # 记录操作日志
            InventoryCheckService._create_operation_log(
                db=db,
                user_id=current_user.get('id') if current_user else None,
                action='execute_adjustment',
                module='inventory_check',
                related_id=order.id,
                related_no=order.check_no,
                details={'adjusted_count': adjusted_count}
            )
            
            logger.info(f"执行库存调整成功 | 盘点单: {order.check_no} | 调整项数: {adjusted_count}")
            return True, f"成功调整{adjusted_count}项库存", adjusted_count
        
        except Exception as e:
            db.rollback()
            logger.error(f"执行库存调整异常 | 错误: {str(e)}")
            return False, f"调整失败: {str(e)}", 0

    @staticmethod
    def _generate_ledger_no(db: Session) -> str:
        """生成流水单号"""
        try:
            date_str = beijing_now().strftime('%Y%m%d')
            today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(InventoryLedger).filter(
                and_(
                    InventoryLedger.created_at >= today_start,
                    InventoryLedger.ledger_no.like(f"LZ{date_str}%")
                )
            ).count()
            
            sequence = str(today_count + 1).zfill(4)
            return f"LZ{date_str}{sequence}"
        
        except Exception as e:
            logger.error(f"生成流水单号异常 | 错误: {str(e)}")
            return f"LZ{beijing_now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def cancel_check_order(
        db: Session,
        check_order_id: int,
        current_user: dict = None
    ) -> Tuple[bool, str, Optional[InventoryCheckOrder]]:
        """
        作废盘点单
        
        参数：
        - db: 数据库会话
        - check_order_id: 盘点单ID
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 盘点单对象)
        """
        try:
            order = db.query(InventoryCheckOrder).filter(
                InventoryCheckOrder.id == check_order_id
            ).first()
            
            if not order:
                return False, "盘点单不存在", None
            
            if order.status in ['completed', 'cancelled']:
                return False, f"当前状态不允许作废: {CHECK_ORDER_STATUS.get(order.status)}", None
            
            order.status = 'cancelled'
            db.commit()
            db.refresh(order)
            
            # 记录操作日志
            InventoryCheckService._create_operation_log(
                db=db,
                user_id=current_user.get('id') if current_user else None,
                action='cancel',
                module='inventory_check',
                related_id=order.id,
                related_no=order.check_no,
                details={}
            )
            
            logger.info(f"作废盘点单成功 | 单号: {order.check_no}")
            return True, "作废成功", order
        
        except Exception as e:
            db.rollback()
            logger.error(f"作废盘点单异常 | 错误: {str(e)}")
            return False, f"作废失败: {str(e)}", None

    @staticmethod
    def _create_operation_log(
        db: Session,
        user_id: int,
        action: str,
        module: str,
        related_id: int = None,
        related_no: str = None,
        details: dict = None
    ):
        """创建操作日志"""
        try:
            log = OperationLog(
                user_id=user_id,
                action=action,
                module=module,
                related_id=related_id,
                related_no=related_no,
                details=details
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"创建操作日志失败 | 错误: {str(e)}")