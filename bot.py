"""
Bot implementation for the Telegram Quiz Bot
This is a wrapper around the original bot implementation
"""
import os
import sys
import logging
import importlib
from config import TELEGRAM_BOT_TOKEN

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_bot():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Please set it in the environment variables.")
        return
    
    logger.info("Starting bot with token %s...", TELEGRAM_BOT_TOKEN[:4] + "..." + TELEGRAM_BOT_TOKEN[-4:])
    
    # Create a sub-process to run the bot
    # This avoids threading issues with the event loop
    try:
        import subprocess
        logger.info("Starting bot in a separate process...")
        
        # Use subprocess to run the bot
        subprocess.Popen(["python", "bot_only.py"])
        logger.info("Bot started in separate process")
        
    except Exception as e:
        logger.error("Error starting bot subprocess: %s", e)

if __name__ == "__main__":
    run_bot()