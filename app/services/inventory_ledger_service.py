"""
库存流水台账业务服务层
- 库存流水记录查询
- 库存变动趋势分析
- 库存台账汇总统计
- 库存追溯查询
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func
from datetime import datetime, date, timedelta
import json

from app.models import (
    InventoryLedger, Inventory, Material, MaterialCategory, Location, Warehouse,
    User, OperationLog, InboundOrder, OutboundOrder, InventoryCheckOrder
)
from app.utils.logger import logger
from app.config import SUPER_ADMIN_ROLE
from app.database import beijing_now


# 业务类型定义
BUSINESS_TYPE = {
    'inbound': '采购入库',
    'outbound': '销售出库',
    'inventory_gain': '盘盈入库',
    'inventory_loss': '盘亏出库',
    'transfer_in': '调拨入库',
    'transfer_out': '调拨出库',
    'return_in': '退货入库',
    'return_out': '退货出库',
    'adjustment': '库存调整',
    'initial': '期初录入',
    'cross_docking': '越库领用'
}

# 流水状态
LEDGER_STATUS = {
    'pending': '待确认',
    'confirmed': '已确认',
    'cancelled': '已取消'
}


class InventoryLedgerService:
    """库存流水台账业务服务"""

    @staticmethod
    def generate_ledger_no(db: Session, prefix: str = 'LZ') -> str:
        """
        生成流水单号
        
        参数：
        - db: 数据库会话
        - prefix: 前缀（默认LZ）
        
        返回：流水单号
        """
        try:
            date_str = beijing_now().strftime('%Y%m%d')
            today_start = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            today_count = db.query(InventoryLedger).filter(
                and_(
                    InventoryLedger.created_at >= today_start,
                    InventoryLedger.ledger_no.like(f"{prefix}{date_str}%")
                )
            ).count()
            
            sequence = str(today_count + 1).zfill(4)
            ledger_no = f"{prefix}{date_str}{sequence}"
            
            logger.info(f"生成流水单号成功 | 单号: {ledger_no}")
            return ledger_no
        
        except Exception as e:
            logger.error(f"生成流水单号异常 | 错误: {str(e)}")
            return f"{prefix}{beijing_now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def create_ledger(
        db: Session,
        material_id: int,
        location_id: int,
        warehouse_id: int,
        business_type: str,
        business_id: Optional[int] = None,
        business_no: Optional[str] = None,
        change_quantity: float = 0,
        before_quantity: float = 0,
        after_quantity: float = 0,
        unit: str = '件',
        operator_id: Optional[int] = None,
        operator_name: Optional[str] = None,
        remark: Optional[str] = None
    ) -> Tuple[bool, str, Optional[InventoryLedger]]:
        """
        创建库存流水记录
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID
        - location_id: 库位ID
        - warehouse_id: 仓库ID
        - business_type: 业务类型
        - business_id: 业务ID
        - business_no: 业务单号
        - change_quantity: 变动数量（正数入库，负数出库）
        - before_quantity: 变动前数量
        - after_quantity: 变动后数量
        - unit: 单位
        - operator_id: 操作人ID
        - operator_name: 操作人姓名
        - remark: 备注
        
        返回：(是否成功, 消息, 流水对象)
        """
        try:
            # 验证业务类型
            if business_type not in BUSINESS_TYPE:
                return False, f"无效的业务类型: {business_type}", None
            
            # 验证物料
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                return False, "物料不存在", None
            
            # 验证库位
            location = db.query(Location).filter(Location.id == location_id).first()
            if not location:
                return False, "库位不存在", None
            
            # 生成流水单号
            prefix_map = {
                'inbound': 'RK',
                'outbound': 'CK',
                'inventory_gain': 'PY',
                'inventory_loss': 'PK',
                'transfer_in': 'DBR',
                'transfer_out': 'DBC',
                'return_in': 'THR',
                'return_out': 'THC',
                'adjustment': 'TZ',
                'initial': 'QC',
                'cross_docking': 'YK'
            }
            prefix = prefix_map.get(business_type, 'LZ')
            ledger_no = InventoryLedgerService.generate_ledger_no(db, prefix)
            
            # 创建流水记录
            ledger = InventoryLedger(
                ledger_no=ledger_no,
                material_id=material_id,
                location_id=location_id,
                warehouse_id=warehouse_id,
                business_type=business_type,
                business_id=business_id or 0,
                business_no=business_no or ledger_no,
                change_quantity=change_quantity,
                before_quantity=before_quantity,
                after_quantity=after_quantity,
                unit=unit,
                operator_id=operator_id,
                operator_name=operator_name,
                remark=remark,
                status='confirmed'
            )
            
            db.add(ledger)
            db.commit()
            db.refresh(ledger)
            
            logger.info(f"创建库存流水成功 | 单号: {ledger_no} | 物料: {material_id} | 变动: {change_quantity}")
            return True, "流水记录创建成功", ledger
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建库存流水异常 | 错误: {str(e)}")
            return False, f"创建失败: {str(e)}", None

    @staticmethod
    def get_ledger_list(
        db: Session,
        material_id: Optional[int] = None,
        location_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        business_type: Optional[str] = None,
        business_no: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 20,
        current_user: dict = None
    ) -> Tuple[bool, str, List[Dict], int]:
        """
        获取流水记录列表
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID筛选
        - location_id: 库位ID筛选
        - warehouse_id: 仓库ID筛选
        - business_type: 业务类型筛选
        - business_no: 业务单号筛选
        - start_date: 开始日期
        - end_date: 结束日期
        - skip: 跳过记录数
        - limit: 每页数量
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 列表数据, 总数)
        """
        try:
            query = db.query(InventoryLedger)
            
            # 权限过滤
            if current_user and current_user.role == 'warehouse_manager':
                # 库管只能看自己仓库的流水
                if current_user.warehouse_id:
                    query = query.filter(InventoryLedger.warehouse_id == current_user.warehouse_id)
            
            # 条件筛选
            if material_id:
                query = query.filter(InventoryLedger.material_id == material_id)
            if location_id:
                query = query.filter(InventoryLedger.location_id == location_id)
            if warehouse_id:
                query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
            if business_type:
                query = query.filter(InventoryLedger.business_type == business_type)
            if business_no:
                query = query.filter(InventoryLedger.business_no.like(f"%{business_no}%"))
            if start_date:
                query = query.filter(InventoryLedger.created_at >= start_date)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                query = query.filter(InventoryLedger.created_at <= end_datetime)
            
            # 排序：按时间倒序
            query = query.order_by(desc(InventoryLedger.created_at))
            
            # 分页
            total = query.count()
            ledgers = query.offset(skip).limit(limit).all()
            
            # 转换为字典
            result = []
            for ledger in ledgers:
                result.append({
                    'id': ledger.id,
                    'ledger_no': ledger.ledger_no,
                    'material_id': ledger.material_id,
                    'material_code': ledger.material.code if ledger.material else None,
                    'material_name': ledger.material.name if ledger.material else None,
                    'material_spec': ledger.material.specification if ledger.material else None,
                    'material_unit': ledger.material.unit if ledger.material else None,
                    'location_id': ledger.location_id,
                    'location_code': ledger.location.code if ledger.location else None,
                    'warehouse_id': ledger.warehouse_id,
                    'warehouse_name': ledger.warehouse.name if ledger.warehouse else None,
                    'business_type': ledger.business_type,
                    'business_type_name': BUSINESS_TYPE.get(ledger.business_type, ledger.business_type),
                    'business_id': ledger.business_id,
                    'business_no': ledger.business_no,
                    'change_quantity': float(ledger.change_quantity) if ledger.change_quantity else 0,
                    'before_quantity': float(ledger.before_quantity) if ledger.before_quantity else 0,
                    'after_quantity': float(ledger.after_quantity) if ledger.after_quantity else 0,
                    'unit': ledger.unit,
                    'operator_id': ledger.operator_id,
                    'operator_name': ledger.operator_name,
                    'status': ledger.status,
                    'status_name': LEDGER_STATUS.get(ledger.status, ledger.status),
                    'remark': ledger.remark,
                    'created_at': ledger.created_at.strftime('%Y-%m-%d %H:%M:%S') if ledger.created_at else None
                })
            
            return True, "获取成功", result, total
        
        except Exception as e:
            logger.error(f"获取流水列表异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", [], 0

    @staticmethod
    def get_ledger_detail(
        db: Session,
        ledger_id: int
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        获取流水详情
        
        参数：
        - db: 数据库会话
        - ledger_id: 流水ID
        
        返回：(是否成功, 消息, 详情数据)
        """
        try:
            ledger = db.query(InventoryLedger).filter(
                InventoryLedger.id == ledger_id
            ).first()
            
            if not ledger:
                return False, "流水记录不存在", None
            
            # 获取关联业务信息
            business_info = None
            if ledger.business_type == 'inbound' and ledger.business_id:
                inbound = db.query(InboundOrder).filter(InboundOrder.id == ledger.business_id).first()
                if inbound:
                    business_info = {
                        'type': 'inbound',
                        'no': inbound.inbound_no,
                        'supplier': inbound.supplier.name if inbound.supplier else None,
                        'inbound_date': inbound.inbound_date.strftime('%Y-%m-%d') if inbound.inbound_date else None
                    }
            elif ledger.business_type == 'outbound' and ledger.business_id:
                outbound = db.query(OutboundOrder).filter(OutboundOrder.id == ledger.business_id).first()
                if outbound:
                    business_info = {
                        'type': 'outbound',
                        'no': outbound.outbound_no,
                        'customer': outbound.customer.name if outbound.customer else None,
                        'outbound_date': outbound.outbound_date.strftime('%Y-%m-%d') if outbound.outbound_date else None
                    }
            elif ledger.business_type in ['inventory_gain', 'inventory_loss'] and ledger.business_id:
                check_order = db.query(InventoryCheckOrder).filter(InventoryCheckOrder.id == ledger.business_id).first()
                if check_order:
                    business_info = {
                        'type': 'inventory_check',
                        'no': check_order.check_no,
                        'check_date': check_order.check_date.strftime('%Y-%m-%d') if check_order.check_date else None
                    }
            
            result = {
                'id': ledger.id,
                'ledger_no': ledger.ledger_no,
                'material_id': ledger.material_id,
                'material_code': ledger.material.code if ledger.material else None,
                'material_name': ledger.material.name if ledger.material else None,
                'material_spec': ledger.material.specification if ledger.material else None,
                'material_unit': ledger.material.unit if ledger.material else None,
                'location_id': ledger.location_id,
                'location_code': ledger.location.code if ledger.location else None,
                'location_name': ledger.location.name if ledger.location else None,
                'warehouse_id': ledger.warehouse_id,
                'warehouse_name': ledger.warehouse.name if ledger.warehouse else None,
                'business_type': ledger.business_type,
                'business_type_name': BUSINESS_TYPE.get(ledger.business_type, ledger.business_type),
                'business_id': ledger.business_id,
                'business_no': ledger.business_no,
                'business_info': business_info,
                'change_quantity': float(ledger.change_quantity) if ledger.change_quantity else 0,
                'before_quantity': float(ledger.before_quantity) if ledger.before_quantity else 0,
                'after_quantity': float(ledger.after_quantity) if ledger.after_quantity else 0,
                'unit': ledger.unit,
                'operator_id': ledger.operator_id,
                'operator_name': ledger.operator_name,
                'status': ledger.status,
                'status_name': LEDGER_STATUS.get(ledger.status, ledger.status),
                'remark': ledger.remark,
                'created_at': ledger.created_at.strftime('%Y-%m-%d %H:%M:%S') if ledger.created_at else None
            }
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取流水详情异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", None

    @staticmethod
    def get_material_ledger_trace(
        db: Session,
        material_id: int,
        location_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        batch_no: Optional[str] = None,  # 批次号筛选
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[bool, str, List[Dict]]:
        """
        物料追溯查询

        查询指定物料的所有库存变动记录

        参数：
        - db: 数据库会话
        - material_id: 物料ID
        - location_id: 库位ID（可选）
        - warehouse_id: 仓库ID（可选）
        - batch_no: 批次号（可选）
        - start_date: 开始日期
        - end_date: 结束日期
        - skip: 跳过记录数
        - limit: 每页数量

        返回：(是否成功, 消息, 流水列表)
        """
        try:
            query = db.query(InventoryLedger).filter(
                InventoryLedger.material_id == material_id
            )

            if location_id:
                query = query.filter(InventoryLedger.location_id == location_id)
            if warehouse_id:
                query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
            if batch_no:
                query = query.filter(InventoryLedger.batch_no == batch_no)
            if start_date:
                query = query.filter(InventoryLedger.created_at >= start_date)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                query = query.filter(InventoryLedger.created_at <= end_datetime)
            
            query = query.order_by(asc(InventoryLedger.created_at))

            total = query.count()
            ledgers = query.offset(skip).limit(limit).all()

            result = []
            running_quantity = 0

            for ledger in ledgers:
                running_quantity += ledger.change_quantity
                result.append({
                    'ledger_no': ledger.ledger_no,
                    'business_type': ledger.business_type,
                    'business_type_name': BUSINESS_TYPE.get(ledger.business_type, ledger.business_type),
                    'business_no': ledger.business_no,
                    'change_quantity': float(ledger.change_quantity) if ledger.change_quantity else 0,
                    'before_quantity': float(ledger.before_quantity) if ledger.before_quantity else 0,
                    'after_quantity': float(ledger.after_quantity) if ledger.after_quantity else 0,
                    'running_quantity': float(running_quantity),
                    'unit': ledger.unit,
                    'operator_name': ledger.operator_name,
                    'remark': ledger.remark,
                    'created_at': ledger.created_at.strftime('%Y-%m-%d %H:%M:%S') if ledger.created_at else None
                })
            
            return True, "获取成功", result, total

        except Exception as e:
            logger.error(f"物料追溯查询异常 | 错误: {str(e)}")
            return False, f"查询失败: {str(e)}", [], 0

    @staticmethod
    def get_inventory_summary(
        db: Session,
        warehouse_id: Optional[int] = None,
        location_id: Optional[int] = None,
        material_id: Optional[int] = None,
        category_id: Optional[int] = None,
        group_by: str = 'material'
    ) -> Tuple[bool, str, List[Dict]]:
        """
        库存台账汇总统计

        参数：
        - db: 数据库会话
        - warehouse_id: 仓库筛选
        - location_id: 库位筛选
        - material_id: 物料筛选
        - category_id: 分类筛选
        - group_by: 分组方式（material/location/warehouse/business_type）

        返回：(是否成功, 消息, 汇总数据)
        """
        try:
            # 基于库存表获取当前库存
            query = db.query(Inventory).join(Material).join(Location).join(MaterialCategory, Material.category_id == MaterialCategory.id)

            if warehouse_id:
                query = query.filter(Location.warehouse_id == warehouse_id)
            if location_id:
                query = query.filter(Inventory.location_id == location_id)
            if material_id:
                query = query.filter(Inventory.material_id == material_id)
            if category_id:
                query = query.filter(Material.category_id == category_id)

            inventories = query.all()
            
            result = []
            for inv in inventories:
                # 查询该物料的入库总量
                inbound_total = db.query(func.sum(InventoryLedger.change_quantity)).filter(
                    and_(
                        InventoryLedger.material_id == inv.material_id,
                        InventoryLedger.location_id == inv.location_id,
                        InventoryLedger.change_quantity > 0
                    )
                ).scalar() or 0
                
                # 查询该物料的出库总量
                outbound_total = db.query(func.sum(InventoryLedger.change_quantity)).filter(
                    and_(
                        InventoryLedger.material_id == inv.material_id,
                        InventoryLedger.location_id == inv.location_id,
                        InventoryLedger.change_quantity < 0
                    )
                ).scalar() or 0
                
                result.append({
                    'material_id': inv.material_id,
                    'material_code': inv.material.code if inv.material else None,
                    'material_name': inv.material.name if inv.material else None,
                    'material_spec': inv.material.specification if inv.material else None,
                    'material_unit': inv.material.unit if inv.material else None,
                    'category_id': inv.material.category_id if inv.material else None,
                    'category_name': inv.material.category.name if inv.material and inv.material.category else None,
                    'location_id': inv.location_id,
                    'location_code': inv.location.code if inv.location else None,
                    'warehouse_id': inv.location.warehouse_id if inv.location else None,
                    'warehouse_name': inv.location.warehouse.name if inv.location and inv.location.warehouse else None,
                    'current_quantity': float(inv.quantity) if inv.quantity else 0,
                    'inbound_total': float(inbound_total),
                    'outbound_total': float(abs(outbound_total)),
                    'last_inbound': InventoryLedgerService._get_last_ledger(
                        db, inv.material_id, inv.location_id, 'inbound'
                    ),
                    'last_outbound': InventoryLedgerService._get_last_ledger(
                        db, inv.material_id, inv.location_id, 'outbound'
                    )
                })
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取库存汇总异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", []

    @staticmethod
    def _get_last_ledger(db: Session, material_id: int, location_id: int, business_type: str) -> Optional[Dict]:
        """获取最后一条指定类型的流水"""
        ledger = db.query(InventoryLedger).filter(
            and_(
                InventoryLedger.material_id == material_id,
                InventoryLedger.location_id == location_id,
                InventoryLedger.business_type == business_type
            )
        ).order_by(desc(InventoryLedger.created_at)).first()
        
        if ledger:
            return {
                'ledger_no': ledger.ledger_no,
                'business_no': ledger.business_no,
                'quantity': float(ledger.change_quantity),
                'date': ledger.created_at.strftime('%Y-%m-%d') if ledger.created_at else None
            }
        return None

    @staticmethod
    def get_inventory_trend(
        db: Session,
        material_id: int,
        warehouse_id: Optional[int] = None,
        days: int = 30
    ) -> Tuple[bool, str, List[Dict]]:
        """
        库存变动趋势分析
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID
        - warehouse_id: 仓库ID
        - days: 查询天数
        
        返回：(是否成功, 消息, 趋势数据)
        """
        try:
            start_date = beijing_now() - timedelta(days=days)
            
            query = db.query(InventoryLedger).filter(
                and_(
                    InventoryLedger.material_id == material_id,
                    InventoryLedger.created_at >= start_date
                )
            )
            
            if warehouse_id:
                query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
            
            ledgers = query.order_by(asc(InventoryLedger.created_at)).all()
            
            # 按日期汇总
            daily_data = {}
            for ledger in ledgers:
                date_key = ledger.created_at.strftime('%Y-%m-%d')
                if date_key not in daily_data:
                    daily_data[date_key] = {
                        'date': date_key,
                        'inbound': 0,
                        'outbound': 0,
                        'inventory_gain': 0,
                        'inventory_loss': 0,
                        'net_change': 0
                    }
                
                change = ledger.change_quantity
                bt = ledger.business_type
                
                if bt == 'inbound':
                    daily_data[date_key]['inbound'] += change
                elif bt == 'outbound':
                    daily_data[date_key]['outbound'] += abs(change)
                elif bt == 'inventory_gain':
                    daily_data[date_key]['inventory_gain'] += change
                elif bt == 'inventory_loss':
                    daily_data[date_key]['inventory_loss'] += abs(change)
                
                daily_data[date_key]['net_change'] += change
            
            result = sorted(daily_data.values(), key=lambda x: x['date'])
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取库存趋势异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", []

    @staticmethod
    def get_warehouse_statistics(
        db: Session,
        warehouse_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Tuple[bool, str, Dict]:
        """
        获取仓库库存统计
        
        参数：
        - db: 数据库会话
        - warehouse_id: 仓库ID
        - start_date: 开始日期
        - end_date: 结束日期
        
        返回：(是否成功, 消息, 统计数据)
        """
        try:
            # 当前库存统计
            inv_query = db.query(Inventory).join(Location)
            if warehouse_id:
                inv_query = inv_query.filter(Location.warehouse_id == warehouse_id)
            
            total_inventory = inv_query.with_entities(
                func.count(Inventory.id),
                func.sum(Inventory.quantity)
            ).first()
            
            # 流水统计
            ledger_query = db.query(InventoryLedger)
            if warehouse_id:
                ledger_query = ledger_query.filter(InventoryLedger.warehouse_id == warehouse_id)
            if start_date:
                ledger_query = ledger_query.filter(InventoryLedger.created_at >= start_date)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                ledger_query = ledger_query.filter(InventoryLedger.created_at <= end_datetime)
            
            # 按业务类型统计
            type_stats = ledger_query.with_entities(
                InventoryLedger.business_type,
                func.count(InventoryLedger.id),
                func.sum(InventoryLedger.change_quantity)
            ).group_by(InventoryLedger.business_type).all()
            
            type_summary = {}
            for stat in type_stats:
                bt = stat[0]
                count = stat[1]
                total_qty = float(stat[2] or 0)
                type_summary[bt] = {
                    'count': count,
                    'quantity': total_qty,
                    'name': BUSINESS_TYPE.get(bt, bt)
                }
            
            result = {
                'current_inventory': {
                    'sku_count': total_inventory[0] or 0,
                    'total_quantity': float(total_inventory[1] or 0)
                },
                'business_summary': type_summary
            }
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取仓库统计异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", {}

    @staticmethod
    def export_ledger(
        db: Session,
        material_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        business_type: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Tuple[bool, str, List[Dict]]:
        """
        导出流水数据
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID筛选
        - warehouse_id: 仓库ID筛选
        - business_type: 业务类型筛选
        - start_date: 开始日期
        - end_date: 结束日期
        
        返回：(是否成功, 消息, 导出数据)
        """
        try:
            query = db.query(InventoryLedger)
            
            if material_id:
                query = query.filter(InventoryLedger.material_id == material_id)
            if warehouse_id:
                query = query.filter(InventoryLedger.warehouse_id == warehouse_id)
            if business_type:
                query = query.filter(InventoryLedger.business_type == business_type)
            if start_date:
                query = query.filter(InventoryLedger.created_at >= start_date)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                query = query.filter(InventoryLedger.created_at <= end_datetime)
            
            query = query.order_by(desc(InventoryLedger.created_at))
            
            ledgers = query.all()
            
            result = []
            for ledger in ledgers:
                result.append({
                    '流水单号': ledger.ledger_no,
                    '物料编码': ledger.material.code if ledger.material else None,
                    '物料名称': ledger.material.name if ledger.material else None,
                    '规格': ledger.material.specification if ledger.material else None,
                    '仓库': ledger.warehouse.name if ledger.warehouse else None,
                    '库位': ledger.location.code if ledger.location else None,
                    '业务类型': BUSINESS_TYPE.get(ledger.business_type, ledger.business_type),
                    '业务单号': ledger.business_no,
                    '变动数量': float(ledger.change_quantity) if ledger.change_quantity else 0,
                    '变动前数量': float(ledger.before_quantity) if ledger.before_quantity else 0,
                    '变动后数量': float(ledger.after_quantity) if ledger.after_quantity else 0,
                    '单位': ledger.unit,
                    '操作人': ledger.operator_name,
                    '备注': ledger.remark,
                    '创建时间': ledger.created_at.strftime('%Y-%m-%d %H:%M:%S') if ledger.created_at else None
                })
            
            return True, "导出成功", result
        
        except Exception as e:
            logger.error(f"导出流水数据异常 | 错误: {str(e)}")
            return False, f"导出失败: {str(e)}", []

    @staticmethod
    def calculate_safety_stock(
        db: Session,
        material_id: int,
        days: int = 30,
        safety_factor: float = 1.5
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        自动计算安全库存。

        基于历史出库消耗数据：
        1. 查询近 N 天的出库记录（change_quantity < 0）
        2. 计算日均消耗量
        3. 安全库存 = 日均消耗 × lead_time_days × safety_factor
        4. 更新 Material.safety_stock

        参数：
        - db: 数据库会话
        - material_id: 物料ID
        - days: 统计天数（默认30天）
        - safety_factor: 安全系数（默认1.5）

        返回：(是否成功, 消息, 计算结果)
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                return False, "物料不存在", None

            since_date = beijing_now() - timedelta(days=days)

            # 查询近 N 天出库总量
            result = db.query(
                func.abs(func.coalesce(func.sum(InventoryLedger.change_quantity), 0))
            ).filter(
                and_(
                    InventoryLedger.material_id == material_id,
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= since_date,
                    InventoryLedger.status == 'confirmed'
                )
            ).scalar()

            total_outbound = float(result or 0)
            daily_avg = total_outbound / days if days > 0 else 0

            lead_time = material.lead_time_days or 0
            calculated_stock = daily_avg * lead_time * safety_factor

            # 更新物料的建议安全库存
            material.safety_stock = round(calculated_stock, 2)
            db.commit()

            result_data = {
                "material_id": material_id,
                "material_code": material.code,
                "material_name": material.name,
                "stat_days": days,
                "total_outbound": round(total_outbound, 2),
                "daily_avg_consumption": round(daily_avg, 2),
                "lead_time_days": lead_time,
                "safety_factor": safety_factor,
                "calculated_safety_stock": round(calculated_stock, 2),
                "previous_safety_stock": float(material.safety_stock)
            }

            logger.info(
                f"安全库存计算完成 | 物料: {material.code} {material.name} | "
                f"日均消耗: {daily_avg:.2f} | 提前期: {lead_time}天 | "
                f"安全库存: {calculated_stock:.2f}"
            )
            return True, "计算成功", result_data

        except Exception as e:
            db.rollback()
            logger.error(f"安全库存计算异常 | 物料ID: {material_id} | 错误: {str(e)}")
            return False, f"计算失败: {str(e)}", None

    @staticmethod
    def get_consumption_comparison(
        db: Session,
        days: int = 30,
        top_n: int = 10
    ) -> Dict:
        """
        获取消耗对比数据。

        对比当前时间段与前一时间段的消耗情况：
        - 当前段：最近 N 天
        - 对比段：前 N 天

        参数：
        - db: 数据库会话
        - days: 时间段长度（默认30天）
        - top_n: 返回的物料数量

        返回：对比数据
        """
        try:
            now = beijing_now()
            current_start = now - timedelta(days=days)
            previous_start = current_start - timedelta(days=days)

            # 当前时间段消耗
            current_rows = db.query(
                InventoryLedger.material_id,
                func.abs(func.sum(InventoryLedger.change_quantity)).label('total_qty')
            ).filter(
                and_(
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= current_start,
                    InventoryLedger.status == 'confirmed'
                )
            ).group_by(
                InventoryLedger.material_id
            ).order_by(
                func.abs(func.sum(InventoryLedger.change_quantity)).desc()
            ).limit(top_n).all()

            # 前一时间段消耗（用于对比）
            previous_rows = db.query(
                InventoryLedger.material_id,
                func.abs(func.sum(InventoryLedger.change_quantity)).label('total_qty')
            ).filter(
                and_(
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= previous_start,
                    InventoryLedger.created_at < current_start,
                    InventoryLedger.status == 'confirmed'
                )
            ).group_by(
                InventoryLedger.material_id
            ).all()

            prev_map = {r.material_id: float(r.total_qty) for r in previous_rows}

            # 总消耗
            current_total = db.query(
                func.abs(func.coalesce(func.sum(InventoryLedger.change_quantity), 0))
            ).filter(
                and_(
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= current_start,
                    InventoryLedger.status == 'confirmed'
                )
            ).scalar() or 0

            previous_total = db.query(
                func.abs(func.coalesce(func.sum(InventoryLedger.change_quantity), 0))
            ).filter(
                and_(
                    InventoryLedger.change_quantity < 0,
                    InventoryLedger.created_at >= previous_start,
                    InventoryLedger.created_at < current_start,
                    InventoryLedger.status == 'confirmed'
                )
            ).scalar() or 0

            # 物料详情
            items = []
            for row in current_rows:
                m = db.query(Material).filter(Material.id == row.material_id).first()
                prev_qty = prev_map.get(row.material_id, 0)
                cur_qty = float(row.total_qty or 0)
                change_pct = ((cur_qty - prev_qty) / prev_qty * 100) if prev_qty > 0 else 100
                items.append({
                    "material_id": row.material_id,
                    "material_code": m.code if m else None,
                    "material_name": m.name if m else None,
                    "specification": m.specification if m else None,
                    "unit": m.unit if m else None,
                    "current_qty": cur_qty,
                    "previous_qty": prev_qty,
                    "change_pct": round(change_pct, 1),
                })

            return {
                "days": days,
                "current_period": {
                    "start": current_start.isoformat(),
                    "end": now.isoformat(),
                    "total_consumption": float(current_total),
                },
                "previous_period": {
                    "start": previous_start.isoformat(),
                    "end": current_start.isoformat(),
                    "total_consumption": float(previous_total),
                },
                "items": items,
            }

        except Exception as e:
            logger.error(f"获取消耗对比数据异常: {e}")
            return {
                "days": days,
                "current_period": {},
                "previous_period": {},
                "items": []
            }
