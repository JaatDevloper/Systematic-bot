"""
Bot-only entry point for the Telegram Quiz Bot
This file only starts the bot without any web server
"""
import logging
import os
import sys
import importlib
import subprocess

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Main function to start the bot directly"""
    try:
        logger.info("Starting bot in a dedicated process...")
        # Use subprocess to run the bot in a separate process
        # This prevents Flask and the bot from conflicting
        process = subprocess.Popen(["python", "run_bot_only.py"])
        return process
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return None

if __name__ == "__main__":
    # Start the bot directly
    process = main()
    # Keep the main process running
    if process:
        try:
            process.wait()
        except KeyboardInterrupt:
            logger.info("Terminating bot process...")
            process.terminate()