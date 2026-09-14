"""
日志配置模块
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config import LOG_DIR, LOG_FILE, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT


def setup_logger():
    """
    配置全局日志系统
    """
    # 创建日志目录
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    
    # 创建logger对象
    logger = logging.getLogger("warehouse")
    logger.setLevel(getattr(logging, LOG_LEVEL))
    
    # 避免重复处理
    if logger.hasHandlers():
        return logger
    
    # 日志格式
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(name)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 文件处理器（轮转日志）
    file_handler = RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


# 全局logger实例
logger = setup_logger()


def log_operation(user_id: int, action: str, module: str, related_id: int = None, 
                  related_no: str = None, details: str = None, ip_address: str = None):
    """
    记录操作日志到数据库（在services中调用）
    
    参数：
    - user_id: 操作用户ID
    - action: 操作类型（如新增用户、删除用户、修改权限等）
    - module: 操作模块（如user_management、auth等）
    - related_id: 关联业务ID
    - related_no: 关联业务单号
    - details: 操作详情（JSON字符串）
    - ip_address: 操作IP
    """
    logger.info(f"操作日志 | 用户:{user_id} | 模块:{module} | 操作:{action} | 相关ID:{related_id} | IP:{ip_address}")
