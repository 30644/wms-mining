"""
库存预警业务服务层
- 预警配置管理（最小/最大库存阈值）
- 预警生成与触发
- 预警处理与确认
- 预警查询与统计
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func
from datetime import datetime, date
import json

from app.models import (
    InventoryAlertConfig, InventoryAlert, Inventory, Material, Location,
    Warehouse, User, OperationLog
)
from app.utils.logger import logger
from app.config import SUPER_ADMIN_ROLE
from app.database import beijing_now


# 预警类型
ALERT_TYPE = {
    'min_stock': '库存不足',
    'max_stock': '库存过剩',
    'expired': '临期预警',
    'zero_stock': '零库存'
}

# 预警级别
ALERT_LEVEL = {
    'low': '低',
    'medium': '中',
    'high': '高',
    'critical': '紧急'
}

# 预警状态
ALERT_STATUS = {
    'pending': '待处理',
    'processing': '处理中',
    'resolved': '已解决',
    'ignored': '已忽略'
}


class InventoryAlertService:
    """库存预警业务服务"""

    @staticmethod
    def create_alert_config(
        db: Session,
        material_id: Optional[int] = None,
        category_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        min_quantity: Optional[float] = None,
        max_quantity: Optional[float] = None,
        alert_level: str = 'medium',
        is_enabled: bool = True,
        remark: Optional[str] = None,
        creator_id: int = None
    ) -> Tuple[bool, str, Optional[InventoryAlertConfig]]:
        """
        创建预警配置
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID（精确配置）
        - category_id: 分类ID（分类级别配置）
        - warehouse_id: 仓库ID
        - min_quantity: 最小库存阈值
        - max_quantity: 最大库存阈值
        - alert_level: 预警级别（low/medium/high/critical）
        - is_enabled: 是否启用
        - remark: 备注
        - creator_id: 创建人ID
        
        返回：(是否成功, 消息, 配置对象)
        """
        try:
            # 验证参数：必须指定物料、分类或仓库之一
            if not material_id and not category_id and not warehouse_id:
                return False, "必须指定物料、分类或仓库", None
            
            if material_id and category_id:
                return False, "物料和分类只能选择其一", None
            
            # 检查是否已存在相同配置
            query = db.query(InventoryAlertConfig)
            if material_id:
                query = query.filter(InventoryAlertConfig.material_id == material_id)
            if category_id:
                query = query.filter(InventoryAlertConfig.category_id == category_id)
            if warehouse_id:
                query = query.filter(InventoryAlertConfig.warehouse_id == warehouse_id)
            
            existing = query.first()
            if existing:
                return False, "该配置已存在，请使用更新接口", None
            
            # 验证物料或分类存在
            if material_id:
                material = db.query(Material).filter(Material.id == material_id).first()
                if not material:
                    return False, "物料不存在", None
            
            if category_id:
                from app.models import MaterialCategory
                category = db.query(MaterialCategory).filter(MaterialCategory.id == category_id).first()
                if not category:
                    return False, "分类不存在", None
            
            # 验证仓库
            if warehouse_id:
                warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
                if not warehouse:
                    return False, "仓库不存在", None
            
            # 验证预警级别
            if alert_level not in ALERT_LEVEL:
                return False, f"无效的预警级别: {alert_level}", None
            
            # 创建配置
            config = InventoryAlertConfig(
                material_id=material_id,
                category_id=category_id,
                warehouse_id=warehouse_id,
                min_quantity=min_quantity,
                max_quantity=max_quantity,
                alert_level=alert_level,
                is_enabled=is_enabled,
                remark=remark,
                creator_id=creator_id
            )
            
            db.add(config)
            db.commit()
            db.refresh(config)
            
            logger.info(f"创建预警配置成功 | ID: {config.id} | 物料: {material_id} | 分类: {category_id}")
            return True, "预警配置创建成功", config
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建预警配置异常 | 错误: {str(e)}")
            return False, f"创建失败: {str(e)}", None

    @staticmethod
    def update_alert_config(
        db: Session,
        config_id: int,
        min_quantity: Optional[float] = None,
        max_quantity: Optional[float] = None,
        alert_level: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        remark: Optional[str] = None,
        updater_id: int = None
    ) -> Tuple[bool, str, Optional[InventoryAlertConfig]]:
        """
        更新预警配置
        
        参数：
        - db: 数据库会话
        - config_id: 配置ID
        - min_quantity: 最小库存阈值
        - max_quantity: 最大库存阈值
        - alert_level: 预警级别
        - is_enabled: 是否启用
        - remark: 备注
        - updater_id: 更新人ID
        
        返回：(是否成功, 消息, 配置对象)
        """
        try:
            config = db.query(InventoryAlertConfig).filter(
                InventoryAlertConfig.id == config_id
            ).first()
            
            if not config:
                return False, "预警配置不存在", None
            
            # 更新字段
            if min_quantity is not None:
                config.min_quantity = min_quantity
            if max_quantity is not None:
                config.max_quantity = max_quantity
            if alert_level is not None:
                if alert_level not in ALERT_LEVEL:
                    return False, f"无效的预警级别: {alert_level}", None
                config.alert_level = alert_level
            if is_enabled is not None:
                config.is_enabled = is_enabled
            if remark is not None:
                config.remark = remark
            
            config.updater_id = updater_id
            config.updated_at = beijing_now()
            
            db.commit()
            db.refresh(config)
            
            logger.info(f"更新预警配置成功 | ID: {config_id}")
            return True, "预警配置更新成功", config
        
        except Exception as e:
            db.rollback()
            logger.error(f"更新预警配置异常 | 错误: {str(e)}")
            return False, f"更新失败: {str(e)}", None

    @staticmethod
    def delete_alert_config(
        db: Session,
        config_id: int
    ) -> Tuple[bool, str]:
        """
        删除预警配置
        
        参数：
        - db: 数据库会话
        - config_id: 配置ID
        
        返回：(是否成功, 消息)
        """
        try:
            config = db.query(InventoryAlertConfig).filter(
                InventoryAlertConfig.id == config_id
            ).first()
            
            if not config:
                return False, "预警配置不存在", None
            
            db.delete(config)
            db.commit()
            
            logger.info(f"删除预警配置成功 | ID: {config_id}")
            return True, "删除成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"删除预警配置异常 | 错误: {str(e)}")
            return False, f"删除失败: {str(e)}"

    @staticmethod
    def get_alert_config_list(
        db: Session,
        material_id: Optional[int] = None,
        category_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        is_enabled: Optional[bool] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[bool, str, List[Dict], int]:
        """
        获取预警配置列表
        
        参数：
        - db: 数据库会话
        - material_id: 物料ID筛选
        - category_id: 分类ID筛选
        - warehouse_id: 仓库ID筛选
        - is_enabled: 是否启用筛选
        - skip: 跳过记录数
        - limit: 每页数量
        
        返回：(是否成功, 消息, 列表数据, 总数)
        """
        try:
            query = db.query(InventoryAlertConfig)
            
            if material_id:
                query = query.filter(InventoryAlertConfig.material_id == material_id)
            if category_id:
                query = query.filter(InventoryAlertConfig.category_id == category_id)
            if warehouse_id:
                query = query.filter(InventoryAlertConfig.warehouse_id == warehouse_id)
            if is_enabled is not None:
                query = query.filter(InventoryAlertConfig.is_enabled == is_enabled)
            
            query = query.order_by(desc(InventoryAlertConfig.created_at))
            
            total = query.count()
            configs = query.offset(skip).limit(limit).all()
            
            result = []
            for config in configs:
                result.append({
                    'id': config.id,
                    'material_id': config.material_id,
                    'material_code': config.material.code if config.material else None,
                    'material_name': config.material.name if config.material else None,
                    'category_id': config.category_id,
                    'category_name': config.category.name if config.category else None,
                    'warehouse_id': config.warehouse_id,
                    'warehouse_name': config.warehouse.name if config.warehouse else None,
                    'min_quantity': float(config.min_quantity) if config.min_quantity else None,
                    'max_quantity': float(config.max_quantity) if config.max_quantity else None,
                    'alert_level': config.alert_level,
                    'alert_level_name': ALERT_LEVEL.get(config.alert_level, config.alert_level),
                    'enabled': config.is_enabled,
                    'remark': config.remark,
                    'creator_id': config.creator_id,
                    'creator_name': config.creator.real_name if config.creator else None,
                    'created_at': config.created_at.strftime('%Y-%m-%d %H:%M:%S') if config.created_at else None
                })
            
            return True, "获取成功", result, total
        
        except Exception as e:
            logger.error(f"获取预警配置列表异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", [], 0

    @staticmethod
    def generate_alerts(db: Session) -> Tuple[bool, str, int]:
        """
        生成库存预警
        
        扫描所有库存记录，根据预警配置生成预警
        
        参数：
        - db: 数据库会话
        
        返回：(是否成功, 消息, 生成预警数量)
        """
        try:
            # 获取所有启用的预警配置
            configs = db.query(InventoryAlertConfig).filter(
                InventoryAlertConfig.is_enabled == True
            ).all()
            
            if not configs:
                return True, "无启用的预警配置", 0
            
            alert_count = 0
            
            for config in configs:
                # 查询对应的库存
                query = db.query(Inventory).join(Material).join(Location)
                
                if config.material_id:
                    query = query.filter(Inventory.material_id == config.material_id)
                if config.category_id:
                    query = query.filter(Material.category_id == config.category_id)
                if config.warehouse_id:
                    query = query.filter(Location.warehouse_id == config.warehouse_id)
                
                inventories = query.all()
                
                for inv in inventories:
                    # 检查是否已存在未处理的相同预警
                    existing_alert = db.query(InventoryAlert).filter(
                        and_(
                            InventoryAlert.material_id == inv.material_id,
                            InventoryAlert.location_id == inv.location_id,
                            InventoryAlert.alert_type == InventoryAlertService._get_alert_type(
                                inv.quantity, config.min_quantity, config.max_quantity
                            ),
                            InventoryAlert.status.in_(['pending', 'processing'])
                        )
                    ).first()
                    
                    if existing_alert:
                        continue
                    
                    # 判断预警类型
                    alert_type = InventoryAlertService._get_alert_type(
                        inv.quantity, config.min_quantity, config.max_quantity
                    )
                    
                    if not alert_type:
                        continue
                    
                    # 生成预警单号
                    import uuid
                    alert_no = f"ALT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8].upper()}"

                    # 创建预警
                    alert = InventoryAlert(
                        alert_no=alert_no,
                        material_id=inv.material_id,
                        location_id=inv.location_id,
                        warehouse_id=inv.location.warehouse_id if inv.location else None,
                        alert_type=alert_type,
                        alert_level=config.alert_level,
                        current_quantity=inv.quantity,
                        threshold_min=config.min_quantity,
                        threshold_max=config.max_quantity,
                        status='pending',
                        remark=config.remark
                    )
                    db.add(alert)
                    alert_count += 1
            
            db.commit()
            
            logger.info(f"生成库存预警成功 | 预警数量: {alert_count}")
            return True, f"成功生成{alert_count}条预警", alert_count
        
        except Exception as e:
            db.rollback()
            logger.error(f"生成库存预警异常 | 错误: {str(e)}")
            return False, f"生成失败: {str(e)}", 0

    @staticmethod
    def _get_alert_type(current_quantity: float, min_qty: Optional[float], max_qty: Optional[float]) -> Optional[str]:
        """判断预警类型"""
        if min_qty is not None and current_quantity < min_qty:
            return 'min_stock'
        if max_qty is not None and current_quantity > max_qty:
            return 'max_stock'
        if min_qty is not None and current_quantity == 0:
            return 'zero_stock'
        return None

    @staticmethod
    def get_alert_list(
        db: Session,
        alert_type: Optional[str] = None,
        alert_level: Optional[str] = None,
        status: Optional[str] = None,
        warehouse_id: Optional[int] = None,
        material_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[bool, str, List[Dict], int]:
        """
        获取预警列表
        
        参数：
        - db: 数据库会话
        - alert_type: 预警类型筛选
        - alert_level: 预警级别筛选
        - status: 状态筛选
        - warehouse_id: 仓库筛选
        - material_id: 物料筛选
        - start_date: 开始日期
        - end_date: 结束日期
        - skip: 跳过记录数
        - limit: 每页数量
        
        返回：(是否成功, 消息, 列表数据, 总数)
        """
        try:
            query = db.query(InventoryAlert)
            
            if alert_type:
                query = query.filter(InventoryAlert.alert_type == alert_type)
            if alert_level:
                query = query.filter(InventoryAlert.alert_level == alert_level)
            if status:
                query = query.filter(InventoryAlert.status == status)
            if warehouse_id:
                query = query.filter(InventoryAlert.warehouse_id == warehouse_id)
            if material_id:
                query = query.filter(InventoryAlert.material_id == material_id)
            if start_date:
                query = query.filter(InventoryAlert.created_at >= start_date)
            if end_date:
                query = query.filter(InventoryAlert.created_at <= end_date)
            
            query = query.order_by(
                desc(InventoryAlert.alert_level),
                desc(InventoryAlert.created_at)
            )
            
            total = query.count()
            alerts = query.offset(skip).limit(limit).all()
            
            result = []
            for alert in alerts:
                result.append({
                    'id': alert.id,
                    'material_id': alert.material_id,
                    'material_code': alert.material.code if alert.material else None,
                    'material_name': alert.material.name if alert.material else None,
                    'material_spec': alert.material.specification if alert.material else None,
                    'material_unit': alert.material.unit if alert.material else None,
                    'location_id': alert.location_id,
                    'location_code': alert.location.code if alert.location else None,
                    'warehouse_id': alert.warehouse_id,
                    'warehouse_name': alert.warehouse.name if alert.warehouse else None,
                    'alert_type': alert.alert_type,
                    'alert_type_name': ALERT_TYPE.get(alert.alert_type, alert.alert_type),
                    'alert_level': alert.alert_level,
                    'alert_level_name': ALERT_LEVEL.get(alert.alert_level, alert.alert_level),
                    'current_quantity': float(alert.current_quantity) if alert.current_quantity else 0,
                    'threshold_min': float(alert.threshold_min) if alert.threshold_min else None,
                    'threshold_max': float(alert.threshold_max) if alert.threshold_max else None,
                    'status': alert.status,
                    'status_name': ALERT_STATUS.get(alert.status, alert.status),
                    'handler_id': alert.handler_id,
                    'handler_name': alert.handler.real_name if alert.handler else None,
                    'handled_at': alert.handled_at.strftime('%Y-%m-%d %H:%M:%S') if alert.handled_at else None,
                    'handle_remark': alert.handle_remark,
                    'remark': alert.remark,
                    'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M:%S') if alert.created_at else None
                })
            
            return True, "获取成功", result, total
        
        except Exception as e:
            logger.error(f"获取预警列表异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", [], 0

    @staticmethod
    def process_alert(
        db: Session,
        alert_id: int,
        resolved: bool,
        handle_remark: Optional[str] = None,
        current_user: dict = None
    ) -> Tuple[bool, str, Optional[InventoryAlert]]:
        """
        处理预警
        
        参数：
        - db: 数据库会话
        - alert_id: 预警ID
        - resolved: 是否已解决
        - handle_remark: 处理备注
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 预警对象)
        """
        try:
            alert = db.query(InventoryAlert).filter(
                InventoryAlert.id == alert_id
            ).first()
            
            if not alert:
                return False, "预警不存在", None
            
            if alert.status in ['resolved', 'ignored']:
                return False, f"该预警已处理，不能重复处理", None
            
            alert.handler_id = current_user.get('id') if current_user else None
            alert.handled_at = beijing_now()
            alert.handle_remark = handle_remark
            
            if resolved:
                alert.status = 'resolved'
            else:
                alert.status = 'ignored'
            
            db.commit()
            db.refresh(alert)
            
            # 记录操作日志
            InventoryAlertService._create_operation_log(
                db=db,
                user_id=current_user.get('id') if current_user else None,
                action='process_alert',
                module='inventory_alert',
                related_id=alert.id,
                details={'resolved': resolved, 'handle_remark': handle_remark}
            )
            
            logger.info(f"处理预警成功 | ID: {alert_id} | 解决: {resolved}")
            return True, "处理成功", alert
        
        except Exception as e:
            db.rollback()
            logger.error(f"处理预警异常 | 错误: {str(e)}")
            return False, f"处理失败: {str(e)}", None

    @staticmethod
    def batch_process_alerts(
        db: Session,
        alert_ids: List[int],
        resolved: bool,
        handle_remark: Optional[str] = None,
        current_user: dict = None
    ) -> Tuple[bool, str, int]:
        """
        批量处理预警
        
        参数：
        - db: 数据库会话
        - alert_ids: 预警ID列表
        - resolved: 是否已解决
        - handle_remark: 处理备注
        - current_user: 当前用户
        
        返回：(是否成功, 消息, 处理数量)
        """
        try:
            success_count = 0
            
            for alert_id in alert_ids:
                alert = db.query(InventoryAlert).filter(
                    InventoryAlert.id == alert_id
                ).first()
                
                if alert and alert.status in ['pending', 'processing']:
                    alert.handler_id = current_user.get('id') if current_user else None
                    alert.handled_at = beijing_now()
                    alert.handle_remark = handle_remark
                    alert.status = 'resolved' if resolved else 'ignored'
                    success_count += 1
            
            db.commit()
            
            logger.info(f"批量处理预警成功 | 处理数量: {success_count}")
            return True, f"成功处理{success_count}条预警", success_count
        
        except Exception as e:
            db.rollback()
            logger.error(f"批量处理预警异常 | 错误: {str(e)}")
            return False, f"处理失败: {str(e)}", 0

    @staticmethod
    def get_alert_statistics(
        db: Session,
        warehouse_id: Optional[int] = None
    ) -> Tuple[bool, str, Dict]:
        """
        获取预警统计
        
        参数：
        - db: 数据库会话
        - warehouse_id: 仓库筛选
        
        返回：(是否成功, 消息, 统计数据)
        """
        try:
            query = db.query(InventoryAlert)
            
            if warehouse_id:
                query = query.filter(InventoryAlert.warehouse_id == warehouse_id)
            
            # 总数
            total = query.count()
            
            # 按状态统计
            status_stats = query.with_entities(
                InventoryAlert.status,
                func.count(InventoryAlert.id)
            ).group_by(InventoryAlert.status).all()
            
            status_dict = {s[0]: s[1] for s in status_stats}
            
            # 按类型统计
            type_stats = query.with_entities(
                InventoryAlert.alert_type,
                func.count(InventoryAlert.id)
            ).group_by(InventoryAlert.alert_type).all()
            
            type_dict = {t[0]: t[1] for t in type_stats}
            
            # 按级别统计
            level_stats = query.with_entities(
                InventoryAlert.alert_level,
                func.count(InventoryAlert.id)
            ).group_by(InventoryAlert.alert_level).all()
            
            level_dict = {l[0]: l[1] for l in level_stats}
            
            result = {
                'total': total,
                'pending': status_dict.get('pending', 0),
                'processing': status_dict.get('processing', 0),
                'resolved': status_dict.get('resolved', 0),
                'ignored': status_dict.get('ignored', 0),
                'by_type': {ALERT_TYPE.get(k, k): v for k, v in type_dict.items()},
                'by_level': {ALERT_LEVEL.get(k, k): v for k, v in level_dict.items()}
            }
            
            return True, "获取成功", result
        
        except Exception as e:
            logger.error(f"获取预警统计异常 | 错误: {str(e)}")
            return False, f"获取失败: {str(e)}", {}

    @staticmethod
    def _create_operation_log(
        db: Session,
        user_id: int,
        action: str,
        module: str,
        related_id: int = None,
        details: dict = None
    ):
        """创建操作日志"""
        try:
            log = OperationLog(
                user_id=user_id,
                action=action,
                module=module,
                related_id=related_id,
                details=details
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"创建操作日志失败 | 错误: {str(e)}")