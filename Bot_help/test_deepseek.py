import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# We use the DeepSeek key provided earlier
key = "sk-25cd68eae0044bbf8367b452d55e900d" 
print(f"Checking DeepSeek key: {key[:10]}...{key[-5:]}")

client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

try:
    print("Sending test request to DeepSeek...")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print("Success!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print("\n--- DEEPSEEK ERROR DETECTED ---")
    print(f"Type: {type(e).__name__}")
    print(f"Message: {e}")
    print("-------------------------------")
    
    if "balance" in str(e).lower() or "insufficient" in str(e).lower():
        print("\nОШИБКА: Скорее всего, на DeepSeek не пополнен баланс.")
    elif "403" in str(e):
        print("\nОШИБКА: Даже DeepSeek выдает 403? Это очень странно для этого провайдера.")
