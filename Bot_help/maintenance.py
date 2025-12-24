import asyncio
import logging
import os
import signal
from aiogram import Bot, Dispatcher, types
import config

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

@dp.message()
async def echo_maintenance(message: types.Message):
    await message.answer(
        "🛠 **Технический перерыв**\n\n"
        "Прямо сейчас бот обновляется, чтобы стать еще лучше! 🚀\n"
        "Пожалуйста, подождите пару минут. Мы скоро вернемся.",
        parse_mode="Markdown"
    )

async def main():
    # Write PID
    with open("maintenance.pid", "w") as f:
        f.write(str(os.getpid()))
        
    print("Maintenance mode started... Press Ctrl+C to stop (or kill via script)")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Maintenance stopped")
