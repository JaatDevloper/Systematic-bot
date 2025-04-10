"""
Main entry point for the Telegram Quiz Bot
This file adapts to different modes depending on EXECUTION_MODE environment variable
"""
import os
import sys
import subprocess
import logging

# Import the Flask app for gunicorn
from app_module import app

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Check execution mode from environment variable
EXECUTION_MODE = os.environ.get("EXECUTION_MODE", "combined").lower()

def start_bot_only():
    """Start just the Telegram bot without any web server"""
    logger.info("Starting in BOT ONLY mode")
    try:
        # Direct execution of the standalone bot script
        import subprocess
        subprocess.call(["python", "bot_standalone.py"])
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    
def start_web_only():
    """Start just the web server without the bot"""
    logger.info("Starting in WEB ONLY mode")
    # The app is already imported from app_module
    # This is just for standalone execution
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
def start_combined():
    """Start both the web server and bot (for production)"""
    logger.info("Starting in COMBINED mode")
    
    # Start the bot in a separate process
    try:
        import subprocess
        logger.info("Starting bot in a separate process...")
        process = subprocess.Popen(["python", "bot_standalone.py"])
        logger.info(f"Bot started in separate process with PID {process.pid}")
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    
    # The app is already imported from app_module
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Check for special command-line arguments
if len(sys.argv) > 1:
    if sys.argv[1] == "--bot-only":
        EXECUTION_MODE = "bot"
    elif sys.argv[1] == "--web-only":
        EXECUTION_MODE = "web"

# Call the appropriate function based on execution mode
if __name__ == "__main__":
    if EXECUTION_MODE == "bot":
        start_bot_only()
    elif EXECUTION_MODE == "web":
        start_web_only()
    else:
        # Default is combined mode
        start_combined()