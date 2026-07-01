"""
库存管理和物资档案管理接口
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel

from app.database import get_db, beijing_now
from app.models import Inventory, Material, MaterialCategory, Location, Warehouse, InventoryCheck, InventoryTransfer, InventoryAlert
from app.schemas.common import APIResponse, PaginationParams
from app.utils.auth import get_current_user, require_role
from app.utils.logger import logger
from app.config import SUPER_ADMIN_ROLE
from app.services.inventory_ledger_service import InventoryLedgerService

router = APIRouter()


# ============================================================================
# 物资分类管理接口
# ============================================================================

@router.get("/material-categories", summary="获取物资分类列表")
async def get_material_categories(
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资分类列表"""
    try:
        query = db.query(MaterialCategory)
        if is_active is not None:
            query = query.filter(MaterialCategory.is_active == is_active)
        
        categories = query.all()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data=[
                {
                    "id": c.id,
                    "name": c.name,
                    "code": c.code,
                    "description": c.description,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat() if c.created_at else None
                } for c in categories
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取物资分类失败: {str(e)}")


# ============================================================================
# 物资档案管理接口
# ============================================================================

class CreateMaterialRequest(BaseModel):
    category_id: int
    name: str
    code: Optional[str] = None
    specification: Optional[str] = None
    model: Optional[str] = None
    unit: str = "件"
    description: Optional[str] = None
    safety_stock: float = 0.0
    warning_threshold: float = 0.0
    lead_time_days: int = 0
    max_per_request: Optional[float] = None
    nc_code: Optional[str] = None

class UpdateMaterialRequest(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    specification: Optional[str] = None
    model: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    safety_stock: Optional[float] = None
    warning_threshold: Optional[float] = None
    lead_time_days: Optional[int] = None
    max_per_request: Optional[float] = None
    nc_code: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/materials", summary="获取物资档案列表")
async def get_materials(
    category_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资档案列表"""
    try:
        query = db.query(Material).join(MaterialCategory)
        
        if category_id:
            query = query.filter(Material.category_id == category_id)
        if is_active is not None:
            query = query.filter(Material.is_active == is_active)
        if search:
            query = query.filter(
                or_(
                    Material.name.contains(search),
                    Material.code.contains(search),
                    Material.specification.contains(search),
                    Material.model.contains(search)
                )
            )
        
        materials = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": m.id,
                        "category_id": m.category_id,
                        "category_name": m.category.name if m.category else None,
                        "name": m.name,
                        "code": m.code,
                        "specification": m.specification,
                        "model": m.model,
                        "unit": m.unit,
                        "description": m.description,
                        "safety_stock": float(m.safety_stock) if m.safety_stock else 0.0,
                        "warning_threshold": float(m.warning_threshold) if m.warning_threshold else 0.0,
                        "lead_time_days": m.lead_time_days,
                        "max_per_request": float(m.max_per_request) if m.max_per_request else None,
                        "nc_code": m.nc_code,
                        "is_active": m.is_active,
                        "created_by": m.created_by,
                        "created_at": m.created_at.isoformat() if m.created_at else None
                    } for m in materials
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取物资档案失败: {str(e)}")


@router.post("/materials", summary="创建物资档案")
async def create_material(
    request: CreateMaterialRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE))
):
    """创建新的物资档案"""
    try:
        # 检查分类是否存在
        category = db.query(MaterialCategory).filter(
            and_(MaterialCategory.id == request.category_id, MaterialCategory.is_active == True)
        ).first()
        if not category:
            raise HTTPException(status_code=400, detail="物资分类不存在或已禁用")
        
        # 检查编码唯一性
        if request.code:
            existing = db.query(Material).filter(Material.code == request.code).first()
            if existing:
                raise HTTPException(status_code=400, detail="物资编码已存在")
        
        # 创建物资
        material = Material(
            category_id=request.category_id,
            name=request.name,
            code=request.code,
            specification=request.specification,
            model=request.model,
            unit=request.unit,
            description=request.description,
            safety_stock=request.safety_stock,
            warning_threshold=request.warning_threshold,
            lead_time_days=request.lead_time_days,
            max_per_request=request.max_per_request,
            nc_code=request.nc_code,
            created_by=current_user.id
        )
        
        db.add(material)
        db.commit()
        db.refresh(material)
        
        logger.info(f"用户 {current_user.username} 创建物资档案: {material.name}")
        
        return APIResponse(
            code=0,
            message="创建成功",
            data={
                "id": material.id,
                "name": material.name,
                "code": material.code,
                "created_at": material.created_at.isoformat() if material.created_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建物资档案失败: {str(e)}")


@router.put("/materials/{material_id}", summary="更新物资档案")
async def update_material(
    material_id: int,
    request: UpdateMaterialRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role(SUPER_ADMIN_ROLE))
):
    """更新物资档案"""
    try:
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资档案不存在")
        
        # 检查分类
        if request.category_id:
            category = db.query(MaterialCategory).filter(
                and_(MaterialCategory.id == request.category_id, MaterialCategory.is_active == True)
            ).first()
            if not category:
                raise HTTPException(status_code=400, detail="物资分类不存在或已禁用")
        
        # 检查编码唯一性
        if request.code and request.code != material.code:
            existing = db.query(Material).filter(
                and_(Material.code == request.code, Material.id != material_id)
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="物资编码已存在")
        
        # 更新字段
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(material, key, value)
        
        db.commit()
        db.refresh(material)
        
        logger.info(f"用户 {current_user.username} 更新物资档案: {material.name}")
        
        return APIResponse(
            code=0,
            message="更新成功",
            data={"id": material.id, "name": material.name}
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新物资档案失败: {str(e)}")


# ============================================================================
# 库存查询接口
# ============================================================================

@router.get("/inventory", summary="获取库存列表")
async def get_inventory(
    material_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取库存信息"""
    try:
        query = db.query(Inventory).join(Material).join(Location)
        
        if material_id:
            query = query.filter(Inventory.material_id == material_id)
        if location_id:
            query = query.filter(Inventory.location_id == location_id)
        
        inventories = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": inv.id,
                        "material_id": inv.material_id,
                        "material_name": inv.material.name,
                        "material_code": inv.material.code,
                        "location_id": inv.location_id,
                        "location_code": inv.location.code,
                        "quantity": float(inv.quantity),
                        "unit": inv.material.unit,
                        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None
                    } for inv in inventories
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库存信息失败: {str(e)}")


@router.get("/query", summary="查询库存")
async def query_inventory(
    warehouse_id: Optional[int] = Query(None),
    material_id: Optional[int] = Query(None),
    material_code: Optional[str] = Query(None),
    material_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """按条件查询库存信息"""
    try:
        query = db.query(Inventory).join(Material).join(Location)

        if warehouse_id:
            query = query.filter(Location.warehouse_id == warehouse_id)
        if material_id:
            query = query.filter(Inventory.material_id == material_id)
        if material_code:
            query = query.filter(Material.code.ilike(f"%{material_code}%"))
        if material_name:
            query = query.filter(Material.name.ilike(f"%{material_name}%"))

        total = query.count()
        inventories = query.offset((page - 1) * page_size).limit(page_size).all()

        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": inv.id,
                        "warehouse_id": inv.location.warehouse_id if inv.location else None,
                        "warehouse_name": inv.location.warehouse.name if inv.location and inv.location.warehouse else None,
                        "area_name": inv.location.shelf.code if inv.location and inv.location.shelf else None,
                        "location_code": inv.location.code if inv.location else None,
                        "material_id": inv.material_id,
                        "material_code": inv.material.code if inv.material else None,
                        "material_name": inv.material.name if inv.material else None,
                        "specification": inv.material.specification if inv.material else None,
                        "unit": inv.material.unit if inv.material else None,
                        "quantity": float(inv.quantity) if inv.quantity else 0,
                        "available_quantity": float(inv.quantity) if inv.quantity else 0,
                        "locked_quantity": 0,
                        "safety_stock": float(inv.material.safety_stock or 0) if inv.material else 0
                    } for inv in inventories
                ],
                "total": total,
                "page": page,
                "page_size": page_size
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询库存信息失败: {str(e)}")


# ============================================================================
# 库存盘点接口
# ============================================================================

class CreateInventoryCheckRequest(BaseModel):
    material_id: int
    location_id: int
    expected_quantity: float
    actual_quantity: float
    remark: Optional[str] = None

@router.post("/inventory-checks", summary="创建库存盘点记录")
async def create_inventory_check(
    request: CreateInventoryCheckRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """创建库存盘点记录"""
    try:
        # 检查物资和库位是否存在
        material = db.query(Material).filter(Material.id == request.material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资不存在")
        
        location = db.query(Location).filter(Location.id == request.location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")
        
        # 生成盘点单号
        import datetime
        check_no = f"IC{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建盘点记录
        check = InventoryCheck(
            check_no=check_no,
            check_date=datetime.beijing_now(),
            material_id=request.material_id,
            location_id=request.location_id,
            expected_quantity=request.expected_quantity,
            actual_quantity=request.actual_quantity,
            difference=request.actual_quantity - request.expected_quantity,
            checker_id=current_user.id,
            status="completed",
            remark=request.remark
        )
        
        db.add(check)
        db.commit()
        db.refresh(check)
        
        logger.info(f"用户 {current_user.username} 创建库存盘点: {check_no}")
        
        return APIResponse(
            code=0,
            message="盘点记录创建成功",
            data={
                "id": check.id,
                "check_no": check.check_no,
                "difference": float(check.difference)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建盘点记录失败: {str(e)}")


# ============================================================================
# 库存调拨接口
# ============================================================================

class CreateInventoryTransferRequest(BaseModel):
    material_id: int
    from_location_id: int
    to_location_id: int
    quantity: float
    reason: str

@router.post("/inventory-transfers", summary="创建库存调拨")
async def create_inventory_transfer(
    request: CreateInventoryTransferRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """创建库存调拨记录"""
    try:
        # 检查物资和库位
        material = db.query(Material).filter(Material.id == request.material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="物资不存在")
        
        from_location = db.query(Location).filter(Location.id == request.from_location_id).first()
        to_location = db.query(Location).filter(Location.id == request.to_location_id).first()
        if not from_location or not to_location:
            raise HTTPException(status_code=400, detail="库位不存在")
        
        # 检查源库位库存
        inventory = db.query(Inventory).filter(
            and_(Inventory.material_id == request.material_id, Inventory.location_id == request.from_location_id)
        ).first()
        if not inventory or inventory.quantity < request.quantity:
            raise HTTPException(status_code=400, detail="源库位库存不足")
        
        # 生成调拨单号
        import datetime
        transfer_no = f"IT{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 创建调拨记录
        transfer = InventoryTransfer(
            transfer_no=transfer_no,
            material_id=request.material_id,
            from_location_id=request.from_location_id,
            to_location_id=request.to_location_id,
            quantity=request.quantity,
            reason=request.reason,
            warehouse_manager_id=current_user.id
        )
        
        # 更新库存
        inventory.quantity -= request.quantity
        
        # 检查目标库位是否有库存记录
        target_inventory = db.query(Inventory).filter(
            and_(Inventory.material_id == request.material_id, Inventory.location_id == request.to_location_id)
        ).first()
        if target_inventory:
            target_inventory.quantity += request.quantity
        else:
            target_inventory = Inventory(
                material_id=request.material_id,
                location_id=request.to_location_id,
                quantity=request.quantity
            )
            db.add(target_inventory)
        
        db.add(transfer)
        db.commit()
        db.refresh(transfer)
        
        logger.info(f"用户 {current_user.username} 创建库存调拨: {transfer_no}")
        
        return APIResponse(
            code=0,
            message="调拨成功",
            data={
                "id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "from_location": from_location.code,
                "to_location": to_location.code,
                "quantity": float(request.quantity)
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建库存调拨失败: {e}")
        raise HTTPException(status_code=500, detail="创建调拨失败")


# ============================================================================
# 仪表板统计接口
# ============================================================================

@router.get("/summary", summary="获取库存汇总数据")
async def get_inventory_summary(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取仪表板统计数据
    - 物料总数
    - 仓库总数
    - 库存条目总数
    - 库存预警数量
    """
    try:
        # 获取物料总数
        material_count = db.query(Material).filter(Material.is_active == True).count()
        
        # 获取仓库总数
        warehouse_count = db.query(Warehouse).count()
        
        # 获取库存条目总数（库存数量大于0的记录）
        total_items = db.query(Inventory).filter(Inventory.quantity > 0).count()
        
        # 获取库存预警数量
        alert_count = db.query(InventoryAlert).filter(
            InventoryAlert.status == 'pending'
        ).count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "material_count": material_count,
                "warehouse_count": warehouse_count,
                "total_items": total_items,
                "alert_count": alert_count
            }
        )
    except Exception as e:
        logger.error(f"获取库存汇总失败: {e}")
        logger.error(f"获取库存汇总异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取库存汇总失败: {str(e)}")


@router.get("/material/{material_id}/stock-summary", summary="查询物料各仓库库存概括")
async def get_material_stock_summary(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    查询指定物料在所有仓库的库存分布。

    按仓库分组返回各仓库可用库存及库位明细。
    用于出库创建时选择仓库和库位。
    """
    try:
        # 查询该物料所有有库存的记录，关联库位和仓库
        records = db.query(Inventory, Location, Warehouse).join(
            Location, Inventory.location_id == Location.id
        ).join(
            Warehouse, Location.warehouse_id == Warehouse.id
        ).filter(
            and_(
                Inventory.material_id == material_id,
                Inventory.quantity > 0,
                Location.is_active == True
            )
        ).all()

        # 按仓库分组
        warehouse_map = {}
        for inv, loc, wh in records:
            wh_id = wh.id
            if wh_id not in warehouse_map:
                warehouse_map[wh_id] = {
                    "warehouse_id": wh.id,
                    "warehouse_name": wh.name,
                    "warehouse_code": wh.code,
                    "total_quantity": 0,
                    "locations": []
                }
            warehouse_map[wh_id]["total_quantity"] += float(inv.quantity)
            warehouse_map[wh_id]["locations"].append({
                "location_id": loc.id,
                "location_code": loc.code,
                "quantity": float(inv.quantity)
            })

        warehouses = list(warehouse_map.values())

        return APIResponse(
            code=0,
            message="获取成功",
            data=warehouses
        )

    except Exception as e:
        logger.error(f"查询物料库存概括异常 | 物料ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询物料库存概括失败: {str(e)}")


@router.post("/calculate-safety-stock", summary="自动计算安全库存")
async def calculate_safety_stock(
    material_id: int = Body(..., embed=True, description="物料ID"),
    days: int = Body(30, embed=True, description="统计天数"),
    safety_factor: float = Body(1.5, embed=True, description="安全系数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    基于历史消耗数据自动计算安全库存。

    计算公式：安全库存 = 日均消耗量 × 采购提前期(天) × 安全系数
    """
    try:
        success, msg, data = InventoryLedgerService.calculate_safety_stock(
            db=db,
            material_id=material_id,
            days=days,
            safety_factor=safety_factor
        )

        if not success:
            raise HTTPException(status_code=400, detail=msg)

        return APIResponse(code=0, message=msg, data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"安全库存计算异常 | 物料ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"计算失败: {str(e)}")