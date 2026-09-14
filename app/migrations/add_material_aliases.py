"""
Migration: Create material_aliases table for AI synonym caching
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlalchemy import create_engine, text
from app.config import DATABASE_URL


def upgrade():
    engine = create_engine(DATABASE_URL)
    conn = engine.connect()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS material_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            alias VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    """))

    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_material_aliases_alias ON material_aliases(alias)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_material_aliases_material_id ON material_aliases(material_id)"
    ))

    conn.commit()
    conn.close()
    print("Migration completed: material_aliases table created")


if __name__ == "__main__":
    upgrade()
