from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class Warehouse(Base):
    __tablename__ = 'warehouses'
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    location = Column(String(100))
    total_shelves = Column(Integer, default=0)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    shelves = relationship('Shelf', back_populates='warehouse')
    locations = relationship('Location', back_populates='warehouse')


class Shelf(Base):
    __tablename__ = 'shelves'
    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    code = Column(String(20), unique=True, nullable=False)
    description = Column(String(100))
    levels = Column(Integer, default=3)
    positions_per_level = Column(Integer, default=2)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    warehouse = relationship('Warehouse', back_populates='shelves')
    locations = relationship('Location', back_populates='shelf')


class Location(Base):
    __tablename__ = 'locations'
    id = Column(Integer, primary_key=True, index=True)
    shelf_id = Column(Integer, ForeignKey('shelves.id'), nullable=False)
    warehouse_id = Column(Integer, ForeignKey('warehouses.id'), nullable=False)
    code = Column(String(30), unique=True, nullable=False)
    level = Column(Integer, nullable=False)
    position = Column(String(1), nullable=False)
    capacity = Column(DECIMAL(12, 2), default=0.00, comment='总容量（体积）')
    capacity_unit = Column(String(10), default='m³', comment='容量单位')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
    shelf = relationship('Shelf', back_populates='locations')
    warehouse = relationship('Warehouse', back_populates='locations')
    inventories = relationship('Inventory', back_populates='location')
    inbound_orders = relationship('InboundOrder', back_populates='location')
    outbound_orders = relationship('OutboundOrder', back_populates='location')
    inventory_checks = relationship('InventoryCheck', back_populates='location')
    transfers_from = relationship('InventoryTransfer', foreign_keys='InventoryTransfer.from_location_id', back_populates='from_location')
    transfers_to = relationship('InventoryTransfer', foreign_keys='InventoryTransfer.to_location_id', back_populates='to_location')
