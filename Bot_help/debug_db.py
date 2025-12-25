import sqlite3
import database

DB_PATH = "bot_database.db"

def debug_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("--- USERS ---")
    cursor.execute("SELECT * FROM users LIMIT 5")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- CATEGORIES ---")
    try:
        cursor.execute("SELECT * FROM categories")
        rows = cursor.fetchall()
        if not rows:
            print("(No categories found)")
        for row in rows:
            print(row)
    except Exception as e:
        print(f"Error reading categories: {e}")

    print("\n--- EXPENSES ---")
    cursor.execute("SELECT user_id, category FROM expenses LIMIT 10")
    for row in cursor.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    debug_db()
