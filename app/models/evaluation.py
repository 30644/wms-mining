"""供应商评估模型"""
from sqlalchemy import Column, Integer, String, Text, DECIMAL, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class SupplierEvaluation(Base):
    __tablename__ = 'supplier_evaluations'
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False, comment='供应商ID')
    score = Column(DECIMAL(5, 2), nullable=False, comment='综合评分')
    quality_score = Column(DECIMAL(5, 2), comment='质量评分')
    delivery_score = Column(DECIMAL(5, 2), comment='交期评分')
    price_score = Column(DECIMAL(5, 2), comment='价格评分')
    service_score = Column(DECIMAL(5, 2), comment='服务评分')
    evaluation_period = Column(String(30), comment='评估周期')
    comment = Column(Text, comment='评估备注')
    evaluator_id = Column(Integer, ForeignKey('users.id'), comment='评估人ID')
    created_at = Column(DateTime, default=datetime.now)
    supplier = relationship('Supplier')
    evaluator = relationship('User')
