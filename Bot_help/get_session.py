#!/usr/bin/env python3
"""
Скрипт для получения session string для UserBot
Запустите этот скрипт ОТДЕЛЬНО от основного бота
"""
import asyncio
from pyrogram import Client
import config

async def main():
    print("=" * 50)
    print("Получение Session String для UserBot")
    print("=" * 50)
    print()
    
    # Создаем временного клиента
    app = Client(
        "my_account",
        api_id=config.API_ID,
        api_hash=config.API_HASH
    )
    
    async with app:
        # Экспортируем session string
        session_string = await app.export_session_string()
        
        print("✅ Успешно!")
        print()
        print("Ваш SESSION STRING:")
        print("-" * 50)
        print(session_string)
        print("-" * 50)
        print()
        print("Сохраните этот string в безопасном месте!")
        print("Его нужно будет добавить в базу данных.")
        
        # Получаем информацию о пользователе
        me = await app.get_me()
        print(f"\nАккаунт: {me.first_name} (ID: {me.id})")

if __name__ == "__main__":
    asyncio.run(main())
