import asyncio
import logging
import re
import os
import httpx
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, CommandObject, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ChatMemberUpdated, WebAppInfo
from openai import OpenAI
from groq import Groq
from gigachat import GigaChat
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import yt_dlp
from bs4 import BeautifulSoup
from pypdf import PdfReader
import speech_recognition as sr
from pydub import AudioSegment

from pyrogram import Client, filters as py_filters, enums, errors
from pyrogram.types import Message as PyMessage

import config
import database

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot, dispatcher and scheduler
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Initialize UserBot (Pyrogram)
userbot = Client(
    "userbot_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    device_model="Antigravity Logger"
) if config.API_ID and config.API_HASH else None

# Initialize AI Clients
ai_client = GigaChat(credentials=config.GIGACHAT_CREDENTIALS, verify_ssl_certs=False)

openai_client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None
groq_client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

async def get_ai_response(prompt: str):
    """Universal function to get AI response with fallbacks."""
    # 1. Try GigaChat (Default)
    try:
        response = ai_client.chat(prompt)
        content = response.choices[0].message.content
        if "Как и любая языковая модель" not in content and len(content) > 50:
            return content
    except Exception as e:
        logging.error(f"GigaChat Error: {e}")

    # 2. Try Groq (Llama 3) - Fast and reliable
    if groq_client:
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Groq Error: {e}")

    # 3. Try OpenAI (GPT-4o-mini)
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"OpenAI Error: {e}")

    return "Прости, мои ИИ-мозги временно перегружены. Попробуй позже!"

async def check_deleted_messages():
    """Periodically check if cached messages still exist"""
    try:
        unchecked = database.get_unchecked_messages(limit=30)
        if not unchecked:
            return
        
        logging.info(f"🔍 Checking {len(unchecked)} messages for deletions...")
        
        for msg_id, chat_id, sender_id, text in unchecked:
            # Get the user's UserBot client
            user_client = None
            for uid, client in ub_manager.clients.items():
                user_client = client
                user_id = uid
                break
            
            if not user_client:
                logging.warning("No active UserBot client found")
                return
            
            try:
                # Try to get the message
                messages = await user_client.get_messages(chat_id, msg_id)
                
                if messages.empty:
                    # Message was deleted!
                    logging.info(f"🗑 Message {msg_id} was deleted!")
                    
                    # Get sender info
                    name = "Неизвестный"
                    try:
                        user = await user_client.get_users(sender_id)
                        name = f"{user.first_name} {user.last_name or ''}".strip()
                    except:
                        pass
                    
                    # Send notification
                    notification = (
                        f"🗑 **Удалено сообщение!**\n\n"
                        f"👤 **От:** {name} (ID: {sender_id})\n"
                        f"💬 **Контент:** {text}"
                    )
                    
                    try:
                        await bot.send_message(user_id, notification, parse_mode="Markdown")
                        logging.info(f"✅ Notification sent for deleted message {msg_id}")
                    except Exception as e:
                        logging.error(f"Failed to send notification: {e}")
                    
                    # Remove from cache
                    database.delete_cached_message(msg_id, chat_id)
                else:
                    # Message still exists, mark as checked
                    database.mark_message_checked(msg_id, chat_id)
                    
            except Exception as e:
                # If we get an error, assume message still exists and mark as checked
                logging.debug(f"Error checking message {msg_id}: {e}")
                database.mark_message_checked(msg_id, chat_id)
                
    except Exception as e:
        logging.error(f"Error in check_deleted_messages: {e}")

# States for broadcast, reminders and UserBot setup
class Form(StatesGroup):
    waiting_for_broadcast = State()

class UserBotStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

class SettingsStates(StatesGroup):
    waiting_for_city = State()

# --- UserBot Manager ---

class UserBotManager:
    def __init__(self):
        self.clients = {} # user_id -> Client

    async def start_client(self, user_id: int, session_string: str):
        if user_id in self.clients:
            return
        
        client = Client(
            name=f"session_{user_id}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=session_string,
            in_memory=True
        )
        
        # Register handlers for this client
        @client.on_message(py_filters.private)
        async def py_on_message(c, message: PyMessage):
            # Cache all incoming messages
            content = message.text or message.caption
            if not content:
                if message.photo: content = "[Фотография]"
                elif message.video: content = "[Видео]"
                elif message.voice: content = "[Голосовое сообщение]"
                elif message.audio: content = "[Аудиозапись]"
                elif message.document: content = "[Документ/Файл]"
                elif message.sticker: content = "[Стикер]"
                else: content = "[Медиа-сообщение]"
            
            sender_id = message.from_user.id if message.from_user else 0
            database.cache_message(message.id, message.chat.id, sender_id, content)
            logging.info(f"📝 Cached message {message.id} from {sender_id} in chat {message.chat.id}")

        # NOTE: on_deleted_messages does NOT work for private chats in Telegram!
        # Telegram API doesn't send deletion events for 1-on-1 chats.
        # 
        # Alternative approach: We need to periodically check if cached messages still exist
        # This is a limitation of Telegram's MTProto protocol for privacy reasons.
        
        logging.warning("⚠️ ВАЖНО: Telegram API не поддерживает отслеживание удаленных сообщений в личных чатах!")
        logging.warning("⚠️ Это ограничение самого Telegram, а не бота.")
        logging.warning("⚠️ Отслеживание удалений работает ТОЛЬКО в группах и каналах.")

        try:
            await client.start()
            self.clients[user_id] = client
            logging.info(f"UserBot for user {user_id} started.")
        except Exception as e:
            logging.error(f"Failed to start UserBot for {user_id}: {e}")
            database.delete_user_session(user_id)

    async def stop_client(self, user_id: int):
        client = self.clients.pop(user_id, None)
        if client:
            await client.stop()

ub_manager = UserBotManager()
def admin_only(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id != config.ADMIN_ID:
            await message.answer("У вас нет прав администратора.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# Main Menu Keyboard
@dp.my_chat_member()
async def leave_groups(event: ChatMemberUpdated):
    if event.chat.type in ["group", "supergroup", "channel"]:
        await bot.leave_chat(event.chat.id)
        logging.info(f"Left chat {event.chat.title} ({event.chat.id}) because I am not allowed in groups.")

def get_main_menu():
    # Only one button for the app
    url = config.WEBAPP_URL if hasattr(config, 'WEBAPP_URL') else "https://google.com"
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Открыть меню", web_app=WebAppInfo(url=url))]
    ], resize_keyboard=True)
    return kb

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    database.add_user(message.from_user.id)
    
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Теперь все функции управления находятся в **Мини-приложении**.\n"
        "Нажми кнопку ниже, чтобы управлять задачами, финансами и настройками.\n\n"
        "💬 А здесь ты можешь просто общаться со мной или задавать вопросы ИИ.",
        reply_markup=get_main_menu()
    )

@dp.message(SettingsStates.waiting_for_city)
async def process_city_setup(message: types.Message, state: FSMContext):
    city = message.text.strip()
    database.update_user_city(message.from_user.id, city)
    await message.answer(
        f"✅ Отлично! Город {city} сохранен.\n"
        "Теперь ты можешь пользоваться всеми функциями:",
        reply_markup=get_main_menu()
    )
    await state.clear()

# WebApp Data Handler
@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get('action')
        
        if action == 'update_city':
            city = data.get('city')
            database.update_user_city(message.from_user.id, city)
            await message.answer(f"🏙 Ваш город изменен на: {city}")
            
        elif action == 'add_expense':
            amount = data.get('amount')
            category = data.get('category')
            database.add_expense(message.from_user.id, amount, category)
            await message.answer(f"💸 Расход записан: {amount}₽ на {category}")
            
        elif action == 'add_task':
            text = data.get('text')
            database.add_task(message.from_user.id, text)
            await message.answer(f"✅ Задача добавлена: {text}")
            
        elif action == 'add_habit':
            text = data.get('text')
            database.add_habit(message.from_user.id, text)
            await message.answer(f"💎 Новая привычка: {text}")

        elif action == 'stop_userbot':
            await ub_manager.stop_client(message.from_user.id)
            database.delete_user_session(message.from_user.id)
            await message.answer("🛑 UserBot отключен.")

    except Exception as e:
        logging.error(f"WebApp Error: {e}")
        await message.answer("Ошибка при обработке данных из приложения.")

@dp.message(F.text == "🏙 Сменить город")
async def cmd_change_city(message: types.Message, state: FSMContext):
    await message.answer("Введите название нового города:")
    await state.set_state(SettingsStates.waiting_for_city)

@dp.message(Command("help"))
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    help_text = (
        "🤖 **Что я умею:**\n\n"
        "💰 **Учет расходов:** Просто напиши `сумма категория` (например: `500 обед`).\n"
        "📊 **Финансы:** Кнопка ниже или `/finance` покажет твои траты.\n"
        "📝 **Заметки:** Используй `/note текст`, чтобы я запомнил что-то важное. ИИ будет учитывать это при ответах.\n"
        "⏰ **Напоминания:** Напиши `/remind ЧЧ:ММ текст` (например: `/remind 14:00 Встреча`).\n"
        "🎥 **Скачать видео:** Просто пришли ссылку на YouTube, TikTok или Instagram.\n"
        "☁️ **Утренний дайджест:** Каждый день в 08:00 присылаю сводку погоды и дел.\n\n"
        "💬 **Чат с ИИ:** Просто напиши мне любой вопрос, и я отвечу!"
    )
    await message.answer(help_text, parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("У вас нет прав администратора.")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    await message.answer("Админ-панель:", reply_markup=keyboard)

@dp.callback_query(F.data == "broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("У вас нет прав.")
        return
        
    await callback.message.answer("Введите сообщение для рассылки всем пользователям:")
    await state.set_state(Form.waiting_for_broadcast)
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("У вас нет прав.")
        return
    
    count = database.get_user_count()
    await callback.message.answer(f"Всего пользователей в системе: {count}")
    await callback.answer()

@dp.message(Form.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = database.get_all_users()
    count = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logging.error(f"Failed to send to {user_id}: {e}")
            
    await message.answer(f"Рассылка завершена. Отправлено {count} пользователям.")
    await state.clear()

# Expense Tracker
@dp.message(F.text.regexp(r'^(\d+)\s+(.+)$'))
async def record_expense(message: types.Message):
    match = re.match(r'^(\d+)\s+(.+)$', message.text)
    amount = float(match.group(1))
    category = match.group(2)
    database.add_expense(message.from_user.id, amount, category)
    await message.answer(f"✅ Записал: {amount} на {category}")

@dp.message(F.text == "📊 Финансы")
@dp.message(Command("finance"))
async def cmd_finance(message: types.Message):
    expenses = database.get_expenses(message.from_user.id)
    if not expenses:
        await message.answer("Расходов пока нет.")
        return
    
    report = "📊 Твои последние расходы:\n"
    total = 0
    for amount, cat, ts in expenses[:10]:
        report += f"• {amount} — {cat} ({ts[:10]})\n"
        total += amount
    
    await message.answer(report)

# Smart Notes
@dp.message(Command("note"))
async def cmd_note(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Используйте: /note текст твоей заметки")
        return
    database.add_note(message.from_user.id, command.args)
    await message.answer("📝 Заметка сохранена!")

# Reminder feature
async def send_reminder(user_id: int, text: str):
    try:
        await bot.send_message(user_id, f"🕒 Напоминание: {text}")
    except Exception as e:
        logging.error(f"Failed to send reminder to {user_id}: {e}")

@dp.message(F.text == "📝 Заметка")
async def btn_note(message: types.Message):
    await message.answer("Чтобы сохранить заметку, используй команду: `/note твой текст`", parse_mode="Markdown")

@dp.message(F.text == "⏰ Напомнить")
async def btn_remind(message: types.Message):
    await message.answer("Чтобы поставить напоминание, используй команду: `/remind ЧЧ:ММ текст` (например: `/remind 15:00 Купить хлеб`)", parse_mode="Markdown")

@dp.message(Command("remind"))
async def cmd_remind(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Используйте: /remind ЧЧ:ММ текст напоминания")
        return

    try:
        time_str, reminder_text = command.args.split(" ", 1)
        target_time = datetime.strptime(time_str, "%H:%M").time()
        now = datetime.now()
        run_date = datetime.combine(now.date(), target_time)
        
        if run_date < now:
            await message.answer("Это время уже прошло. Попробуйте на сегодня попозже.")
            return

        scheduler.add_job(send_reminder, 'date', run_date=run_date, args=[message.from_user.id, reminder_text])
        await message.answer(f"Ок! Напомню в {time_str}: {reminder_text}")
    except ValueError:
        await message.answer("Ошибка формата. Пример: /remind 14:00 Сходить в магазин")

# Daily Morning Brief
async def get_weather(city_name: str):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={config.WEATHER_API_KEY}&units=metric&lang=ru"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            data = r.json()
            if r.status_code != 200:
                return f"Ошибка: {data.get('message', 'Неизвестная ошибка')}"
            
            temp = data['main']['temp']
            desc = data['weather'][0]['description']
            return f"{temp}°C, {desc}"
    except Exception as e:
        return f"Ошибка получения погоды: {e}"


async def get_currency():
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            data = r.json()
            return f"{data['rates']['RUB']:.2f} руб."
    except:
        return "98.40 руб. (ошибка API)"

async def send_morning_brief():
    users = database.get_all_users()
    currency = await get_currency()
    
    for user_id in users:
        city = database.get_user_city(user_id)
        weather = await get_weather(city)
        
        brief = f"☀️ Доброе утро! Вот твой утренний дайджест ({city}):\n"
        brief += f"🌡 Погода: {weather}\n"
        brief += f"💵 Курс USD: {currency}\n"
        brief += "📅 Не забудь проверить свои дела на сегодня!"
        
        try:
            await bot.send_message(user_id, brief)
        except Exception as e:
            logging.error(f"Failed to send brief to {user_id}: {e}")

@dp.message(F.text == "🌦 Погода")
async def btn_weather(message: types.Message):
    city = database.get_user_city(message.from_user.id)
    weather = await get_weather(city)
    await message.answer(f"🌡 Погода в {city}: {weather}")

# To-Do List
@dp.message(Command("todo"))
async def cmd_todo(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Используйте: /todo текст задачи")
        return
    database.add_task(message.from_user.id, command.args)
    await message.answer(f"✅ Задача добавлена: {command.args}")

@dp.message(F.text == "📋 Задачи")
@dp.message(Command("tasks"))
async def cmd_tasks(message: types.Message):
    tasks = database.get_tasks(message.from_user.id)
    if not tasks:
        await message.answer("У тебя нет активных задач! 🎉")
        return
    
    kb = []
    text = "📋 Твои задачи:\n"
    for tid, ttext, _ in tasks:
        text += f"• {ttext}\n"
        kb.append([InlineKeyboardButton(text=f"✅ {ttext[:20]}...", callback_data=f"done_{tid}")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("done_"))
async def process_task_done(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    database.complete_task(task_id)
    await callback.message.edit_text(callback.message.text + "\n\n(Обновлено: задача выполнена!)")
    await callback.answer("Молодец!")

# Habit Tracker
@dp.message(Command("addhabit"))
async def cmd_add_habit(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Используйте: /addhabit название привычки")
        return
    database.add_habit(message.from_user.id, command.args)
    await message.answer(f"🚀 Привычка '{command.args}' добавлена! Буду напоминать о ней вечером.")

@dp.message(F.text == "💎 Привычки")
@dp.message(Command("habits"))
async def cmd_habits(message: types.Message):
    habits = database.get_habits(message.from_user.id)
    if not habits:
        await message.answer("У тебя пока нет привычек. Добавь: /addhabit")
        return
    
    kb = []
    for hid, name in habits:
        kb.append([InlineKeyboardButton(text=f"💎 {name}", callback_data=f"log_{hid}")])
    
    await message.answer("Твои привычки (нажми, чтобы отметить выполнение за сегодня):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("log_"))
async def process_habit_log(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    today = datetime.now().date().isoformat()
    database.log_habit(habit_id, callback.from_user.id, today)
    await callback.answer("Отлично! Засчитано.")

# Media Downloader (yt-dlp)
@dp.message(F.text.regexp(r'https?://(www\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)/'))
async def download_media(message: types.Message):
    url = re.search(r'https?://[^\s]+', message.text).group(0)
    await message.answer("⏳ Начинаю загрузку видео, это может занять минуту...")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'max_filesize': 50000000, # 50MB
    }
    
    try:
        if not os.path.exists('downloads'):
            os.makedirs('downloads')
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
        video = FSInputFile(filename)
        await message.answer_video(video, caption="Вот твое видео!")
        os.remove(filename)
    except Exception as e:
        logging.error(f"Download Error: {e}")
        await message.answer("❌ Не удалось скачать видео. Возможно, оно слишком тяжелое или ссылка не поддерживается.")

# Summarizer (Articles)
@dp.message(F.text.regexp(r'https?://(?!www\.youtube|youtu\.be|tiktok\.com|instagram\.com)[^\s]+'))
async def summarize_link(message: types.Message):
    url = message.text
    await message.answer("⏳ Читаю статью и готовлю краткий пересказ...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            r = await client.get(url, timeout=15.0)
            soup = BeautifulSoup(r.text, 'html.parser')
            # Filter out scripts, styles, and small navigation texts
            for script_or_style in soup(["script", "style", "nav", "footer", "header"]):
                script_or_style.decompose()
                
            paragraphs = [p.get_text().strip() for p in soup.find_all(['p', 'h1', 'h2'])]
            text = " ".join([p for p in paragraphs if len(p) > 20])[:6000]
            
        if not text:
            await message.answer("❌ Не удалось извлечь текст из статьи. Попробуй другую ссылку.")
            return

        prompt = (
            "Твоя задача — сделать качественный и объективный пересказ статьи на русском языке. "
            "Избегай общих фраз и дисклеймеров. Пиши сразу по существу.\n\n"
            f"Текст статьи:\n{text}"
        )
        
        summary = await get_ai_response(prompt)
        await message.answer(f"📝 **Краткое содержание:**\n\n{summary}", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Summarize Error: {e}")
        await message.answer("❌ Не удалось прочитать статью. Возможно, доступ заблокирован.")

# Summarizer (PDF)
@dp.message(F.document.mime_type == "application/pdf")
async def summarize_pdf(message: types.Message):
    await message.answer("⏳ Анализирую PDF-документ...")
    
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = f"downloads/{file_id}.pdf"
    
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await bot.download_file(file.file_path, file_path)
    
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages[:5]: # Only first 5 pages for brevity
            text += page.extract_text() + " "
        text = text[:4000]
        
        prompt = f"Сделай краткий пересказ этого документа (самая суть):\n\n{text}"
        summary = await get_ai_response(prompt)
        await message.answer(f"📄 **Суть документа:**\n\n{summary}", parse_mode="Markdown")
        os.remove(file_path)
    except Exception as e:
        logging.error(f"PDF Error: {e}")
        await message.answer("❌ Ошибка при чтении PDF.")

# Voice-to-Text
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await message.answer("🎤 Обрабатываю твое голосовое...")
    
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    ogg_path = f"downloads/{file_id}.ogg"
    wav_path = f"downloads/{file_id}.wav"
    
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await bot.download_file(file.file_path, ogg_path)
    
    try:
        # Convert OGG to WAV
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")
        
        # Recognize Speech
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            
        await message.answer(f"🗣 **Я услышал:**\n_{text}_\n\n(Передаю этот запрос нейросети...)", parse_mode="Markdown")
        
        # Pass recognized text to AI
        await message.answer(await get_ai_response(text))
        
        os.remove(ogg_path)
        os.remove(wav_path)
    except Exception as e:
        logging.error(f"Voice Error: {e}")
        await message.answer("❌ Не удалось распознать голос. Попробуй говорить четче!")

@dp.message(F.text == "📧 Почта")
@dp.message(Command("tempmail"))
async def cmd_tempmail(message: types.Message):
    # Check if user already has an email
    existing_email = database.get_temp_email(message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить почту", callback_data="check_mail")],
        [InlineKeyboardButton(text="🆕 Сгенерировать новый", callback_data="new_mail")]
    ])
    
    if existing_email:
        await message.answer(f"Твой текущий адрес:\n`{existing_email}`\n\nИспользуй его для регистраций или создай новый.", reply_markup=kb, parse_mode="Markdown")
    else:
        await generate_new_email(message, kb)

async def generate_new_email(message, kb):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        async with httpx.AsyncClient() as client:
            # Get available domains
            dr = await client.get("https://www.1secmail.com/api/v1/?action=getDomainList")
            domains = dr.json()
            domain = domains[0] if domains else "1secmail.com"
            
            import random
            import string
            login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            email = f"{login}@{domain}"
            
            database.save_temp_email(message.from_user.id, email)
            await message.answer(f"✅ Создан новый адрес:\n`{email}`\n\nОжидай письма и нажимай кнопку ниже.", reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Generate Mail Error: {e}")
        await message.answer("❌ Ошибка при создании почты.")

@dp.callback_query(F.data == "new_mail")
async def process_new_mail(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить почту", callback_data="check_mail")],
        [InlineKeyboardButton(text="🆕 Сгенерировать новый", callback_data="new_mail")]
    ])
    await generate_new_email(callback.message, kb)
    await callback.answer()

@dp.callback_query(F.data == "check_mail")
async def process_check_mail(callback: types.CallbackQuery):
    email = database.get_temp_email(callback.from_user.id)
    if not email:
        await callback.answer("Сначала создай почту!")
        return
        
    login, domain = email.split("@")
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            messages = r.json()
            
            if not messages:
                await callback.answer("Писем пока нет. Попробуй позже.", show_alert=True)
                return
            
            res_text = "📩 **Новые письма:**\n\n"
            for m in messages[:5]: # Last 5 messages
                m_id = m['id']
                m_from = m['from']
                m_subject = m['subject']
                m_date = m['date']
                
                # Fetch full message content
                msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={m_id}"
                mr = await client.get(msg_url)
                msg_data = mr.json()
                content = msg_data['textBody'] if msg_data['textBody'] else msg_data['htmlBody']
                
                res_text += f"👤 От: {m_from}\n📅 Дата: {m_date}\n📌 Тема: {m_subject}\n\n{content[:500]}...\n---\n"
            
            await callback.message.answer(res_text, parse_mode="Markdown")
            await callback.answer()
    except Exception as e:
        logging.error(f"Mail Check Error: {e}")
        await callback.answer("Ошибка при проверке почты.")


# --- UserBot Setup Handlers ---

@dp.message(F.text == "🕵️ UserBot")
@dp.message(Command("userbot"))
async def cmd_userbot(message: types.Message, state: FSMContext):
    session = database.get_user_session(message.from_user.id)
    if session:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔴 Отключить", callback_data="ub_stop")]])
        await message.answer("✅ У вас уже подключен UserBot для отслеживания удаленных сообщений.", reply_markup=kb)
        return

    await message.answer(
        "🕵️ **Настройка UserBot**\n\n"
        "Эта функция позволит мне видеть удаленные сообщения в ваших личных диалогах.\n"
        "Для этого мне нужно временно авторизоваться под вашим аккаунтом.\n\n"
        "Введите ваш номер телефона в международном формате (например: `+79991234567`):",
        parse_mode="Markdown"
    )
    await state.set_state(UserBotStates.waiting_for_phone)

@dp.callback_query(F.data == "ub_stop")
async def process_ub_stop(callback: types.CallbackQuery):
    await ub_manager.stop_client(callback.from_user.id)
    database.delete_user_session(callback.from_user.id)
    await callback.message.edit_text("🔴 UserBot отключен. Данные сессии удалены.")
    await callback.answer()

@dp.message(UserBotStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    if not phone.startswith("+"):
        await message.answer("Пожалуйста, введите номер, начиная с +")
        return

    temp_client = Client(
        name=f"temp_{message.from_user.id}",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        in_memory=True
    )
    await temp_client.connect()
    try:
        code_info = await temp_client.send_code(phone)
        await state.update_data(phone=phone, phone_code_hash=code_info.phone_code_hash, temp_client=temp_client)
        await message.answer("📲 Код подтверждения отправлен в ваш Telegram. Введите его:")
        await state.set_state(UserBotStates.waiting_for_code)
    except Exception as e:
        logging.error(f"Send code error: {e}")
        await message.answer(f"❌ Ошибка: {e}. Попробуйте позже.")
        await temp_client.disconnect()
        await state.clear()

@dp.message(UserBotStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_client = data['temp_client']
    code = message.text.strip()

    try:
        await temp_client.sign_in(data['phone'], data['phone_code_hash'], code)
    except errors.SessionPasswordNeeded:
        await message.answer("🔐 У вас включена двухфакторная аутентификация. Введите ваш пароль:")
        await state.set_state(UserBotStates.waiting_for_password)
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await temp_client.disconnect()
        await state.clear()
        return

    await finalize_ub_login(message, state, temp_client)

@dp.message(UserBotStates.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    temp_client = data['temp_client']
    password = message.text.strip()

    try:
        await temp_client.check_password(password)
    except Exception as e:
        await message.answer(f"❌ Неверный пароль или ошибка: {e}")
        return

    await finalize_ub_login(message, state, temp_client)

async def finalize_ub_login(message: types.Message, state: FSMContext, temp_client: Client):
    session_string = await temp_client.export_session_string()
    database.save_user_session(message.from_user.id, session_string)
    
    await ub_manager.start_client(message.from_user.id, session_string)
    await temp_client.disconnect()
    
    await message.answer("🎉 **Готово!**\nТеперь я буду присылать уведомления, если кто-то удалит сообщение в вашем ЛС.", parse_mode="Markdown")
    await state.clear()


# --- Old single-user code removed ---
# (Removing the manual userbot initialization and handlers)

# AI logic (enhanced with notes) - MUST BE LAST HANDLER
@dp.message()
async def chat_with_ai(message: types.Message):
    if not message.text:
        return

    await bot.send_chat_action(message.chat.id, "typing")
    
    # Get user notes for context
    notes = database.get_notes(message.from_user.id)
    notes_context = "\n".join(notes[-10:]) if notes else "Заметок нет."
    
    try:
        prompt = f"Заметки пользователя:\n{notes_context}\n\nВопрос: {message.text}"
        ai_response = await get_ai_response(prompt)
        await message.answer(ai_response)
    except Exception as e:
        logging.error(f"AI Error: {e}")
        await message.answer("Прости, мой ИИ-мозг временно недоступен. Попробуй позже!")

async def main():
    database.init_db()
    
    # Save PID for management scripts
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))
    
    # Schedule jobs
    scheduler.add_job(send_morning_brief, 'cron', hour=8, minute=0)
    scheduler.add_job(database.cleanup_old_messages, 'cron', hour=4, minute=0)
    scheduler.add_job(check_deleted_messages, 'interval', minutes=2)  # Check every 2 minutes
    scheduler.start()
    
    # Start saved user sessions
    sessions = database.get_all_sessions()
    for user_id, session_str in sessions:
        await ub_manager.start_client(user_id, session_str)
    
    logging.info("Starting Aiogram Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
