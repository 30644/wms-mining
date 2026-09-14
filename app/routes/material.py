"""
物资档案完整业务API层
- 物资增删改查
- 分类管理
- 库存上下限预警
- 物料信息同步接口
"""
from typing import List, Optional
import base64
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path, status, File, UploadFile
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import datetime

from app.database import get_db, beijing_now
from app.models import Material, MaterialCategory, MaterialAlias, Inventory, User
from app.schemas.common import APIResponse, PaginationParams
from app.utils.auth import get_current_user
from app.services.material_service import MaterialService, MaterialCategoryService
from app.services.ai_service import AISearchService
from app.utils.business_tools import PermissionService, OperationLog
from app.utils.logger import logger

router = APIRouter()


# ============================================================================
# 数据模型定义
# ============================================================================

class MaterialCategoryCreate(BaseModel):
    """创建物资分类请求"""
    name: str = Field(..., description="分类名称", min_length=1, max_length=50)
    code: Optional[str] = Field(None, description="分类编码", max_length=20)
    description: Optional[str] = Field(None, description="分类描述", max_length=500)
    inspector_role: Optional[str] = Field(None, description="验收员角色", max_length=30)
    is_active: Optional[bool] = Field(True, description="是否启用")

    class Config:
        schema_extra = {
            "example": {
                "name": "保养耗材",
                "code": "MC001",
                "description": "设备保养耗材",
                "inspector_role": "mechanical_inspector",
                "is_active": True
            }
        }


class MaterialCategoryUpdate(BaseModel):
    """更新物资分类请求"""
    name: Optional[str] = Field(None, description="分类名称", min_length=1, max_length=50)
    code: Optional[str] = Field(None, description="分类编码", max_length=20)
    description: Optional[str] = Field(None, description="分类描述", max_length=500)
    inspector_role: Optional[str] = Field(None, description="验收员角色", max_length=30)
    is_active: Optional[bool] = Field(None, description="是否启用")


class MaterialCreate(BaseModel):
    """创建物资请求"""
    category_id: int = Field(..., description="分类ID")
    name: str = Field(..., description="物资名称", min_length=1, max_length=100)
    code: Optional[str] = Field(None, description="物资编码", max_length=50)
    specification: Optional[str] = Field(None, description="规格", max_length=100)
    model: Optional[str] = Field(None, description="型号", max_length=100)
    unit: str = Field("件", description="计量单位", max_length=20)
    description: Optional[str] = Field(None, description="物资描述", max_length=500)
    safety_stock: float = Field(0.0, description="安全库存量", ge=0)
    warning_threshold: float = Field(0.0, description="库存预警阈值", ge=0)
    lead_time_days: int = Field(0, description="采购到货时间（天）", ge=0)
    max_per_request: Optional[float] = Field(None, description="单次最大领用量", gt=0)
    nc_code: Optional[str] = Field(None, description="NC物资编码", max_length=50)
    unit_volume: float = Field(0.001, description="单件体积（m³），用于库位空间计算", ge=0)
    volume_unit: str = Field("m³", description="体积单位", max_length=10)
    
    class Config:
        schema_extra = {
            "example": {
                "category_id": 1,
                "name": "液压油",
                "code": "MAT001",
                "specification": "32号",
                "model": "标准型",
                "unit": "升",
                "safety_stock": 100.0,
                "warning_threshold": 50.0,
                "max_per_request": 1000.0,
                "nc_code": "NC001"
            }
        }


class MaterialUpdate(BaseModel):
    """修改物资请求"""
    name: Optional[str] = Field(None, description="物资名称", min_length=1, max_length=100)
    code: Optional[str] = Field(None, description="物资编码", max_length=50)
    specification: Optional[str] = Field(None, description="规格", max_length=100)
    model: Optional[str] = Field(None, description="型号", max_length=100)
    unit: Optional[str] = Field(None, description="计量单位", max_length=20)
    description: Optional[str] = Field(None, description="物资描述", max_length=500)
    safety_stock: Optional[float] = Field(None, description="安全库存量", ge=0)
    warning_threshold: Optional[float] = Field(None, description="库存预警阈值", ge=0)
    lead_time_days: Optional[int] = Field(None, description="采购到货时间（天）", ge=0)
    max_per_request: Optional[float] = Field(None, description="单次最大领用量", gt=0)
    nc_code: Optional[str] = Field(None, description="NC物资编码", max_length=50)
    unit_volume: Optional[float] = Field(None, description="单件体积（m³），用于库位空间计算", ge=0)
    volume_unit: Optional[str] = Field(None, description="体积单位", max_length=10)
    is_active: Optional[bool] = Field(None, description="是否启用")


# ============================================================================
# 物资分类管理接口
# ============================================================================

@router.post("/categories", summary="创建物资分类", status_code=status.HTTP_201_CREATED)
async def create_category(
    request: MaterialCategoryCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    创建物资分类
    
    权限要求：warehouse_manager或super_admin
    """
    try:
        # 权限检查
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            logger.warning(f"无权限创建物资分类 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg, category = MaterialCategoryService.create_category(
            name=request.name,
            code=request.code,
            description=request.description,
            inspector_role=request.inspector_role,
            created_by=current_user.id,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        
        return APIResponse(
            code=0,
            message="物资分类创建成功",
            data={
                "id": category.id,
                "name": category.name,
                "code": category.code,
                "description": category.description
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建物资分类异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建物资分类失败: {str(e)}")


@router.get("/categories", summary="获取物资分类列表")
async def get_categories(
    is_active: Optional[bool] = Query(True, description="是否启用"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资分类列表"""
    try:
        categories = MaterialCategoryService.get_category_list(is_active=is_active, db=db)
        
        return APIResponse(
            code=0,
            message="获取物资分类列表成功",
            data=categories
        )
    
    except Exception as e:
        logger.error(f"获取物资分类列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取物资分类列表失败: {str(e)}")


@router.put("/categories/{category_id}", summary="更新物资分类")
async def update_category(
    category_id: int = Path(..., description="分类ID"),
    request: MaterialCategoryUpdate = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """更新物资分类"""
    try:
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            logger.warning(f"无权限更新物资分类 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg, category = MaterialCategoryService.update_category(
            category_id=category_id,
            name=request.name,
            code=request.code,
            description=request.description,
            inspector_role=request.inspector_role,
            is_active=request.is_active,
            updated_by=current_user.id,
            db=db
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(
            code=0,
            message="物资分类更新成功",
            data={
                "id": category.id,
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "is_active": category.is_active
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新物资分类异常 | 分类ID: {category_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新物资分类失败: {str(e)}")


@router.delete("/categories/{category_id}", summary="删除物资分类")
async def delete_category(
    category_id: int = Path(..., description="分类ID"),
    cascade: bool = Query(False, description="是否同时删除分类下所有物料"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """删除物资分类"""
    try:
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            logger.warning(f"无权限删除物资分类 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        success, msg = MaterialCategoryService.delete_category(
            category_id=category_id,
            deleted_by=current_user.id,
            db=db,
            cascade=cascade
        )

        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

        return APIResponse(
            code=0,
            message=msg
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除物资分类异常 | 分类ID: {category_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除物资分类失败: {str(e)}")


# AI智能搜索接口
# ============================================================================

class AISearchRequest(BaseModel):
    keyword: str

@router.post("/ai-search", summary="AI语义搜索物料")
async def ai_search_materials(
    request: AISearchRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """AI扩展同义词后搜索物料"""
    try:
        keyword = request.keyword.strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="请输入搜索关键词")

        # AI扩展同义词
        terms = AISearchService.expand_search_query(keyword)

        # 搜索所有相关物料
        materials, _ = MaterialService.get_material_list(
            search=keyword,
            page=1,
            page_size=50,
            db=db
        )
        seen_ids = {m["id"] for m in materials}

        # 逐一搜索扩展词并缓存别名
        for term in terms:
            if term == keyword:
                continue
            matched, _ = MaterialService.get_material_list(
                search=term,
                page=1,
                page_size=50,
                db=db
            )
            for m in matched:
                if m["id"] not in seen_ids:
                    seen_ids.add(m["id"])
                    materials.append(m)
                AISearchService.cache_aliases(m["id"], term, db)

        return APIResponse(
            code=0,
            message=f"AI搜索完成，共找到{len(materials)}个物料",
            data={"list": materials, "total": len(materials), "ai_expanded": terms}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI搜索异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI搜索失败: {str(e)}")


@router.post("/image-search", summary="AI图片识别搜索物料")
async def image_search_materials(
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """上传图片，AI识别物料后搜索"""
    try:
        if file:
            image_bytes = await file.read()
            if len(image_bytes) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="图片大小不能超过10MB")
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        else:
            raise HTTPException(status_code=400, detail="请上传图片文件")

        # AI识别关键词（最多5个）
        keywords = AISearchService.identify_keywords_from_image(image_b64)
        if not keywords:
            identified_name = AISearchService.identify_material_from_image(image_bytes)
            keywords = [identified_name] if identified_name else []

        if not keywords:
            raise HTTPException(status_code=400, detail="AI识别失败，请重试或使用文字搜索")

        # 用第一个关键词搜索
        materials, total = MaterialService.get_material_list(
            search=keywords[0],
            page=1,
            page_size=50,
            db=db
        )

        return APIResponse(
            code=0,
            message=f"AI识别完成，共{len(keywords)}个关键词",
            data={
                "list": materials,
                "total": total,
                "identified_name": keywords[0],
                "keywords": keywords,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"图片搜索异常: {str(e)}")
        raise HTTPException(status_code=500, detail=f"图片搜索失败: {str(e)}")


# ============================================================================


# ============================================================================
# 物资档案管理接口
# ============================================================================

@router.post("", summary="创建物资档案", status_code=status.HTTP_201_CREATED)
async def create_material(
    request: MaterialCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    创建物资档案
    
    权限要求：warehouse_manager或super_admin
    """
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "material:create", db):
            logger.warning(f"无权限创建物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg, material = MaterialService.create_material(
            category_id=request.category_id,
            name=request.name,
            unit=request.unit,
            code=request.code,
            specification=request.specification,
            model=request.model,
            description=request.description,
            safety_stock=request.safety_stock,
            warning_threshold=request.warning_threshold,
            lead_time_days=request.lead_time_days,
            max_per_request=request.max_per_request,
            nc_code=request.nc_code,
            unit_volume=request.unit_volume,
            volume_unit=request.volume_unit,
            created_by=current_user.id,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        
        return APIResponse(
            code=0,
            message="物资档案创建成功",
            data=MaterialService.get_material_by_id(material.id, db)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建物资档案异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建物资档案失败: {str(e)}")


@router.get("", summary="获取物资档案列表")
@router.get("/list", summary="获取物资档案列表")
async def get_materials(
    category_id: Optional[int] = Query(None, description="分类ID"),
    is_active: Optional[bool] = Query(True, description="是否启用"),
    search: Optional[str] = Query(None, description="搜索关键词（名称/编码）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资档案列表（分页、多条件筛选）"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "material:view", db):
            logger.warning(f"无权限查看物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        materials, total = MaterialService.get_material_list(
            category_id=category_id,
            is_active=is_active,
            search=search,
            page=page,
            page_size=page_size,
            db=db
        )
        
        return APIResponse(
            code=0,
            message="获取物资档案列表成功",
            data={
                "list": materials,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取物资档案列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取物资档案列表失败: {str(e)}")


@router.get("/code/{code}", summary="根据物资编码获取物资档案")
async def get_material_by_code(
    code: str = Path(..., description="物资编码"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """根据物资编码获取物资档案"""
    try:
        if not PermissionService.check_permission(current_user.id, "material:view", db):
            logger.warning(f"无权限查看物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        material = MaterialService.get_material_by_code(code, db)
        if not material:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="物资不存在")

        return APIResponse(
            code=0,
            message="获取物资档案成功",
            data=material
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"根据物资编码获取物资档案异常 | 编码: {code} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取物资档案失败: {str(e)}")


@router.get("/export", summary="导出物资档案")
async def export_materials(
    category_id: Optional[int] = Query(None, description="分类ID"),
    is_active: Optional[bool] = Query(True, description="是否启用"),
    search: Optional[str] = Query(None, description="搜索关键词（名称/编码）"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """导出物资档案为 CSV 文件"""
    try:
        if not PermissionService.check_permission(current_user.id, "material:view", db):
            logger.warning(f"无权限导出物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        materials, _ = MaterialService.get_material_list(
            category_id=category_id,
            is_active=is_active,
            search=search,
            page=1,
            page_size=10000,
            db=db
        )

        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID",
            "名称",
            "编码",
            "分类ID",
            "分类名称",
            "规格",
            "型号",
            "单位",
            "描述",
            "安全库存",
            "预警阈值",
            "最大领用量",
            "NC编码",
            "启用状态",
            "创建时间"
        ])

        for item in materials:
            writer.writerow([
                item.get("id"),
                item.get("name"),
                item.get("code"),
                item.get("category_id"),
                item.get("category_name"),
                item.get("specification"),
                item.get("model"),
                item.get("unit"),
                item.get("description"),
                item.get("safety_stock"),
                item.get("warning_threshold"),
                item.get("max_per_request"),
                item.get("nc_code"),
                "启用" if item.get("is_active") else "禁用",
                item.get("created_at")
            ])

        output.seek(0)
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=materials_export.csv"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出物资档案异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导出物资档案失败: {str(e)}")


@router.post("/import", summary="导入物资档案")
async def import_materials(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """从 CSV 文件导入物资档案"""
    try:
        if not PermissionService.check_permission(current_user.id, "material:create", db):
            logger.warning(f"无权限导入物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        if not file.filename.lower().endswith(".csv") and file.content_type != "text/csv":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 CSV 文件导入")

        import csv
        import io

        content = await file.read()
        reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

        imported = 0
        failed = 0
        errors = []
        for idx, row in enumerate(reader, start=1):
            try:
                category_id = int(row.get("category_id") or row.get("分类ID") or 0)
                name = row.get("name") or row.get("名称")
                if not category_id or not name:
                    raise ValueError("缺少 category_id 或 name")

                safety_stock = float(row.get("safety_stock") or row.get("安全库存") or 0)
                warning_threshold = float(row.get("warning_threshold") or row.get("预警阈值") or 0)
                max_per_request = row.get("max_per_request") or row.get("最大领用量")
                max_per_request = float(max_per_request) if max_per_request else None

                success, msg, _ = MaterialService.create_material(
                    category_id=category_id,
                    name=name,
                    unit=row.get("unit") or row.get("单位") or "件",
                    code=row.get("code") or row.get("编码"),
                    specification=row.get("specification") or row.get("规格"),
                    model=row.get("model") or row.get("型号"),
                    description=row.get("description") or row.get("描述"),
                    safety_stock=safety_stock,
                    warning_threshold=warning_threshold,
                    max_per_request=max_per_request,
                    nc_code=row.get("nc_code") or row.get("NC编码"),
                    unit_volume=float(row.get("unit_volume") or row.get("单件体积") or 0),
                    volume_unit=row.get("volume_unit") or row.get("体积单位") or "m³",
                    created_by=current_user.id,
                    db=db
                )
                if success:
                    imported += 1
                else:
                    failed += 1
                    errors.append({"row": idx, "error": msg})
            except Exception as item_err:
                failed += 1
                errors.append({"row": idx, "error": str(item_err)})

        return APIResponse(
            code=0,
            message="物资导入完成",
            data={"imported": imported, "failed": failed, "errors": errors}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入物资档案异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入物资档案失败: {str(e)}")


@router.get("/emergency", summary="获取应急物资列表（低于安全库存）")
async def get_emergency_materials(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """返回库存量 < 安全库存 且 安全库存>0 的物料，用于应急物资管理"""
    try:
        materials = db.query(Material).filter(Material.is_active == True).all()
        result = []
        for m in materials:
            safety = float(m.safety_stock or 0)
            if safety <= 0:
                continue  # 未设置安全库存的物料不列入应急
            total_qty = float(
                db.query(func.coalesce(func.sum(Inventory.quantity), 0))
                .filter(Inventory.material_id == m.id)
                .scalar()
            )
            if total_qty >= safety:
                continue  # 库存充足，无需应急

            # 获取仓库、库位、仓库ID
            inv = db.query(Inventory).filter(Inventory.material_id == m.id).first()
            warehouse_name = ""
            location_code = ""
            warehouse_id = None
            if inv and inv.location:
                location_code = inv.location.code or ""
                if inv.location.warehouse:
                    warehouse_name = inv.location.warehouse.name or ""
                    warehouse_id = inv.location.warehouse.id

            result.append({
                "id": m.id,
                "code": m.code or "",
                "name": m.name,
                "specification": m.specification or "",
                "unit": m.unit,
                "stock_quantity": total_qty,
                "emergency_threshold": safety,
                "category_name": m.category.name if m.category else "",
                "warehouse_id": warehouse_id,
                "warehouse_name": warehouse_name,
                "location_code": location_code,
            })
        return APIResponse(code=0, message="获取成功", data={"list": result, "total": len(result)})
    except Exception as e:
        logger.error(f"获取应急物资异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{material_id}", summary="获取物资档案详情")
async def get_material_detail(
    material_id: int = Path(..., description="物资ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资档案详情"""
    try:
        if not PermissionService.check_permission(current_user.id, "material:view", db):
            logger.warning(f"无权限查看物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        material = MaterialService.get_material_by_id(material_id, db)
        if not material:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="物资不存在")
        warning_info = MaterialService.check_inventory_warning(material_id, db)
        return APIResponse(
            code=0, message="获取物资档案详情成功",
            data={**material, "inventory_warning": warning_info}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取物资档案详情异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取物资档案详情失败: {str(e)}")


@router.put("/{material_id}", summary="修改物资档案")
async def update_material(
    material_id: int = Path(..., description="物资ID"),
    request: MaterialUpdate = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """修改物资档案"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "material:update", db):
            logger.warning(f"无权限修改物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg, material = MaterialService.update_material(
            material_id=material_id,
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
            unit_volume=request.unit_volume,
            volume_unit=request.volume_unit,
            is_active=request.is_active,
            updated_by=current_user.id,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        
        return APIResponse(
            code=0,
            message="物资档案修改成功",
            data=MaterialService.get_material_by_id(material_id, db)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改物资档案异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"修改物资档案失败: {str(e)}")


@router.delete("/{material_id}", summary="删除物资档案")
async def delete_material(
    material_id: int = Path(..., description="物资ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """删除物资档案（逻辑删除）"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "material:delete", db):
            logger.warning(f"无权限删除物资档案 | 用户ID: {current_user.id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        success, msg = MaterialService.delete_material(
            material_id=material_id,
            deleted_by=current_user.id,
            db=db
        )
        
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
        
        return APIResponse(
            code=0,
            message="物资档案删除成功"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除物资档案异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除物资档案失败: {str(e)}")


# ============================================================================
# 库存预警接口
# ============================================================================

@router.get("/{material_id}/inventory-warning", summary="获取物资库存预警信息")
async def get_inventory_warning(
    material_id: int = Path(..., description="物资ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取物资库存预警信息"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inventory:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        warning_info = MaterialService.check_inventory_warning(material_id, db)
        
        return APIResponse(
            code=0,
            message="获取库存预警信息成功",
            data=warning_info
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取库存预警信息异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取库存预警信息失败: {str(e)}")


@router.get("/warnings/list", summary="获取库存预警列表")
async def get_warning_list(
    warning_level: Optional[str] = Query(None, pattern="^(critical|warning)$", description="预警级别"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """获取所有库存预警列表"""
    try:
        # 权限检查
        if not PermissionService.check_permission(current_user.id, "inventory:view", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")
        
        materials = db.query(Material).filter(Material.is_active == True).all()
        
        warnings = []
        for material in materials:
            warning_info = MaterialService.check_inventory_warning(material.id, db)
            if warning_info.get("has_warning"):
                if not warning_level or warning_info.get("level") == warning_level:
                    warnings.append(warning_info)
        
        # 分页处理
        total = len(warnings)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_warnings = warnings[start_idx:end_idx]
        
        return APIResponse(
            code=0,
            message="获取库存预警列表成功",
            data={
                "list": paginated_warnings,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取库存预警列表异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取库存预警列表失败: {str(e)}")


# ============================================================================
# 体积自动填充接口
# ============================================================================

class AutoFillVolumeRequest(BaseModel):
    """自动填充体积请求"""
    default_volume: float = Field(0.001, description="默认体积（m³）", ge=0)

@router.patch("/auto-fill-volume", summary="自动填充已有物料的体积（0→默认值）")
async def auto_fill_volume(
    request: AutoFillVolumeRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """将所有 unit_volume=0 的物料设为指定默认体积，使库位容量图显示正确数据"""
    try:
        if not PermissionService.check_permission(current_user.id, "material:update", db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        materials = db.query(Material).filter(
            and_(Material.unit_volume == 0, Material.is_active == True)
        ).all()

        updated = 0
        for m in materials:
            m.unit_volume = request.default_volume
            updated += 1

        db.commit()
        return APIResponse(
            code=0,
            message=f"已更新 {updated} 个物料的体积为 {request.default_volume} m³",
            data={"updated_count": updated, "default_volume": request.default_volume}
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"自动填充体积异常 | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"自动填充体积失败: {str(e)}")


# ============================================================================
# 物料信息同步接口（与用友NC6.5对接）
# ============================================================================

@router.post("/{material_id}/sync-to-nc", summary="同步物料到用友NC6.5")
async def sync_material_to_nc(
    material_id: int = Path(..., description="物资ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    同步物料到用友NC6.5系统

    权限要求：warehouse_manager或super_admin
    """
    try:
        # 权限检查
        if not PermissionService.check_role(current_user.id, "warehouse_manager", db) and current_user.role != "super_admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限执行此操作")

        from app.services.nc_sync_service import NcSyncService

        success, msg = NcSyncService.sync_material_to_nc(material_id, db)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        material = db.query(Material).filter(Material.id == material_id).first()
        return APIResponse(
            code=0,
            message=msg,
            data={
                "material_id": material_id,
                "material_code": material.code,
                "material_name": material.name,
                "nc_code": material.nc_code,
                "sync_time": beijing_now().isoformat()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步物料到NC6.5异常 | 物资ID: {material_id} | 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步物料失败: {str(e)}")

