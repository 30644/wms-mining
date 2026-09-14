"""
数据库迁移脚本：添加验收员角色支持和通知系统
运行: python -m app.migrations.add_inspector_notification
"""
from sqlalchemy import text
from app.database import engine


def upgrade():
    """执行迁移"""
    with engine.connect() as conn:
        # 1. MaterialCategory 加 inspector_role
        try:
            conn.execute(text("ALTER TABLE material_categories ADD COLUMN inspector_role VARCHAR(30)"))
            print("OK material_categories.inspector_role")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("SKIP material_categories.inspector_role (exists)")
            else:
                print(f"FAIL material_categories.inspector_role: {e}")

        # 2. InboundOrder 加 assigned_role
        try:
            conn.execute(text("ALTER TABLE inbound_orders ADD COLUMN assigned_role VARCHAR(30)"))
            print("OK inbound_orders.assigned_role")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("SKIP inbound_orders.assigned_role (exists)")
            else:
                print(f"FAIL inbound_orders.assigned_role: {e}")

        # 3. 创建 notifications 表
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    title VARCHAR(100) NOT NULL,
                    content TEXT,
                    type VARCHAR(30) DEFAULT 'system',
                    related_id INTEGER,
                    related_no VARCHAR(50),
                    related_type VARCHAR(30),
                    is_read BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("OK notifications table created")
        except Exception as e:
            print(f"FAIL notifications table: {e}")

        conn.commit()
    print("DONE migration")


if __name__ == "__main__":
    upgrade()
