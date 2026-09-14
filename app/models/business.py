from sqlalchemy import Column, Integer, String, Boolean, DateTime, DECIMAL, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class TransferOrder(Base):
    __tablename__ = 'transfer_orders'
    id = Column(Integer, primary_key=True, index=True)
    transfer_no = Column(String(50), unique=True, nullable=False)
    from_warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    to_warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    from_location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)
    to_location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)
    reason = Column(String(200))
    remark = Column(Text)
    status = Column(String(30), default='draft')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_synced_to_nc = Column(Boolean, default=False)
    nc_sync_time = Column(DateTime)
    nc_order_no = Column(String(50))
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    items = relationship('TransferOrderItem', back_populates='order', cascade='all, delete-orphan')
    from_warehouse = relationship('Warehouse', foreign_keys=[from_warehouse_id])
    to_warehouse = relationship('Warehouse', foreign_keys=[to_warehouse_id])
    creator = relationship('User')


class TransferOrderItem(Base):
    __tablename__ = 'transfer_order_items'
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey('transfer_orders.id'), nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    order = relationship('TransferOrder', back_populates='items')
    material = relationship('Material')


class ScrapOrder(Base):
    __tablename__ = 'scrap_orders'
    id = Column(Integer, primary_key=True, index=True)
    scrap_no = Column(String(50), unique=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    scrap_date = Column(DateTime, nullable=False)
    reason = Column(String(200))
    remark = Column(Text)
    status = Column(String(30), default='draft')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    total_amount = Column(DECIMAL(12, 2), default=0.00)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    is_synced_to_nc = Column(Boolean, default=False)
    nc_sync_time = Column(DateTime)
    nc_order_no = Column(String(50))
    items = relationship('ScrapOrderItem', back_populates='order', cascade='all, delete-orphan')
    warehouse = relationship('Warehouse')
    creator = relationship('User')


class ScrapOrderItem(Base):
    __tablename__ = 'scrap_order_items'
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey('scrap_orders.id'), nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_price = Column(DECIMAL(12, 2), default=0.00)
    total_price = Column(DECIMAL(12, 2), default=0.00)
    created_at = Column(DateTime, default=beijing_now)
    order = relationship('ScrapOrder', back_populates='items')
    material = relationship('Material')


class ReturnOrder(Base):
    __tablename__ = 'return_orders'
    id = Column(Integer, primary_key=True, index=True)
    return_no = Column(String(50), unique=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    return_date = Column(DateTime, nullable=False)
    reason = Column(String(200))
    remark = Column(Text)
    status = Column(String(30), default='draft')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    is_synced_to_nc = Column(Boolean, default=False)
    nc_sync_time = Column(DateTime)
    nc_order_no = Column(String(50))
    items = relationship('ReturnOrderItem', back_populates='order', cascade='all, delete-orphan')
    warehouse = relationship('Warehouse')
    supplier = relationship('Supplier', back_populates='return_orders')
    creator = relationship('User')


class ReturnOrderItem(Base):
    __tablename__ = 'return_order_items'
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey('return_orders.id'), nullable=False)
    material_id = Column(Integer, ForeignKey('materials.id'), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    created_at = Column(DateTime, default=beijing_now)
    order = relationship('ReturnOrder', back_populates='items')
    material = relationship('Material')
