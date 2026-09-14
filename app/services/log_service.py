import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from datetime import date, datetime, timedelta as dt_timedelta

from app.models import OperationLog, User
from app.utils.logger import logger

ROLE_DISPLAY = {
    'super_admin': '超级管理员', 'employee': '车间员工', 'team_leader': '车间班长',
    'department_leader': '部门领导', 'warehouse_manager': '库管领导', 'warehouse_operator': '库管',
    'finance': '财务', 'procurement_officer': '采购员', 'receiving_inspector': '到货审核员',
    'technical_officer': '技术员', 'requester': '申请人', 'approver': '审批人', 'viewer': '查看员',
    'electrical_inspector': '电气验收员', 'mechanical_inspector': '机械验收员', 'logistics_inspector': '后勤验收员',
}


def _parse_details(details) -> Dict:
    """兼容处理 details: dict / JSON字符串"""
    if details is None:
        return {}
    if isinstance(details, dict):
        return details
    if isinstance(details, str):
        try:
            return json.loads(details)
        except (json.JSONDecodeError, TypeError):
            return {"info": details}
    return {}


def _build_content(details) -> str:
    """从 details 提取可读内容"""
    d = _parse_details(details)
    if not d:
        return ""
    if "description" in d:
        return str(d["description"])
    if "info" in d:
        return str(d["info"])
    parts = [f"{k}={v}" for k, v in d.items() if v]
    return "; ".join(parts)


def _log_to_dict(log, include_id=False) -> Dict:
    """将 OperationLog 转换为字典"""
    item = {
        "username": log.user.username if log.user else "",
        "real_name": log.user.real_name if log.user else "",
        "role": ROLE_DISPLAY.get(log.user.role, log.user.role) if log.user else "",
        "action": log.action,
        "module": log.module or "",
        "content": _build_content(log.details),
        "ip": log.ip_address or "",
        "create_time": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
    }
    if include_id:
        item["id"] = log.id
        item["details"] = log.details
        item["related_id"] = log.related_id
        item["related_no"] = log.related_no or ""
    return item


class LogService:
    """操作日志查询服务"""

    @staticmethod
    def _apply_filters(q, username=None, keyword=None, action=None, start_date=None, end_date=None):
        """应用通用筛选条件"""
        if keyword:
            # 多关键词空格分隔，模糊匹配操作人/姓名/操作类型/内容
            keywords = keyword.strip().split()
            for kw in keywords:
                # 同时匹配角色代码和显示名
                matched_roles = [code for code, name in ROLE_DISPLAY.items() if kw in code or kw in name]
                role_filter = User.role.contains(kw)
                if matched_roles:
                    role_filter = User.role.in_(matched_roles)
                q = q.filter(
                    or_(
                        User.username.contains(kw),
                        User.real_name.contains(kw),
                        role_filter,
                        OperationLog.action.contains(kw),
                        OperationLog.module.contains(kw),
                    )
                )
        if username:
            q = q.filter(User.username.contains(username))
        if action:
            q = q.filter(OperationLog.action.contains(action))
        if start_date:
            q = q.filter(OperationLog.created_at >= datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            q = q.filter(OperationLog.created_at <= datetime.strptime(end_date, "%Y-%m-%d") + dt_timedelta(days=1))
        return q

    @staticmethod
    def get_logs(
        db: Session,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询操作日志"""
        q = db.query(OperationLog).join(User, OperationLog.user_id == User.id)
        q = LogService._apply_filters(q, username=username, keyword=keyword, action=action,
                                       start_date=start_date, end_date=end_date)
        total = q.count()
        logs = q.order_by(desc(OperationLog.created_at)).offset((page - 1) * page_size).limit(page_size).all()
        items = [_log_to_dict(log, include_id=True) for log in logs]
        return {"list": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def export_logs(
        db: Session,
        keyword: Optional[str] = None,
        username: Optional[str] = None,
        action: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """导出操作日志（不分页）"""
        q = db.query(OperationLog).join(User, OperationLog.user_id == User.id)
        q = LogService._apply_filters(q, username=username, keyword=keyword, action=action,
                                       start_date=start_date, end_date=end_date)
        logs = q.order_by(desc(OperationLog.created_at)).all()
        return [_log_to_dict(log) for log in logs]
