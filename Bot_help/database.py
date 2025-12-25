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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Ensure user exists first
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city, user_id))
    conn.commit()
    conn.close()

def get_user_city(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Moscow"

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
    conn.commit()
    conn.close()

def delete_expenses_by_category(user_id: int, category: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM expenses WHERE user_id = ? AND category = ?", (user_id, category))
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

def get_unchecked_messages(limit: int = 50):
    """Get unchecked messages from last 24 hours"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT message_id, chat_id, user_id, text 
        FROM message_cache 
        WHERE checked = 0 
        AND timestamp > datetime('now', '-1 day')
        ORDER BY timestamp DESC 
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def mark_message_checked(message_id: int, chat_id: int):
    """Mark message as checked"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE message_cache SET checked = 1 WHERE message_id = ? AND chat_id = ?", 
                   (message_id, chat_id))
    conn.commit()
    conn.close()

def delete_cached_message(message_id: int, chat_id: int):
    """Delete message from cache (when confirmed deleted)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM message_cache WHERE message_id = ? AND chat_id = ?", 
                   (message_id, chat_id))
    conn.commit()
    conn.close()
