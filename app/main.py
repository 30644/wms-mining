from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.routes import auth, inventory, request_routes, users, warehouse, inbound, material, inbound_business, outbound_business
from app.routes.inventory_check_routes import router as inventory_check_router
from app.routes.inventory_alert_routes import router as inventory_alert_router
from app.routes.inventory_ledger_routes import router as inventory_ledger_router
from app.routes.transfer_routes import router as transfer_router
from app.routes.scrap_routes import router as scrap_router
from app.routes.return_routes import router as return_router
from app.routes.supplier_routes import router as supplier_router
from app.routes.supplier_evaluation_routes import router as supplier_evaluation_router
from app.routes.department_routes import router as department_router
from app.routes.approval_routes import router as approval_router
from app.routes.nc_routes import router as nc_router
from app.routes.inventory_turnover_routes import router as turnover_router
from app.routes.slow_moving_routes import router as slow_moving_router
from app.routes.inventory_age_routes import router as inventory_age_router
from app.routes.reconciliation_routes import router as reconciliation_router
from app.routes.purchase_routes import router as purchase_router
from app.routes.report_routes import router as report_router
from app.routes.notification_routes import router as notification_router
from app.routes.log_routes import router as log_router
from app.routes.backup_routes import router as backup_router
from app.routes.nc_config_routes import router as nc_config_router
from app.routes.system_config_routes import router as system_config_router
from app.database import engine, Base
from app.config import CORS_ORIGINS, CORS_ALLOW_CREDENTIALS
from app.exception_handlers import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    integrity_error_handler,
    sqlalchemy_exception_handler
)
from app.utils.logger import logger, setup_logger

# 初始化日志
setup_logger()
logger.info("=" * 60)
logger.info("应用启动中 | 大红柳滩矿区智能仓储管理系统")
logger.info("=" * 60)

# 先创建应用和注册路由
app = FastAPI(
    title="大红柳滩矿区智能仓储管理系统",
    description="专用的智能仓储管理系统，集成物料管理、库存管理、领料申请等功能",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册异常处理器
from fastapi.exceptions import HTTPException
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_error_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 注册路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(warehouse.router, prefix="/api/warehouse", tags=["库房管理"])
app.include_router(material.router, prefix="/api/materials", tags=["物资档案"])
app.include_router(material.router, prefix="/api/material", tags=["物资档案兼容"], include_in_schema=False)
app.include_router(inventory.router, prefix="/api/inventory", tags=["库存管理"])
app.include_router(inbound.router, prefix="/api/inbound", tags=["入库管理"])
app.include_router(inbound_business.router, prefix="/api/inbound-business", tags=["入库业务"])
app.include_router(outbound_business.router, prefix="/api/outbound-business", tags=["出库业务"])
app.include_router(request_routes.router, prefix="/api/requests", tags=["领料申请"])
# 第六步新增路由
app.include_router(inventory_check_router, prefix="/api/inventory-check", tags=["库存盘点"])
app.include_router(inventory_alert_router, prefix="/api/inventory-alert", tags=["库存预警"])
app.include_router(inventory_ledger_router, prefix="/api/inventory-ledger", tags=["库存流水台账"])
# 调拨、报废、退货、供应商路由
app.include_router(transfer_router, prefix="/api/transfer", tags=["调拨管理"])
app.include_router(scrap_router, prefix="/api/scrap", tags=["报废管理"])
app.include_router(return_router, prefix="/api/return", tags=["退货管理"])
app.include_router(supplier_router, prefix="/api/supplier", tags=["供应商管理"])
app.include_router(supplier_evaluation_router, tags=["供应商评估"])
app.include_router(department_router, prefix="/api/department", tags=["部门管理"])
app.include_router(approval_router, prefix="/api/approval", tags=["审批中心"])
app.include_router(nc_router, tags=["NC数据同步"])
app.include_router(notification_router, prefix="/api", tags=["消息通知"])
app.include_router(turnover_router, tags=["报表分析"])
app.include_router(slow_moving_router, tags=["报表分析"])
app.include_router(inventory_age_router, tags=["报表分析"])
app.include_router(reconciliation_router, tags=["报表分析"])
app.include_router(purchase_router, prefix="/api", tags=["采购清单"])
app.include_router(report_router, tags=["报表统计"])
app.include_router(log_router, tags=["系统日志"])
app.include_router(backup_router, prefix="/api/backup", tags=["数据备份"])
app.include_router(nc_config_router, tags=["NC配置"])
app.include_router(system_config_router, tags=["系统配置"])

logger.info(f"已注册路由: auth, users, warehouse, material, inventory, inbound, inbound_business, outbound_business, requests, inventory_check, inventory_alert, inventory_ledger, transfer, scrap, return, supplier, department, approval, nc, purchase, report, log")

# 创建数据库表（在所有模型都导入后）
try:
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成")
except Exception as e:
    logger.error(f"数据库初始化失败 | 错误: {str(e)}")
    raise

# 数据库迁移：为已有表补充新列
try:
    from sqlalchemy import text as sa_text
    with engine.connect() as conn:
        # 检查 inbound_orders 表是否有 is_direct_issue 列
        columns = [row[1] for row in conn.execute(sa_text("PRAGMA table_info('inbound_orders')")).fetchall()]
        new_cols = ['is_direct_issue', 'direct_issue_quantity', 'inbound_reviewer_id', 'inbound_reviewed_at', 'inbound_review_comment',
                    'direct_issue_recipient', 'direct_issue_reason', 'outbound_order_id']
        for col in new_cols:
            if col not in columns:
                type_map = {
                    'is_direct_issue': 'BOOLEAN DEFAULT 0',
                    'direct_issue_quantity': 'DECIMAL(12,2)',
                    'inbound_reviewer_id': 'INTEGER REFERENCES users(id)',
                    'inbound_reviewed_at': 'DATETIME',
                    'inbound_review_comment': 'TEXT',
                    'direct_issue_recipient': 'VARCHAR(100)',
                    'direct_issue_reason': 'VARCHAR(200)',
                    'outbound_order_id': 'INTEGER REFERENCES outbound_orders(id)',
                }
                conn.execute(sa_text(f"ALTER TABLE inbound_orders ADD COLUMN {col} {type_map[col]}"))
                logger.info(f"数据库迁移: inbound_orders 新增列 {col}")
        conn.commit()

        # 检查 materials 表是否有 unit_volume 列
        mat_columns = [row[1] for row in conn.execute(sa_text("PRAGMA table_info('materials')")).fetchall()]
        if 'unit_volume' not in mat_columns:
            conn.execute(sa_text("ALTER TABLE materials ADD COLUMN unit_volume DECIMAL(12,4) DEFAULT 0"))
            logger.info("数据库迁移: materials 新增列 unit_volume")
        if 'volume_unit' not in mat_columns:
            conn.execute(sa_text("ALTER TABLE materials ADD COLUMN volume_unit VARCHAR(10) DEFAULT 'm³'"))
            logger.info("数据库迁移: materials 新增列 volume_unit")

        # 检查 locations 表是否有 capacity_unit 列
        loc_columns = [row[1] for row in conn.execute(sa_text("PRAGMA table_info('locations')")).fetchall()]
        if 'capacity_unit' not in loc_columns:
            conn.execute(sa_text("ALTER TABLE locations ADD COLUMN capacity_unit VARCHAR(10) DEFAULT 'm³'"))
            logger.info("数据库迁移: locations 新增列 capacity_unit")

        conn.commit()
    logger.info("数据库迁移检查完成")
except Exception as e:
    logger.warning(f"数据库迁移检查异常（可忽略）: {str(e)}")


@app.get("/", summary="健康检查")
async def read_root():
    """
    应用根路由 - 健康检查
    """
    return {
        "message": "欢迎使用大红柳滩矿区智能仓储管理系统",
        "status": "运行中"
    }


@app.on_event("startup")
async def startup_event():
    """
    应用启动事件
    """
    # 同步系统角色到数据库
    try:
        from app.database import SessionLocal
        from app.utils.business_tools import PermissionService
        db = SessionLocal()
        try:
            PermissionService.sync_system_roles(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"系统角色同步异常（可忽略）: {str(e)}")

    logger.info("应用启动完成 | 版本: 1.0.0")


@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭事件
    """
    logger.info("=" * 60)
    logger.info("应用已关闭")
    logger.info("=" * 60)


if __name__ == "__main__":
    import uvicorn
    # 注意：Windows 下 reload=True 会导致 python -m app.main 启动后端口不监听
    # 请使用 python -m uvicorn app.main:app --host 0.0.0.0 --port 8765 启动
    # 或双击运行 start.bat
    uvicorn.run(app, host="0.0.0.0", port=8766, reload=True)
# ====== Serve Frontend Static Files ======
from fastapi.staticfiles import StaticFiles
import os

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
