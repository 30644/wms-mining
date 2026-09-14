"""
报表分析路由
- 仪表盘概览
- 出库频次分析
- 部门领料金额
- 到货周期
- ABC分类
- 消耗趋势
- 库存价值
- 部门对比
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date

from app.database import get_db
from app.schemas.common import APIResponse
from app.utils.auth import get_current_user
from app.services.report_service import ReportService
from app.utils.logger import logger

router = APIRouter(prefix="/api/report", tags=["报表分析"])


@router.get("/dashboard", summary="仪表盘概览")
def dashboard(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取仪表盘概览统计"""
    try:
        data = ReportService.get_dashboard_stats(db)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"仪表盘概览异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory-summary", summary="库存汇总报表")
def inventory_summary(
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    category_id: Optional[int] = Query(None, description="分类ID"),
    material_name: Optional[str] = Query(None, description="物料名称"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """库存汇总报表 - 分页物料库存明细 + 汇总统计"""
    try:
        from app.models.inventory import Inventory
        from app.models.catalog import Material, MaterialCategory
        from app.models.location import Location, Warehouse
        from sqlalchemy import func, and_

        query = db.query(Inventory, Material, Location, Warehouse).join(
            Material, Inventory.material_id == Material.id
        ).join(
            Location, Inventory.location_id == Location.id
        ).join(
            Warehouse, Location.warehouse_id == Warehouse.id
        ).filter(
            Inventory.quantity > 0,
            Material.is_active == True
        )

        if warehouse_id:
            query = query.filter(Location.warehouse_id == warehouse_id)
        if category_id:
            query = query.filter(Material.category_id == category_id)
        if material_name:
            query = query.filter(Material.name.contains(material_name))

        total = query.count()
        total_quantity = query.with_entities(func.sum(Inventory.quantity)).scalar() or 0
        total_items = db.query(Material).filter(Material.is_active == True).count()
        warehouse_count = db.query(Warehouse).count()

        offset = (page - 1) * page_size
        results = query.order_by(Material.code).offset(offset).limit(page_size).all()

        list_data = []
        for inv, mat, loc, wh in results:
            list_data.append({
                "id": inv.id,
                "material_id": mat.id,
                "material_code": mat.code,
                "material_name": mat.name,
                "specification": mat.specification or "",
                "unit": mat.unit or "",
                "unit_price": float(mat.unit_price) if mat.unit_price else 0,
                "warehouse_id": wh.id,
                "warehouse_name": wh.name,
                "area_name": loc.shelf.code if loc.shelf else "",
                "location_code": loc.code,
                "quantity": float(inv.quantity),
                "available_quantity": float(inv.quantity),
                "frozen_quantity": 0,
                "total_amount": round(float(inv.quantity) * float(mat.unit_price or 0), 2),
            })

        return {
            "code": 0, "message": "获取成功",
            "data": {
                "list": list_data, "total": total,
                "stats": {
                    "total_items": total_items,
                    "total_quantity": float(total_quantity),
                    "total_amount": 0,
                    "warehouse_count": warehouse_count,
                }
            }
        }
    except Exception as e:
        logger.error(f"库存汇总异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/outbound-frequency", summary="出库频次分析")
def outbound_frequency(
    period: str = Query('month', description="分组周期: month/quarter/year"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    top_n: int = Query(20, ge=5, le=100, description="返回TOP N"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """出库频次分析 - 按时间周期统计物料出库次数和数量"""
    try:
        data = ReportService.get_outbound_frequency(
            db, period=period, start_date=start_date,
            end_date=end_date, top_n=top_n
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"出库频次分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/department-cost", summary="部门领料金额分析")
def department_cost(
    period: str = Query('month', description="分组周期: month/quarter/year"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    department: Optional[str] = Query(None, description="筛选部门"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """部门领料金额分析 - 按时间周期统计各领用部门的物料花费"""
    try:
        data = ReportService.get_department_cost(
            db, period=period, start_date=start_date, end_date=end_date,
            department=department
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"部门领料金额异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/procurement-cycle", summary="到货周期分析")
def procurement_cycle(
    material_id: Optional[int] = Query(None, description="物料ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """到货周期分析 - 统计物料实际到货与预期到货的天数偏差"""
    try:
        data = ReportService.get_procurement_cycle(db, material_id=material_id)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"到货周期分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/abc-analysis", summary="ABC分类分析")
def abc_analysis(
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """ABC分类 - 按出库金额累计占比分为A/B/C类"""
    try:
        data = ReportService.get_abc_analysis(
            db, start_date=start_date, end_date=end_date
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"ABC分类分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consumption-trend", summary="消耗趋势分析")
def consumption_trend(
    material_id: Optional[int] = Query(None, description="物料ID（不传=全部物料汇总）"),
    months: int = Query(12, ge=3, le=36, description="分析月数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """消耗趋势 - 最近N个月月度消耗量及未来3个月预测"""
    try:
        data = ReportService.get_consumption_trend(
            db, material_id=material_id, months=months
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"消耗趋势分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory-value", summary="库存价值分析")
def inventory_value(
    warehouse_id: Optional[int] = Query(None, description="仓库ID"),
    category_id: Optional[int] = Query(None, description="分类ID"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """库存价值分析 - 按仓库/分类汇总当前库存价值"""
    try:
        data = ReportService.get_inventory_value(
            db, warehouse_id=warehouse_id, category_id=category_id
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"库存价值分析异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sparkline", summary="迷你图数据")
def sparkline(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """近30天每日出库量 + 近7天每日领料金额，用于KPI迷你图"""
    try:
        data = ReportService.get_sparkline_data(db)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"迷你图数据异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar-heatmap", summary="日历热力图")
def calendar_heatmap(
    year: int = Query(..., description="年份"),
    month: int = Query(..., ge=1, le=12, description="月份"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """按日出库次数，用于日历热力图"""
    try:
        data = ReportService.get_calendar_heatmap(db, year, month)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"日历热力图异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yoy-mom", summary="同比环比")
def yoy_mom(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """本月 vs 上月、本月 vs 去年同月 出库量/金额增长率"""
    try:
        data = ReportService.get_yoy_mom_growth(db)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"同比环比异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/procurement-ontime", summary="采购准时率")
def procurement_ontime(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """按供应商统计到货准时率、偏差天数分布"""
    try:
        data = ReportService.get_procurement_ontime(db)
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"采购准时率异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/department-comparison", summary="部门消耗对比")
def department_comparison(
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """部门消耗对比 - 指定时间段内各部门领料金额/数量排名"""
    try:
        data = ReportService.get_department_comparison(
            db, start_date=start_date, end_date=end_date
        )
        return APIResponse(code=0, message="获取成功", data=data)
    except Exception as e:
        logger.error(f"部门消耗对比异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slow-moving/export", summary="呆滞物料导出CSV")
def slow_moving_export(
    days: int = Query(90, ge=30, le=730),
    warehouse_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """导出呆滞物料为CSV"""
    try:
        from io import StringIO
        import csv
        from fastapi.responses import StreamingResponse
        from app.services.slow_moving_service import SlowMovingService

        data = SlowMovingService.get_slow_moving(db=db, days=days, warehouse_id=warehouse_id)

        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["物料编码", "物料名称", "所在仓库", "当前库存", "最后出库日期", "滞销天数", "库存价值"])
        for item in data:
            writer.writerow([
                item["material_code"],
                item["material_name"],
                item["warehouse_name"],
                item["quantity"],
                item["last_outbound_date"] or '从未出库',
                item["days_since_last_outbound"],
                item["total_value"],
            ])

        buf.seek(0)
        content = '﻿' + buf.getvalue()

        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=slow_moving_{date.today()}.csv"},
        )
    except Exception as e:
        logger.error(f"呆滞物料导出异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))



