"""
全局配置文件
"""
import os
from datetime import timedelta

# ========== 数据库配置 ==========
# 获取当前app目录的父目录（backend目录）
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(APP_DIR, "warehouse.db")  # 已经在backend目录中

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DB_PATH}"  # 使用绝对路径
)

# ========== JWT认证配置 ==========
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8小时
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ========== 日志配置 ==========
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "warehouse.log")
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 10

# ========== 跨域配置 ==========
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
    "http://localhost:8085",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8083",
    "http://127.0.0.1:8084",
    "http://127.0.0.1:8085",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]

# ========== 系统配置 ==========
APP_NAME = "大红柳滩矿区智能仓储管理系统"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "基于FastAPI的仓储管理后端系统"

# ========== 业务配置 ==========
# 超级管理员角色
SUPER_ADMIN_ROLE = "super_admin"

# 系统角色
SYSTEM_ROLES = [
    "super_admin",          # 超级管理员
    "employee",             # 车间普通员工
    "team_leader",          # 车间班长
    "department_leader",    # 部门领导
    "warehouse_manager",    # 库管
    "finance",              # 财务
    "procurement_officer",  # 采购员
    "warehouse_operator",   # 库管（执行出入库操作）
    "receiving_inspector",  # 到货审核员（验收物资）
    "technical_officer",    # 技术员
    "requester",            # 申请人
    "approver",             # 审批人
    "viewer",               # 查看员
    "electrical_inspector",  # 电气验收员
    "mechanical_inspector",  # 机械验收员
    "logistics_inspector",   # 后勤验收员
]

# 不需要认证的接口
UNAUTHENTICATED_PATHS = [
    "/api/auth/login",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
]

# ========== 密码策略 ==========
MIN_PASSWORD_LENGTH = 8
PASSWORD_REQUIRE_UPPERCASE = True
PASSWORD_REQUIRE_LOWERCASE = True
PASSWORD_REQUIRE_DIGITS = True
PASSWORD_REQUIRE_SPECIAL = False  # 特殊字符可选

# ========== 分页配置 ==========
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 10000

# ========== 用友NC6.5对接配置 ==========
NC_API_URL = os.getenv("NC_API_URL", "http://localhost:8080/nc-api")
NC_API_TIMEOUT = int(os.getenv("NC_API_TIMEOUT", "30"))  # 30秒超时
NC_MAX_RETRY = int(os.getenv("NC_MAX_RETRY", "3"))  # 最多重试3次
NC_API_TOKEN = os.getenv("NC_API_TOKEN", "your-nc-token")  # NC API令牌

# ========== 库存并发控制配置 ==========
INVENTORY_LOCK_TIMEOUT = int(os.getenv("INVENTORY_LOCK_TIMEOUT", "10"))  # 库存锁超时时间
INVENTORY_CHECK_INTERVAL = int(os.getenv("INVENTORY_CHECK_INTERVAL", "3600"))  # 库存一致性检查间隔（秒）

# ========== AI智能搜索配置 ==========
AI_API_KEY = "sk-f50276af4fc24e0d969b9d206ccbd43a"
AI_API_URL = "https://api.deepseek.com/chat/completions"
AI_MODEL = "deepseek-chat"

# ========== 通义千问视觉识别配置 ==========
QWEN_API_KEY = "sk-f91de9fdbd2c48d7a99c1cda410071d6"
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_VL_MODEL = "qwen-vl-max"

# ========== 业务风控配置 ==========
# 禁止重复审核
PREVENT_DUPLICATE_APPROVAL = True
# 禁止修改已审核单据
PREVENT_MODIFY_APPROVED_ORDER = True
# 禁止超量领用
PREVENT_EXCESS_requisition = True
# 禁止负库存
PREVENT_NEGATIVE_INVENTORY = True