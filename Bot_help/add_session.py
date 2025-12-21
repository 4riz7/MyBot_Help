#!/usr/bin/env python3
"""
Скрипт для добавления session string в базу данных
"""
import database

# Инициализируем БД
database.init_db()

# Ваши данные
USER_ID = 956714918  # Ваш ID из config.py (ADMIN_ID)
SESSION_STRING = "AgJSo6cAlXXcQ9f8w2D8ZZxLLfIk9j8b8ubGUnxUfMPJmP5HERvRMCTULX-5JpcoRerTlX-3pnfon2sUVIBaiXKQkX1SW1VZOymkx4Qhycraohjm1jpd2NRTqK9wEpY9q3SGWTeB4-d6cShAjRKfS_3oOvdd_KLvJRzfXlXxyls7XTMQv5HZlEfB-OmslMv06EHirCc4I4vrFEumEoCaIkhbr6rgU2r2WsR9WsuhNoGR-oO4uanjA_nYO8JZt4AS1h1DCNKWuU4AHBEdNM1sjKumsin3lHScFMcUxwwTGoUpocAispxyKihBvDkBhnH_erki8YlBake1-sxKHz-gxz5RB_vSJgAAAABCBknZAA"

# Сохраняем в БД
database.save_user_session(USER_ID, SESSION_STRING)

print("✅ Session string успешно добавлен в базу данных!")
print(f"User ID: {USER_ID}")
print(f"Session: {SESSION_STRING[:50]}...")
