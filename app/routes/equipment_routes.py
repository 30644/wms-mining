from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db, beijing_now
from app.models import Equipment, EquipmentSparePart, Material
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.utils.business_tools import PermissionService
from app.utils.logger import logger

router = APIRouter()


class CreateEquipmentRequest(BaseModel):
    code: str = Field(..., max_length=50, description="设备编码")
    name: str = Field(..., max_length=100, description="设备名称")
    model: Optional[str] = Field(None, max_length=100, description="设备型号")
    location_desc: Optional[str] = Field(None, max_length=200, description="安装位置")
    status: Optional[str] = Field("running", description="运行状态")
    description: Optional[str] = Field(None, description="设备描述")


class UpdateEquipmentRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="设备名称")
    model: Optional[str] = Field(None, max_length=100, description="设备型号")
    location_desc: Optional[str] = Field(None, max_length=200, description="安装位置")
    status: Optional[str] = Field(None, description="运行状态")
    description: Optional[str] = Field(None, description="设备描述")


class AddSparePartRequest(BaseModel):
    material_id: int = Field(..., description="物料ID")
    quantity: int = Field(1, ge=1, description="用量")
    remark: Optional[str] = Field(None, max_length=200, description="备注")


@router.get("", summary="获取设备列表")
async def list_equipment(
    search: Optional[str] = Query(None, description="设备名称/编码搜索"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")

        query = db.query(Equipment)
        if search:
            query = query.filter(
                Equipment.name.contains(search) | Equipment.code.contains(search)
            )
        total = query.count()
        equipments = query.order_by(Equipment.id.desc()).offset(skip).limit(limit).all()

        return APIResponse(code=0, message="获取成功", data={
            "list": [
                {
                    "id": e.id,
                    "code": e.code,
                    "name": e.name,
                    "model": e.model,
                    "location_desc": e.location_desc,
                    "status": e.status,
                    "description": e.description,
                    "created_by": e.created_by,
                    "creator_name": e.creator.real_name if e.creator else None,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "updated_at": e.updated_at.isoformat() if e.updated_at else None,
                    "spare_count": len(e.spare_parts),
                }
                for e in equipments
            ],
            "total": total,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"获取设备列表异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"获取设备列表失败: {str(exc)}")


@router.post("", summary="新增设备")
async def create_equipment(
    req: CreateEquipmentRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:add", db):
            raise HTTPException(status_code=403, detail="无权限")

        existing = db.query(Equipment).filter(Equipment.code == req.code).first()
        if existing:
            raise HTTPException(status_code=400, detail="设备编码已存在")

        equip = Equipment(
            code=req.code,
            name=req.name,
            model=req.model,
            location_desc=req.location_desc,
            status=req.status or "running",
            description=req.description,
            created_by=current_user.id,
        )
        db.add(equip)
        db.commit()
        db.refresh(equip)
        return APIResponse(code=0, message="创建成功", data={"id": equip.id})
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"新增设备异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"新增设备失败: {str(exc)}")


@router.get("/{equipment_id}", summary="获取设备详情（含备件列表）")
async def get_equipment(
    equipment_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:view", db):
            raise HTTPException(status_code=403, detail="无权限")

        equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equip:
            raise HTTPException(status_code=404, detail="设备不存在")

        spare_parts = []
        for sp in equip.spare_parts:
            spare_parts.append({
                "id": sp.id,
                "material_id": sp.material_id,
                "material_code": sp.material.code if sp.material else None,
                "material_name": sp.material.name if sp.material else None,
                "specification": sp.material.specification if sp.material else None,
                "unit": sp.material.unit if sp.material else None,
                "quantity": sp.quantity,
                "remark": sp.remark,
            })

        return APIResponse(code=0, message="获取成功", data={
            "id": equip.id,
            "code": equip.code,
            "name": equip.name,
            "model": equip.model,
            "location_desc": equip.location_desc,
            "status": equip.status,
            "description": equip.description,
            "created_by": equip.created_by,
            "creator_name": equip.creator.real_name if equip.creator else None,
            "created_at": equip.created_at.isoformat() if equip.created_at else None,
            "updated_at": equip.updated_at.isoformat() if equip.updated_at else None,
            "spare_parts": spare_parts,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"获取设备详情异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"获取设备详情失败: {str(exc)}")


@router.put("/{equipment_id}", summary="更新设备信息")
async def update_equipment(
    req: UpdateEquipmentRequest,
    equipment_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:edit", db):
            raise HTTPException(status_code=403, detail="无权限")

        equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equip:
            raise HTTPException(status_code=404, detail="设备不存在")

        if req.name is not None:
            equip.name = req.name
        if req.model is not None:
            equip.model = req.model
        if req.location_desc is not None:
            equip.location_desc = req.location_desc
        if req.status is not None:
            equip.status = req.status
        if req.description is not None:
            equip.description = req.description
        equip.updated_at = beijing_now()

        db.commit()
        return APIResponse(code=0, message="更新成功")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"更新设备异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"更新设备失败: {str(exc)}")


@router.delete("/{equipment_id}", summary="删除设备")
async def delete_equipment(
    equipment_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:delete", db):
            raise HTTPException(status_code=403, detail="无权限")

        equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equip:
            raise HTTPException(status_code=404, detail="设备不存在")

        db.delete(equip)
        db.commit()
        return APIResponse(code=0, message="删除成功")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"删除设备异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"删除设备失败: {str(exc)}")


@router.post("/{equipment_id}/spare-parts", summary="添加备件关联")
async def add_spare_part(
    req: AddSparePartRequest,
    equipment_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:edit", db):
            raise HTTPException(status_code=403, detail="无权限")

        equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equip:
            raise HTTPException(status_code=404, detail="设备不存在")

        material = db.query(Material).filter(Material.id == req.material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="物料不存在")

        existing = db.query(EquipmentSparePart).filter(
            EquipmentSparePart.equipment_id == equipment_id,
            EquipmentSparePart.material_id == req.material_id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="该备件已关联到此设备")

        sp = EquipmentSparePart(
            equipment_id=equipment_id,
            material_id=req.material_id,
            quantity=req.quantity,
            remark=req.remark,
        )
        db.add(sp)
        db.commit()
        db.refresh(sp)
        return APIResponse(code=0, message="添加成功", data={"id": sp.id})
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"添加备件关联异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"添加备件关联失败: {str(exc)}")


@router.delete("/spare-parts/{part_id}", summary="删除备件关联")
async def delete_spare_part(
    part_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        if not PermissionService.check_permission(current_user.id, "equipment:edit", db):
            raise HTTPException(status_code=403, detail="无权限")

        sp = db.query(EquipmentSparePart).filter(EquipmentSparePart.id == part_id).first()
        if not sp:
            raise HTTPException(status_code=404, detail="备件关联不存在")

        db.delete(sp)
        db.commit()
        return APIResponse(code=0, message="删除成功")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"删除备件关联异常 | 错误: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"删除备件关联失败: {str(exc)}")
