import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
CITY = os.getenv("CITY", "Moscow")

# Fallback AI Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# UserBot Sync
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
WEBAPP_URL = "https://4riz7.github.io/4riz-github.io/index.html?v=2.0"
