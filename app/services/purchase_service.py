"""
采购清单业务服务层
- 采购清单CRUD
- 多级审批流转（班长→技术员→审核员→采购员）
- 从预警生成采购
"""
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.models import PurchaseOrder, PURCHASE_STATUS, Material, MaterialCategory, Warehouse, User, InventoryAlert
from app.utils.logger import logger


class PurchaseService:
    """采购清单业务服务"""

    @staticmethod
    def _generate_purchase_no(db: Session) -> str:
        """生成采购单号 CG + 日期 + 序号"""
        from sqlalchemy import func
        today = datetime.now().strftime('%Y%m%d')
        prefix = f"CG{today}"
        last = db.query(PurchaseOrder).filter(
            PurchaseOrder.purchase_no.like(f"{prefix}%")
        ).order_by(desc(PurchaseOrder.id)).first()
        if last:
            seq = int(last.purchase_no[-4:]) + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    @staticmethod
    def create_purchase(
        db: Session,
        material_id: Optional[int] = None,
        warehouse_id: int = None,
        quantity: float = 1,
        applicant_id: int = None,
        source: str = 'manual',
        source_alert_id: Optional[int] = None,
        remark: Optional[str] = None,
        material_name: Optional[str] = None,
        material_spec: Optional[str] = None,
        material_unit: Optional[str] = None,
        material_category_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[PurchaseOrder]]:
        """创建采购清单（状态: pending_team_leader 直接进入审批流程）"""
        try:
            warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
            if not warehouse:
                return False, "仓库不存在", None
            if quantity <= 0:
                return False, "采购数量必须大于0", None

            # 确定物料：material_id 优先，否则自动新增
            if material_id:
                material = db.query(Material).filter(Material.id == material_id).first()
                if not material:
                    return False, "物料不存在", None
            elif material_name:
                # 自动新增物料
                # 查找或创建默认分类
                cat_name = (material_category_name or '').strip() or '通用物资'
                category = db.query(MaterialCategory).filter(
                    MaterialCategory.name == cat_name
                ).first()
                if not category:
                    category = MaterialCategory(name=cat_name, is_active=True)
                    db.add(category)
                    db.flush()

                # 生成物料编码
                from datetime import datetime
                code = f"P{datetime.now().strftime('%Y%m%d%H%M%S')}"

                material = Material(
                    category_id=category.id,
                    name=material_name.strip(),
                    code=code,
                    specification=material_spec.strip() if material_spec else None,
                    unit=material_unit.strip() if material_unit else '个',
                    is_active=True,
                )
                db.add(material)
                db.flush()
                logger.info(f"采购新增物料 | ID: {material.id} | 名称: {material_name}")
            else:
                return False, "请指定物料ID或填写物料名称", None

            purchase_no = PurchaseService._generate_purchase_no(db)
            order = PurchaseOrder(
                purchase_no=purchase_no,
                material_id=material.id,
                warehouse_id=warehouse_id,
                quantity=quantity,
                source=source,
                source_alert_id=source_alert_id,
                status='pending_finance',
                applicant_id=applicant_id,
                remark=remark,
            )
            db.add(order)
            db.commit()
            db.refresh(order)

            # 如果有关联预警，更新预警状态
            if source_alert_id:
                alert = db.query(InventoryAlert).filter(
                    InventoryAlert.id == source_alert_id
                ).first()
                if alert and alert.status in ('pending', 'processing'):
                    alert.status = 'processing'
                    alert.handle_remark = f"已生成采购单 {purchase_no}"
                    db.commit()

            logger.info(f"创建采购清单成功 | 单号: {purchase_no} | 物料: {material_id}")
            return True, "采购清单创建成功", order
        except Exception as e:
            db.rollback()
            logger.error(f"创建采购清单异常: {str(e)}")
            return False, f"创建失败: {str(e)}", None

    @staticmethod
    def get_purchase_list(
        db: Session,
        status: Optional[str] = None,
        material_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        applicant_id: Optional[int] = None,
        keyword: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[bool, str, List[Dict], int]:
        """获取采购清单列表"""
        try:
            query = db.query(PurchaseOrder)

            if status:
                query = query.filter(PurchaseOrder.status == status)
            if material_id:
                query = query.filter(PurchaseOrder.material_id == material_id)
            if warehouse_id:
                query = query.filter(PurchaseOrder.warehouse_id == warehouse_id)
            if applicant_id:
                query = query.filter(PurchaseOrder.applicant_id == applicant_id)
            if keyword:
                query = query.outerjoin(Material, PurchaseOrder.material_id == Material.id).filter(
                    db.or_(
                        PurchaseOrder.purchase_no.like(f"%{keyword}%"),
                        PurchaseOrder.remark.like(f"%{keyword}%"),
                        Material.name.like(f"%{keyword}%"),
                    )
                ).distinct()
            if start_date:
                query = query.filter(PurchaseOrder.created_at >= start_date)
            if end_date:
                query = query.filter(PurchaseOrder.created_at <= end_date)

            query = query.order_by(desc(PurchaseOrder.created_at))
            total = query.count()
            orders = query.offset(skip).limit(limit).all()

            result = []
            for o in orders:
                result.append(PurchaseService._format_purchase(o))

            return True, "获取成功", result, total
        except Exception as e:
            logger.error(f"获取采购清单列表异常: {str(e)}")
            return False, f"获取失败: {str(e)}", [], 0

    @staticmethod
    def get_purchase_detail(
        db: Session,
        purchase_id: int
    ) -> Tuple[bool, str, Optional[Dict]]:
        """获取采购清单详情"""
        try:
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_id).first()
            if not order:
                return False, "采购清单不存在", None
            return True, "获取成功", PurchaseService._format_purchase(order)
        except Exception as e:
            logger.error(f"获取采购清单详情异常: {str(e)}")
            return False, f"获取失败: {str(e)}", None

    @staticmethod
    def approve_purchase(
        db: Session,
        purchase_id: int,
        reviewer_id: int,
        action: str = 'approve',
        comment: Optional[str] = None
    ) -> Tuple[bool, str, Optional[PurchaseOrder]]:
        """
        审批采购清单
        班长 -> 技术员 -> 审核员 三级审批流转
        """
        try:
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_id).first()
            if not order:
                return False, "采购清单不存在", None

            reviewer = db.query(User).filter(User.id == reviewer_id).first()
            if not reviewer:
                return False, "审批人不存在", None

            if action == 'reject':
                order.status = 'rejected'
                order.reviewer_id = reviewer_id
                order.review_comment = comment
                order.reviewed_at = datetime.now()
                db.commit()
                logger.info(f"采购清单驳回 | 单号: {order.purchase_no} | 审批人: {reviewer_id}")
                return True, "已驳回", order

            # 超管一级审批直接通过，其他角色二级流转: 财务 → 领导
            if reviewer.role == 'super_admin':
                status_flow = {
                    'pending_finance': 'approved',
                    'pending_leader': 'approved',
                }
            else:
                status_flow = {
                    'pending_finance': 'pending_leader',
                    'pending_leader': 'approved',
                }

            current_status = order.status
            if current_status not in status_flow:
                return False, f"当前状态 {PURCHASE_STATUS.get(current_status, current_status)} 不可审批", None

            next_status = status_flow[current_status]
            order.status = next_status
            order.reviewer_id = reviewer_id
            order.review_comment = comment
            order.reviewed_at = datetime.now()

            # 如果最终审批通过，记录完成时间
            if next_status == 'approved':
                order.completed_at = datetime.now()

            db.commit()
            db.refresh(order)

            status_name = PURCHASE_STATUS.get(next_status, next_status)
            logger.info(f"采购清单审批通过 | 单号: {order.purchase_no} | 新状态: {status_name}")
            return True, f"审批通过，当前状态: {status_name}", order
        except Exception as e:
            db.rollback()
            logger.error(f"审批采购清单异常: {str(e)}")
            return False, f"审批失败: {str(e)}", None

    @staticmethod
    def execute_purchase(
        db: Session,
        purchase_id: int,
        purchaser_id: int,
        remark: Optional[str] = None
    ) -> Tuple[bool, str, Optional[PurchaseOrder]]:
        """执行采购（采购员确认已采购）"""
        try:
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_id).first()
            if not order:
                return False, "采购清单不存在", None
            if order.status != 'approved':
                return False, f"当前状态 {PURCHASE_STATUS.get(order.status, order.status)} 不可执行采购", None

            order.status = 'completed'
            order.purchaser_id = purchaser_id
            order.completed_at = datetime.now()
            if remark:
                order.remark = remark
            db.commit()
            db.refresh(order)

            logger.info(f"采购清单执行完成 | 单号: {order.purchase_no} | 采购员: {purchaser_id}")
            return True, "采购完成", order
        except Exception as e:
            db.rollback()
            logger.error(f"执行采购异常: {str(e)}")
            return False, f"执行失败: {str(e)}", None

    @staticmethod
    def cancel_purchase(
        db: Session,
        purchase_id: int,
        user_id: int,
        reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """作废采购清单"""
        try:
            order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_id).first()
            if not order:
                return False, "采购清单不存在"
            if order.status in ('completed', 'cancelled'):
                return False, f"当前状态 {PURCHASE_STATUS.get(order.status, order.status)} 不可作废", None

            order.status = 'cancelled'
            order.reviewer_id = user_id
            order.review_comment = reason
            db.commit()
            logger.info(f"采购清单已作废 | 单号: {order.purchase_no}")
            return True, "作废成功"
        except Exception as e:
            db.rollback()
            logger.error(f"作废采购清单异常: {str(e)}")
            return False, f"作废失败: {str(e)}"

    @staticmethod
    def get_pending_approvals_for_role(
        db: Session,
        role: str
    ) -> List[Dict]:
        """根据角色获取待审批的采购清单（供审批中心调用）"""
        try:
            # 角色到状态的映射: 财务→领导 二级
            role_status_map = {
                'finance': 'pending_finance',
                'department_leader': 'pending_leader',
                'approver': 'pending_leader',
            }
            # 管理员可以看到所有待审批
            manager_roles = ('warehouse_manager', 'super_admin', 'admin')

            statuses = []
            if role in role_status_map:
                statuses.append(role_status_map[role])
            elif role in manager_roles:
                statuses = ['pending_finance', 'pending_leader']
            else:
                return []

            query = db.query(PurchaseOrder).filter(
                PurchaseOrder.status.in_(statuses)
            ).order_by(desc(PurchaseOrder.created_at))

            orders = query.all()
            results = []
            for o in orders:
                mat = o.material
                results.append({
                    'id': f"purchase_{o.id}",
                    'type': 'purchase',
                    'business_no': o.purchase_no,
                    'title': f"采购申请 {o.purchase_no}",
                    'applicant_name': o.applicant.real_name if o.applicant else '',
                    'apply_date': o.created_at.strftime('%Y-%m-%d') if o.created_at else '',
                    'created_at': o.created_at.isoformat() if o.created_at else '',
                    'status': 'pending',
                    'current_approver': PURCHASE_STATUS.get(o.status, o.status),
                    'material_name': mat.name if mat else '',
                    'specification_text': mat.specification if mat else '',
                    'unit_text': mat.unit if mat else '',
                    'quantity': float(o.quantity),
                    'warehouse_name': o.warehouse.name if o.warehouse else '',
                    'remark': o.remark or '',
                })
            return results
        except Exception as e:
            logger.error(f"获取采购待审批列表异常: {str(e)}")
            return []

    @staticmethod
    def get_pending_purchases(
        db: Session
    ) -> List[Dict]:
        """获取待采购清单（采购员用）"""
        try:
            orders = db.query(PurchaseOrder).filter(
                PurchaseOrder.status == 'approved'
            ).order_by(desc(PurchaseOrder.created_at)).all()

            return [PurchaseService._format_purchase(o) for o in orders]
        except Exception as e:
            logger.error(f"获取待采购清单异常: {str(e)}")
            return []

    @staticmethod
    def _format_purchase(o: PurchaseOrder) -> Dict:
        """格式化采购清单输出"""
        return {
            'id': o.id,
            'purchase_no': o.purchase_no,
            'material_id': o.material_id,
            'material_code': o.material.code if o.material else None,
            'material_name': o.material.name if o.material else None,
            'material_spec': o.material.specification if o.material else None,
            'material_unit': o.material.unit if o.material else None,
            'warehouse_id': o.warehouse_id,
            'warehouse_name': o.warehouse.name if o.warehouse else None,
            'quantity': float(o.quantity),
            'source': o.source,
            'source_alert_id': o.source_alert_id,
            'status': o.status,
            'status_name': PURCHASE_STATUS.get(o.status, o.status),
            'applicant_id': o.applicant_id,
            'applicant_name': o.applicant.real_name if o.applicant else None,
            'reviewer_id': o.reviewer_id,
            'reviewer_name': o.reviewer.real_name if o.reviewer else None,
            'review_comment': o.review_comment,
            'purchaser_id': o.purchaser_id,
            'purchaser_name': o.purchaser.real_name if o.purchaser else None,
            'remark': o.remark,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M:%S') if o.created_at else None,
            'updated_at': o.updated_at.strftime('%Y-%m-%d %H:%M:%S') if o.updated_at else None,
            'reviewed_at': o.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if o.reviewed_at else None,
            'completed_at': o.completed_at.strftime('%Y-%m-%d %H:%M:%S') if o.completed_at else None,
        }
