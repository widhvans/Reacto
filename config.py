import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", "123456"))  # Replace with your API ID
    API_HASH = os.getenv("API_HASH", "your_api_hash") # Replace with your API Hash
    BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token") # Replace with your Bot Token
    MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://...") # Your MongoDB Connection String
    OWNER_ID = int(os.getenv("OWNER_ID", "123456789")) # Your personal Telegram ID
  
