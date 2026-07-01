from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 确保Base只创建一次
try:
    Base
except NameError:
    Base = declarative_base()

from datetime import datetime, timezone, timedelta

def beijing_now():
    """返回北京时间(UTC+8)当前时间"""
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()