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
                if len(row) == 9: # Newest with Title
                    mid, cid, sid, content, sname, mtype, fid, s_username, chat_title = row
                elif len(row) == 8: # Compat with username
                    mid, cid, sid, content, sname, mtype, fid, s_username = row
                    chat_title = None
                elif len(row) == 7: # Old compat
                    mid, cid, sid, content, sname, mtype, fid = row
                    s_username, chat_title = None, None
                else:
                    mid, cid, sid, content, sname = row
                    mtype, fid, s_username, chat_title = None, None, None, None
                    
                if cid not in chats_to_check: chats_to_check[cid] = {}
                chats_to_check[cid][mid] = (content, sname, sid, mtype, fid, s_username, chat_title)

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
                        content, sname, sid, mtype, fid, s_username, chat_title = messages_dict[original_msg_id]
                        
                        is_deleted = False
                        if msg_obj is None: is_deleted = True
                        elif hasattr(msg_obj, 'empty') and msg_obj.empty: is_deleted = True
                        
                        if is_deleted:
                            # Notify user via main bot
                            username_text = f"(@{s_username})" if s_username else ""
                            chat_label = chat_title or "Личный чат"
                            alert_text = (
                                f"🗑 Удаленное сообщение!\n"
                                f"📁 Чат: {chat_label}\n"
                                f"👤 От: {sname} {username_text}\n"
                                f"💬 Текст: {content}\n"
                            )
                            
                            # Try to recover media if present
                            if mtype and fid:
                                try:
                                    # New Logic: UserBot downloads -> Main Bot sends to User (Private Chat)
                                    # This avoids "Saved Messages" and uses the Bot interface.
                                    
                                    # 1. Download via UserBot (since it has access to the file_id)
                                    media_path = await client.download_media(fid)
                                    
                                    if media_path:
                                        # 2. Send via Main Bot
                                        sent_restored = None
                                        input_file = FSInputFile(media_path)
                                        restored_caption = f"🗑 Восстановленное медиа от {sname}\n📁 Чат: {chat_label}"
                                        
                                        try:
                                            if mtype == "photo":
                                                sent_restored = await bot.send_photo(user_id, input_file, caption=restored_caption)
                                            elif mtype == "video":
                                                sent_restored = await bot.send_video(user_id, input_file, caption=restored_caption)
                                            elif mtype == "voice":
                                                sent_restored = await bot.send_voice(user_id, input_file, caption=restored_caption)
                                            elif mtype == "audio":
                                                sent_restored = await bot.send_audio(user_id, input_file, caption=restored_caption)
                                            elif mtype == "video_note":
                                                sent_restored = await bot.send_video_note(user_id, input_file)
                                                await bot.send_message(user_id, restored_caption)
                                            elif mtype == "animation":
                                                sent_restored = await bot.send_animation(user_id, input_file, caption=restored_caption)
                                            elif mtype == "sticker":
                                                 # Stickers are tricky to download/send as files sometimes, but let's try
                                                 sent_restored = await bot.send_sticker(user_id, input_file)
                                            
                                            # Fallback
                                            if not sent_restored:
                                                 await bot.send_document(user_id, input_file, caption=restored_caption + " (Как файл)")
                                            
                                            alert_text += "\n💾 **Медиафайл восстановлен ботом.**"
                                        except Exception as bot_e:
                                            logging.error(f"Restoration send failed: {bot_e}")
                                            alert_text += f"\n❌ Бот не смог отправить файл: {bot_e}"
                                        
                                        # 3. Cleanup
                                        if os.path.exists(media_path):
                                            os.remove(media_path)
                                    else:
                                        alert_text += "\n❌ Не удалось скачать файл (доступ запрещен или устарел)."

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
            # Intercept custom commands from SELF (to manage settings)
            if message.from_user and message.from_user.is_self and message.text:
                if message.text.lower() == "/ignore":
                    database.add_excluded_chat(user_id, message.chat.id, message.chat.title or "Unknown Chat")
                    await message.edit_text("🔇 **Чат добавлен в исключения!**\nСообщения отсюда больше не будут сохраняться.")
                    await asyncio.sleep(3)
                    await message.delete()
                    return
                elif message.text.lower() == "/unignore":
                    database.remove_excluded_chat(user_id, message.chat.id)
                    await message.edit_text("🔊 **Чат убран из исключений!**\nМониторинг удалений снова активен.")
                    await asyncio.sleep(3)
                    await message.delete()
                    return

            # Cache all incoming messages from others
            if message.from_user and message.from_user.is_self:
                return
            
            # Helper logging to debug "Not working" issues
            logging.info(f"📩 Получено сообщение: {message.chat.id} | {message.from_user.id if message.from_user else 'Anon'}")

            # Ignore messages from the main bot to avoid loops
            if message.chat.id == BOT_ID or (message.from_user and message.from_user.id == BOT_ID):
                return
            
            # Check Settings & Exclusions
            is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]
            if is_group:
                # 1. Check Global Switch
                if not database.get_track_groups(user_id):
                    return # Tracking Groups is OFF
                
                # 2. Check Exclusions
                excluded = database.get_excluded_chats(user_id) # Returns [(id, title), ...]
                excluded_ids = [row[0] for row in excluded]
                if message.chat.id in excluded_ids:
                    return # Chat is Blacklisted

            # Helper to safely get file_id
            def get_fid(obj): return getattr(obj, "file_id", None)

            def extract_message_data(msg):
                # Extract sender info
                s_id = msg.from_user.id if msg.from_user else 0
                s_name = msg.from_user.first_name if msg.from_user else "Unknown"
                s_username = msg.from_user.username if msg.from_user and msg.from_user.username else None
                
                # Robust Media Detection
                m_type = None
                f_id = None
                cnt = msg.text or msg.caption or ""
                
                if msg.photo:
                    m_type = "photo"; f_id = get_fid(msg.photo)
                    if not cnt: cnt = "[Фотография]"
                elif msg.video:
                    m_type = "video"; f_id = get_fid(msg.video)
                    if not cnt: cnt = "[Видео]"
                elif msg.video_note:
                    m_type = "video_note"; f_id = get_fid(msg.video_note)
                    if not cnt: cnt = "[Видеокружок]"
                elif msg.voice:
                    m_type = "voice"; f_id = get_fid(msg.voice)
                    if not cnt: cnt = "[Голосовое сообщение]"
                elif msg.audio:
                    m_type = "audio"; f_id = get_fid(msg.audio)
                    if not cnt: cnt = "[Аудиозапись]"
                elif msg.document:
                    m_type = "document"; f_id = get_fid(msg.document)
                    if not cnt: cnt = "[Документ/Файл]"
                elif msg.sticker:
                    m_type = "sticker"; f_id = get_fid(msg.sticker)
                    if not cnt: cnt = "[Стикер]"
                elif msg.animation:
                    m_type = "animation"; f_id = get_fid(msg.animation)
                    if not cnt: cnt = "[GIF/Анимация]"
                
                # Fallback
                if not m_type and getattr(msg, "media", None):
                    raw_media = str(msg.media)
                    if "PHOTO" in raw_media: m_type = "photo"
                    elif "VIDEO_NOTE" in raw_media: m_type = "video_note"
                    elif "VIDEO" in raw_media: m_type = "video"
                    elif "VOICE" in raw_media: m_type = "voice"
                    else: m_type = "document"
                    
                    cnt = f"[Медиа: {raw_media}]"
                    if not f_id: f_id = "unknown_but_present"
                
                return s_id, s_name, s_username, m_type, f_id, cnt

            sender_id, sender_name, sender_username, media_type, file_id, content = extract_message_data(message)

            if not content or content == "[Неизвестный тип]":
                content = "[Неизвестный тип]"
                # DEBUG: Log the full message structure using vars() to see hidden fields
                logging.warning(f"⚠️ Неизвестный тип сообщения! Внутренности: {vars(message)}")
                try:
                     import pyrogram
                     logging.warning(f"Technical Info - Pyrogram Version: {pyrogram.__version__}")
                     if hasattr(pyrogram.raw.all, 'layer'):
                        logging.warning(f"Technical Info - API Layer: {pyrogram.raw.all.layer}")
                except:
                    pass
                
                # Experimental: Try to download ANYWAY. 
                # Sometimes Pyrogram sees the media but doesn't map it to a property yet.
                try:
                    logging.info("🔮 Попытка принудительной загрузки неизвестного вложения...")
                    
                    # 1. Try to re-fetch full message (sometimes updates are partial)
                    try:
                        full_msg = await client.get_messages(message.chat.id, message.id)
                        if full_msg and (full_msg.media or getattr(full_msg, 'photo', None) or getattr(full_msg, 'video', None)):
                            logging.info(f"🔄 Сообщение обновлено! Обнаружен тип: {full_msg.media}")
                            message = full_msg
                    except Exception as refetch_e:
                        logging.warning(f"Refetch failed: {refetch_e}")

                    # 2. Try download (on original or refreshed message)
                    file_path = await message.download()
                    if file_path:
                         media_type = "unknown_file"
                         content = f"[📁 Найден скрытый файл] {content}"
                         is_protected = True 
                         has_ttl = True
                         
                        # Form caption with tag
                         user_tag = f"@{sender_username}" if sender_username else sender_name
                         caption_text = f"🔮 Скрытый файл от {user_tag}\n📁 Чат: {message.chat.title or 'Личный'}"
                         
                         # Send via Main Bot to the User's private chat
                         try:
                             input_file = FSInputFile(file_path)
                             await bot.send_document(user_id, input_file, caption=caption_text)
                         except Exception as bot_send_e:
                             logging.error(f"Main Bot send error: {bot_send_e}")
                             await client.send_message("me", f"❌ Бот не смог отправить файл в ЛС: {bot_send_e}")

                         if os.path.exists(file_path):
                            os.remove(file_path)
                except Exception as e:
                    logging.error(f"Brute-force download failed: {e}")

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
                    await client.send_message("me", f"🔐 Загружаю секретное медиа от {sender_name}...")
                    file_path = await message.download()
                    
                    if file_path:
                        # Use username (tag) instead of ID
                        user_tag = f"@{sender_username}" if sender_username else sender_name
                        caption_text = f"🔐 Секретное медиа от {user_tag}\n📁 Чат: {message.chat.title or 'Личный'}"
                        
                        # Send via Main Bot to User
                        try:
                            input_file = FSInputFile(file_path)
                            sent_msg = None
                            
                            if media_type == "photo":
                                sent_msg = await bot.send_photo(user_id, input_file, caption=caption_text)
                            elif media_type == "video":
                                sent_msg = await bot.send_video(user_id, input_file, caption=caption_text)
                            elif media_type == "voice":
                                sent_msg = await bot.send_voice(user_id, input_file, caption=caption_text)
                            elif media_type == "video_note":
                                sent_msg = await bot.send_video_note(user_id, input_file)
                                await bot.send_message(user_id, caption_text)
                            elif media_type == "audio":
                                sent_msg = await bot.send_audio(user_id, input_file, caption=caption_text)
                            elif media_type == "animation":
                                sent_msg = await bot.send_animation(user_id, input_file, caption=caption_text)
                            
                            # Fallback
                            if not sent_msg:
                                await bot.send_document(user_id, input_file, caption=caption_text + " (Как файл)")
                            
                            logging.info(f"✅ Секретный контент отправлен ботом пользователю {user_id}: {file_path}")
                            
                        except Exception as bot_err:
                            logging.error(f"Bot send failed: {bot_err}")
                            # Fallback to UserBot Saved Messages if Main Bot fails (e.g. file too big)
                            await client.send_document("me", file_path, caption=caption_text + f"\n⚠️ (Бот не смог отправить: {bot_err})")

                        if os.path.exists(file_path):
                            os.remove(file_path)
                    else:
                        logging.error("❌ Download failed (file_path is None)")
                        
                 except Exception as e:
                     logging.error(f"Failed to auto-save protected media: {e}")

            
            
            @client.on_edited_message()
            async def py_on_edited_message(c, message: PyMessage):
                if message.from_user and message.from_user.is_self: return
                if message.chat.id == BOT_ID: return
                
                # Check Settings & Exclusions
                is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]
                if is_group:
                    if not database.get_track_groups(user_id): return
                    excluded = database.get_excluded_chats(user_id)
                    if message.chat.id in [row[0] for row in excluded]: return

                # 1. Always extract new data first (needed for cache update)
                new_text = message.text or message.caption or ""
                if not new_text:
                    if message.photo: new_text = "[Фотография]"
                    elif message.video: new_text = "[Видео]"
                    elif message.voice: new_text = "[Голосовое]"
                    elif message.video_note: new_text = "[Видеокружок]"
                    elif message.sticker: new_text = "[Стикер]"
                    elif message.animation: new_text = "[GIF]"
                    elif message.document: new_text = "[Файл]"
                    else: new_text = "[Медиа/Неизвестно]"

                # 2. Get old content from cache
                old_data = database.get_cached_message_content(message.id, message.chat.id)
                
                if old_data:
                    # Unpack safely
                    old_text, old_media, old_name, old_username = "", "", "", ""
                    if len(old_data) == 5:
                        old_text, old_media, old_name, old_username, old_title = old_data
                    elif len(old_data) == 4:
                        old_text, old_media, old_name, old_username = old_data
                    
                    # Compare text
                    if old_text and old_text != new_text:
                        # Prepare Alert
                        s_name = message.from_user.first_name if message.from_user else "Unknown"
                        s_tag = f"@{message.from_user.username}" if message.from_user and message.from_user.username else s_name
                        
                        alert = (
                            f"✏️ Сообщение изменено!\n"
                            f"📁 Чат: {message.chat.title or 'Личный'}\n"
                            f"👤 Автор: {s_tag}\n\n"
                            f"🕰 Было:\n{old_text}\n\n"
                            f"🆕 Стало:\n{new_text}"
                        )
                        
                        try:
                            await bot.send_message(user_id, alert)
                        except Exception as e:
                            logging.error(f"Failed to send edit alert: {e}")

                # 3. Update Cache with new content
                s_id = message.from_user.id if message.from_user else 0
                s_name = message.from_user.first_name if message.from_user else "Unknown"
                s_username = message.from_user.username if message.from_user and message.from_user.username else None
                m_type = None
                f_id = None
                
                if message.photo: m_type="photo"; f_id=getattr(message.photo, "file_id", None)
                elif message.video: m_type="video"; f_id=getattr(message.video, "file_id", None)
                
                database.cache_message(
                    message.id, 
                    message.chat.id, 
                    user_id, 
                    s_id, 
                    new_text,
                    s_name,
                    m_type,
                    f_id,
                    s_username,
                    message.chat.title or "Личный чат"
                )

            
            database.cache_message(
                message.id, 
                message.chat.id, 
                user_id, 
                sender_id, 
                content,
                sender_name,
                media_type,
                file_id,
                sender_username,
                message.chat.title or "Личный чат"
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
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🕵️ Мой UserBot"), KeyboardButton(text="⚙️ Настройки")],
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="� Привычки"), KeyboardButton(text="💰 Финансы")],
        [KeyboardButton(text="📧 Временная почта"), KeyboardButton(text="🌦 Погода")],
        [KeyboardButton(text="❓ Помощь")]
    ], resize_keyboard=True)
    return kb

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    database.add_user(message.from_user.id)
    
    await message.answer(
        f"👋 **Привет, {message.from_user.first_name}!**\n\n"
        "Я твой **Супер-Бот** — все инструменты в одном месте! 🚀\n\n"
        "**Что я умею?**\n"
        "🤖 **ИИ-ассистент:** Отвечаю на вопросы и помню контекст.\n"
        "🕵️ **UserBot (Слежка):** Ловлю удаленные сообщения и секретные фото.\n"
        "🎙 **Голос:** Превращаю голосовые в текст.\n"
        "💼 **Органайзер:** Задачи, Привычки, Финансы, Заметки.\n"
        "� **Утилиты:** Временная почта, Скачивание видео.\n\n"
        "👇 **Выбирай функцию в меню ниже:**",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
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


@dp.message(F.text == "⚙️ Настройки")
@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    user_id = message.from_user.id
    track_groups = database.get_track_groups(user_id)
    status_icon = "✅" if track_groups else "❌"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Мониторинг групп: {status_icon}", callback_data=f"settings_toggle")],
        [InlineKeyboardButton(text="🚫 Список исключений", callback_data="show_exclusions")]
    ])
    
    await message.answer(
        "⚙️ **Настройки UserBot**\n\n"
        "Здесь вы можете управлять слежкой за удаленными сообщениями в группах.\n\n"
        "ℹ️ **Как исключить группу?**\n"
        "Напишите `/ignore` прямо в чате группы (от своего лица).\n"
        "Чтобы вернуть слежку, напишите `/unignore`.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "settings_toggle")
async def process_settings_toggle(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    current_status = database.get_track_groups(user_id)
    new_status = not current_status
    database.set_track_groups(user_id, new_status)
    
    status_icon = "✅" if new_status else "❌"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Мониторинг групп: {status_icon}", callback_data=f"settings_toggle")],
        [InlineKeyboardButton(text="🚫 Список исключений", callback_data="show_exclusions")]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"Мониторинг групп {'включен' if new_status else 'выключен'}!")

@dp.callback_query(F.data == "show_exclusions")
async def process_show_exclusions(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    exclusions = database.get_excluded_chats(user_id)
    
    if not exclusions:
        text = "✅ **Список исключений пуст.**\nБот следит за всеми группами (если мониторинг включен)."
    else:
        text = "🚫 **Исключенные чаты:**\n\n"
        for i, (chat_id, title) in enumerate(exclusions, 1):
            text += f"{i}. {title} (ID: `{chat_id}`)\n"
        
        text += "\nℹ️ Чтобы убрать чат из исключений, напишите в нем `/unignore` или используйте ID."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔙 Назад", callback_data="back_to_settings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_settings")
async def process_back_settings(callback: types.CallbackQuery):
    await callback.message.delete()
    # Re-trigger settings menu logic
    user_id = callback.from_user.id
    track_groups = database.get_track_groups(user_id)
    status_icon = "✅" if track_groups else "❌"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Мониторинг групп: {status_icon}", callback_data=f"settings_toggle")],
        [InlineKeyboardButton(text="🚫 Список исключений", callback_data="show_exclusions")]
    ])
    
    await callback.message.answer(
        "⚙️ **Настройки UserBot**\n\n"
        "Здесь вы можете управлять слежкой за удаленными сообщениями в группах.\n\n"
        "ℹ️ **Как исключить группу?**\n"
        "Напишите `/ignore` прямо в чате группы (от своего лица).\n"
        "Чтобы вернуть слежку, напишите `/unignore`.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


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
