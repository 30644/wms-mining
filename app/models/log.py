from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, BigInteger, Boolean
from sqlalchemy.orm import relationship
from app.database import Base, beijing_now
from datetime import datetime


class OperationLog(Base):
    __tablename__ = 'operation_logs'
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(100), nullable=False)
    module = Column(String(50))
    related_id = Column(Integer)
    related_no = Column(String(50))
    details = Column(JSON)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=beijing_now)
    user = relationship('User', back_populates='operation_logs')

    @classmethod
    def create_log(cls, user_id, action, module=None, related_id=None, related_no=None, details=None, ip_address=None, db=None):
        try:
            log = cls(
                user_id=user_id, action=action, module=module,
                related_id=related_id, related_no=related_no,
                details=details, ip_address=ip_address
            )
            if db:
                db.add(log)
                db.commit()
            return log
        except Exception as e:
            if db:
                db.rollback()
            return None


class NcSyncRecord(Base):
    __tablename__ = 'nc_sync_records'
    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String(50), nullable=False)
    business_id = Column(Integer, nullable=False)
    business_no = Column(String(50), nullable=False)
    nc_code = Column(String(50))
    sync_status = Column(String(30), default='pending')
    attempt_count = Column(Integer, default=0)
    error_message = Column(Text)
    synced_at = Column(DateTime)
    created_at = Column(DateTime, default=beijing_now)
    updated_at = Column(DateTime, default=beijing_now, onupdate=beijing_now)
