"""
Completely standalone Telegram bot script with no web components
"""
import os
import sys
import logging
import importlib

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Check if token is set
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)
    
    logger.info(f"Starting Telegram bot with token {token[:4]}...{token[-4:]}")
    
    try:
        # Import simple_bot module
        sys.path.append(os.getcwd())
        simple_bot = importlib.import_module("simple_bot")
        
        # Run the bot
        logger.info("Starting bot...")
        simple_bot.main()
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        sys.exit(1)