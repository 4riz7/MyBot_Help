import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

key = os.getenv("OPENAI_API_KEY")
print(f"Checking key: {key[:10]}...{key[-5:]}")

client = OpenAI(api_key=key)

try:
    print("Sending test request...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print("Success!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print("\n--- ERROR DETECTED ---")
    print(f"Type: {type(e).__name__}")
    print(f"Message: {e}")
    print("----------------------")
    
    if "insufficient_quota" in str(e):
        print("\nОШИБКА: У тебя закончились деньги на счету OpenAI или истек бесплатный лимит.")
        print("Тебе нужно пополнить баланс (минимум $5) здесь: https://platform.openai.com/settings/organization/billing/overview")
    elif "invalid_api_key" in str(e):
        print("\nОШИБКА: Неверный API ключ. Проверь файл .env")
