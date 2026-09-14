"""
物资档案管理业务服务层
- 物资增删改查、分类管理
- 库存上下限预警
- 物料信息同步接口
"""
from typing import Optional, Tuple, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, and_, or_
from datetime import datetime
import json

from app.models import Material, MaterialCategory, MaterialAlias, Inventory, Location, OperationLog, NcSyncRecord
from app.utils.logger import logger


class MaterialService:
    """物资档案服务"""
    
    @staticmethod
    def create_material(
        category_id: int,
        name: str,
        unit: str,
        code: Optional[str] = None,
        specification: Optional[str] = None,
        model: Optional[str] = None,
        description: Optional[str] = None,
        safety_stock: float = 0.0,
        warning_threshold: float = 0.0,
        lead_time_days: int = 0,
        max_per_request: Optional[float] = None,
        nc_code: Optional[str] = None,
        unit_volume: float = 0.0,
        volume_unit: str = "m³",
        created_by: int = None,
        db: Session = None
    ) -> Tuple[bool, str, Optional[Material]]:
        """
        创建物资档案
        
        参数：
        - category_id: 分类ID
        - name: 物资名称
        - unit: 计量单位
        - code: 物资编码
        - specification: 规格
        - model: 型号
        - description: 描述
        - safety_stock: 安全库存量
        - warning_threshold: 库存预警阈值
        - max_per_request: 单次最大领用量
        - nc_code: NC物资编码
        - created_by: 创建人ID
        - db: 数据库会话
        
        返回：(成功标志, 消息, 物资对象)
        """
        try:
            # 检查分类是否存在
            category = db.query(MaterialCategory).filter(
                and_(MaterialCategory.id == category_id, MaterialCategory.is_active == True)
            ).first()
            if not category:
                logger.warning(f"创建物资失败: 物资分类不存在 | 分类ID: {category_id}")
                return False, "物资分类不存在", None
            
            # 检查物资编码是否重复
            if code:
                existing = db.query(Material).filter(Material.code == code).first()
                if existing:
                    logger.warning(f"创建物资失败: 物资编码已存在 | 编码: {code}")
                    return False, "物资编码已存在", None
            
            # 检查物资名称是否重复（同分类内）
            existing_name = db.query(Material).filter(
                and_(Material.category_id == category_id, Material.name == name)
            ).first()
            if existing_name:
                logger.warning(f"创建物资失败: 同分类内物资名称已存在 | 分类: {category_id} | 名称: {name}")
                return False, "同分类内物资名称已存在", None
            
            # 创建物资
            material = Material(
                category_id=category_id,
                name=name,
                code=code,
                specification=specification,
                model=model,
                unit=unit,
                description=description,
                safety_stock=safety_stock,
                warning_threshold=warning_threshold,
                lead_time_days=lead_time_days,
                max_per_request=max_per_request,
                nc_code=nc_code,
                unit_volume=unit_volume,
                volume_unit=volume_unit,
                is_active=True,
                created_by=created_by
            )
            
            db.add(material)
            db.flush()
            db.commit()
            
            logger.info(f"物资创建成功 | 物资ID: {material.id} | 物资名: {name} | 物资编码: {code}")
            
            # 记录操作日志
            if created_by:
                OperationLog.create_log(
                    user_id=created_by,
                    action="create_material",
                    module="material_management",
                    related_id=material.id,
                    related_no=code or name,
                    details={
                        "material_id": material.id,
                        "name": name,
                        "category_id": category_id,
                        "code": code
                    },
                    db=db
                )
            
            return True, "物资创建成功", material
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建物资异常 | 名称: {name} | 错误: {str(e)}")
            return False, f"创建物资失败: {str(e)}", None
    
    @staticmethod
    def update_material(
        material_id: int,
        name: Optional[str] = None,
        code: Optional[str] = None,
        specification: Optional[str] = None,
        model: Optional[str] = None,
        unit: Optional[str] = None,
        description: Optional[str] = None,
        safety_stock: Optional[float] = None,
        warning_threshold: Optional[float] = None,
        lead_time_days: Optional[int] = None,
        max_per_request: Optional[float] = None,
        nc_code: Optional[str] = None,
        unit_volume: Optional[float] = None,
        volume_unit: Optional[str] = None,
        is_active: Optional[bool] = None,
        updated_by: int = None,
        db: Session = None
    ) -> Tuple[bool, str, Optional[Material]]:
        """
        更新物资档案
        
        参数同create_material相同，增加updated_by: 更新人ID
        
        返回：(成功标志, 消息, 物资对象)
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                logger.warning(f"更新物资失败: 物资不存在 | 物资ID: {material_id}")
                return False, "物资不存在", None
            
            old_values = {}
            
            if name is not None and name != material.name:
                old_values['name'] = material.name
                material.name = name
            
            if code is not None and code != material.code:
                old_values['code'] = material.code
                material.code = code
            
            if specification is not None:
                old_values['specification'] = material.specification
                material.specification = specification
            
            if model is not None:
                old_values['model'] = material.model
                material.model = model
            
            if unit is not None:
                old_values['unit'] = material.unit
                material.unit = unit
            
            if description is not None:
                old_values['description'] = material.description
                material.description = description
            
            if safety_stock is not None:
                old_values['safety_stock'] = float(material.safety_stock)
                material.safety_stock = safety_stock
            
            if warning_threshold is not None:
                old_values['warning_threshold'] = float(material.warning_threshold)
                material.warning_threshold = warning_threshold
            
            if lead_time_days is not None:
                old_values['lead_time_days'] = int(material.lead_time_days)
                material.lead_time_days = lead_time_days
            
            if max_per_request is not None:
                old_values['max_per_request'] = float(material.max_per_request) if material.max_per_request else None
                material.max_per_request = max_per_request
            
            if nc_code is not None:
                old_values['nc_code'] = material.nc_code
                material.nc_code = nc_code

            if unit_volume is not None:
                old_values['unit_volume'] = float(material.unit_volume)
                material.unit_volume = unit_volume

            if volume_unit is not None:
                old_values['volume_unit'] = material.volume_unit
                material.volume_unit = volume_unit

            if is_active is not None:
                old_values['is_active'] = material.is_active
                material.is_active = is_active
            
            db.commit()
            
            logger.info(f"物资更新成功 | 物资ID: {material_id} | 修改字段: {list(old_values.keys())}")
            
            # 记录操作日志
            if updated_by:
                OperationLog.create_log(
                    user_id=updated_by,
                    action="update_material",
                    module="material_management",
                    related_id=material_id,
                    related_no=material.code or material.name,
                    details=old_values,
                    db=db
                )
            
            return True, "物资更新成功", material
        
        except Exception as e:
            db.rollback()
            logger.error(f"更新物资异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return False, f"更新物资失败: {str(e)}", None
    
    @staticmethod
    def delete_material(
        material_id: int,
        deleted_by: int = None,
        db: Session = None
    ) -> Tuple[bool, str]:
        """
        删除物资档案（逻辑删除，标记is_active=False）
        
        参数：
        - material_id: 物资ID
        - deleted_by: 删除人ID
        - db: 数据库会话
        
        返回：(成功标志, 消息)
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                logger.warning(f"删除物资失败: 物资不存在 | 物资ID: {material_id}")
                return False, "物资不存在"
            
            # 删除相关库存
            inventory_count = db.query(Inventory).filter(
                Inventory.material_id == material_id
            ).count()
            if inventory_count > 0:
                db.query(Inventory).filter(Inventory.material_id == material_id).delete()
                logger.info(f"删除物资时同步删除库存记录 | 物资ID: {material_id} | 数量: {inventory_count}")

            material.is_active = False
            db.commit()
            
            logger.info(f"物资删除成功 | 物资ID: {material_id}")
            
            # 记录操作日志
            if deleted_by:
                OperationLog.create_log(
                    user_id=deleted_by,
                    action="delete_material",
                    module="material_management",
                    related_id=material_id,
                    related_no=material.code or material.name,
                    details={"material_id": material_id},
                    db=db
                )
            
            return True, "物资删除成功"
        
        except Exception as e:
            db.rollback()
            logger.error(f"删除物资异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return False, f"删除物资失败: {str(e)}"
    
    @staticmethod
    def get_material_list(
        category_id: Optional[int] = None,
        is_active: Optional[bool] = True,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        db: Session = None
    ) -> Tuple[List[Dict], int]:
        """
        查询物资列表
        
        参数：
        - category_id: 分类ID（可选）
        - is_active: 是否启用
        - search: 搜索关键词（物资名称、编码）
        - page: 页码
        - page_size: 每页数量
        - db: 数据库会话
        
        返回：(物资列表, 总数)
        """
        try:
            query = db.query(Material)
            
            if is_active is not None:
                query = query.filter(Material.is_active == is_active)
            
            if category_id is not None:
                query = query.filter(Material.category_id == category_id)
            
            if search:
                query = query.outerjoin(MaterialAlias, MaterialAlias.material_id == Material.id).filter(
                    or_(
                        Material.name.like(f"%{search}%"),
                        Material.code.like(f"%{search}%"),
                        MaterialAlias.alias.like(f"%{search}%")
                    )
                )
                query = query.distinct()

            total = query.count()

            materials = query.order_by(desc(Material.created_at)).offset(
                (page - 1) * page_size
            ).limit(page_size).all()
            
            result = []
            for m in materials:
                # 查询库存总量
                total_inventory = db.query(Inventory).filter(
                    Inventory.material_id == m.id
                ).count()
                
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "code": m.code,
                    "category_id": m.category_id,
                    "category_name": m.category.name if m.category else None,
                    "specification": m.specification,
                    "model": m.model,
                    "unit": m.unit,
                    "description": m.description,
                    "safety_stock": float(m.safety_stock),
                    "warning_threshold": float(m.warning_threshold),
                    "lead_time_days": int(m.lead_time_days),
                    "max_per_request": float(m.max_per_request) if m.max_per_request else None,
                    "nc_code": m.nc_code,
                    "unit_volume": float(m.unit_volume) if m.unit_volume else 0,
                    "volume_unit": m.volume_unit or "m³",
                    "is_active": m.is_active,
                    "created_by": m.created_by,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "inventory_count": total_inventory
                })
            
            return result, total
        
        except Exception as e:
            logger.error(f"查询物资列表异常 | 错误: {str(e)}")
            return [], 0
    
    @staticmethod
    def get_material_by_id(material_id: int, db: Session = None) -> Optional[Dict]:
        """
        获取物资详情
        
        参数：
        - material_id: 物资ID
        - db: 数据库会话
        
        返回：物资详情字典或None
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                return None
            
            return {
                "id": material.id,
                "name": material.name,
                "code": material.code,
                "category_id": material.category_id,
                "category_name": material.category.name if material.category else None,
                "specification": material.specification,
                "model": material.model,
                "unit": material.unit,
                "description": material.description,
                "safety_stock": float(material.safety_stock),
                "warning_threshold": float(material.warning_threshold),
                "lead_time_days": material.lead_time_days,
                "max_per_request": float(material.max_per_request) if material.max_per_request else None,
                "nc_code": material.nc_code,
                "unit_volume": float(material.unit_volume) if material.unit_volume else 0,
                "volume_unit": material.volume_unit or "m³",
                "is_active": material.is_active,
                "created_by": material.created_by,
                "created_at": material.created_at.isoformat() if material.created_at else None
            }

        except Exception as e:
            logger.error(f"获取物资详情异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return None

    @staticmethod
    def get_material_by_code(code: str, db: Session = None) -> Optional[Dict]:
        """
        根据物资编码获取物资详情
        """
        try:
            material = db.query(Material).filter(Material.code == code).first()
            if not material:
                return None

            return {
                "id": material.id,
                "name": material.name,
                "code": material.code,
                "category_id": material.category_id,
                "category_name": material.category.name if material.category else None,
                "specification": material.specification,
                "model": material.model,
                "unit": material.unit,
                "description": material.description,
                "safety_stock": float(material.safety_stock),
                "warning_threshold": float(material.warning_threshold),
                "lead_time_days": material.lead_time_days,
                "max_per_request": float(material.max_per_request) if material.max_per_request else None,
                "nc_code": material.nc_code,
                "unit_volume": float(material.unit_volume) if material.unit_volume else 0,
                "volume_unit": material.volume_unit or "m³",
                "is_active": material.is_active,
                "created_by": material.created_by,
                "created_at": material.created_at.isoformat() if material.created_at else None
            }
        except Exception as e:
            logger.error(f"根据编码获取物资异常 | 编码: {code} | 错误: {str(e)}")
            return None
    
    @staticmethod
    def check_inventory_warning(material_id: int, db: Session = None) -> Dict:
        """
        检查物资库存预警
        
        参数：
        - material_id: 物资ID
        - db: 数据库会话
        
        返回：预警信息字典
        """
        try:
            material = db.query(Material).filter(Material.id == material_id).first()
            if not material:
                return {"has_warning": False, "level": None, "message": None}
            
            # 计算物资总库存
            total_quantity = db.query(Inventory).filter(
                Inventory.material_id == material_id
            ).with_entities(
                __import__('sqlalchemy').func.sum(Inventory.quantity)
            ).scalar() or 0
            
            warning_info = {
                "material_id": material_id,
                "material_name": material.name,
                "current_quantity": float(total_quantity),
                "safety_stock": float(material.safety_stock),
                "warning_threshold": float(material.warning_threshold),
                "has_warning": False,
                "level": None,
                "message": None
            }
            
            if total_quantity < material.safety_stock:
                warning_info["has_warning"] = True
                warning_info["level"] = "critical"
                warning_info["message"] = f"物资库存{float(total_quantity)}{material.unit}已低于安全库存{float(material.safety_stock)}{material.unit}"
            elif total_quantity < material.warning_threshold:
                warning_info["has_warning"] = True
                warning_info["level"] = "warning"
                warning_info["message"] = f"物资库存{float(total_quantity)}{material.unit}已低于预警阈值{float(material.warning_threshold)}{material.unit}"
            
            return warning_info
        
        except Exception as e:
            logger.error(f"检查库存预警异常 | 物资ID: {material_id} | 错误: {str(e)}")
            return {"has_warning": False, "level": None, "message": None}


class MaterialCategoryService:
    """物资分类服务"""
    
    @staticmethod
    def create_category(
        name: str,
        code: Optional[str] = None,
        description: Optional[str] = None,
        inspector_role: Optional[str] = None,
        created_by: int = None,
        db: Session = None
    ) -> Tuple[bool, str, Optional[MaterialCategory]]:
        """
        创建物资分类
        
        参数：
        - name: 分类名称
        - code: 分类编码
        - description: 分类描述
        - created_by: 创建人ID
        - db: 数据库会话
        
        返回：(成功标志, 消息, 分类对象)
        """
        try:
            # 检查分类名称是否重复
            existing = db.query(MaterialCategory).filter(MaterialCategory.name == name).first()
            if existing:
                logger.warning(f"创建物资分类失败: 分类名称已存在 | 名称: {name}")
                return False, "分类名称已存在", None
            
            category = MaterialCategory(
                name=name,
                code=code,
                description=description,
                inspector_role=inspector_role,
                is_active=True
            )
            
            db.add(category)
            db.commit()
            
            logger.info(f"物资分类创建成功 | 分类ID: {category.id} | 分类名: {name}")
            
            return True, "分类创建成功", category
        
        except Exception as e:
            db.rollback()
            logger.error(f"创建物资分类异常 | 名称: {name} | 错误: {str(e)}")
            return False, f"创建分类失败: {str(e)}", None

    @staticmethod
    def update_category(
        category_id: int,
        name: Optional[str] = None,
        code: Optional[str] = None,
        description: Optional[str] = None,
        inspector_role: Optional[str] = None,
        is_active: Optional[bool] = None,
        updated_by: int = None,
        db: Session = None
    ) -> Tuple[bool, str, Optional[MaterialCategory]]:
        """
        更新物资分类
        """
        try:
            category = db.query(MaterialCategory).filter(MaterialCategory.id == category_id).first()
            if not category:
                logger.warning(f"更新物资分类失败: 分类不存在 | 分类ID: {category_id}")
                return False, "分类不存在", None

            if name is not None and name != category.name:
                existing_name = db.query(MaterialCategory).filter(MaterialCategory.name == name).first()
                if existing_name:
                    logger.warning(f"更新物资分类失败: 分类名称已存在 | 名称: {name}")
                    return False, "分类名称已存在", None
                category.name = name

            if code is not None and code != category.code:
                existing_code = db.query(MaterialCategory).filter(MaterialCategory.code == code).first()
                if existing_code:
                    logger.warning(f"更新物资分类失败: 分类编码已存在 | 编码: {code}")
                    return False, "分类编码已存在", None
                category.code = code

            if description is not None:
                category.description = description

            if is_active is not None:
                category.is_active = is_active

            if inspector_role is not None:
                category.inspector_role = inspector_role

            db.commit()

            logger.info(f"物资分类更新成功 | 分类ID: {category_id}")
            if updated_by:
                OperationLog.create_log(
                    user_id=updated_by,
                    action="update_material_category",
                    module="material_management",
                    related_id=category_id,
                    related_no=category.code or category.name,
                    details={
                        "name": category.name,
                        "code": category.code,
                        "description": category.description,
                        "is_active": category.is_active
                    },
                    db=db
                )

            return True, "分类更新成功", category
        except Exception as e:
            db.rollback()
            logger.error(f"更新物资分类异常 | 分类ID: {category_id} | 错误: {str(e)}")
            return False, f"更新分类失败: {str(e)}", None

    @staticmethod
    def delete_category(
        category_id: int,
        deleted_by: int = None,
        db: Session = None,
        cascade: bool = False
    ) -> Tuple[bool, str]:
        """
        删除物资分类（逻辑删除）

        参数：
        - cascade: 是否同时删除分类下所有物料
        """
        try:
            category = db.query(MaterialCategory).filter(MaterialCategory.id == category_id).first()
            if not category:
                logger.warning(f"删除物资分类失败: 分类不存在 | 分类ID: {category_id}")
                return False, "分类不存在"

            material_count = db.query(Material).filter(Material.category_id == category_id).count()
            if material_count > 0 and not cascade:
                logger.warning(f"删除物资分类失败: 分类下存在物资 | 分类ID: {category_id}")
                return False, f"分类下存在 {material_count} 个物料，无法删除"

            if cascade and material_count > 0:
                # 级联删除：逻辑删除该分类下所有物料，并清除库存
                materials = db.query(Material).filter(Material.category_id == category_id).all()
                material_ids = [m.id for m in materials]
                inv_count = db.query(Inventory).filter(Inventory.material_id.in_(material_ids)).delete(synchronize_session=False)
                for material in materials:
                    material.is_active = False
                logger.info(f"级联删除物料 | 分类ID: {category_id} | 物料数: {material_count} | 库存记录: {inv_count}")

            category.is_active = False
            db.commit()

            logger.info(f"物资分类删除成功 | 分类ID: {category_id}")
            if deleted_by:
                OperationLog.create_log(
                    user_id=deleted_by,
                    action="delete_material_category",
                    module="material_management",
                    related_id=category_id,
                    related_no=category.code or category.name,
                    details={"category_id": category_id, "cascade": cascade, "material_count": material_count},
                    db=db
                )

            return True, f"分类删除成功{'，已同时删除 ' + str(material_count) + ' 个物料' if cascade and material_count > 0 else ''}"
        except Exception as e:
            db.rollback()
            logger.error(f"删除物资分类异常 | 分类ID: {category_id} | 错误: {str(e)}")
            return False, f"删除分类失败: {str(e)}"

    @staticmethod
    def get_category_list(
        is_active: Optional[bool] = True,
        db: Session = None
    ) -> List[Dict]:
        """
        获取物资分类列表
        
        参数：
        - is_active: 是否启用
        - db: 数据库会话
        
        返回：分类列表
        """
        try:
            query = db.query(MaterialCategory)
            
            if is_active is not None:
                query = query.filter(MaterialCategory.is_active == is_active)
            
            categories = query.order_by(asc(MaterialCategory.id)).all()
            
            return [{
                "id": c.id,
                "name": c.name,
                "code": c.code,
                "description": c.description,
                "inspector_role": c.inspector_role,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() if c.created_at else None
            } for c in categories]
        
        except Exception as e:
            logger.error(f"查询物资分类列表异常 | 错误: {str(e)}")
            return []
