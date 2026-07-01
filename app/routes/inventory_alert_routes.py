"""
库存预警模块路由
- 预警配置管理（创建、修改、删除、查询）
- 预警生成与触发
- 预警处理与确认
- 预警查询与统计
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from datetime import date

from app.database import get_db
from app.utils.auth import get_current_user, require_permission
from app.services.inventory_alert_service import (
    InventoryAlertService, ALERT_TYPE, ALERT_LEVEL, ALERT_STATUS
)
from app.models import User

router = APIRouter(tags=["库存预警"])


# ========== Request Models ==========

class CreateAlertConfigRequest(BaseModel):
    """创建预警配置请求"""
    material_id: Optional[int] = Field(None, description="物料ID（精确配置）")
    category_id: Optional[int] = Field(None, description="分类ID（分类级别配置）")
    warehouse_id: Optional[int] = Field(None, description="仓库ID")
    min_quantity: Optional[float] = Field(None, description="最小库存阈值")
    max_quantity: Optional[float] = Field(None, description="最大库存阈值")
    alert_level: str = Field('medium', description="预警级别：low/medium/high/critical")
    is_enabled: bool = Field(True, description="是否启用")
    remark: Optional[str] = Field(None, description="备注")


class UpdateAlertConfigRequest(BaseModel):
    """更新预警配置请求"""
    min_quantity: Optional[float] = Field(None, description="最小库存阈值")
    max_quantity: Optional[float] = Field(None, description="最大库存阈值")
    alert_level: Optional[str] = Field(None, description="预警级别")
    enabled: Optional[bool] = Field(None, description="是否启用")
    remark: Optional[str] = Field(None, description="备注")


class ProcessAlertRequest(BaseModel):
    """处理预警请求"""
    resolved: bool = Field(..., description="是否已解决")
    handle_remark: Optional[str] = Field(None, description="处理备注")


class BatchProcessAlertsRequest(BaseModel):
    """批量处理预警请求"""
    alert_ids: List[int] = Field(..., description="预警ID列表")
    resolved: bool = Field(..., description="是否已解决")
    handle_remark: Optional[str] = Field(None, description="处理备注")


# ========== 预警配置管理接口 ==========

@router.post("/configs", summary="创建预警配置")
def create_alert_config(
    request: CreateAlertConfigRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:config:create'))
):
    """
    创建预警配置
    
    **权限**: inventory_alert:config:create
    
    **配置说明**:
    - 精确配置：指定物料ID，针对单个物料
    - 分类配置：指定分类ID，针对该分类下所有物料
    - 仓库配置：可限定仓库范围
    
    **阈值说明**:
    - min_quantity: 最小库存，低于此值触发"库存不足"预警
    - max_quantity: 最大库存，超过此值触发"库存过剩"预警
    """
    success, message, config = InventoryAlertService.create_alert_config(
        db=db,
        material_id=request.material_id,
        category_id=request.category_id,
        warehouse_id=request.warehouse_id,
        min_quantity=request.min_quantity,
        max_quantity=request.max_quantity,
        alert_level=request.alert_level,
        is_enabled=request.is_enabled,
        remark=request.remark,
        creator_id=current_user.id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": config.id,
            "material_id": config.material_id,
            "category_id": config.category_id,
            "warehouse_id": config.warehouse_id,
            "min_quantity": float(config.min_quantity) if config.min_quantity else None,
            "max_quantity": float(config.max_quantity) if config.max_quantity else None,
            "alert_level": config.alert_level,
            "alert_level_name": ALERT_LEVEL.get(config.alert_level),
            "enabled": config.is_enabled,
            "created_at": config.created_at.strftime('%Y-%m-%d %H:%M:%S') if config.created_at else None
        }
    }


@router.put("/configs/{config_id}", summary="更新预警配置")
def update_alert_config(
    config_id: int,
    request: UpdateAlertConfigRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:config:update'))
):
    """
    更新预警配置
    
    **权限**: inventory_alert:config:update
    """
    success, message, config = InventoryAlertService.update_alert_config(
        db=db,
        config_id=config_id,
        min_quantity=request.min_quantity,
        max_quantity=request.max_quantity,
        alert_level=request.alert_level,
        is_enabled=request.enabled,
        remark=request.remark,
        updater_id=current_user.id
    )

    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": config.id,
            "min_quantity": float(config.min_quantity) if config.min_quantity else None,
            "max_quantity": float(config.max_quantity) if config.max_quantity else None,
            "alert_level": config.alert_level,
            "alert_level_name": ALERT_LEVEL.get(config.alert_level),
            "enabled": config.enabled,
            "updated_at": config.updated_at.strftime('%Y-%m-%d %H:%M:%S') if config.updated_at else None
        }
    }


@router.delete("/configs/{config_id}", summary="删除预警配置")
def delete_alert_config(
    config_id: int,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:config:delete'))
):
    """
    删除预警配置
    
    **权限**: inventory_alert:config:delete
    """
    success, message = InventoryAlertService.delete_alert_config(
        db=db,
        config_id=config_id
    )
    
    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {
        "code": 0,
        "message": message
    }


@router.get("/configs", summary="获取预警配置列表")
def get_alert_config_list(
    material_id: Optional[int] = Query(None, description="物料ID筛选"),
    category_id: Optional[int] = Query(None, description="分类ID筛选"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    enabled: Optional[bool] = Query(None, description="是否启用筛选"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取预警配置列表
    
    **权限**: inventory_alert:config:list
    """
    success, message, data, total = InventoryAlertService.get_alert_config_list(
        db=db,
        material_id=material_id,
        category_id=category_id,
        warehouse_id=warehouse_id,
        is_enabled=enabled,
        skip=skip,
        limit=limit
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "list": data or [],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    }


# ========== 预警生成接口 ==========

@router.post("/generate", summary="生成库存预警")
def generate_alerts(
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:generate'))
):
    """
    生成库存预警
    
    **权限**: inventory_alert:generate
    
    **说明**: 
    - 扫描所有库存记录
    - 根据预警配置判断是否触发预警
    - 跳过已存在未处理预警的记录
    """
    success, message, count = InventoryAlertService.generate_alerts(db=db)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "generated_count": count
        }
    }


# ========== 预警查询接口 ==========

@router.get("/alerts", summary="获取预警列表")
def get_alert_list(
    alert_type: Optional[str] = Query(None, description="预警类型筛选：min_stock/max_stock/zero_stock"),
    alert_level: Optional[str] = Query(None, description="预警级别筛选：low/medium/high/critical"),
    status: Optional[str] = Query(None, description="状态筛选：pending/processing/resolved/ignored"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    material_id: Optional[int] = Query(None, description="物料ID筛选"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取预警列表
    
    **权限**: inventory_alert:list
    
    **预警类型**:
    - min_stock: 库存不足
    - max_stock: 库存过剩
    - zero_stock: 零库存
    
    **预警级别**:
    - low: 低
    - medium: 中
    - high: 高
    - critical: 紧急
    
    **状态**:
    - pending: 待处理
    - processing: 处理中
    - resolved: 已解决
    - ignored: 已忽略
    """
    success, message, data, total = InventoryAlertService.get_alert_list(
        db=db,
        alert_type=alert_type,
        alert_level=alert_level,
        status=status,
        warehouse_id=warehouse_id,
        material_id=material_id,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "list": data or [],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    }


@router.get("/alerts/{alert_id}", summary="获取预警详情")
def get_alert_detail(
    alert_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取预警详情
    
    **权限**: inventory_alert:detail
    """
    # 复用列表查询逻辑
    success, message, data, _ = InventoryAlertService.get_alert_list(
        db=db,
        skip=0,
        limit=1
    )
    
    # 手动获取详情
    from app.models import InventoryAlert
    alert = db.query(InventoryAlert).filter(InventoryAlert.id == alert_id).first()
    
    if not alert:
        raise HTTPException(status_code=404, detail="预警不存在")
    
    return {
        "code": 0,
        "message": "获取成功",
        "data": {
            'id': alert.id,
            'material_id': alert.material_id,
            'material_code': alert.material.code if alert.material else None,
            'material_name': alert.material.name if alert.material else None,
            'material_spec': alert.material.specification if alert.material else None,
            'material_unit': alert.material.unit if alert.material else None,
            'location_id': alert.location_id,
            'location_code': alert.location.code if alert.location else None,
            'warehouse_id': alert.warehouse_id,
            'warehouse_name': alert.warehouse.name if alert.warehouse else None,
            'alert_type': alert.alert_type,
            'alert_type_name': ALERT_TYPE.get(alert.alert_type, alert.alert_type),
            'alert_level': alert.alert_level,
            'alert_level_name': ALERT_LEVEL.get(alert.alert_level, alert.alert_level),
            'current_quantity': float(alert.current_quantity) if alert.current_quantity else 0,
            'threshold_min': float(alert.threshold_min) if alert.threshold_min else None,
            'threshold_max': float(alert.threshold_max) if alert.threshold_max else None,
            'status': alert.status,
            'status_name': ALERT_STATUS.get(alert.status, alert.status),
            'handler_id': alert.handler_id,
            'handler_name': alert.handler.real_name if alert.handler else None,
            'handled_at': alert.handled_at.strftime('%Y-%m-%d %H:%M:%S') if alert.handled_at else None,
            'handle_remark': alert.handle_remark,
            'remark': alert.remark,
            'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M:%S') if alert.created_at else None
        }
    }


# ========== 预警处理接口 ==========

@router.post("/alerts/{alert_id}/process", summary="处理预警")
def process_alert(
    alert_id: int,
    request: ProcessAlertRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:process'))
):
    """
    处理预警
    
    **权限**: inventory_alert:process
    
    **处理结果**:
    - resolved: 已解决，预警关闭
    - ignored: 已忽略，预警关闭（不处理）
    """
    success, message, alert = InventoryAlertService.process_alert(
        db=db,
        alert_id=alert_id,
        resolved=request.resolved,
        handle_remark=request.handle_remark,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": alert.id,
            "status": alert.status,
            "status_name": ALERT_STATUS.get(alert.status),
            "handled_at": alert.handled_at.strftime('%Y-%m-%d %H:%M:%S') if alert.handled_at else None
        }
    }


@router.post("/alerts/batch-process", summary="批量处理预警")
def batch_process_alerts(
    request: BatchProcessAlertsRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_alert:process'))
):
    """
    批量处理预警
    
    **权限**: inventory_alert:process
    """
    success, message, count = InventoryAlertService.batch_process_alerts(
        db=db,
        alert_ids=request.alert_ids,
        resolved=request.resolved,
        handle_remark=request.handle_remark,
        current_user={'id': current_user.id, 'role': current_user.role}
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "processed_count": count
        }
    }


# ========== 统计接口 ==========

@router.get("/statistics", summary="获取预警统计")
def get_alert_statistics(
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取预警统计
    
    **权限**: inventory_alert:statistics
    
    **返回**:
    - total: 预警总数
    - pending: 待处理数量
    - processing: 处理中数量
    - resolved: 已解决数量
    - ignored: 已忽略数量
    - by_type: 按类型统计
    - by_level: 按级别统计
    """
    success, message, data = InventoryAlertService.get_alert_statistics(
        db=db,
        warehouse_id=warehouse_id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": data
    }


# ========== 辅助接口 ==========

@router.get("/alert-types", summary="获取预警类型列表")
def get_alert_types():
    """获取预警类型列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in ALERT_TYPE.items()
        ]
    }


@router.get("/alert-levels", summary="获取预警级别列表")
def get_alert_levels():
    """获取预警级别列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in ALERT_LEVEL.items()
        ]
    }


@router.get("/alert-statuses", summary="获取预警状态列表")
def get_alert_statuses():
    """获取预警状态列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in ALERT_STATUS.items()
        ]
    }