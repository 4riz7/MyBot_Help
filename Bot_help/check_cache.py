#!/usr/bin/env python3
"""
Проверка кэша сообщений
"""
import database

database.init_db()

import sqlite3
conn = sqlite3.connect(database.DB_PATH)
cursor = conn.cursor()

print("=== Последние 10 закэшированных сообщений ===")
cursor.execute("SELECT message_id, chat_id, user_id, text, timestamp FROM message_cache ORDER BY timestamp DESC LIMIT 10")
rows = cursor.fetchall()

if not rows:
    print("❌ Кэш пуст! Сообщения не кэшируются.")
else:
    for row in rows:
        msg_id, chat_id, user_id, text, ts = row
        print(f"MSG {msg_id} | Chat {chat_id} | User {user_id} | {ts}")
        print(f"  Текст: {text[:50]}...")
        print()

print(f"\nВсего сообщений в кэше: {len(rows)}")

conn.close()
