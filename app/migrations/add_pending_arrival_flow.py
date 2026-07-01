"""
Migration: Add pending_arrival flow columns to inbound_orders
- actual_quantity: actual received quantity
- arrival_confirmed_at: when arrival was confirmed
- arrival_confirmed_by: who confirmed arrival
- expected_arrival_date: expected delivery date (from procurement)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlalchemy import create_engine, text
from app.config import DATABASE_URL


def upgrade():
    engine = create_engine(DATABASE_URL)
    conn = engine.connect()

    print("Adding actual_quantity column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN actual_quantity DECIMAL(12,2)"))

    print("Adding arrival_confirmed_at column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN arrival_confirmed_at DATETIME"))

    print("Adding arrival_confirmed_by column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN arrival_confirmed_by INTEGER REFERENCES users(id)"))

    print("Adding expected_arrival_date column to inbound_orders...")
    conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN expected_arrival_date DATETIME"))

    conn.commit()
    conn.close()
    print("Migration completed successfully")


if __name__ == "__main__":
    upgrade()
