"""
Bot-only runner script - completely headless with no web server
"""
import logging
import os
import sys
import importlib

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Main function to run the bot directly"""
    # Get the token from environment
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Please set it in the environment variables.")
        sys.exit(1)
    
    logger.info("Starting bot with token %s...", token[:4] + "..." + token[-4:])
    
    try:
        # Load the main bot module
        sys.path.append(os.getcwd())
        simple_bot = importlib.import_module("simple_bot")
        
        # Call the main function directly
        logger.info("Starting bot directly from simple_bot...")
        simple_bot.main()
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()