import asyncio
import logging
import re
import os
import httpx
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command, CommandObject, ChatMemberUpdatedFilter, JOIN_TRANSITION, StateFilter
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

# Charts removed in favor of text stats
CHARTS_AVAILABLE = False
    
try:
    from pydub import AudioSegment
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    logging.warning("Pydub not found. Voice features disabled.")

from pyrogram import Client, filters as py_filters, enums, errors
from pyrogram.types import Message as PyMessage

import config
import database

# Extract Bot ID for filtering loopback messages
try:
    BOT_ID = int(config.BOT_TOKEN.split(':')[0])
except:
    BOT_ID = 0

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
        # Iterate over all connected userbots
        for user_id, client in ub_manager.clients.items():
            if not client.is_connected:
                continue
                
            # Get cached messages to check (last 100)
            cached_msgs = database.get_messages_for_check(user_id)
            if not cached_msgs:
                continue
                
            # Group by chat_id to batch requests
            # {chat_id: {msg_id: (content, sname, sid, mtype, fid, s_username)}}
            chats_to_check = {}
            for row in cached_msgs:
                if len(row) == 8: # Compatibility helper with username
                    mid, cid, sid, content, sname, mtype, fid, s_username = row
                elif len(row) == 7: # Old compat
                    mid, cid, sid, content, sname, mtype, fid = row
                    s_username = None
                else:
                    mid, cid, sid, content, sname = row
                    mtype, fid, s_username = None, None, None
                    
                if cid not in chats_to_check: chats_to_check[cid] = {}
                chats_to_check[cid][mid] = (content, sname, sid, mtype, fid, s_username)

            # Check each chat
            for chat_id, messages_dict in chats_to_check.items():
                msg_ids = list(messages_dict.keys())
                try:
                    # Batch request to Telegram
                    current_messages = await client.get_messages(chat_id, msg_ids)
                    
                    # Ensure it's a list even if 1 message
                    if not isinstance(current_messages, list):
                        current_messages = [current_messages]
                        
                    # logging.info(f"🔍 Checking {len(current_messages)} messages in chat {chat_id}")
                        
                    # Check statuses
                    for i, msg_obj in enumerate(current_messages):
                        original_msg_id = msg_ids[i]
                        # unpack cached data
                        content, sname, sid, mtype, fid, s_username = messages_dict[original_msg_id]
                        
                        is_deleted = False
                        if msg_obj is None: is_deleted = True
                        elif hasattr(msg_obj, 'empty') and msg_obj.empty: is_deleted = True
                        
                        if is_deleted:
                            # Notify user via main bot
                            username_text = f"(@{s_username})\n" if s_username else ""
                            alert_text = (
                                f"🗑 **Удаленное сообщение!**\n"
                                f"👤 От: {sname} {username_text}"
                                f"💬 Текст: {content}\n"
                            )
                            
                            # Try to recover media if present
                            if mtype and fid:
                                try:
                                    # Send to Saved Messages (UserBot self)
                                    if mtype == "photo":
                                        await client.send_photo("me", fid, caption="🗑 Восстановленное фото")
                                    elif mtype == "video":
                                        await client.send_video("me", fid, caption="🗑 Восстановленное видео")
                                    elif mtype == "voice":
                                        await client.send_voice("me", fid, caption="🗑 Восстановленное голосовое")
                                    elif mtype == "audio":
                                        await client.send_audio("me", fid, caption="🗑 Восстановленное аудио")
                                    elif mtype == "document":
                                        await client.send_document("me", fid, caption="🗑 Восстановленный файл")
                                    elif mtype == "sticker":
                                        await client.send_sticker("me", fid)
                                    elif mtype == "video_note":
                                        await client.send_video_note("me", fid)
                                    elif mtype == "animation":
                                        await client.send_animation("me", fid, caption="🗑 Восстановленная GIF")
                                        
                                    alert_text += "\n💾 **Медиафайл сохранен в 'Избранное' (Saved Messages).**"
                                except Exception as e:
                                    alert_text += f"\n❌ Не удалось восстановить медиа: {e}"

                            await bot.send_message(user_id, alert_text, parse_mode="HTML")
                            logging.info(f"✅ Alert sent for msg {original_msg_id}")
                            
                            # Remove from cache
                            database.delete_cached_message(original_msg_id, chat_id)
                        else:
                            # Message exists.
                            # We don't need to do anything, it stays in cache for next check.
                            pass
                            
                except (ValueError, KeyError, IndexError) as e:
                     # This happens if we try to check messages in a chat the bot hasn't "seen" in this session,
                     # or if the peer ID is invalid. We just skip this chat for now.
                     # logging.warning(f"Could not check messages in chat {chat_id}: {e}")
                     pass
                except Exception as e:
                    logging.debug(f"Error checking chat {chat_id}: {e}")
                    
    except Exception as e:
        logging.error(f"Global check error: {e}")

# States for broadcast, reminders and UserBot setup
class Form(StatesGroup):
    waiting_for_broadcast = State()

class UserBotStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()
    waiting_for_session_string = State()

class SettingsStates(StatesGroup):
    waiting_for_city = State()
    waiting_for_category = State()

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
        # Listen to ALL messages (Private + Groups) to support global deletion tracking
        @client.on_message()
        async def py_on_message(c, message: PyMessage):
            # Cache all incoming messages from others
            if message.from_user and message.from_user.is_self:
                return
            
            # Helper logging to debug "Not working" issues
            logging.info(f"📩 Получено сообщение: {message.chat.id} | {message.from_user.id if message.from_user else 'Anon'}")

            # Ignore messages from the main bot to avoid loops
            if message.chat.id == BOT_ID or (message.from_user and message.from_user.id == BOT_ID):
                return

            # Extract sender info early
            sender_id = message.from_user.id if message.from_user else 0
            sender_name = message.from_user.first_name if message.from_user else "Unknown"
            sender_username = message.from_user.username if message.from_user and message.from_user.username else None

            # Robust Media Detection
            media_type = None
            file_id = None
            content = message.text or message.caption or ""
            
            # Helper to safely get file_id
            def get_fid(obj):
                return getattr(obj, "file_id", None)

            if message.photo:
                media_type = "photo"
                file_id = get_fid(message.photo)
                if not content: content = "[Фотография]"
            elif message.video:
                media_type = "video"
                file_id = get_fid(message.video)
                if not content: content = "[Видео]"
            elif message.video_note:
                media_type = "video_note"
                file_id = get_fid(message.video_note)
                if not content: content = "[Видеокружок]"
            elif message.voice:
                media_type = "voice"
                file_id = get_fid(message.voice)
                if not content: content = "[Голосовое сообщение]"
            elif message.audio:
                media_type = "audio"
                file_id = get_fid(message.audio)
                if not content: content = "[Аудиозапись]"
            elif message.document:
                media_type = "document"
                file_id = get_fid(message.document)
                if not content: content = "[Документ/Файл]"
            elif message.sticker:
                media_type = "sticker"
                file_id = get_fid(message.sticker)
                if not content: content = "[Стикер]"
            elif message.animation:
                media_type = "animation"
                file_id = get_fid(message.animation)
                if not content: content = "[GIF/Анимация]"
            
            # Fallback for ANY other media
            if not media_type and getattr(message, "media", None):
                # Try to infer from the media enum string
                raw_media = str(message.media)
                if "PHOTO" in raw_media: media_type = "photo"
                elif "VIDEO_NOTE" in raw_media: media_type = "video_note"
                elif "VIDEO" in raw_media: media_type = "video"
                elif "VOICE" in raw_media: media_type = "voice"
                else: media_type = "document"
                
                content = f"[Медиа: {raw_media}]"
                # If we found media but standard parsing failed, set file_id to something non-None to allow download
                if not file_id:
                     file_id = "unknown_but_present"

            if not content:
                content = "[Неизвестный тип]"
                # DEBUG: Log the full message structure for unknown types to see what we are missing
                logging.warning(f"⚠️ Неизвестный тип сообщения! Структура: {message}")

            # Check for view-once (self-destructing) media
            is_protected = getattr(message, "protected_content", False) or getattr(message, "has_protected_content", False)
            has_ttl = False
            
            # Check TTL on message object
            if hasattr(message, 'ttl_seconds') and message.ttl_seconds:
                has_ttl = True
            
            # Additional check for media-specific TTL
            if not has_ttl:
                # Deep check for nested TTL
                for attr in ['photo', 'video', 'voice', 'video_note', 'audio', 'document', 'animation']:
                    obj = getattr(message, attr, None)
                    if obj and hasattr(obj, 'ttl_seconds') and obj.ttl_seconds:
                        has_ttl = True
                        break

            if is_protected or has_ttl:
                 # Update content text regardless of whether we identified the exact type
                 content = f"[🔐 Секретное медиа ({media_type or 'Файл'})] {content}"
                 # Ensure we don't duplicate tags if the loop runs for some reason
                 if "(Сгорающее/Секретное)" not in content:
                    content += " (Сгорающее/Секретное)"
                 
                 logging.info(f"🕵️ Обнаружен секретный контент от {sender_name}. Пробую сохранить...")
                 
                 try:
                    await client.send_message("me", f"🔐 Начинаю загрузку секретного медиа от {sender_name}...")
                    file_path = await message.download()
                    
                    if file_path:
                        caption_text = f"🔐 Секретное медиа от {sender_name} ({sender_id})"
                        
                        sent = False
                        if media_type == "photo":
                            sent = await client.send_photo("me", file_path, caption=caption_text)
                        elif media_type == "video":
                            sent = await client.send_video("me", file_path, caption=caption_text)
                        elif media_type == "voice":
                            sent = await client.send_voice("me", file_path, caption=caption_text)
                        elif media_type == "video_note":
                            sent = await client.send_video_note("me", file_path)
                            await client.send_message("me", caption_text)
                        elif media_type == "audio":
                            sent = await client.send_audio("me", file_path, caption=caption_text)
                        elif media_type == "animation":
                            sent = await client.send_animation("me", file_path, caption=caption_text)
                        
                        # Fallback: Send as Document if type unknown or specific send failed (but file exists)
                        if not sent:
                            await client.send_document("me", file_path, caption=caption_text + " (Как файл)")

                        logging.info(f"✅ Секретный контент сохранен в Saved Messages: {file_path}")
                        
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    else:
                        logging.error("❌ Download failed (file_path is None)")
                        
                 except Exception as e:
                     logging.error(f"Failed to auto-save protected media: {e}")
                     await client.send_message("me", f"❌ Не удалось сохранить секретное медиа от {sender_name}: {e}")

            
            database.cache_message(
                message.id, 
                message.chat.id, 
                user_id, 
                sender_id, 
                content,
                sender_name,
                media_type,
                file_id,
                sender_username
            )

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
        [KeyboardButton(text="📱 Открыть меню", web_app=WebAppInfo(url=url))],
        [KeyboardButton(text="📧 Временная почта"), KeyboardButton(text="🌦 Погода")],
        [KeyboardButton(text="💰 Финансы")]
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



# WebApp Data Handler
@dp.message(F.content_type == types.ContentType.WEB_APP_DATA)
async def handle_webapp_data(message: types.Message):
    logging.info(f"📲 Received WebApp Data: {message.web_app_data.data}")
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
            time = data.get('time') # "HH:MM" or ""
            if not time:
                time = None
            database.add_habit(message.from_user.id, text, time)
            msg = f"💎 Новая привычка: {text}"
            if time:
                msg += f"\n⏰ Напоминание в {time}"
            await message.answer(msg)

        elif action == 'stop_userbot':
            await ub_manager.stop_client(message.from_user.id)
            database.delete_user_session(message.from_user.id)
            await message.answer("🛑 UserBot отключен.")

        elif action == 'get_stats':
            await send_expense_chart(message)

        elif action == 'manage_categories':
            await send_delete_categories_menu(message)

    except Exception as e:
        logging.error(f"WebApp Error: {e}")
        await message.answer("Ошибка при обработке данных из приложения.")

@dp.message(F.text == "❓ Помощь")
@dp.message(Command("help"))
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

@dp.message(F.text == "🧹 Очистить чат")
@dp.message(Command("clear_ai"))
async def cmd_clear_ai(message: types.Message):
    # Currently context is not stored persistently, but if we add memory later, clear it here.
    # For now, we just inform the user.
    await message.answer("🧹 Контекст общения с ИИ очищен! Я забыл всё, о чем мы говорили (кроме ваших заметок).")

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

# Manage Categories
# Manage Categories
async def send_delete_categories_menu(message: types.Message, user_id: int = None):
    if user_id is None:
        user_id = message.from_user.id
        # In private chat with bot, user_id is chat.id
        if message.from_user.is_bot:
            user_id = message.chat.id

    try:
        categories = database.get_categories(user_id)
        
        if not categories:
            await message.answer("У вас пока нет категорий.")
            return

        buttons = []
        for cat in categories:
            buttons.append([InlineKeyboardButton(text=f"❌ {cat}", callback_data=f"del_cat_{cat}")])
        
        buttons.append([InlineKeyboardButton(text="Отмена", callback_data="cancel_del_cat")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите категорию для удаления (все расходы в ней будут удалены!):", reply_markup=kb)
        
    except Exception as e:
        logging.error(f"Cat Menu Error: {e}")
        await message.answer("Ошибка списка категорий.")

@dp.callback_query(F.data.startswith("del_cat_"))
async def process_delete_category(callback: types.CallbackQuery):
    category = callback.data.replace("del_cat_", "")
    database.delete_expenses_by_category(callback.from_user.id, category)
    await callback.answer(f"Категория '{category}' и все расходы удалены.")
    await callback.message.edit_text(f"✅ Категория **{category}** удалена.", parse_mode="Markdown")

@dp.callback_query(F.data == "cancel_del_cat")
async def process_cancel_delete_cat(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.message(Command("finance"))
@dp.message(F.text == "💰 Финансы")
async def cmd_finance(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мои расходы", callback_data="fin_stats")],
        [InlineKeyboardButton(text="➕ Добавить категорию", callback_data="fin_add_cat")],
        [InlineKeyboardButton(text="❌ Удалить категорию", callback_data="fin_del_cat_menu")]
    ])
    await message.answer("💰 **Управление финансами**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "fin_stats")
async def cb_fin_stats(callback: types.CallbackQuery):
    await send_expense_chart(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "fin_add_cat")
async def cb_fin_add_cat(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введите название новой категории:")
    await state.set_state(SettingsStates.waiting_for_category)
    await callback.answer()

@dp.message(SettingsStates.waiting_for_category)
async def process_new_category(message: types.Message, state: FSMContext):
    cat_name = message.text.strip()
    database.add_category(message.from_user.id, cat_name)
    await message.answer(f"✅ Категория **{cat_name}** сохранена!", parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "fin_del_cat_menu")
async def cb_fin_del_cat_menu(callback: types.CallbackQuery):
    # Pass explicit user_id because callback.message.from_user is the bot
    await send_delete_categories_menu(callback.message, user_id=callback.from_user.id)
    await callback.answer()

# Daily Morning Brief
async def send_expense_chart(message: types.Message):
    # If message is from bot (callback), use chat.id as user_id approximation or handle better
    # But usually send_expense_chart is called with user message or we need to pass user_id
    
    # Check if message is from bot
    user_id = message.from_user.id
    if message.from_user.is_bot:
         # In private chat, chat.id is user_id
         user_id = message.chat.id
         
    try:
        conn = database.sqlite3.connect(database.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id = ? GROUP BY category", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await message.answer("📊 У вас пока нет расходов для статистики.")
            return

        total = sum(row[1] for row in rows)
        text = "📊 <b>Ваши расходы:</b>\n\n"
        
        # Sort by amount desc
        rows.sort(key=lambda x: x[1], reverse=True)
        
        for category, amount in rows:
            percent = (amount / total) * 100
            text += f"▫️ <b>{category}</b>: {amount:.0f}₽ ({percent:.1f}%)\n"
            
        text += f"\n💰 <b>Всего:</b> {total:.0f}₽"
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Stats Error: {e}")
        await message.answer("Не удалось получить статистику.")

async def get_weather(lat=None, lon=None, city_name=None):
    if not config.WEATHER_API_KEY:
        return "Ключ погоды не настроен."
    
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "appid": config.WEATHER_API_KEY,
            "units": "metric",
            "lang": "ru"
        }
        
        if lat and lon:
            params["lat"] = lat
            params["lon"] = lon
        elif city_name:
            params["q"] = city_name
        else:
            return "Не указана локация"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params)
            data = r.json()
            if r.status_code != 200:
                return f"Ошибка: {data.get('message', 'Неизвестная ошибка')}"
            
            temp = data['main']['temp']
            desc = data['weather'][0]['description']
            place = data.get('name', 'Неизвестное место')
            return f"{temp}°C, {desc} ({place})"
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
        loc = database.get_user_location(user_id)
        if loc:
            weather = await get_weather(lat=loc[0], lon=loc[1])
        else:
            city = database.get_user_city(user_id)
            weather = await get_weather(city_name=city)
        
        brief = f"☀️ Доброе утро! Вот твой утренний дайджест:\n"
        brief += f"🌡 Погода: {weather}\n"
        brief += f"💵 Курс USD: {currency}\n"
        brief += "📅 Не забудь проверить свои дела на сегодня!"
        
        try:
            await bot.send_message(user_id, brief)
        except Exception as e:
            logging.error(f"Failed to send brief to {user_id}: {e}")

@dp.message(F.location)
async def handle_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude
    database.update_user_location(message.from_user.id, lat, lon)
    
    weather = await get_weather(lat=lat, lon=lon)
    await message.answer(f"✅ Локация сохранена!\n🌡 Погода здесь: {weather}", reply_markup=get_main_menu())

@dp.message(F.text == "🌦 Погода")
async def btn_weather(message: types.Message):
    loc = database.get_user_location(message.from_user.id)
    text = ""
    if loc:
        weather = await get_weather(lat=loc[0], lon=loc[1])
        text = f"🌡 Текущая погода: {weather}\n\n📍 Ищем по вашим координатам."
    else:
        city = database.get_user_city(message.from_user.id)
        weather = await get_weather(city_name=city)
        text = f"🌡 Погода в {city}: {weather}\n\n🏙 Используется город по умолчанию."

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Обновить геопозицию", request_location=True)],
        [KeyboardButton(text="🔙 Назад в меню")]
    ], resize_keyboard=True)
    
    await message.answer(text, reply_markup=kb)

@dp.message(F.text == "🔙 Назад в меню")
@dp.message(F.text == "Отмена")
async def cancel_action(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_menu())

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

# --- TEMPORARY MAIL (Mail.tm API) ---
@dp.message(F.text == "📧 Временная почта")
async def cmd_temp_mail(message: types.Message):
    # 1. Get Domain
    # 2. Create Account
    try:
        async with httpx.AsyncClient() as client:
            # Get domains
            resp = await client.get("https://api.mail.tm/domains")
            if resp.status_code != 200: raise Exception("Domains error")
            domain_data = resp.json()['hydra:member'][0]['domain']
            
            # Generate credentials
            import random, string
            username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            email = f"{username}@{domain_data}"
            
            # Create account
            reg_resp = await client.post("https://api.mail.tm/accounts", json={
                "address": email,
                "password": password
            })
            
            if reg_resp.status_code != 201:
                raise Exception(f"Registration failed: {reg_resp.text}")
            
            # Provide button with password embedded (to get token later)
            # Format: check_mail_email:password
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📬 Проверить входящие", callback_data=f"check_mail_{email}:{password}")]
            ])
            
            await message.answer(
                f"📧 <b>Ваш временный адрес:</b>\n<code>{email}</code>\n\n"
                "Нажмите кнопку ниже, чтобы проверить новые письма.",
                parse_mode="HTML",
                reply_markup=kb
            )
    except Exception as e:
        logging.error(f"Temp mail error: {e}")
        await message.answer(f"Ошибка сервиса почты: {e}")

@dp.callback_query(F.data.startswith("check_mail_"))
async def check_temp_mail(callback: types.CallbackQuery):
    # Format: check_mail_email:password
    data = callback.data.replace("check_mail_", "")
    email, password = data.split(":")
    
    try:
        async with httpx.AsyncClient() as client:
            # Get Token
            token_resp = await client.post("https://api.mail.tm/token", json={
                "address": email,
                "password": password
            })
            
            if token_resp.status_code != 200:
                await callback.answer("Ошибка авторизации почты.", show_alert=True)
                return
                
            token = token_resp.json()['token']
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get Messages
            msgs_resp = await client.get("https://api.mail.tm/messages", headers=headers)
            messages = msgs_resp.json()['hydra:member']
            
            if not messages:
                await callback.answer("📭 Входящих писем нет.", show_alert=True)
                return
            
            # Show messages
            text = f"📬 <b>Входящие ({len(messages)}):</b>\n\n"
            for msg in messages[:5]:
                sender = msg['from']['address']
                subject = msg['subject']
                intro = msg.get('intro', 'Empty body')
                text += f"🔹 <b>От:</b> {sender}\n<b>Тема:</b> {subject}\n<b>Текст:</b> {intro}\n\n"
            
            await callback.message.answer(text, parse_mode="HTML")
            await callback.answer()
            
    except Exception as e:
        logging.error(f"Check mail error: {e}")
        await callback.answer("Ошибка проверки почты.", show_alert=True)

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
    if not VOICE_AVAILABLE:
        await message.answer("⚠️ Обработка голосовых недоступна (pydub не установлен).")
        return
        
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

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 Подключить", callback_data="ub_connect")]])
    await message.answer(
        "🕵️ **Настройка UserBot**\n\n"
        "Эта функция позволит мне видеть удаленные сообщения в ваших личных диалогах.\n"
        "Для этого мне нужно временно авторизоваться под вашим аккаунтом.\n\n"
        "Нажмите кнопку ниже, чтобы начать подключение.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "ub_stop")
async def process_ub_stop(callback: types.CallbackQuery):
    await ub_manager.stop_client(callback.from_user.id)
    database.delete_user_session(callback.from_user.id)
    await callback.message.edit_text("🔴 UserBot отключен. Данные сессии удалены.")
    await callback.answer()

@dp.callback_query(F.data == "ub_connect")
async def process_ub_connect(callback: types.CallbackQuery, state: FSMContext):
    # Instead of interactive login (which fails due to IP/timeouts), ask for session string
    await callback.message.edit_text(
        "🔐 **Авторизация UserBot**\n\n"
        "1. Перейдите на [my.telegram.org](https://my.telegram.org), залогиньтесь и выберите 'API development tools'.\n"
        "2. Создайте новое приложение. Нажимайте на текст ниже, чтобы скопировать:\n"
        "   • App title: `MyUserBot`\n"
        "   • Short name: `my_bot_123`\n"
        "   • URL: `http://localhost`\n"
        "   • Platform: Desktop\n"
        "   Нажмите 'Create application'.\n"
        "   ⚠️ **Если сайт выдает ошибку [object Object]:** Попробуйте с мобильного интернета или используйте эти публичные ключи (Android):\n"
        "   `api_id` = `6`\n"
        "   `api_hash` = `eb06d4abfb49dc3eeb1aeb98ae0f581e`\n\n"
        "3. Скопируйте `App api_id` и `App api_hash`.\n"
        "4. Вставьте их в скрипт ниже и запустите на своем ПК (не на сервере!):\n"
        "```python\n"
        "from pyrogram import Client\n"
        "async def main():\n"
        "    # Вставьте свои данные (или публичные ключи выше):\n"
        "    api_id = 123456 \n"
        "    api_hash = 'ваша_хэш_строка'\n"
        "    \n"
        "    print('ВАЖНО: Код подтверждения придет в приложение Telegram (на другом устройстве), а НЕ в СМС!')\n"
        "    \n"
        "    app = Client('my_account', api_id=api_id, api_hash=api_hash, in_memory=True)\n"
        "    await app.start()\n"
        "    print(await app.export_session_string())\n"
        "    await app.stop()\n"
        "\n"
        "import asyncio; asyncio.run(main())\n"
        "```\n"
        "4. Скопируйте полученную длинную строку.\n"
        "5. Отправьте её мне боту в ответном сообщении.",
        parse_mode="Markdown"
    )
    await state.set_state(UserBotStates.waiting_for_session_string)
    await callback.answer()

@dp.message(UserBotStates.waiting_for_session_string)
async def process_session_string(message: types.Message, state: FSMContext):
    session_string = message.text.strip()
    
    # Basic validation
    if len(session_string) < 100:
        await message.answer("❌ Это не похоже на строку сессии. Она должна быть очень длинной.")
        return

    try:
        # Test the session
        temp_client = Client(
            name=f"test_{message.from_user.id}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=session_string,
            in_memory=True
        )
        await temp_client.start()
        me = await temp_client.get_me()
        await temp_client.stop()
        
        # Save and start
        database.save_user_session(message.from_user.id, session_string)
        await ub_manager.start_client(message.from_user.id, session_string)
        
        await message.answer(f"✅ **Успешно!** Вы вошли как {me.first_name}.\nUserBot запущен и следит за удаленными сообщениями.", parse_mode="Markdown")
        await state.clear()
        
    except Exception as e:
        logging.error(f"Session Import Error: {e}")
        await message.answer(f"❌ Ошибка ессии: {e}\nВозможно, строка скопирована не полностью или отозвана.")


# --- Old single-user code removed ---
# (Removing the manual userbot initialization and handlers)

# AI logic - MUST BE LAST HANDLER
@dp.message(StateFilter(None))
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

# Check Habit Reminders
async def check_habit_reminders():
    # Only run check if seconds are near 00 to avoid duplicates? APScheduler handles interval gracefully generally.
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    habits = database.get_habits_with_reminders()
    for row in habits:
        # id, user_id, name, reminder_time
        habit_id, user_id, name, reminder_time = row
        
        if reminder_time == current_time:
            try:
                await bot.send_message(user_id, f"💎 Напоминание о привычке:\n👉 {name}")
                logging.info(f"Sent habit reminder to {user_id} for {name}")
            except Exception as e:
                logging.error(f"Failed to send habit reminder: {e}")

async def main():
    database.init_db()
    
    # Write PID for update script
    pid = os.getpid()
    with open("bot.pid", "w") as f:
        f.write(str(pid))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_morning_brief, "cron", hour=8, minute=0)
    # database.cleanup_old_messages removed as it is not implemented
    scheduler.add_job(check_deleted_messages, "interval", seconds=60, max_instances=2)
    scheduler.add_job(check_habit_reminders, "cron", second=0) # Run every minute at 00 seconds
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
