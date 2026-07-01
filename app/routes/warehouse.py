"""
库房、货架、库位管理接口
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime

from app.database import get_db, beijing_now
from app.models import Warehouse, Shelf, Location
from app.schemas.common import APIResponse, PaginationParams
from app.utils.auth import get_current_user
from collections import defaultdict


class CreateWarehouseRequest(BaseModel):
    """创建库房请求"""
    code: str = Field(..., min_length=1, max_length=50, description="库房编码")
    name: str = Field(..., min_length=1, max_length=100, description="库房名称")
    location: Optional[str] = Field(None, max_length=200, description="位置")
    total_shelves: int = Field(4, ge=1, description="货架数量")


class UpdateWarehouseRequest(BaseModel):
    """更新库房请求"""
    code: Optional[str] = Field(None, min_length=1, max_length=50, description="库房编码")
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="库房名称")
    location: Optional[str] = Field(None, max_length=200, description="位置")
    total_shelves: Optional[int] = Field(None, ge=1, description="货架数量")

router = APIRouter()


# ============================================================================
# 库房管理接口
# ============================================================================

@router.get("/list", summary="获取库房列表（兼容旧接口）")
@router.get("/warehouses", summary="获取库房列表")
async def get_warehouses(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取所有库房信息"""
    try:
        warehouses = db.query(Warehouse).offset(skip).limit(limit).all()
        total = db.query(Warehouse).count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": w.id,
                        "code": w.code,
                        "name": w.name,
                        "warehouse_name": w.name,
                        "location": w.location,
                        "total_shelves": w.total_shelves,
                        "created_at": w.created_at.isoformat() if w.created_at else None
                    } for w in warehouses
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库房列表失败: {str(e)}")


@router.post("", summary="创建库房")
async def create_warehouse(
    req: CreateWarehouseRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """创建新库房"""
    try:
        existing = db.query(Warehouse).filter(Warehouse.code == req.code).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"库房编码 '{req.code}' 已存在")
        warehouse = Warehouse(
            code=req.code,
            name=req.name,
            location=req.location or "",
            total_shelves=req.total_shelves,
        )
        db.add(warehouse)
        db.commit()
        db.refresh(warehouse)
        return APIResponse(code=0, message="创建成功", data={"id": warehouse.id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建库房失败: {str(e)}")


@router.put("/{warehouse_id}", summary="更新库房")
async def update_warehouse(
    warehouse_id: int,
    req: UpdateWarehouseRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """更新库房信息"""
    try:
        warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="库房不存在")
        if req.code is not None:
            existing = db.query(Warehouse).filter(Warehouse.code == req.code, Warehouse.id != warehouse_id).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"库房编码 '{req.code}' 已存在")
            warehouse.code = req.code
        if req.name is not None:
            warehouse.name = req.name
        if req.location is not None:
            warehouse.location = req.location
        if req.total_shelves is not None:
            warehouse.total_shelves = req.total_shelves
        warehouse.updated_at = beijing_now()
        db.commit()
        return APIResponse(code=0, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新库房失败: {str(e)}")


@router.delete("/{warehouse_id}", summary="删除库房")
async def delete_warehouse(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """删除库房（若有货架则禁止删除）"""
    try:
        warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="库房不存在")
        shelf_count = db.query(Shelf).filter(Shelf.warehouse_id == warehouse_id).count()
        if shelf_count > 0:
            raise HTTPException(status_code=400, detail=f"该库房下有 {shelf_count} 个货架，请先删除货架")
        db.delete(warehouse)
        db.commit()
        return APIResponse(code=0, message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除库房失败: {str(e)}")


@router.get("/warehouses/{warehouse_id}", summary="获取库房详情")
async def get_warehouse(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取单个库房详情"""
    try:
        warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="库房不存在")
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": warehouse.id,
                "code": warehouse.code,
                "name": warehouse.name,
                "location": warehouse.location,
                "total_shelves": warehouse.total_shelves,
                "created_at": warehouse.created_at.isoformat() if warehouse.created_at else None,
                "updated_at": warehouse.updated_at.isoformat() if warehouse.updated_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库房详情失败: {str(e)}")


# ============================================================================
# 货架管理接口
# ============================================================================

@router.get("/shelves", summary="获取货架列表")
async def get_shelves(
    warehouse_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取货架列表，可按库房筛选"""
    try:
        query = db.query(Shelf)
        if warehouse_id:
            query = query.filter(Shelf.warehouse_id == warehouse_id)
        
        shelves = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": s.id,
                        "warehouse_id": s.warehouse_id,
                        "code": s.code,
                        "description": s.description,
                        "levels": s.levels,
                        "positions_per_level": s.positions_per_level,
                        "created_at": s.created_at.isoformat() if s.created_at else None
                    } for s in shelves
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取货架列表失败: {str(e)}")


@router.get("/shelves/{shelf_id}", summary="获取货架详情")
async def get_shelf(
    shelf_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取单个货架详情"""
    try:
        shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
        if not shelf:
            raise HTTPException(status_code=404, detail="货架不存在")
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": shelf.id,
                "warehouse_id": shelf.warehouse_id,
                "code": shelf.code,
                "description": shelf.description,
                "levels": shelf.levels,
                "positions_per_level": shelf.positions_per_level,
                "created_at": shelf.created_at.isoformat() if shelf.created_at else None,
                "updated_at": shelf.updated_at.isoformat() if shelf.updated_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取货架详情失败: {str(e)}")


# ============================================================================
# 库位管理接口
# ============================================================================

@router.get("/locations", summary="获取库位列表")
async def get_locations(
    warehouse_id: Optional[int] = Query(None),
    shelf_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    keyword: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取库位列表，可按库房、货架、状态筛选"""
    try:
        query = db.query(Location)
        
        if warehouse_id:
            query = query.filter(Location.warehouse_id == warehouse_id)
        if shelf_id:
            query = query.filter(Location.shelf_id == shelf_id)
        if is_active is not None:
            query = query.filter(Location.is_active == is_active)
        if keyword:
            query = query.join(Shelf, Location.shelf).join(Warehouse, Location.warehouse).filter(
                or_(
                    Location.code.ilike(f"%{keyword}%"),
                    Shelf.code.ilike(f"%{keyword}%"),
                    Warehouse.name.ilike(f"%{keyword}%")
                )
            )
        
        locations = query.offset(skip).limit(limit).all()
        total = query.count()
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "list": [
                    {
                        "id": l.id,
                        "shelf_id": l.shelf_id,
                        "warehouse_id": l.warehouse_id,
                        "code": l.code,
                        "level": l.level,
                        "position": l.position,
                        "capacity": float(l.capacity) if l.capacity else 0.0,
                        "capacity_unit": l.capacity_unit or 'm³',
                        "is_active": l.is_active,
                        "warehouse_name": l.warehouse.name if l.warehouse else None,
                        "shelf_code": l.shelf.code if l.shelf else None,
                        "created_at": l.created_at.isoformat() if l.created_at else None
                    } for l in locations
                ],
                "total": total,
                "skip": skip,
                "limit": limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库位列表失败: {str(e)}")


@router.get("/locations/{location_id}", summary="获取库位详情")
async def get_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取单个库位详情"""
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": location.id,
                "shelf_id": location.shelf_id,
                "warehouse_id": location.warehouse_id,
                "code": location.code,
                "level": location.level,
                "position": location.position,
                "capacity": float(location.capacity) if location.capacity else 0.0,
                "capacity_unit": location.capacity_unit or 'm³',
                "is_active": location.is_active,
                "created_at": location.created_at.isoformat() if location.created_at else None,
                "updated_at": location.updated_at.isoformat() if location.updated_at else None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库位详情失败: {str(e)}")


@router.get("/locations/{location_id}/inventory", summary="获取库位库存")
async def get_location_inventory(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取指定库位的库存信息"""
    try:
        from app.models import Inventory, Material
        
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")
        
        inventories = db.query(Inventory).filter(Inventory.location_id == location_id).all()
        
        inventory_data = []
        for inv in inventories:
            material = db.query(Material).filter(Material.id == inv.material_id).first()
            if material:
                inventory_data.append({
                    "material_id": inv.material_id,
                    "material_name": material.name,
                    "material_code": material.code,
                    "quantity": float(inv.quantity),
                    "unit": material.unit,
                    "updated_at": inv.updated_at.isoformat() if inv.updated_at else None
                })
        
        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "location_code": location.code,
                "inventories": inventory_data
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库位库存失败: {str(e)}")


# ============================================================================
# 库位新增/编辑/删除
# ============================================================================

class CreateLocationRequest(BaseModel):
    """创建库位请求"""
    shelf_id: int = Field(..., description="货架ID")
    warehouse_id: int = Field(..., description="仓库ID")
    code: str = Field(..., min_length=1, max_length=30, description="库位编码")
    level: int = Field(1, ge=1, description="层数")
    position: str = Field("A", max_length=1, description="位置")
    capacity: float = Field(0, ge=0, description="容量（体积）")
    capacity_unit: str = Field('m³', max_length=10, description="容量单位")


class UpdateLocationRequest(BaseModel):
    """更新库位请求"""
    code: Optional[str] = Field(None, min_length=1, max_length=30, description="库位编码")
    capacity: Optional[float] = Field(None, ge=0, description="容量")
    capacity_unit: Optional[str] = Field(None, max_length=10, description="容量单位")
    is_active: Optional[bool] = Field(None, description="是否启用")


@router.post("/locations", summary="创建库位")
async def create_location(
    req: CreateLocationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """创建新库位"""
    try:
        shelf = db.query(Shelf).filter(Shelf.id == req.shelf_id).first()
        if not shelf:
            raise HTTPException(status_code=404, detail="货架不存在")
        warehouse = db.query(Warehouse).filter(Warehouse.id == req.warehouse_id).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="仓库不存在")

        existing = db.query(Location).filter(Location.code == req.code).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"库位编码 '{req.code}' 已存在")

        location = Location(
            shelf_id=req.shelf_id,
            warehouse_id=req.warehouse_id,
            code=req.code,
            level=req.level,
            position=req.position,
            capacity=req.capacity,
        )
        db.add(location)
        db.commit()
        db.refresh(location)
        return APIResponse(code=0, message="创建成功", data={"id": location.id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建库位失败: {str(e)}")


@router.put("/locations/{location_id}", summary="更新库位")
async def update_location(
    location_id: int,
    req: UpdateLocationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """更新库位信息"""
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")

        if req.code is not None:
            existing = db.query(Location).filter(
                Location.code == req.code, Location.id != location_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"库位编码 '{req.code}' 已存在")
            location.code = req.code
        if req.capacity is not None:
            location.capacity = req.capacity
        if req.is_active is not None:
            location.is_active = req.is_active

        db.commit()
        return APIResponse(code=0, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新库位失败: {str(e)}")


@router.delete("/locations/{location_id}", summary="删除库位")
async def delete_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """删除库位（有库存时禁止删除）"""
    try:
        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")

        from app.models import Inventory
        inv_count = db.query(Inventory).filter(Inventory.location_id == location_id).count()
        if inv_count > 0:
            raise HTTPException(status_code=400, detail=f"该库位下有 {inv_count} 种物料库存，请先清空库存再删除")

        db.delete(location)
        db.commit()
        return APIResponse(code=0, message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除库位失败: {str(e)}")


@router.get("/locations/{location_id}/detail", summary="获取库位详情（含空间和库存）")
async def get_location_detail(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取库位详细信息，包括：
    - 库位基本信息
    - 空间使用情况（总容量/已用/可用）
    - 库存物料列表（含分类）
    - 相邻库位
    """
    try:
        from app.models import Inventory, Material, MaterialCategory

        location = db.query(Location).filter(Location.id == location_id).first()
        if not location:
            raise HTTPException(status_code=404, detail="库位不存在")

        # 空间计算
        capacity = float(location.capacity or 0)
        used_space = 0.0
        inventories = db.query(Inventory).filter(Inventory.location_id == location_id).all()
        inventory_list = []
        for inv in inventories:
            material = db.query(Material).filter(Material.id == inv.material_id).first()
            if material:
                unit_vol = float(material.unit_volume or 0)
                qty = float(inv.quantity)
                space_used = unit_vol * qty
                used_space += space_used
                inventory_list.append({
                    "material_id": material.id,
                    "material_name": material.name,
                    "material_code": material.code,
                    "category_name": material.category.name if material.category else None,
                    "quantity": qty,
                    "unit": material.unit,
                    "unit_volume": unit_vol,
                    "volume_unit": material.volume_unit or 'm³',
                    "space_used": space_used,
                })

        # 相邻库位（同一货架邻近层/位）
        neighbor_locations = db.query(Location).filter(
            Location.shelf_id == location.shelf_id,
            Location.id != location_id,
            Location.is_active == True
        ).order_by(Location.level, Location.position).limit(10).all()
        neighbors = [
            {
                "id": nl.id,
                "code": nl.code,
                "level": nl.level,
                "position": nl.position,
                "capacity": float(nl.capacity or 0),
            }
            for nl in neighbor_locations
        ]

        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "id": location.id,
                "shelf_id": location.shelf_id,
                "warehouse_id": location.warehouse_id,
                "code": location.code,
                "level": location.level,
                "position": location.position,
                "capacity": capacity,
                "capacity_unit": location.capacity_unit or 'm³',
                "used_space": used_space,
                "available_space": max(0, capacity - used_space),
                "usage_rate": round(used_space / capacity * 100, 1) if capacity > 0 else 0,
                "is_active": location.is_active,
                "warehouse_name": location.warehouse.name if location.warehouse else None,
                "shelf_code": location.shelf.code if location.shelf else None,
                "inventories": inventory_list,
                "neighbor_locations": neighbors,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取库位详情失败: {str(e)}")


# ============================================================================
# 物料位置分布接口
# ============================================================================

@router.get("/material-distribution", summary="获取物料位置分布数据")
async def get_material_distribution(
    warehouse_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取物料在仓库中的位置分布数据，包括：
    - 各仓库容量使用概览
    - 各货架物料分布
    - 各库位物料明细
    - 物料分类分布
    """
    try:
        from app.models import Inventory, Material, MaterialCategory

        wh_query = db.query(Warehouse).order_by(Warehouse.id)
        if warehouse_id:
            wh_query = wh_query.filter(Warehouse.id == warehouse_id)
        warehouses = wh_query.all()

        warehouse_list = []

        for wh in warehouses:
            locations = db.query(Location).filter(
                Location.warehouse_id == wh.id
            ).order_by(Location.code).all()

            loc_ids = [loc.id for loc in locations]

            inventories = db.query(Inventory).filter(
                Inventory.location_id.in_(loc_ids)
            ).all() if loc_ids else []

            inv_by_loc = defaultdict(list)
            for inv in inventories:
                inv_by_loc[inv.location_id].append(inv)

            total_capacity = 0.0
            total_used_space = 0.0
            material_ids = set()
            category_ids = set()
            shelf_data = defaultdict(lambda: {
                "capacity": 0.0, "used_space": 0.0,
                "location_count": 0, "material_ids": set(),
                "levels": defaultdict(lambda: {"capacity": 0.0, "used_space": 0.0, "location_count": 0})
            })
            loc_details = []

            for loc in locations:
                cap = float(loc.capacity or 0)
                total_capacity += cap

                loc_inv = inv_by_loc.get(loc.id, [])
                loc_used = 0.0
                loc_materials = []

                for inv in loc_inv:
                    mat = db.query(Material).filter(Material.id == inv.material_id).first()
                    if mat:
                        unit_vol = float(mat.unit_volume or 0)
                        qty = float(inv.quantity)
                        space = unit_vol * qty
                        loc_used += space
                        total_used_space += space
                        material_ids.add(mat.id)
                        if mat.category_id:
                            category_ids.add(mat.category_id)
                        shelf_data[loc.shelf_id]["material_ids"].add(mat.id)
                        loc_materials.append({
                            "material_id": mat.id,
                            "material_code": mat.code,
                            "material_name": mat.name,
                            "category_name": mat.category.name if mat.category else None,
                            "quantity": qty,
                            "unit": mat.unit,
                            "unit_volume": unit_vol,
                            "volume_unit": mat.volume_unit or 'm³',
                            "space_used": space,
                        })

                shelf_data[loc.shelf_id]["capacity"] += cap
                shelf_data[loc.shelf_id]["used_space"] += loc_used
                shelf_data[loc.shelf_id]["location_count"] += 1
                shelf_data[loc.shelf_id]["levels"][loc.level]["capacity"] += cap
                shelf_data[loc.shelf_id]["levels"][loc.level]["used_space"] += loc_used
                shelf_data[loc.shelf_id]["levels"][loc.level]["location_count"] += 1

                loc_details.append({
                    "location_id": loc.id,
                    "location_code": loc.code,
                    "shelf_id": loc.shelf_id,
                    "level": loc.level,
                    "position": loc.position,
                    "capacity": cap,
                    "capacity_unit": loc.capacity_unit or 'm³',
                    "used_space": loc_used,
                    "available_space": max(0, cap - loc_used),
                    "usage_rate": round(loc_used / cap * 100, 1) if cap > 0 else 0,
                    "materials": loc_materials,
                    "material_count": len(loc_materials),
                })

            shelves = db.query(Shelf).filter(Shelf.warehouse_id == wh.id).all()
            shelf_list = []
            for s in shelves:
                sd = shelf_data.get(s.id, {})
                levels_dict = sd.get("levels", {})
                shelf_list.append({
                    "shelf_id": s.id,
                    "shelf_code": s.code,
                    "location_count": sd.get("location_count", 0),
                    "capacity": sd.get("capacity", 0.0),
                    "used_space": sd.get("used_space", 0.0),
                    "usage_rate": round(sd["used_space"] / sd["capacity"] * 100, 1) if sd.get("capacity", 0) > 0 else 0,
                    "material_count": len(sd.get("material_ids", set())),
                    "levels": [
                        {
                            "level": lv,
                            "capacity": ld["capacity"],
                            "used_space": ld["used_space"],
                            "available_space": max(0, ld["capacity"] - ld["used_space"]),
                            "usage_rate": round(ld["used_space"] / ld["capacity"] * 100, 1) if ld["capacity"] > 0 else 0,
                            "location_count": ld["location_count"],
                        }
                        for lv, ld in sorted(levels_dict.items())
                    ],
                })

            # 分类分布
            cat_dist = defaultdict(lambda: {
                "material_count": 0, "location_count": 0, "total_quantity": 0.0
            })
            for inv in inventories:
                mat = db.query(Material).filter(Material.id == inv.material_id).first()
                if mat and mat.category:
                    key = mat.category.name
                    cat_dist[key]["material_count"] += 1
                    cat_dist[key]["total_quantity"] += float(inv.quantity)
            for loc_inv_list in inv_by_loc.values():
                loc_cats = set()
                for inv in loc_inv_list:
                    mat = db.query(Material).filter(Material.id == inv.material_id).first()
                    if mat and mat.category:
                        loc_cats.add(mat.category.name)
                for c in loc_cats:
                    cat_dist[c]["location_count"] += 1

            category_distribution = [
                {"category_name": k, **v}
                for k, v in sorted(cat_dist.items(), key=lambda x: -x[1]["total_quantity"])
            ]

            usage_rate = round(total_used_space / total_capacity * 100, 1) if total_capacity > 0 else 0

            warehouse_list.append({
                "id": wh.id,
                "name": wh.name,
                "code": wh.code,
                "total_capacity": total_capacity,
                "total_used_space": total_used_space,
                "available_space": max(0, total_capacity - total_used_space),
                "usage_rate": usage_rate,
                "material_count": len(material_ids),
                "category_count": len(category_ids),
                "location_count": len(locations),
                "shelf_count": len(shelves),
                "shelves": shelf_list,
                "category_distribution": category_distribution,
                "locations": loc_details,
            })

        total_cap_all = sum(w["total_capacity"] for w in warehouse_list)
        total_used_all = sum(w["total_used_space"] for w in warehouse_list)
        total_mat_all = sum(w["material_count"] for w in warehouse_list)

        return APIResponse(
            code=0,
            message="获取成功",
            data={
                "warehouses": warehouse_list,
                "summary": {
                    "warehouse_count": len(warehouse_list),
                    "total_capacity": total_cap_all,
                    "total_used_space": total_used_all,
                    "available_space": max(0, total_cap_all - total_used_all),
                    "usage_rate": round(total_used_all / total_cap_all * 100, 1) if total_cap_all > 0 else 0,
                    "total_materials": total_mat_all,
                },
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取物料分布失败: {str(e)}")


# ============================================================================
# 按分类整理库存 — 同分类物料放到同一货架的相邻库位
# ============================================================================

@router.post("/reorganize-by-category", summary="按分类整理库存位置")
async def reorganize_by_category(
    warehouse_id: Optional[int] = Query(None, description="指定仓库（不传则整理所有仓库）"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    将所有库存按物料分类重新整理到同一货架的相邻库位：
    - 同分类物料集中到同一货架
    - 优先使用已有同分类物料的货架
    - 相同物料尽量合并到同一库位
    """
    try:
        from app.models import Inventory, Material, MaterialCategory, InventoryLedger
        from datetime import datetime
        import math

        # 加载所有库存
        query = db.query(Inventory, Material, Location).join(
            Material, Inventory.material_id == Material.id
        ).join(
            Location, Inventory.location_id == Location.id
        ).filter(
            Inventory.quantity > 0
        )
        if warehouse_id:
            query = query.filter(Location.warehouse_id == warehouse_id)

        all_inventory = query.all()

        if not all_inventory:
            return APIResponse(code=0, message="没有需要整理的库存", data={"moved": 0, "details": []})

        # 按分类分组
        cat_groups = defaultdict(list)
        for inv, mat, loc in all_inventory:
            cat_groups[mat.category_id].append((inv, mat, loc))

        moved_count = 0
        move_details = []

        # 预加载货架编码
        all_shelves = db.query(Shelf).all()
        shelf_code_map = {s.id: s.code for s in all_shelves}

        for cat_id, items in cat_groups.items():
            category = db.query(MaterialCategory).filter(MaterialCategory.id == cat_id).first()
            cat_name = category.name if category else f"分类#{cat_id}"

            # 找该分类下的物料涉及的仓库/货架分布
            warehouse_shelf_items = defaultdict(lambda: defaultdict(list))
            for inv, mat, loc in items:
                warehouse_shelf_items[loc.warehouse_id][loc.shelf_id].append((inv, mat, loc))

            # 对每个仓库分别整理
            for wh_id, shelf_items in warehouse_shelf_items.items():
                # 挑选目标货架：已有该分类物料最多的货架
                target_shelf_id = None
                max_count = 0
                for sid, sitems in shelf_items.items():
                    total_qty = sum(float(inv.quantity) for inv, mat, loc in sitems)
                    if total_qty > max_count:
                        max_count = total_qty
                        target_shelf_id = sid

                if not target_shelf_id:
                    continue

                # 获取目标货架的所有可用库位
                target_locations = db.query(Location).filter(
                    Location.shelf_id == target_shelf_id,
                    Location.is_active == True
                ).order_by(Location.level, Location.position).all()

                # 计算每个库位的可用空间
                loc_available = {}
                for tl in target_locations:
                    cap = float(tl.capacity or 0)
                    used = 0.0
                    for inv, mat, loc in items:
                        if loc.id == tl.id:
                            used += float(mat.unit_volume or 0) * float(inv.quantity)
                    loc_available[tl.id] = {
                        "capacity": cap,
                        "used": used,
                        "available": max(0, cap - used),
                        "location": tl,
                    }

                # 将不在目标货架上的物料移到目标货架的可用库位
                for inv, mat, loc in items:
                    if loc.shelf_id == target_shelf_id:
                        continue  # 已经在目标货架上

                    # 找目标货架上有空间的库位（优先选已有同物料的）
                    target_loc_id = None
                    target_loc_obj = None

                    # 先看是否有库位已经放了同种物料且有空间
                    for tl in target_locations:
                        if float(tl.capacity or 0) == 0:
                            target_loc_id = tl.id
                            target_loc_obj = tl
                            break
                        avail = loc_available[tl.id]["available"]
                        need = float(mat.unit_volume or 0) * float(inv.quantity)
                        if avail >= need:
                            target_loc_id = tl.id
                            target_loc_obj = tl
                            break

                    if not target_loc_obj:
                        continue  # 没有可用库位，跳过

                    old_loc_code = loc.code
                    new_loc_code = target_loc_obj.code

                    # 检查目标库位是否已有同种物料
                    existing = db.query(Inventory).filter(
                        Inventory.material_id == inv.material_id,
                        Inventory.location_id == target_loc_id,
                        Inventory.id != inv.id
                    ).first()

                    old_quantity = float(inv.quantity)

                    if existing:
                        # 合并到已有记录
                        existing.quantity = float(existing.quantity) + old_quantity
                        existing.updated_at = beijing_now()
                        # 删除原记录
                        db.delete(inv)
                        moved_inv_id = existing.id
                    else:
                        # 直接移动
                        inv.location_id = target_loc_id
                        inv.updated_at = beijing_now()
                        moved_inv_id = inv.id

                    move_details.append({
                        "material_id": mat.id,
                        "material_code": mat.code,
                        "material_name": mat.name,
                        "quantity": old_quantity,
                        "from_location": old_loc_code,
                        "to_location": new_loc_code,
                        "shelf_code": shelf_code_map.get(target_shelf_id, ""),
                    })
                    moved_count += 1

                # 同分类下同物料合并到同一库位
                # 收集目标货架上每个物料ID对应的所有库存
                shelf_mat_inv = defaultdict(list)
                for inv, mat, loc in items:
                    shelf_mat_inv[mat.id].append((inv, mat, loc))

                for mat_id, mat_items in shelf_mat_inv.items():
                    if len(mat_items) <= 1:
                        continue
                    # 保留一条记录，其余合并
                    kept = mat_items[0]
                    kept_inv, kept_mat, kept_loc = kept
                    for extra_inv, extra_mat, extra_loc in mat_items[1:]:
                        if extra_inv.id != kept_inv.id:
                            kept_inv.quantity = float(kept_inv.quantity) + float(extra_inv.quantity)
                            db.delete(extra_inv)
                    kept_inv.updated_at = beijing_now()

        db.commit()

        return APIResponse(
            code=0,
            message=f"整理完成，共移动 {moved_count} 条库存记录",
            data={
                "moved": moved_count,
                "details": move_details[:200],  # 最多返回200条
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"整理库存失败: {str(e)}")