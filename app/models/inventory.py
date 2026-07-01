from sqlalchemy import Column, Integer, DateTime, DECIMAL, ForeignKey, BigInteger, Text, String, Boolean
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class Inventory(Base):
    __tablename__ = 'inventory'
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False)
    quantity = Column(DECIMAL(12, 2), default=0.00)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    material = relationship('Material', back_populates='inventories')
    location = relationship('Location', back_populates='inventories')


class InventoryLedger(Base):
    __tablename__ = 'inventory_ledger'
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ledger_no = Column(String(50), unique=True, nullable=False, comment='流水单号')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False, comment='物料ID')
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False, comment='库位ID')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False, comment='仓库ID')
    business_type = Column(String(30), nullable=False, comment='业务类型')
    business_id = Column(Integer, nullable=False, comment='业务单据ID')
    business_no = Column(String(50), nullable=False, comment='业务单据编号')
    change_quantity = Column(DECIMAL(12, 2), nullable=False, comment='变动数量')
    before_quantity = Column(DECIMAL(12, 2), nullable=False, comment='变动前库存')
    after_quantity = Column(DECIMAL(12, 2), nullable=False, comment='变动后库存')
    unit = Column(String(20), nullable=False, comment='单位')
    operator_id = Column(Integer, ForeignKey('users.id'), nullable=False, comment='操作人ID')
    operator_name = Column(String(50), comment='操作人姓名')
    status = Column(String(30), default='confirmed', comment='状态')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    material = relationship('Material')
    location = relationship('Location')
    warehouse = relationship('Warehouse')
    operator = relationship('User')


class InventorySnapshot(Base):
    __tablename__ = 'inventory_snapshots'
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    snapshot_no = Column(String(50), nullable=False, comment='快照单号')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False, comment='物料ID')
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False, comment='库位ID')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False, comment='仓库ID')
    quantity = Column(DECIMAL(12, 2), nullable=False, comment='库存数量')
    snapshot_date = Column(DateTime, nullable=False, comment='快照日期')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    material = relationship('Material')
    location = relationship('Location')
    warehouse = relationship('Warehouse')


class InventoryAlertConfig(Base):
    __tablename__ = 'inventory_alert_configs'
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey('materials.id'), comment='物料ID')
    category_id = Column(Integer, ForeignKey('material_categories.id'), comment='分类ID')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), comment='仓库ID')
    min_quantity = Column(DECIMAL(12, 2), default=0.00, comment='库存下限')
    max_quantity = Column(DECIMAL(12, 2), default=999999.99, comment='库存上限')
    is_enabled = Column(Boolean, default=True, comment='是否启用预警')
    alert_level = Column(String(20), default='warning', comment='预警级别')
    creator_id = Column(Integer, ForeignKey('users.id'), comment='创建人ID')
    updater_id = Column(Integer, ForeignKey('users.id'), comment='更新人ID')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    material = relationship('Material')
    category = relationship('MaterialCategory')
    warehouse = relationship('Warehouse')
    creator = relationship('User', foreign_keys=[creator_id])
    updater = relationship('User', foreign_keys=[updater_id])


class InventoryAlert(Base):
    __tablename__ = 'inventory_alerts'
    id = Column(Integer, primary_key=True, index=True)
    alert_no = Column(String(50), unique=True, nullable=False, comment='预警单号')
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False, comment='物料ID')
    location_id = Column(Integer, ForeignKey('locations.id'), comment='库位ID')
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), comment='仓库ID')
    current_quantity = Column(DECIMAL(12, 2), nullable=False, comment='当前库存数量')
    threshold_min = Column(DECIMAL(12, 2), comment='下限阈值')
    threshold_max = Column(DECIMAL(12, 2), comment='上限阈值')
    alert_type = Column(String(30), nullable=False, comment='预警类型')
    alert_level = Column(String(20), default='warning', comment='预警级别')
    status = Column(String(30), default='pending', comment='状态')
    handler_id = Column(Integer, ForeignKey('users.id'), comment='处理人ID')
    handled_at = Column(DateTime, comment='处理时间')
    handle_remark = Column(Text, comment='处理备注')
    creator_id = Column(Integer, ForeignKey('users.id'), comment='创建人ID')
    remark = Column(Text, comment='备注')
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    material = relationship('Material')
    location = relationship('Location')
    warehouse = relationship('Warehouse')
    handler = relationship('User', foreign_keys=[handler_id])
    creator = relationship('User', foreign_keys=[creator_id])
