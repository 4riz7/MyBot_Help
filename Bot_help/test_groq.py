import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

key = os.getenv("GROQ_API_KEY")
print(f"Checking Groq key: {key[:10]}...{key[-5:]}")

client = Groq(api_key=key)

try:
    print("Sending test request to Groq...")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print("Success!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print("\n--- GROQ ERROR DETECTED ---")
    print(f"Type: {type(e).__name__}")
    print(f"Message: {e}")
    print("---------------------------")
