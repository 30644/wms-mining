"""
Migration: Add material_name_text, specification_text, unit_text columns to inbound_orders
Make material_id nullable for unmatched scan items
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlalchemy import create_engine, text
from app.config import DATABASE_URL


def upgrade():
    engine = create_engine(DATABASE_URL)
    conn = engine.connect()

    print("Adding material_name_text column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN material_name_text VARCHAR(200)"))

    print("Adding specification_text column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN specification_text VARCHAR(200)"))

    print("Adding unit_text column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN unit_text VARCHAR(50)"))

    conn.commit()
    conn.close()
    print("Migration completed successfully")


if __name__ == "__main__":
    upgrade()
