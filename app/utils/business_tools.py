"""
权限控制和库存管理工具
- 细粒度权限控制
- 库存并发安全控制
- 操作日志记录增强
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, insert
from datetime import datetime
import json

from app.config import SYSTEM_ROLES, SUPER_ADMIN_ROLE
from app.models import User, RoleDefinition, RolePermission, OperationLog as OperationLogModel, Inventory, Material, Location
from app.utils.logger import logger
from app.database import beijing_now


class PermissionService:
    """权限管理服务"""

    # 权限定义（全量）
    PERMISSIONS = {
        # 物资管理
        'material:create': '创建物资档案',
        'material:update': '修改物资档案',
        'material:delete': '删除物资档案',
        'material:view': '查看物资档案',

        # 仓库管理
        'warehouse:create': '创建仓库',
        'warehouse:update': '修改仓库',
        'warehouse:delete': '删除仓库',
        'warehouse:list': '查看仓库列表',

        # 入库管理
        'inbound:create': '创建入库单',
        'inbound:update': '修改入库单',
        'inbound:delete': '删除入库单',
        'inbound:list': '查看入库单列表',
        'inbound:detail': '查看入库单详情',
        'inbound:approve': '审批入库单',
        'inbound:execute': '执行入库',
        'inbound:cancel': '作废入库单',
        'inbound:view': '查看入库单',
        'inbound:review_procurement': '采购审核入库',
        'inbound:review_technical': '技术审核入库',
        'inbound:confirm': '确认入库',

        # 出库管理
        'outbound:create': '创建出库单',
        'outbound:update': '修改出库单',
        'outbound:delete': '删除出库单',
        'outbound:list': '查看出库单列表',
        'outbound:detail': '查看出库单详情',
        'outbound:approve': '审批出库单',
        'outbound:execute': '执行出库',
        'outbound:cancel': '作废出库单',
        'outbound:view': '查看出库单',

        # 库存管理
        'inventory:view': '查看库存',
        'inventory:query': '查询库存',
        'inventory:adjust': '调整库存',
        'inventory:transfer': '库存调拨',

        # 库存盘点
        'inventory_check:create': '创建盘点单',
        'inventory_check:list': '查看盘点列表',
        'inventory_check:detail': '查看盘点详情',
        'inventory_check:input': '录入盘点数据',
        'inventory_check:submit': '提交盘点',
        'inventory_check:review': '审核盘点',
        'inventory_check:adjust': '盘点调整',
        'inventory_check:execute': '执行盘点调整',
        'inventory_check:cancel': '作废盘点单',

        # 库存预警
        'inventory_alert:config:create': '创建预警配置',
        'inventory_alert:config:update': '修改预警配置',
        'inventory_alert:config:delete': '删除预警配置',
        'inventory_alert:config:list': '查看预警配置',
        'inventory_alert:generate': '生成预警',
        'inventory_alert:list': '查看预警列表',
        'inventory_alert:detail': '查看预警详情',
        'inventory_alert:process': '处理预警',
        'inventory_alert:statistics': '预警统计',

        # 库存台账
        'inventory_ledger:list': '查看流水列表',
        'inventory_ledger:detail': '查看流水详情',
        'inventory_ledger:trace': '物料追溯',
        'inventory_ledger:summary': '库存汇总',
        'inventory_ledger:trend': '库存趋势',
        'inventory_ledger:statistics': '仓库统计',
        'inventory_ledger:export': '导出流水',
        'inventory_ledger:create': '手动补录流水',

        # 调拨管理
        'transfer:create': '创建调拨单',
        'transfer:update': '修改调拨单',
        'transfer:delete': '删除调拨单',
        'transfer:list': '查看调拨列表',
        'transfer:detail': '查看调拨详情',
        'transfer:submit': '提交调拨',
        'transfer:approve': '审批调拨',
        'transfer:execute': '执行调拨',
        'transfer:cancel': '作废调拨单',

        # 报废管理
        'scrap:create': '创建报废单',
        'scrap:update': '修改报废单',
        'scrap:delete': '删除报废单',
        'scrap:list': '查看报废列表',
        'scrap:detail': '查看报废详情',
        'scrap:submit': '提交报废',
        'scrap:approve': '审批报废',
        'scrap:execute': '执行报废',
        'scrap:cancel': '作废报废单',

        # 退货管理
        'return:create': '创建退货单',
        'return:update': '修改退货单',
        'return:delete': '删除退货单',
        'return:list': '查看退货列表',
        'return:detail': '查看退货详情',
        'return:submit': '提交退货',
        'return:approve': '审批退货',
        'return:execute': '执行退货',
        'return:cancel': '作废退货单',

        # 需求申请
        'request:create': '创建领料申请',
        'request:update': '修改领料申请',
        'request:delete': '删除领料申请',
        'request:list': '查看领料申请列表',
        'request:detail': '查看领料申请详情',
        'request:submit': '提交领料申请',
        'request:approve': '审批领料申请',
        'request:cancel': '作废领料申请',

        # 审批中心
        'approval:view': '查看审批中心',
        'approval:list': '查看审批列表',
        'approval:approve': '执行审批通过',
        'approval:reject': '执行审批驳回',
        'approval:batch': '批量审批',

        # 供应商管理
        'supplier:create': '创建供应商',
        'supplier:update': '修改供应商',
        'supplier:delete': '删除供应商',
        'supplier:list': '查看供应商列表',
        'supplier:detail': '查看供应商详情',
        'supplier:view': '查看供应商',

        # NC同步
        'nc:sync': '执行NC同步',
        'nc:config': '配置NC参数',

        # 报表
        'report:view': '查看报表',
        'report:export': '导出报表',
        'report:consumption': '查看消耗报表',
        'report:cost': '查看成本报表',
        'report:inventory-summary': '库存汇总报表',
        'report:inventory-trend': '库存趋势报表',
        'report:inbound-summary': '入库统计报表',
        'report:outbound-summary': '出库统计报表',
        'report:slow-moving': '呆滞物料报表',
        'report:reconciliation': '数据对账报表',
        'report:inventory-age': '库龄分析报表',

        # 用户管理
        'user:create': '创建用户',
        'user:update': '修改用户',
        'user:delete': '删除用户',
        'user:list': '查看用户列表',
        'user:disable': '禁用用户',
        'user:enable': '启用用户',
        'user:reset_pwd': '重置密码',

        # 角色管理
        'role:create': '创建角色',
        'role:update': '修改角色',
        'role:delete': '删除角色',
        'role:list': '查看角色列表',

        # 采购清单
        'purchase:create': '创建采购清单',
        'purchase:list': '查看采购清单',
        'purchase:detail': '查看采购详情',
        'purchase:approve': '审批采购清单',
        'purchase:execute': '执行采购',
        'purchase:cancel': '作废采购清单',

        # 消息通知
        'notification:list': '查看通知列表',
        'notification:read': '标记已读',
        'notification:delete': '删除通知',

        # 系统日志
        'log:list': '查看日志列表',
        'log:export': '导出日志',

        # 部门人员
        'department:create': '创建部门',
        'department:update': '修改部门',
        'department:delete': '删除部门',
        'department:list': '查看部门列表',
        'employee:create': '创建人员',
        'employee:update': '修改人员',
        'employee:delete': '删除人员',
        'employee:list': '查看人员列表',
    }

    # 角色权限映射（按用户规范对齐）
    ROLE_PERMISSIONS = {
        # ===== 班长 =====
        'team_leader': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'request:create', 'request:list', 'request:detail', 'request:submit',
            'purchase:create', 'purchase:list', 'purchase:detail', 'purchase:approve',
        ],
        # ===== 采购员 =====
        'procurement_officer': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'inbound:list', 'inbound:detail', 'inbound:view',
            'supplier:create', 'supplier:update', 'supplier:list',
            'supplier:detail', 'supplier:view',
            'report:view', 'report:export',
            'inventory_alert:list', 'inventory_alert:detail',
            'purchase:create', 'purchase:list', 'purchase:detail', 'purchase:execute',
        ],
        # ===== 库管 =====
        'warehouse_operator': [
            'material:list', 'material:view',
            'warehouse:list', 'warehouse:detail',
            'inventory:view', 'inventory:query', 'inventory:adjust',
            'inbound:create', 'inbound:update', 'inbound:list',
            'inbound:detail', 'inbound:execute', 'inbound:view', 'inbound:confirm',
            'outbound:create', 'outbound:update', 'outbound:list',
            'outbound:detail', 'outbound:execute', 'outbound:view',
            'inventory_check:create', 'inventory_check:list',
            'inventory_check:detail', 'inventory_check:input',
            'inventory_check:submit',
            'scrap:create', 'scrap:list', 'scrap:detail',
            'scrap:submit', 'scrap:execute',
            'return:create', 'return:list', 'return:detail',
            'return:submit', 'return:execute',
            'transfer:create', 'transfer:list', 'transfer:detail',
            'transfer:submit', 'transfer:execute',
        ],
        # ===== 到货审核员 =====
        'receiving_inspector': [
            'material:list', 'material:view',
            'warehouse:list',
            'inbound:list', 'inbound:detail', 'inbound:view',
            'inbound:review_technical', 'inbound:review_procurement',
            'inbound:confirm',
            'purchase:create', 'purchase:list', 'purchase:detail', 'purchase:approve',
        ],
        # 兼容旧名
        'technical_officer': [
            'material:list', 'material:view',
            'warehouse:list',
            'inbound:list', 'inbound:detail', 'inbound:view',
            'inbound:review_technical', 'inbound:review_procurement',
            'inbound:confirm',
            'purchase:create', 'purchase:list', 'purchase:detail', 'purchase:approve',
        ],
        # ===== 库管领导 =====
        'warehouse_manager': [
            'material:create', 'material:update', 'material:delete', 'material:view',
            'warehouse:create', 'warehouse:update', 'warehouse:delete', 'warehouse:list',
            'inbound:create', 'inbound:update', 'inbound:delete', 'inbound:list',
            'inbound:detail', 'inbound:approve', 'inbound:execute', 'inbound:cancel', 'inbound:view', 'inbound:confirm',
            'outbound:create', 'outbound:update', 'outbound:delete', 'outbound:list',
            'outbound:detail', 'outbound:approve', 'outbound:execute', 'outbound:cancel', 'outbound:view',
            'inventory:view', 'inventory:query', 'inventory:adjust', 'inventory:transfer',
            'inventory_check:create', 'inventory_check:list', 'inventory_check:detail',
            'inventory_check:input', 'inventory_check:submit', 'inventory_check:review',
            'inventory_check:adjust', 'inventory_check:execute', 'inventory_check:cancel',
            'inventory_alert:config:create', 'inventory_alert:config:update',
            'inventory_alert:config:delete', 'inventory_alert:config:list',
            'inventory_alert:generate', 'inventory_alert:list', 'inventory_alert:detail',
            'inventory_alert:process', 'inventory_alert:statistics',
            'inventory_ledger:list', 'inventory_ledger:detail', 'inventory_ledger:trace',
            'inventory_ledger:summary', 'inventory_ledger:trend', 'inventory_ledger:statistics',
            'inventory_ledger:export', 'inventory_ledger:create',
            'transfer:create', 'transfer:update', 'transfer:delete', 'transfer:list',
            'transfer:detail', 'transfer:submit', 'transfer:approve', 'transfer:execute', 'transfer:cancel',
            'scrap:create', 'scrap:list', 'scrap:detail', 'scrap:submit',
            'scrap:approve', 'scrap:execute', 'scrap:cancel',
            'return:create', 'return:list', 'return:detail', 'return:submit',
            'return:approve', 'return:execute', 'return:cancel',
            'request:list', 'request:detail', 'request:approve',
            'approval:view', 'approval:list', 'approval:approve', 'approval:reject', 'approval:batch',
            'supplier:list', 'supplier:detail', 'supplier:view',
            'report:view', 'report:export', 'report:consumption', 'report:cost',
            'report:inventory-summary', 'report:inventory-trend',
            'report:inbound-summary', 'report:outbound-summary',
            'report:slow-moving', 'report:reconciliation', 'report:inventory-age',
            'nc:sync', 'nc:config',
            'notification:list', 'notification:read',
            'user:list',
            'purchase:create', 'purchase:list', 'purchase:detail',
            'purchase:approve', 'purchase:execute', 'purchase:cancel',
        ],
        # ===== 财务 =====
        'finance': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'inbound:list', 'inbound:detail', 'inbound:view',
            'outbound:list', 'outbound:detail', 'outbound:view',
            'supplier:list', 'supplier:detail', 'supplier:view',
            'report:view', 'report:export', 'report:consumption', 'report:cost',
            'report:inventory-summary', 'report:inventory-trend',
            'report:inbound-summary', 'report:outbound-summary',
            'report:slow-moving', 'report:reconciliation', 'report:inventory-age',
            'nc:sync', 'nc:config',
        ],
        # ===== 基础角色 =====
        'employee': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'request:create', 'request:list', 'request:detail',
        ],
        'viewer': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'inbound:list', 'inbound:detail', 'inbound:view',
            'outbound:list', 'outbound:detail', 'outbound:view',
            'report:view',
        ],
        'department_leader': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'outbound:approve', 'outbound:view',
            'report:consumption', 'report:cost',
            'request:list', 'request:detail', 'request:approve',
        ],
        'approver': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'outbound:approve', 'outbound:view',
            'report:consumption', 'report:cost',
            'request:list', 'request:detail', 'request:approve',
            'purchase:create', 'purchase:list', 'purchase:detail', 'purchase:approve',
        ],
        'requester': [
            'material:view',
            'warehouse:list',
            'inventory:view', 'inventory:query',
            'request:create', 'request:list', 'request:detail', 'request:submit',
        ],
        'super_admin': list(PERMISSIONS.keys())
    }

    ROLE_ALIASES = {
        'approver': 'department_leader',
        'viewer': 'team_leader',
        'department_leader': 'approver',
        'team_leader': 'viewer',
        'procurement_officer': 'procurement',
        'procurement': 'procurement_officer',
        'receiving_inspector': 'technical_officer',
        'technical_officer': 'receiving_inspector',
    }

    @staticmethod
    def _resolve_role_alias(role: str) -> str:
        return PermissionService.ROLE_ALIASES.get(role, role)

    @staticmethod
    def _get_role_variants(role: str) -> List[str]:
        variants = {role, PermissionService._resolve_role_alias(role)}
        return list(variants)
    
    @staticmethod
    def check_permission(user_id: int, permission: str, db: Session) -> bool:
        """
        检查用户是否具有指定权限
        
        参数：
        - user_id: 用户ID
        - permission: 权限标识
        - db: 数据库会话
        
        返回：是否有权限
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return False
            
            # 超级管理员拥有所有权限
            if user.role == 'super_admin':
                return True
            
            # 检查角色及别名角色是否拥有该权限
            candidate_roles = PermissionService._get_role_variants(user.role)
            for candidate_role in candidate_roles:
                role_permissions = PermissionService.ROLE_PERMISSIONS.get(candidate_role, [])
                if permission in role_permissions:
                    return True
            
            # 从数据库检查自定义权限
            perm = db.query(RolePermission).filter(
                and_(
                    RolePermission.role.in_(candidate_roles),
                    RolePermission.permission == permission
                )
            ).first()
            
            return perm is not None
        
        except Exception as e:
            logger.error(f"权限检查异常 | 用户ID: {user_id} | 权限: {permission} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def check_role(user_id: int, required_role: str, db: Session) -> bool:
        """
        检查用户是否具有指定角色
        
        参数：
        - user_id: 用户ID
        - required_role: 需要的角色
        - db: 数据库会话
        
        返回：是否具有角色
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return False
            
            # 超级管理员拥有所有角色权限
            if user.role == 'super_admin':
                return True
            
            return user.role in PermissionService._get_role_variants(required_role)
        
        except Exception as e:
            logger.error(f"角色检查异常 | 用户ID: {user_id} | 需要角色: {required_role} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def check_multiple_roles(user_id: int, required_roles: List[str], db: Session) -> bool:
        """
        检查用户是否具有列表中的任一角色
        
        参数：
        - user_id: 用户ID
        - required_roles: 需要的角色列表
        - db: 数据库会话
        
        返回：是否具有任一角色
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                return False
            
            if user.role == 'super_admin':
                return True
            
            matched_roles = set()
            for required_role in required_roles:
                matched_roles.update(PermissionService._get_role_variants(required_role))
            return user.role in matched_roles
        
        except Exception as e:
            logger.error(f"多角色检查异常 | 用户ID: {user_id} | 需要角色: {required_roles} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def get_user_permissions(user_id: int, db: Session) -> List[str]:
        """
        获取用户的所有权限
        
        参数：
        - user_id: 用户ID
        - db: 数据库会话
        
        返回：权限列表
        """
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return []
            
            permissions = list(PermissionService.ROLE_PERMISSIONS.get(user.role, []))
            
            # 添加别名角色的权限
            for variant_role in PermissionService._get_role_variants(user.role):
                if variant_role != user.role:
                    for perm in PermissionService.ROLE_PERMISSIONS.get(variant_role, []):
                        if perm not in permissions:
                            permissions.append(perm)
            
            # 添加自定义权限
            custom_perms = db.query(RolePermission).filter(
                RolePermission.role.in_(PermissionService._get_role_variants(user.role))
            ).all()
            
            for perm in custom_perms:
                if perm.permission not in permissions:
                    permissions.append(perm.permission)
            
            return permissions
        
        except Exception as e:
            logger.error(f"获取用户权限异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return []

    @staticmethod
    def get_all_permissions() -> Dict[str, str]:
        """
        获取系统所有权限定义
        """
        return PermissionService.PERMISSIONS.copy()

    # 系统角色中文名称映射
    SYSTEM_ROLE_NAMES = {
        'super_admin': '超级管理员',
        'employee': '车间员工',
        'team_leader': '车间班长',
        'department_leader': '部门领导',
        'warehouse_manager': '库管领导',
        'warehouse_operator': '库管',
        'finance': '财务',
        'procurement_officer': '采购员',
        'receiving_inspector': '到货审核员',
        'technical_officer': '技术员',
        'requester': '申请人',
        'approver': '审批人',
        'viewer': '查看员',
        'electrical_inspector': '电气验收员',
        'mechanical_inspector': '机械验收员',
        'logistics_inspector': '后勤验收员',
    }
    # 系统角色描述
    SYSTEM_ROLE_DESCRIPTIONS = {
        'super_admin': '系统超级管理员，拥有所有权限',
        'employee': '车间普通员工，可查看库存和发起领料申请',
        'team_leader': '车间班长，可审批采购和查看物料',
        'department_leader': '部门领导，可审批出库和查看报表',
        'warehouse_manager': '库管领导，管理仓库所有业务',
        'warehouse_operator': '库管操作员，执行出入库等操作',
        'finance': '财务人员，查看报表和NC同步',
        'procurement_officer': '采购员，创建采购清单和执行采购',
        'receiving_inspector': '到货审核员，验收采购物资',
        'technical_officer': '技术员，技术审核入库',
        'requester': '申请人，发起领料申请',
        'approver': '审批人，审批各类申请',
        'viewer': '查看员，只读查看权限',
        'electrical_inspector': '电气验收员',
        'mechanical_inspector': '机械验收员',
        'logistics_inspector': '后勤验收员',
    }

    @staticmethod
    def get_roles(db: Session = None) -> List[str]:
        """
        获取所有角色列表（系统角色 + 自定义角色）

        当 db 可用时从数据库读取，否则返回系统默认列表
        """
        if db is None:
            return SYSTEM_ROLES.copy()
        try:
            definitions = db.query(RoleDefinition).filter(
                RoleDefinition.is_active == True
            ).all()
            if definitions:
                return [d.name for d in definitions]
        except Exception:
            pass
        return SYSTEM_ROLES.copy()

    @staticmethod
    def get_role_definitions(db: Session) -> List[Dict]:
        """
        获取所有角色定义（含元数据）
        """
        try:
            definitions = db.query(RoleDefinition).filter(
                RoleDefinition.is_active == True
            ).order_by(RoleDefinition.id).all()
            result = []
            for d in definitions:
                perms = PermissionService.get_role_permissions(d.name, db)
                result.append({
                    'role': d.name,
                    'display_name': d.display_name,
                    'description': d.description,
                    'is_system': d.is_system,
                    'is_active': d.is_active,
                    'permissions': perms,
                })
            return result
        except Exception as e:
            logger.error(f"获取角色定义异常: {str(e)}")
            return []

    @staticmethod
    def sync_system_roles(db: Session):
        """
        同步系统角色到 role_definitions 表（启动时调用）
        """
        try:
            for role_name in SYSTEM_ROLES:
                existing = db.query(RoleDefinition).filter(
                    RoleDefinition.name == role_name
                ).first()
                if not existing:
                    display_name = PermissionService.SYSTEM_ROLE_NAMES.get(role_name, role_name)
                    description = PermissionService.SYSTEM_ROLE_DESCRIPTIONS.get(role_name, '')
                    definition = RoleDefinition(
                        name=role_name,
                        display_name=display_name,
                        description=description,
                        is_system=True,
                        is_active=True,
                    )
                    db.add(definition)
            db.commit()
            logger.info(f"系统角色同步完成 | 数量: {len(SYSTEM_ROLES)}")
        except Exception as e:
            db.rollback()
            logger.error(f"系统角色同步异常: {str(e)}")

    @staticmethod
    def create_role(
        db: Session,
        name: str,
        display_name: str,
        description: str = None,
        permissions: List[str] = None,
        created_by: int = None,
    ) -> Tuple[bool, str]:
        """
        创建自定义角色
        """
        if not name or not display_name:
            return False, "角色标识和显示名称不能为空"
        if name in SYSTEM_ROLES:
            return False, f"角色标识 '{name}' 与系统角色冲突"
        existing = db.query(RoleDefinition).filter(RoleDefinition.name == name).first()
        if existing:
            return False, f"角色 '{name}' 已存在"
        try:
            definition = RoleDefinition(
                name=name,
                display_name=display_name,
                description=description or '',
                is_system=False,
                is_active=True,
            )
            db.add(definition)
            db.flush()

            # 设置权限
            if permissions:
                for perm in permissions:
                    db.add(RolePermission(role=name, permission=perm,
                           description=PermissionService.PERMISSIONS.get(perm)))
            db.commit()

            if created_by:
                OperationLogModel.create_log(
                    user_id=created_by, action="create_role",
                    module="user_management", related_no=name,
                    details={"display_name": display_name, "permissions": permissions},
                    db=db
                )
            return True, f"角色 '{display_name}' 创建成功"
        except Exception as e:
            db.rollback()
            logger.error(f"创建角色异常: {str(e)}")
            return False, f"创建角色失败: {str(e)}"

    @staticmethod
    def update_role(
        db: Session,
        name: str,
        display_name: str = None,
        description: str = None,
        updated_by: int = None,
    ) -> Tuple[bool, str]:
        """
        更新角色元数据
        """
        definition = db.query(RoleDefinition).filter(RoleDefinition.name == name).first()
        if not definition:
            return False, f"角色 '{name}' 不存在"
        try:
            if display_name is not None:
                definition.display_name = display_name
            if description is not None:
                definition.description = description
            db.commit()

            if updated_by:
                OperationLogModel.create_log(
                    user_id=updated_by, action="update_role",
                    module="user_management", related_no=name,
                    details={"display_name": display_name, "description": description},
                    db=db
                )
            return True, "角色更新成功"
        except Exception as e:
            db.rollback()
            logger.error(f"更新角色异常: {str(e)}")
            return False, f"更新角色失败: {str(e)}"

    @staticmethod
    def delete_role(db: Session, name: str, deleted_by: int = None, force: bool = False) -> Tuple[bool, str]:
        """
        删除自定义角色（系统角色禁止删除）

        Args:
            force: 为 True 时同时删除使用该角色的所有用户
        """
        definition = db.query(RoleDefinition).filter(RoleDefinition.name == name).first()
        if not definition:
            return False, f"角色 '{name}' 不存在"
        if definition.is_system:
            return False, "系统内置角色不可删除"
        try:
            # 检查是否有用户使用此角色
            users_using = db.query(User).filter(User.role == name).all()
            if users_using:
                if not force:
                    usernames = [f"{u.real_name}({u.username})" for u in users_using]
                    return False, f"还有 {len(users_using)} 个用户使用此角色: {', '.join(usernames)}"
                else:
                    # 强制删除：同时删除使用该角色的用户
                    user_ids = [u.id for u in users_using]
                    for u in users_using:
                        db.delete(u)
                    logger.info(f"强制删除角色: {name} | 同时删除了 {len(users_using)} 个用户: {user_ids}")

            # 删除角色权限
            db.query(RolePermission).filter(RolePermission.role == name).delete()
            # 删除角色定义
            db.delete(definition)
            db.commit()

            if deleted_by:
                OperationLogModel.create_log(
                    user_id=deleted_by, action="delete_role",
                    module="user_management", related_no=name,
                    details={"deleted": True, "force": force,
                             "deleted_users": [u.username for u in users_using] if users_using else []},
                    db=db
                )
            return True, f"角色 '{definition.display_name or name}' 已删除"
        except Exception as e:
            db.rollback()
            logger.error(f"删除角色异常: {str(e)}")
            return False, f"删除角色失败: {str(e)}"

    @staticmethod
    def get_role_permissions(role: str, db: Session) -> List[str]:
        """
        获取指定角色的权限列表

        优先级：自定义权限（数据库）> 静态默认权限
        - 如果角色有自定义权限记录，返回自定义权限列表
        - 否则返回静态默认权限
        """
        custom_perms = db.query(RolePermission).filter(
            RolePermission.role == role
        ).all()
        if custom_perms:
            return sorted(list(set(p.permission for p in custom_perms)))
        return sorted(PermissionService.ROLE_PERMISSIONS.get(role, []))

    @staticmethod
    def set_role_permissions(role: str, permissions: List[str], updated_by: int = None, db: Session = None) -> Tuple[bool, str]:
        """
        更新指定角色的权限配置
        """
        if role == SUPER_ADMIN_ROLE:
            return False, "不能修改超级管理员的权限"

        invalid_permissions = [p for p in permissions if p not in PermissionService.PERMISSIONS]
        if invalid_permissions:
            return False, f"权限列表中存在无效项: {', '.join(invalid_permissions)}"

        try:
            # 删除已有自定义权限
            db.query(RolePermission).filter(RolePermission.role == role).delete(synchronize_session=False)
            db.commit()

            # 插入新的权限记录
            for permission in permissions:
                db.add(RolePermission(role=role, permission=permission, description=PermissionService.PERMISSIONS.get(permission)))
            db.commit()

            logger.info(f"角色权限更新成功 | 角色: {role} | 权限数量: {len(permissions)}")

            if updated_by:
                OperationLog.create_log(
                    user_id=updated_by,
                    action="update_role_permissions",
                    module="user_management",
                    related_no=role,
                    details={"permissions": permissions},
                    db=db
                )

            return True, "角色权限更新成功"
        except Exception as e:
            db.rollback()
            logger.error(f"设置角色权限异常 | 角色: {role} | 错误: {str(e)}")
            return False, f"设置角色权限失败: {str(e)}"


class OperationLog:
    """操作日志管理"""
    
    @staticmethod
    def create_log(
        user_id: int,
        action: str,
        module: str,
        related_id: Optional[int] = None,
        related_no: Optional[str] = None,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        db: Session = None
    ) -> bool:
        """
        记录操作日志
        
        参数：
        - user_id: 操作用户ID
        - action: 操作类型
        - module: 操作模块
        - related_id: 相关业务ID
        - related_no: 相关业务单号
        - details: 操作详情（字典）
        - ip_address: 操作IP
        - db: 数据库会话
        
        返回：记录是否成功
        """
        try:
            log = OperationLogModel(
                user_id=user_id,
                action=action,
                module=module,
                related_id=related_id,
                related_no=related_no,
                details=details if isinstance(details, dict) else None,
                ip_address=ip_address,
                created_at=beijing_now()
            )
            
            db.add(log)
            db.commit()
            
            logger.debug(f"操作日志记录 | 用户ID: {user_id} | 操作: {action} | 模块: {module}")
            
            return True
        
        except Exception as e:
            logger.error(f"记录操作日志异常 | 用户ID: {user_id} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def get_logs(
        user_id: Optional[int] = None,
        action: Optional[str] = None,
        module: Optional[str] = None,
        related_no: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
        db: Session = None
    ) -> tuple:
        """
        查询操作日志
        
        参数：
        - user_id: 用户ID
        - action: 操作类型
        - module: 操作模块
        - related_no: 业务单号
        - start_date: 开始时间
        - end_date: 结束时间
        - page: 页码
        - page_size: 每页数量
        - db: 数据库会话
        
        返回：(日志列表, 总数)
        """
        try:
            from sqlalchemy import desc
            
            query = db.query(OperationLogModel)
            
            if user_id:
                query = query.filter(OperationLogModel.user_id == user_id)
            
            if action:
                query = query.filter(OperationLogModel.action == action)
            
            if module:
                query = query.filter(OperationLogModel.module == module)
            
            if related_no:
                query = query.filter(OperationLogModel.related_no == related_no)
            
            if start_date:
                query = query.filter(OperationLogModel.created_at >= start_date)
            
            if end_date:
                query = query.filter(OperationLogModel.created_at <= end_date)
            
            total = query.count()
            
            logs = query.order_by(desc(OperationLogModel.created_at)).offset(
                (page - 1) * page_size
            ).limit(page_size).all()
            
            result = []
            for log in logs:
                result.append({
                    "id": log.id,
                    "user_id": log.user_id,
                    "action": log.action,
                    "module": log.module,
                    "related_id": log.related_id,
                    "related_no": log.related_no,
                    "details": log.details,
                    "ip_address": log.ip_address,
                    "created_at": log.created_at.isoformat() if log.created_at else None
                })
            
            return result, total
        
        except Exception as e:
            logger.error(f"查询操作日志异常 | 错误: {str(e)}")
            return [], 0


class InventoryConcurrencyControl:
    """库存并发控制管理"""
    
    @staticmethod
    def check_inventory_locked(
        material_id: int,
        location_id: int,
        db: Session
    ) -> bool:
        """
        检查库存是否被锁定
        
        参数：
        - material_id: 物资ID
        - location_id: 库位ID
        - db: 数据库会话
        
        返回：是否被锁定
        """
        try:
            inventory = db.query(Inventory).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.location_id == location_id
                )
            ).with_for_update(nowait=True).first()
            
            return inventory is not None
        
        except Exception as e:
            logger.warning(f"库存锁定检查失败 | 物资ID: {material_id} | 库位ID: {location_id} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def acquire_inventory_lock(
        material_id: int,
        location_id: int,
        timeout: int = 30,
        db: Session = None
    ) -> bool:
        """
        获取库存锁（行级锁）
        
        参数：
        - material_id: 物资ID
        - location_id: 库位ID
        - timeout: 超时时间（秒）
        - db: 数据库会话
        
        返回：是否成功获取锁
        """
        try:
            inventory = db.query(Inventory).filter(
                and_(
                    Inventory.material_id == material_id,
                    Inventory.location_id == location_id
                )
            ).with_for_update(nowait=False).first()
            
            logger.debug(f"获取库存锁成功 | 物资ID: {material_id} | 库位ID: {location_id}")
            return inventory is not None
        
        except Exception as e:
            logger.warning(f"获取库存锁失败 | 物资ID: {material_id} | 库位ID: {location_id} | 错误: {str(e)}")
            return False
    
    @staticmethod
    def validate_inventory_consistency(
        material_id: int,
        db: Session
    ) -> Dict:
        """
        验证物资库存一致性
        
        参数：
        - material_id: 物资ID
        - db: 数据库会话
        
        返回：一致性检查结果
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                return {"consistent": False, "error": "物资不存在"}
            
            inventories = db.query(Inventory).filter(
                Inventory.material_id == material_id
            ).all()
            
            total_quantity = sum(float(inv.quantity) for inv in inventories)
            negative_count = sum(1 for inv in inventories if inv.quantity < 0)
            zero_count = sum(1 for inv in inventories if inv.quantity == 0)
            
            return {
                "consistent": negative_count == 0,
                "material_id": material_id,
                "material_name": material.name,
                "total_quantity": total_quantity,
                "location_count": len(inventories),
                "negative_count": negative_count,
                "zero_count": zero_count,
                "check_time": beijing_now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"库存一致性验证异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return {"consistent": False, "error": str(e)}
