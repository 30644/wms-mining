"""
用友NC6.5数据同步服务
- 物料数据同步
- 库存数据同步
- 成本数据双向映射同步
- 同步失败重试、异常记录机制
"""
from typing import Optional, Tuple, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from datetime import datetime, timedelta
import json
import requests

from app.models import NcSyncRecord, InboundOrder, OutboundOrder, Material, Inventory, TransferOrder, ScrapOrder, ReturnOrder
from app.models.nc_config import NcConfig
from app.utils.logger import logger
from app.config import NC_API_URL, NC_API_TIMEOUT, NC_MAX_RETRY
from app.database import beijing_now


class NcSyncService:
    """用友NC6.5数据同步服务"""
    
    # 同步类型
    SYNC_TYPE_INBOUND = 'inbound'
    SYNC_TYPE_OUTBOUND = 'outbound'
    SYNC_TYPE_MATERIAL = 'material'
    SYNC_TYPE_INVENTORY = 'inventory'
    SYNC_TYPE_TRANSFER = 'transfer'
    SYNC_TYPE_SCRAP = 'scrap'
    SYNC_TYPE_RETURN = 'return'
    
    # 同步状态
    SYNC_STATUS_PENDING = 'pending'
    SYNC_STATUS_SUCCESS = 'success'
    SYNC_STATUS_FAILED = 'failed'
    SYNC_STATUS_RETRYING = 'retrying'
    
    @staticmethod
    def sync_inbound_to_nc(
        inbound_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步入库单到用友NC6.5
        
        参数：
        - inbound_order_id: 入库单ID
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            inbound_order = db.query(InboundOrder).filter(
                InboundOrder.id == inbound_order_id
            ).first()
            
            if not inbound_order:
                logger.warning(f"同步入库单失败: 入库单不存在 | 入库单ID: {inbound_order_id}")
                return False, "入库单不存在"
            
            # 检查入库单是否已入库
            if inbound_order.status != 'in_stock':
                logger.warning(f"同步入库单失败: 入库单未入库 | 状态: {inbound_order.status}")
                return False, f"入库单未入库（当前状态: {inbound_order.status}）"
            
            # 准备同步数据
            sync_data = {
                "business_no": inbound_order.inbound_no,
                "inbound_type": NcSyncService._map_inbound_type_to_nc(inbound_order.inbound_type),
                "material_code": inbound_order.material.nc_code or inbound_order.material.code,
                "material_name": inbound_order.material.name,
                "quantity": float(inbound_order.quantity),
                "unit": inbound_order.material.unit,
                "supplier": inbound_order.supplier,
                "batch_info": inbound_order.batch_info,
                "warehouse_code": inbound_order.location.warehouse.code if inbound_order.location.warehouse else None,
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp()
            }
            
            # 调用NC接口
            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/inbound",
                data=sync_data
            )
            
            if not nc_order_no:
                logger.warning(f"同步入库单失败: NC接口调用失败 | 入库单: {inbound_order.inbound_no}")
                return False, "NC接口调用失败"
            
            # 更新入库单同步状态
            inbound_order.is_synced_to_nc = True
            inbound_order.nc_sync_time = beijing_now()
            inbound_order.nc_order_no = nc_order_no
            
            # 创建同步记录
            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_INBOUND,
                business_id=inbound_order.id,
                business_no=inbound_order.inbound_no,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now()
            )
            
            db.add(sync_record)
            db.commit()
            
            logger.info(f"同步入库单成功 | 入库单: {inbound_order.inbound_no} | NC单号: {nc_order_no}")
            
            return True, f"同步成功，NC单号: {nc_order_no}"
        
        except Exception as e:
            db.rollback()
            logger.error(f"同步入库单异常 | 入库单ID: {inbound_order_id} | 错误: {str(e)}")
            
            # 记录失败的同步
            try:
                sync_record = NcSyncRecord(
                    sync_type=NcSyncService.SYNC_TYPE_INBOUND,
                    business_id=inbound_order_id,
                    business_no=inbound_order.inbound_no if inbound_order else f"unknown_{inbound_order_id}",
                    sync_status=NcSyncService.SYNC_STATUS_FAILED,
                    error_message=str(e),
                    attempt_count=1
                )
                db.add(sync_record)
                db.commit()
            except:
                pass
            
            return False, f"同步失败: {str(e)}"
    
    @staticmethod
    def sync_outbound_to_nc(
        outbound_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步出库单到用友NC6.5
        
        参数：
        - outbound_order_id: 出库单ID
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            outbound_order = db.query(OutboundOrder).filter(
                OutboundOrder.id == outbound_order_id
            ).first()
            
            if not outbound_order:
                logger.warning(f"同步出库单失败: 出库单不存在 | 出库单ID: {outbound_order_id}")
                return False, "出库单不存在"
            
            # 检查出库单是否已出库
            if outbound_order.status != 'out_of_stock':
                logger.warning(f"同步出库单失败: 出库单未出库 | 状态: {outbound_order.status}")
                return False, f"出库单未出库（当前状态: {outbound_order.status}）"
            
            # 准备同步数据
            sync_data = {
                "business_no": outbound_order.outbound_no,
                "outbound_type": NcSyncService._map_outbound_type_to_nc(outbound_order.outbound_type),
                "material_code": outbound_order.material.nc_code or outbound_order.material.code,
                "material_name": outbound_order.material.name,
                "quantity": float(outbound_order.quantity),
                "unit": outbound_order.material.unit,
                "destination": outbound_order.destination_warehouse,
                "reason": outbound_order.reason,
                "warehouse_code": outbound_order.location.warehouse.code if outbound_order.location.warehouse else None,
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp()
            }
            
            # 调用NC接口
            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/outbound",
                data=sync_data
            )
            
            if not nc_order_no:
                logger.warning(f"同步出库单失败: NC接口调用失败 | 出库单: {outbound_order.outbound_no}")
                return False, "NC接口调用失败"
            
            # 更新出库单同步状态
            outbound_order.is_synced_to_nc = True
            outbound_order.nc_sync_time = beijing_now()
            outbound_order.nc_order_no = nc_order_no
            
            # 创建同步记录
            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_OUTBOUND,
                business_id=outbound_order.id,
                business_no=outbound_order.outbound_no,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now()
            )
            
            db.add(sync_record)
            db.commit()
            
            logger.info(f"同步出库单成功 | 出库单: {outbound_order.outbound_no} | NC单号: {nc_order_no}")
            
            return True, f"同步成功，NC单号: {nc_order_no}"
        
        except Exception as e:
            db.rollback()
            logger.error(f"同步出库单异常 | 出库单ID: {outbound_order_id} | 错误: {str(e)}")
            
            # 记录失败的同步
            try:
                sync_record = NcSyncRecord(
                    sync_type=NcSyncService.SYNC_TYPE_OUTBOUND,
                    business_id=outbound_order_id,
                    business_no=outbound_order.outbound_no if outbound_order else f"unknown_{outbound_order_id}",
                    sync_status=NcSyncService.SYNC_STATUS_FAILED,
                    error_message=str(e),
                    attempt_count=1
                )
                db.add(sync_record)
                db.commit()
            except:
                pass
            
            return False, f"同步失败: {str(e)}"
    
    @staticmethod
    def sync_inventory_to_nc(
        material_id: int,
        db: Session = None,
        timeout: int = None
    ) -> Tuple[bool, str]:
        """
        同步库存数据到用友NC6.5

        参数：
        - material_id: 物资ID
        - db: 数据库会话
        - timeout: HTTP超时秒数

        返回：(成功标志, 消息)
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                logger.warning(f"同步库存失败: 物资不存在 | 物资ID: {material_id}")
                return False, "物资不存在"

            # 查询物资总库存
            inventories = db.query(Inventory).filter(
                Inventory.material_id == material_id
            ).all()

            total_quantity = sum(float(inv.quantity) for inv in inventories)

            # 准备同步数据
            sync_data = {
                "material_code": material.nc_code or material.code,
                "material_name": material.name,
                "total_quantity": total_quantity,
                "unit": material.unit,
                "safety_stock": float(material.safety_stock),
                "warning_threshold": float(material.warning_threshold),
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp()
            }

            # 调用NC接口
            result = NcSyncService._call_nc_api(
                endpoint="/api/inventory/sync",
                data=sync_data,
                timeout=timeout
            )
            
            if not result:
                logger.warning(f"同步库存失败: NC接口调用失败 | 物资: {material.name}")
                return False, "NC接口调用失败"
            
            # 创建同步记录
            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_INVENTORY,
                business_id=material_id,
                business_no=material.code or material.name,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now()
            )
            
            db.add(sync_record)
            db.commit()
            
            logger.info(f"同步库存成功 | 物资: {material.name} | 库存: {total_quantity}")
            
            return True, "库存同步成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"同步库存异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return False, f"同步失败: {str(e)}"

    @staticmethod
    def sync_material_to_nc(
        material_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步物料档案到用友NC6.5

        参数：
        - material_id: 物资ID
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                logger.warning(f"同步物料失败: 物料不存在 | 物资ID: {material_id}")
                return False, "物料不存在"

            sync_data = {
                "material_code": material.code,
                "material_name": material.name,
                "specification": material.specification or "",
                "unit": material.unit,
                "category": material.category.name if material.category else "",
                "safety_stock": float(material.safety_stock or 0),
                "warning_threshold": float(material.warning_threshold or 0),
                "nc_code": material.nc_code or "",
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp(),
            }

            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/material/sync",
                data=sync_data,
                db=db
            )

            if not nc_order_no:
                logger.warning(f"同步物料失败: NC接口调用失败 | 物料: {material.name}")
                return False, "NC接口调用失败"

            # 更新物料NC编码
            material.nc_code = nc_order_no

            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_MATERIAL,
                business_id=material.id,
                business_no=material.code or material.name,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now(),
            )
            db.add(sync_record)
            db.commit()

            logger.info(f"同步物料成功 | 物料: {material.name} | NC编码: {nc_order_no}")
            return True, f"同步成功，NC编码: {nc_order_no}"

        except Exception as e:
            db.rollback()
            logger.error(f"同步物料异常 | 物资ID: {material_id} | 错误: {str(e)}")
            try:
                material_name = material.name if material else f"unknown_{material_id}"
                sync_record = NcSyncRecord(
                    sync_type=NcSyncService.SYNC_TYPE_MATERIAL,
                    business_id=material_id,
                    business_no=material.code if material else material_name,
                    sync_status=NcSyncService.SYNC_STATUS_FAILED,
                    error_message=str(e),
                    attempt_count=1,
                )
                db.add(sync_record)
                db.commit()
            except:
                pass
            return False, f"同步失败: {str(e)}"

    @staticmethod
    def sync_transfer_to_nc(
        transfer_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步调拨单到用友NC6.5

        参数：
        - transfer_order_id: 调拨单ID
        - db: 数据库会话

        返回：(成功标志, 消息)
        """
        try:
            order = db.query(TransferOrder).filter(
                TransferOrder.id == transfer_order_id
            ).first()
            if not order:
                return False, "调拨单不存在"

            if order.status not in ('completed', 'approved'):
                return False, f"调拨单未完成（当前状态: {order.status}）"

            # 构建行项目数据
            items_data = []
            for item in order.items:
                items_data.append({
                    "material_code": item.material.code if item.material else "",
                    "material_name": item.material.name if item.material else "",
                    "quantity": float(item.quantity),
                })

            sync_data = {
                "business_no": order.transfer_no,
                "from_warehouse": order.from_warehouse.name if order.from_warehouse else "",
                "to_warehouse": order.to_warehouse.name if order.to_warehouse else "",
                "reason": order.reason or "",
                "items": items_data,
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp(),
            }

            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/transfer",
                data=sync_data,
                db=db
            )
            if not nc_order_no:
                return False, "NC接口调用失败"

            order.is_synced_to_nc = True
            order.nc_sync_time = beijing_now()
            order.nc_order_no = nc_order_no

            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_TRANSFER,
                business_id=order.id,
                business_no=order.transfer_no,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now(),
            )
            db.add(sync_record)
            db.commit()
            return True, f"同步成功，NC单号: {nc_order_no}"

        except Exception as e:
            db.rollback()
            logger.error(f"同步调拨单异常 | ID: {transfer_order_id} | 错误: {str(e)}")
            return False, f"同步失败: {str(e)}"

    @staticmethod
    def sync_scrap_to_nc(
        scrap_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步报废单到用友NC6.5
        """
        try:
            order = db.query(ScrapOrder).filter(
                ScrapOrder.id == scrap_order_id
            ).first()
            if not order:
                return False, "报废单不存在"

            if order.status not in ('completed', 'approved'):
                return False, f"报废单未完成（当前状态: {order.status}）"

            items_data = []
            for item in order.items:
                items_data.append({
                    "material_code": item.material.code if item.material else "",
                    "material_name": item.material.name if item.material else "",
                    "quantity": float(item.quantity),
                    "unit_price": float(item.unit_price or 0),
                })

            sync_data = {
                "business_no": order.scrap_no,
                "warehouse": order.warehouse.name if order.warehouse else "",
                "reason": order.reason or "",
                "scrap_date": order.scrap_date.isoformat() if order.scrap_date else "",
                "items": items_data,
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp(),
            }

            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/scrap",
                data=sync_data,
                db=db
            )
            if not nc_order_no:
                return False, "NC接口调用失败"

            order.is_synced_to_nc = True
            order.nc_sync_time = beijing_now()
            order.nc_order_no = nc_order_no

            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_SCRAP,
                business_id=order.id,
                business_no=order.scrap_no,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now(),
            )
            db.add(sync_record)
            db.commit()
            return True, f"同步成功，NC单号: {nc_order_no}"

        except Exception as e:
            db.rollback()
            logger.error(f"同步报废单异常 | ID: {scrap_order_id} | 错误: {str(e)}")
            return False, f"同步失败: {str(e)}"

    @staticmethod
    def sync_return_to_nc(
        return_order_id: int,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        同步退货单到用友NC6.5
        """
        try:
            order = db.query(ReturnOrder).filter(
                ReturnOrder.id == return_order_id
            ).first()
            if not order:
                return False, "退货单不存在"

            if order.status not in ('completed', 'approved'):
                return False, f"退货单未完成（当前状态: {order.status}）"

            items_data = []
            for item in order.items:
                items_data.append({
                    "material_code": item.material.code if item.material else "",
                    "material_name": item.material.name if item.material else "",
                    "quantity": float(item.quantity),
                })

            sync_data = {
                "business_no": order.return_no,
                "supplier": order.supplier.supplier_name if order.supplier else "",
                "warehouse": order.warehouse.name if order.warehouse else "",
                "reason": order.reason or "",
                "items": items_data,
                "sync_time": beijing_now().isoformat(),
                "timestamp": beijing_now().timestamp(),
            }

            nc_order_no = NcSyncService._call_nc_api(
                endpoint="/api/return",
                data=sync_data,
                db=db
            )
            if not nc_order_no:
                return False, "NC接口调用失败"

            order.is_synced_to_nc = True
            order.nc_sync_time = beijing_now()
            order.nc_order_no = nc_order_no

            sync_record = NcSyncRecord(
                sync_type=NcSyncService.SYNC_TYPE_RETURN,
                business_id=order.id,
                business_no=order.return_no,
                nc_code=nc_order_no,
                sync_status=NcSyncService.SYNC_STATUS_SUCCESS,
                synced_at=beijing_now(),
            )
            db.add(sync_record)
            db.commit()
            return True, f"同步成功，NC单号: {nc_order_no}"

        except Exception as e:
            db.rollback()
            logger.error(f"同步退货单异常 | ID: {return_order_id} | 错误: {str(e)}")
            return False, f"同步失败: {str(e)}"

    @staticmethod
    def retry_failed_syncs(db: Session = None) -> Dict:
        """
        重试失败的同步
        
        参数：
        - db: 数据库会话
        
        返回：重试结果统计
        """
        try:
            # 查询未成功的同步记录
            nc_config = NcSyncService._get_db_config(db)
            max_retry = nc_config["max_retry"]
            failed_records = db.query(NcSyncRecord).filter(
                and_(
                    NcSyncRecord.sync_status.in_([
                        NcSyncService.SYNC_STATUS_FAILED,
                        NcSyncService.SYNC_STATUS_RETRYING
                    ]),
                    NcSyncRecord.attempt_count < max_retry
                )
            ).all()
            
            retry_stats = {
                "total": len(failed_records),
                "success": 0,
                "failed": 0,
                "records": []
            }
            
            for record in failed_records:
                record.attempt_count += 1
                record.sync_status = NcSyncService.SYNC_STATUS_RETRYING
                
                try:
                    # 根据同步类型重试
                    if record.sync_type == NcSyncService.SYNC_TYPE_INBOUND:
                        success, msg = NcSyncService.sync_inbound_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_OUTBOUND:
                        success, msg = NcSyncService.sync_outbound_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_INVENTORY:
                        success, msg = NcSyncService.sync_inventory_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_MATERIAL:
                        success, msg = NcSyncService.sync_material_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_TRANSFER:
                        success, msg = NcSyncService.sync_transfer_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_SCRAP:
                        success, msg = NcSyncService.sync_scrap_to_nc(
                            record.business_id,
                            db
                        )
                    elif record.sync_type == NcSyncService.SYNC_TYPE_RETURN:
                        success, msg = NcSyncService.sync_return_to_nc(
                            record.business_id,
                            db
                        )
                    else:
                        success = False
                    
                    if success:
                        record.sync_status = NcSyncService.SYNC_STATUS_SUCCESS
                        record.synced_at = beijing_now()
                        retry_stats["success"] += 1
                        logger.info(f"重试同步成功 | 类型: {record.sync_type} | 业务号: {record.business_no}")
                    else:
                        record.sync_status = NcSyncService.SYNC_STATUS_FAILED
                        record.error_message = msg
                        retry_stats["failed"] += 1
                        logger.warning(f"重试同步失败 | 类型: {record.sync_type} | 业务号: {record.business_no}")
                    
                    retry_stats["records"].append({
                        "sync_type": record.sync_type,
                        "business_no": record.business_no,
                        "attempt_count": record.attempt_count,
                        "success": success
                    })
                
                except Exception as e:
                    record.sync_status = NcSyncService.SYNC_STATUS_FAILED
                    record.error_message = str(e)
                    retry_stats["failed"] += 1
                    logger.error(f"重试同步异常 | 类型: {record.sync_type} | 业务号: {record.business_no} | 错误: {str(e)}")
            
            db.commit()
            
            logger.info(f"同步重试完成 | 总数: {retry_stats['total']} | 成功: {retry_stats['success']} | 失败: {retry_stats['failed']}")
            
            return retry_stats
        
        except Exception as e:
            db.rollback()
            logger.error(f"重试同步异常 | 错误: {str(e)}")
            return {"total": 0, "success": 0, "failed": 0, "error": str(e)}
    
    @staticmethod
    def _map_inbound_type_to_nc(inbound_type: str) -> str:
        """映射入库类型到NC编码"""
        mapping = {
            'procurement': '01',      # 采购入库
            'transfer_in': '02',      # 调拨入库
            'return': '03',           # 退库入库
            'inventory_gain': '04'    # 盘盈入库
        }
        return mapping.get(inbound_type, '01')
    
    @staticmethod
    def _map_outbound_type_to_nc(outbound_type: str) -> str:
        """映射出库类型到NC编码"""
        mapping = {
            'requisition': '01',      # 物资领用
            'maintenance': '02',      # 维修出库
            'transfer_out': '03',     # 调拨出库
            'inventory_loss': '04'    # 盘亏出库
        }
        return mapping.get(outbound_type, '01')
    
    @staticmethod
    def _get_db_config(db: Session = None) -> dict:
        """从数据库读取NC配置，fallback到config.py"""
        if db is not None:
            config = db.query(NcConfig).first()
            if config:
                return {
                    "api_url": config.nc_url,
                    "api_token": config.api_token,
                    "timeout": config.timeout,
                    "max_retry": config.max_retry,
                }
        return {
            "api_url": NC_API_URL,
            "api_token": "your-nc-token",
            "timeout": NC_API_TIMEOUT,
            "max_retry": NC_MAX_RETRY,
        }

    @staticmethod
    def _call_nc_api(endpoint: str, data: Dict, db: Session = None, timeout: int = None) -> Optional[str]:
        """
        调用用友NC API

        参数：
        - endpoint: 接口端点
        - data: 请求数据
        - db: 数据库会话（用于读取NC配置）
        - timeout: 超时时间（覆盖配置）

        返回：NC返回的单号或None
        """
        try:
            nc_config = NcSyncService._get_db_config(db)
            url = f"{nc_config['api_url']}{endpoint}"
            actual_timeout = timeout or nc_config["timeout"]
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {nc_config['api_token']}"
            }

            response = requests.post(
                url,
                json=data,
                headers=headers,
                timeout=actual_timeout
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0 and result.get("data"):
                    return result["data"].get("order_no")

            logger.warning(f"NC API调用失败 | 端点: {endpoint} | 状态码: {response.status_code}")
            return None

        except requests.Timeout:
            logger.error(f"NC API调用超时 | 端点: {endpoint}")
            return None
        except Exception as e:
            logger.error(f"NC API调用异常 | 端点: {endpoint} | 错误: {str(e)}")
            return None
