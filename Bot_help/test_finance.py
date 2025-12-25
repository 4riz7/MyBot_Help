import sqlite3
import os

DB_PATH = "bot_database.db"
TEST_USER_ID = 999999

def test_categories():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Clean up
    cursor.execute("DELETE FROM categories WHERE user_id = ?", (TEST_USER_ID,))
    conn.commit()
    
    print("1. Categories cleared.")
    
    # Add category
    cat_name = "Бензин"
    cursor.execute("INSERT OR IGNORE INTO categories (user_id, name) VALUES (?, ?)", (TEST_USER_ID, cat_name))
    conn.commit()
    print(f"2. Added category '{cat_name}'.")
    
    # Read back
    cursor.execute("SELECT name FROM categories WHERE user_id = ?", (TEST_USER_ID,))
    rows = cursor.fetchall()
    print(f"3. Read categories: {rows}")
    
    if not rows:
        print("FAIL: Categories not saved!")
    elif rows[0][0] == "Бензин":
        print("SUCCESS: Category saved and read.")
    else:
        print(f"FAIL: Wrong data read: {rows}")

    conn.close()

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("DB not found!")
    else:
        test_categories()
