import sqlite3

DB_PATH = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT DEFAULT 'Moscow'
        )
    """)
    # Migration for existing table
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN city TEXT DEFAULT 'Moscow'")
        conn.commit()
    except sqlite3.OperationalError:
        # Column already exists
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            category TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            is_done BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            reminder_time TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        cursor.execute("ALTER TABLE habits ADD COLUMN reminder_time TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_messages (
            message_id INTEGER,
            chat_id INTEGER,
            user_id INTEGER,
            sender_id INTEGER,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sender_name TEXT,
            media_type TEXT,
            file_id TEXT,
            sender_username TEXT,
            PRIMARY KEY (message_id, chat_id)
        )
    """)
    
    # Migration for new columns
    try:
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN media_type TEXT")
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN file_id TEXT")
    except sqlite3.OperationalError:
        pass # Columns already exist

    try:
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN sender_username TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN chat_title TEXT")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            session_string TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER,
            user_id INTEGER,
            done_date DATE,
            UNIQUE(habit_id, done_date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS temp_emails (
            user_id INTEGER PRIMARY KEY,
            email TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_cache (
            message_id INTEGER,
            chat_id INTEGER,
            user_id INTEGER,
            text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            checked BOOLEAN DEFAULT 0,
            PRIMARY KEY (message_id, chat_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            session_string TEXT
        )
    """)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN latitude REAL")
        cursor.execute("ALTER TABLE users ADD COLUMN longitude REAL")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            UNIQUE(user_id, name)
        )
    """)
    
    # Auto-fill categories from existing expenses
    cursor.execute("""
        INSERT OR IGNORE INTO categories (user_id, name)
        SELECT DISTINCT user_id, category FROM expenses
    """)
    init_settings(conn)
    conn.commit()
    conn.close()

def add_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def update_user_city(user_id: int, city: str):
    # Deprecated but kept for compatibility or fallback
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city, user_id))
    conn.commit()
    conn.close()

def update_user_location(user_id: int, lat: float, lon: float):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET latitude = ?, longitude = ? WHERE user_id = ?", (lat, lon, user_id))
    conn.commit()
    conn.close()

def get_user_city(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Moscow"

def get_user_location(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT latitude, longitude FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0] is not None:
        return row[0], row[1]
    return None

def get_user_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def add_expense(user_id: int, amount: float, category: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO expenses (user_id, amount, category) VALUES (?, ?, ?)", 
                   (user_id, amount, category))
    # Also ensure category exists
    cursor.execute("INSERT OR IGNORE INTO categories (user_id, name) VALUES (?, ?)", (user_id, category))
    conn.commit()
    conn.close()

def add_category(user_id: int, category: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO categories (user_id, name) VALUES (?, ?)", (user_id, category))
    conn.commit()
    conn.close()

def get_categories(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM categories WHERE user_id = ? ORDER BY name", (user_id,))
    cats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return cats

def delete_expenses_by_category(user_id: int, category: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM expenses WHERE user_id = ? AND category = ?", (user_id, category))
    cursor.execute("DELETE FROM categories WHERE user_id = ? AND name = ?", (user_id, category))
    conn.commit()
    conn.close()

def get_expenses(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT amount, category, timestamp FROM expenses WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_note(user_id: int, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO notes (user_id, content) VALUES (?, ?)", (user_id, content))
    conn.commit()
    conn.close()

def get_notes(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM notes WHERE user_id = ?", (user_id,))
    notes = [row[0] for row in cursor.fetchall()]
    conn.close()
    return notes
# To-Do List Functions
def add_task(user_id: int, text: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (user_id, text) VALUES (?, ?)", (user_id, text))
    conn.commit()
    conn.close()

def get_tasks(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, text, is_done FROM tasks WHERE user_id = ? AND is_done = 0", (user_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def complete_task(task_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET is_done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

# Habit Tracker Functions
def add_habit(user_id: int, name: str, reminder_time: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO habits (user_id, name, reminder_time) VALUES (?, ?, ?)", (user_id, name, reminder_time))
    conn.commit()
    conn.close()

def get_habits(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, reminder_time FROM habits WHERE user_id = ?", (user_id,))
    habits = cursor.fetchall()
    conn.close()
    return habits

def get_habits_with_reminders():
    """Get all habits that have a reminder set"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, name, reminder_time FROM habits WHERE reminder_time IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    return rows

def log_habit(habit_id: int, user_id: int, date_str: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO habit_logs (habit_id, user_id, done_date) VALUES (?, ?, ?)", 
                   (habit_id, user_id, date_str))
    conn.commit()
    conn.close()

# Temp Mail Functions
def save_temp_email(user_id: int, email: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO temp_emails (user_id, email) VALUES (?, ?)", (user_id, email))
    conn.commit()
    conn.close()

def get_temp_email(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM temp_emails WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

# Message Cache Functions (for UserBot)
def cache_message(message_id: int, chat_id: int, user_id: int, text: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO message_cache (message_id, chat_id, user_id, text) VALUES (?, ?, ?, ?)", 
                   (message_id, chat_id, user_id, text))
    conn.commit()
    conn.close()

def get_cached_message(message_id: int, chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, text FROM message_cache WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
    row = cursor.fetchone()
    conn.close()
    return row

def cleanup_old_messages(days: int = 1):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM message_cache WHERE timestamp < datetime('now', '-' || ? || ' days')", (days,))
    conn.commit()
    conn.close()

# User Session Functions
def save_user_session(user_id: int, session_string: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_sessions (user_id, session_string) VALUES (?, ?)", (user_id, session_string))
    conn.commit()
    conn.close()

def get_user_session(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT session_string FROM user_sessions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_sessions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, session_string FROM user_sessions")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_user_session(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def cache_message(message_id, chat_id, user_id, sender_id, content, sender_name, media_type=None, file_id=None, sender_username=None, chat_title=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO cached_messages 
        (message_id, chat_id, user_id, sender_id, content, sender_name, media_type, file_id, sender_username, chat_title) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (message_id, chat_id, user_id, sender_id, content, sender_name, media_type, file_id, sender_username, chat_title))
    conn.commit()
    conn.close()

def get_messages_for_check(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Fetch media info as well
    cursor.execute("SELECT message_id, chat_id, sender_id, content, sender_name, media_type, file_id, sender_username, chat_title FROM cached_messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_cached_message(message_id, chat_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cached_messages WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
    conn.commit()
    conn.close()

def get_cached_message_content(message_id, chat_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT content, media_type, sender_name, sender_username, chat_title FROM cached_messages WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
    row = cursor.fetchone()
    conn.close()
    return row # (content, media_type, name, username, title)

# Settings & Exclusions
def init_settings(conn):
    cursor = conn.cursor()
    # Add track_groups to users if not exists
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN track_groups BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass
        
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS excluded_chats (
            user_id INTEGER,
            chat_id INTEGER,
            title TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    conn.commit()

def set_track_groups(user_id: int, enabled: bool):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET track_groups = ? WHERE user_id = ?", (1 if enabled else 0, user_id))
    # Ensure user exists if update failed (though they should)
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO users (user_id, track_groups) VALUES (?, ?)", (user_id, 1 if enabled else 0))
    conn.commit()
    conn.close()

def get_track_groups(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT track_groups FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row and row[0] is not None else True

def add_excluded_chat(user_id: int, chat_id: int, title: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO excluded_chats (user_id, chat_id, title) VALUES (?, ?, ?)", (user_id, chat_id, title))
    conn.commit()
    conn.close()

def remove_excluded_chat(user_id: int, chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM excluded_chats WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
    conn.commit()
    conn.close()

def get_excluded_chats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, title FROM excluded_chats WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows
