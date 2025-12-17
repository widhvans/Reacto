import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", "32618962"))  # Replace with your API ID
    API_HASH = os.getenv("API_HASH", "e30edea9a94912fad51753d80c7299bc") # Replace with your API Hash
    BOT_TOKEN = os.getenv("BOT_TOKEN", "7759947933:AAFKx1H_Tn39mvg_6lMRAbd3Ox0IQSRxgGY") # Replace with your Bot Token
    MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://soniji:chaloji@cluster0.i5zy74f.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0") # Your MongoDB Connection String
    OWNER_ID = int(os.getenv("OWNER_ID", "8110137558")) # Your personal Telegram ID
  
