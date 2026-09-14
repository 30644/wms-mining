from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class InventoryCheck(Base):
    __tablename__ = 'inventory_checks'
    id = Column(Integer, primary_key=True, index=True)
    check_no = Column(String(50), unique=True, nullable=False)
    check_date = Column(DateTime, nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False)
    expected_quantity = Column(DECIMAL(12, 2), default=0.00)
    actual_quantity = Column(DECIMAL(12, 2), default=0.00)
    difference = Column(DECIMAL(12, 2), default=0.00)
    checker_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(30), default='pending')
    remark = Column(Text)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    material = relationship('Material', back_populates='inventory_checks')
    location = relationship('Location', back_populates='inventory_checks')
    checker = relationship('User', back_populates='inventory_checks')


class InventoryCheckOrder(Base):
    __tablename__ = 'inventory_check_orders'
    id = Column(Integer, primary_key=True, index=True)
    check_no = Column(String(50), unique=True, nullable=False, comment='盘点单号')
    check_type = Column(String(30), default='full', comment='盘点类型')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), comment='库房ID')
    category_id = Column(Integer, ForeignKey('material_categories.id'), comment='分类ID')
    material_ids = Column(Text, comment='物料ID列表，JSON格式')
    check_date = Column(DateTime, nullable=False, comment='盘点日期')
    status = Column(String(30), default='draft', comment='状态')
    total_items = Column(Integer, default=0, comment='盘点物料项数')
    expected_total = Column(DECIMAL(12, 2), default=0.00, comment='账面库存总量')
    actual_total = Column(DECIMAL(12, 2), default=0.00, comment='实盘库存总量')
    profit_total = Column(DECIMAL(12, 2), default=0.00, comment='盘盈总量')
    loss_total = Column(DECIMAL(12, 2), default=0.00, comment='盘亏总量')
    creator_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='创建人ID')
    reviewer_id = Column(Integer, ForeignKey('users.id'), comment='审核人ID')
    reviewed_at = Column(DateTime, comment='审核时间')
    review_comment = Column(Text, comment='审核意见')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    warehouse = relationship('Warehouse')
    category = relationship('MaterialCategory')
    creator = relationship('User', foreign_keys=[creator_id])
    reviewer = relationship('User', foreign_keys=[reviewer_id])
    items = relationship('InventoryCheckItem', back_populates='check_order', cascade='all, delete-orphan')


class InventoryCheckItem(Base):
    __tablename__ = 'inventory_check_items'
    id = Column(Integer, primary_key=True, index=True)
    check_order_id = Column(Integer, ForeignKey('inventory_check_orders.id'), nullable=False, comment='盘点主表ID')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False, comment='物料ID')
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False, comment='库位ID')
    expected_quantity = Column(DECIMAL(12, 2), default=0.00, comment='账面库存数量')
    actual_quantity = Column(DECIMAL(12, 2), default=0.00, comment='实盘数量')
    difference = Column(DECIMAL(12, 2), default=0.00, comment='差异数量')
    difference_reason = Column(String(200), comment='差异原因备注')
    status = Column(String(30), default='pending', comment='状态')
    adjusted_quantity = Column(DECIMAL(12, 2), comment='调整后数量')
    adjusted_at = Column(DateTime, comment='调整时间')
    adjusted_by = Column(Integer, ForeignKey('users.id'), comment='调整人ID')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    check_order = relationship('InventoryCheckOrder', back_populates='items')
    material = relationship('Material')
    location = relationship('Location')
    adjusted_by_user = relationship('User', foreign_keys=[adjusted_by])
