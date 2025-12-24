#!/usr/bin/env python3
"""
Migrate database to add 'checked' column
"""
import sqlite3

DB_PATH = "bot_database.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

try:
    # Try to add the column (will fail if it already exists)
    cursor.execute("ALTER TABLE message_cache ADD COLUMN checked BOOLEAN DEFAULT 0")
    conn.commit()
    print("✅ Added 'checked' column to message_cache table")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("ℹ️ Column 'checked' already exists")
    else:
        print(f"❌ Error: {e}")

conn.close()
print("✅ Migration complete!")
