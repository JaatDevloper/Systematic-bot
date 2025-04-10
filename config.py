"""
Configuration file for the Telegram Quiz Bot
"""
import os

# Required environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Optional environment variables
API_ID = os.getenv("API_ID")  # For Pyrogram (Telegram client)
API_HASH = os.getenv("API_HASH")  # For Pyrogram (Telegram client)
BOT_NAME = os.getenv("BOT_NAME", "QuizBot")
DATA_DIR = os.getenv("DATA_DIR", "data")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
QUESTIONS_FILE = os.path.join(DATA_DIR, 'questions.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Optional test mode flag
TEST_MODE = os.getenv('TEST_MODE') == '1'