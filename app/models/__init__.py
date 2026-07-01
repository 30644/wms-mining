"""
数据库模型定义
所有模型通过子模块组织，在此统一导出以保持向后兼容。
"""
from app.database import Base

from .location import Warehouse, Shelf, Location
from .catalog import MaterialCategory, Material, MaterialAlias, Supplier
from .user import User, RoleDefinition, RolePermission, Department
from .inventory import Inventory, InventoryLedger, InventorySnapshot, InventoryAlertConfig, InventoryAlert
from .transaction import InboundOrder, OutboundOrder, OutboundOrderItem, Request, InventoryTransfer, ScanInboundSession
from .check import InventoryCheck, InventoryCheckOrder, InventoryCheckItem
from .business import TransferOrder, TransferOrderItem, ScrapOrder, ScrapOrderItem, ReturnOrder, ReturnOrderItem
from .log import OperationLog, NcSyncRecord
from .nc_config import NcConfig
from .system_config import SystemConfig
from .evaluation import SupplierEvaluation
from .purchase import PurchaseOrder, PURCHASE_STATUS

__all__ = [
    'Warehouse', 'Shelf', 'Location', 'MaterialCategory', 'Material', 'Inventory',
    'User', 'RoleDefinition', 'RolePermission', 'Request', 'InboundOrder', 'OutboundOrder',
    'InventoryCheck', 'OperationLog', 'NcSyncRecord', 'InventoryTransfer', 'Supplier',
    'TransferOrder', 'TransferOrderItem', 'ScrapOrder', 'ScrapOrderItem',
    'ReturnOrder', 'ReturnOrderItem',
    'InventoryAlertConfig', 'InventoryAlert', 'InventoryLedger', 'InventorySnapshot',
    'ScanInboundSession', 'Department', 'NcConfig', 'MaterialAlias',
    'PurchaseOrder', 'PURCHASE_STATUS',
]
