"""
Migration: Add supplementary_unit & conversion_rate to materials
Run: python -m app.migrations.add_unit_conversion
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import engine
from sqlalchemy import text


def upgrade():
    with engine.connect() as conn:
        for col, col_type in [
            ('supplementary_unit', 'VARCHAR(20)'),
            ('conversion_rate', 'DECIMAL(12, 4) DEFAULT 0'),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE materials ADD COLUMN {col} {col_type}"))
                conn.commit()
                print(f"  + Added column: {col}")
            except Exception as e:
                if 'duplicate' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f"  - Column already exists: {col}")
                else:
                    print(f"  ! Failed to add {col}: {e}")


if __name__ == '__main__':
    print("Running migration: add_unit_conversion")
    upgrade()
    print("Migration completed")
