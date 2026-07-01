"""
采购清单模型
- PurchaseOrder: 采购清单主表
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PurchaseOrder(Base):
    """采购清单"""
    __tablename__ = 'purchase_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_no = Column(String(50), unique=True, nullable=False, comment='采购单号')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False, comment='物料ID')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False, comment='仓库ID')
    quantity = Column(Float, nullable=False, default=1, comment='采购数量')
    source = Column(String(20), default='manual', comment='来源: alert/manual')
    source_alert_id = Column(Integer, ForeignKey('inventory_alerts.id'), nullable=True, comment='关联预警ID')
    status = Column(String(30), default='draft', comment='状态: draft/pending_team_leader/pending_technical/pending_auditor/approved/rejected/completed/cancelled')
    applicant_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='申请人ID')
    reviewer_id = Column(Integer, ForeignKey('users.id'), nullable=True, comment='处理人ID')
    review_comment = Column(String(500), nullable=True, comment='处理意见')
    purchaser_id = Column(Integer, ForeignKey('users.id'), nullable=True, comment='采购员ID')
    remark = Column(String(500), nullable=True, comment='备注')
    created_at = Column(DateTime, default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='更新时间')
    reviewed_at = Column(DateTime, nullable=True, comment='审核时间')
    completed_at = Column(DateTime, nullable=True, comment='完成时间')

    # 关系
    material = relationship('Material', foreign_keys=[material_id], lazy='joined')
    warehouse = relationship('Warehouse', foreign_keys=[warehouse_id], lazy='joined')
    applicant = relationship('User', foreign_keys=[applicant_id], lazy='joined')
    reviewer = relationship('User', foreign_keys=[reviewer_id], lazy='joined')
    purchaser = relationship('User', foreign_keys=[purchaser_id], lazy='joined')
    source_alert = relationship('InventoryAlert', foreign_keys=[source_alert_id], lazy='joined')


# 采购状态映射
PURCHASE_STATUS = {
    'draft': '草稿',
    'pending_finance': '待财务审批',
    'pending_leader': '待领导审批',
    'approved': '已审批',
    'rejected': '已驳回',
    'completed': '已采购',
    'cancelled': '已作废',
}
