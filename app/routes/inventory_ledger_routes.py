"""
库存流水台账模块路由
- 库存流水记录查询
- 物料追溯查询
- 库存汇总统计
- 库存趋势分析
- 数据导出
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date, datetime

from app.database import get_db
from app.utils.auth import get_current_user, require_permission
from app.utils.logger import logger
from app.services.inventory_ledger_service import (
    InventoryLedgerService, BUSINESS_TYPE, LEDGER_STATUS
)
from app.models import User

router = APIRouter(tags=["库存流水台账"])


# ========== Request Models ==========

class CreateLedgerRequest(BaseModel):
    """创建库存流水请求（用于手动补录）"""
    material_id: int = Field(..., description="物料ID")
    warehouse_id: int = Field(..., description="仓库ID")
    location_id: Optional[int] = Field(None, description="库位ID")
    ledger_type: str = Field(..., description="流水类型")
    quantity: float = Field(..., description="数量（正数增加，负数减少）")
    unit_price: Optional[float] = Field(None, description="单价")
    related_doc_type: Optional[str] = Field(None, description="关联单据类型")
    related_doc_no: Optional[str] = Field(None, description="关联单据号")
    batch_no: Optional[str] = Field(None, description="批次号")
    remark: Optional[str] = Field(None, description="备注")


class ExportLedgerRequest(BaseModel):
    """导出库存流水请求"""
    material_id: Optional[int] = Field(None, description="物料ID筛选")
    warehouse_id: Optional[int] = Field(None, description="仓库ID筛选")
    ledger_type: Optional[str] = Field(None, description="流水类型筛选")
    start_date: Optional[date] = Field(None, description="开始日期")
    end_date: Optional[date] = Field(None, description="结束日期")
    export_format: str = Field('excel', description="导出格式：excel/csv")


# ========== 库存流水查询接口 ==========

@router.get("/records", summary="获取库存流水列表")
def get_ledger_list(
    material_id: Optional[int] = Query(None, description="物料ID筛选"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    location_id: Optional[int] = Query(None, description="库位ID筛选"),
    ledger_type: Optional[str] = Query(None, description="流水类型筛选"),
    related_doc_type: Optional[str] = Query(None, description="关联单据类型"),
    related_doc_no: Optional[str] = Query(None, description="关联单据号"),
    batch_no: Optional[str] = Query(None, description="批次号"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取库存流水列表（带分页）
    
    **权限**: inventory_ledger:list
    
    **流水类型**:
    - inbound: 入库
    - outbound: 出库
    - transfer: 调拨
    - check_adjustment: 盘点调整
    - inventory_loss: 盘亏
    - inventory_profit: 盘盈
    - return: 退货
    - scrap: 报废
    - manual: 手动调整
    """
    success, message, data, total = InventoryLedgerService.get_ledger_list(
        db=db,
        material_id=material_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        business_type=ledger_type,
        business_no=related_doc_no,
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


@router.get("/records/{ledger_id}", summary="获取库存流水详情")
def get_ledger_detail(
    ledger_id: int,
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取库存流水详情
    
    **权限**: inventory_ledger:detail
    """
    success, message, data = InventoryLedgerService.get_ledger_detail(
        db=db,
        ledger_id=ledger_id
    )
    
    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": data
    }


# ========== 物料追溯接口 ==========
# 物料追溯查询

@router.get("/material/{material_id}/trace", summary="物料追溯查询")
def get_material_ledger_trace(
    material_id: int,
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    batch_no: Optional[str] = Query(None, description="批次号筛选"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    物料追溯查询
    
    **权限**: inventory_ledger:trace
    
    **说明**: 
    - 查询指定物料的所有库存流水记录
    - 可按仓库、批次号、日期范围筛选
    - 返回流水明细及当前余额
    """
    success, message, data, total = InventoryLedgerService.get_material_ledger_trace(
        db=db,
        material_id=material_id,
        warehouse_id=warehouse_id,
        batch_no=batch_no,
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


# ========== 库存汇总统计接口 ==========

@router.get("/summary", summary="获取库存汇总")
def get_inventory_summary(
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    category_id: Optional[int] = Query(None, description="分类ID筛选"),
    material_id: Optional[int] = Query(None, description="物料ID筛选"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取库存汇总
    
    **权限**: inventory_ledger:summary
    
    **返回**: 
    - 按物料/仓库维度的库存汇总
    - 包含数量、金额等信息
    """
    success, message, data = InventoryLedgerService.get_inventory_summary(
        db=db,
        warehouse_id=warehouse_id,
        category_id=category_id,
        material_id=material_id
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": data
    }


# ========== 库存趋势分析接口 ==========

@router.get("/trend", summary="获取库存趋势")
def get_inventory_trend(
    material_id: Optional[int] = Query(None, description="物料ID（单物料趋势）"),
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    category_id: Optional[int] = Query(None, description="分类ID"),
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    group_by: str = Query('day', description="分组方式：day/week/month"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取库存趋势
    
    **权限**: inventory_ledger:trend
    
    **分组方式**:
    - day: 按天
    - week: 按周
    - month: 按月
    
    **返回**: 
    - 时间序列的库存变化数据
    - 包含期初库存、入库、出库、期末库存
    """
    success, message, data = InventoryLedgerService.get_inventory_trend(
        db=db,
        material_id=material_id,
        warehouse_id=warehouse_id,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        group_by=group_by
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": data
    }


# ========== 仓库统计接口 ==========

@router.get("/warehouse-statistics", summary="获取仓库统计")
def get_warehouse_statistics(
    warehouse_id: Optional[int] = Query(None, description="仓库ID筛选"),
    db = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取仓库统计
    
    **权限**: inventory_ledger:statistics
    
    **返回**:
    - 各仓库的库存总量、物料种类数
    - 库存周转情况
    - 滞销/畅销物料
    """
    success, message, data = InventoryLedgerService.get_warehouse_statistics(
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


# ========== 数据导出接口 ==========

@router.post("/export", summary="导出库存流水")
def export_ledger(
    request: ExportLedgerRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_ledger:export'))
):
    """
    导出库存流水
    
    **权限**: inventory_ledger:export
    
    **导出格式**:
    - excel: Excel格式
    - csv: CSV格式
    
    **说明**: 返回文件下载链接或Base64编码的文件内容
    """
    success, message, file_data = InventoryLedgerService.export_ledger(
        db=db,
        material_id=request.material_id,
        warehouse_id=request.warehouse_id,
        business_type=request.ledger_type,
        start_date=request.start_date,
        end_date=request.end_date
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": file_data
    }


# ========== 手动创建流水（补录）接口 ==========

@router.post("/records", summary="手动创建库存流水")
def create_ledger(
    request: CreateLedgerRequest,
    db = Depends(get_db),
    current_user: User = Depends(require_permission('inventory_ledger:create'))
):
    """
    手动创建库存流水（用于补录）
    
    **权限**: inventory_ledger:create
    
    **说明**: 
    - 仅用于特殊情况下的手动补录
    - 需要记录补录原因
    - 正常业务通过业务单据自动生成
    """
    success, message, ledger = InventoryLedgerService.create_ledger(
        db=db,
        material_id=request.material_id,
        warehouse_id=request.warehouse_id,
        location_id=request.location_id or 0,
        business_type=request.ledger_type,
        change_quantity=request.quantity,
        operator_id=current_user.id,
        operator_name=current_user.real_name,
        remark=request.remark
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "code": 0,
        "message": message,
        "data": {
            "id": ledger.id,
            "ledger_no": ledger.ledger_no,
            "material_id": ledger.material_id,
            "warehouse_id": ledger.warehouse_id,
            "ledger_type": ledger.business_type,
            "ledger_type_name": BUSINESS_TYPE.get(ledger.business_type),
            "quantity": float(ledger.change_quantity),
            "status": ledger.status,
            "status_name": LEDGER_STATUS.get(ledger.status),
            "created_at": ledger.created_at.strftime('%Y-%m-%d %H:%M:%S') if ledger.created_at else None
        }
    }


# ========== 辅助接口 ==========

@router.get("/ledger-types", summary="获取流水类型列表")
def get_ledger_types():
    """获取流水类型列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in BUSINESS_TYPE.items()
        ]
    }


@router.get("/ledger-statuses", summary="获取流水状态列表")
def get_ledger_statuses():
    """获取流水状态列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": k, "label": v} for k, v in LEDGER_STATUS.items()
        ]
    }


@router.get("/doc-types", summary="获取关联单据类型列表")
def get_related_doc_types():
    """获取关联单据类型列表"""
    return {
        "code": 0,
        "message": "获取成功",
        "data": [
            {"value": "inbound", "label": "入库单"},
            {"value": "outbound", "label": "出库单"},
            {"value": "transfer", "label": "调拨单"},
            {"value": "check_order", "label": "盘点单"},
            {"value": "return", "label": "退货单"},
            {"value": "scrap", "label": "报废单"},
            {"value": "manual", "label": "手动调整"}
        ]
    }


@router.get("/consumption-comparison", summary="消耗对比分析")
async def consumption_comparison(
    days: int = Query(30, ge=7, le=365, description="统计天数"),
    top_n: int = Query(10, ge=5, le=50, description="返回物料数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    获取当前时间段与前一时间段的消耗对比数据。

    用于需求预测看板，展示 Top N 物料的消耗变化趋势。
    """
    try:
        data = InventoryLedgerService.get_consumption_comparison(
            db=db, days=days, top_n=top_n
        )
        return {"code": 0, "message": "获取成功", "data": data}
    except Exception as e:
        logger.error(f"消耗对比分析异常: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")