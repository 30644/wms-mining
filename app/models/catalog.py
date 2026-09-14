from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class MaterialCategory(Base):
    __tablename__ = 'material_categories'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    code = Column(String(20))
    description = Column(Text)
    inspector_role = Column(String(30), comment='验收员角色：electrical_inspector/mechanical_inspector/logistics_inspector等')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    materials = relationship('Material', back_populates='category')


class Material(Base):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey('material_categories.id'), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(50))
    specification = Column(String(100))
    model = Column(String(100))
    unit = Column(String(20), nullable=False, default='piece')
    unit_price = Column(DECIMAL(12, 2), default=0.00, comment='参考单价')
    description = Column(Text)
    safety_stock = Column(DECIMAL(12, 2), default=0.00)
    warning_threshold = Column(DECIMAL(12, 2), default=0.00)
    lead_time_days = Column(Integer, default=0, comment='采购到货时间（天）')
    max_per_request = Column(DECIMAL(12, 2))
    unit_volume = Column(DECIMAL(12, 4), default=0, comment='单件体积/占位系数（用于库位空间计算）')
    volume_unit = Column(String(10), default='m³', comment='体积单位')
    nc_code = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    category = relationship('MaterialCategory', back_populates='materials')
    inventories = relationship('Inventory', back_populates='material')
    requests = relationship('Request', back_populates='material')
    inbound_orders = relationship('InboundOrder', back_populates='material')
    outbound_orders = relationship('OutboundOrder', back_populates='material')
    inventory_checks = relationship('InventoryCheck', back_populates='material')
    transfers = relationship('InventoryTransfer', back_populates='material')
    aliases = relationship('MaterialAlias', back_populates='material', cascade='all, delete-orphan')


class MaterialAlias(Base):
    __tablename__ = 'material_aliases'
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    alias = Column(String(100), nullable=False, comment='别名/同义词')
    created_at = Column(DateTime, default=beijing_now)
    material = relationship('Material', back_populates='aliases')


class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True, index=True)
    supplier_name = Column(String(100), nullable=False)
    contact = Column(String(100))
    phone = Column(String(50))
    address = Column(String(200))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    return_orders = relationship('ReturnOrder', back_populates='supplier')
