"""
站内通知
端点: /api/notifications | unread-count | {id}/read | read-all
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, Notification
from app.routes.auth import get_current_user
from app.schemas.common import APIResponse

router = APIRouter()


def _create_notification(db: Session, user_id: int, title: str, content: str = "",
                         related_type: str = "", related_id: int = None):
    notif = Notification(
        user_id=user_id, title=title, content=content,
        related_type=related_type, related_id=related_id)
    db.add(notif)
    db.commit()


@router.get("/notifications", summary="获取当前用户通知列表")
async def list_notifications(
    is_read: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if is_read is not None:
        q = q.filter(Notification.is_read == is_read)
    total = q.count()
    items = q.order_by(desc(Notification.created_at)).offset(
        (page - 1) * page_size).limit(page_size).all()

    return APIResponse(code=0, message="success", data={
        "list": [{
            "id": n.id, "title": n.title, "content": n.content,
            "is_read": n.is_read, "related_type": n.related_type,
            "related_id": n.related_id,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in items],
        "total": total, "page": page, "page_size": page_size,
    })


@router.get("/notifications/unread-count", summary="获取未读通知数量")
async def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).count()
    return APIResponse(code=0, message="success", data={"count": count})


@router.put("/notifications/{id}/read", summary="标记单条已读")
async def mark_read(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    notif = db.query(Notification).filter(
        Notification.id == id, Notification.user_id == current_user.id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="通知不存在")
    notif.is_read = True
    db.commit()
    return APIResponse(code=0, message="已标记为已读")


@router.put("/notifications/read-all", summary="全部标记已读")
async def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return APIResponse(code=0, message="全部已读")
