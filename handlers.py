"""
Message handlers for the Telegram Quiz Bot
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Hello! I'm the Telegram Quiz Bot. Use /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "Available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/quiz - Start a quiz\n"
        "/category - Start a quiz from a specific category\n"
        "/add - Add a new question\n"
        "/edit - Edit a question\n"
        "/delete - Delete a question\n"
        "/stats - View your quiz statistics\n"
        "/clone - Import a quiz from a URL or manually"
    )
    await update.message.reply_text(help_text)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    await update.message.reply_text(
        "I don't understand that command. Use /help to see available commands."
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors that occur during the execution of the bot."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Send message to developer
    if update and hasattr(update, 'effective_chat'):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="An error occurred while processing your request. Please try again later."
        )