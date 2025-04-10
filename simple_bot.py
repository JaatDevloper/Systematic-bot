"""
Telegram Quiz Bot with improved poll conversion, custom ID management,
animated timers, and detailed result tracking.
"""
import os
import json
import random
import asyncio
import logging
import re
import requests
from urllib.parse import urlparse
from datetime import datetime
from telegram import Update, Poll, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, PollHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PollAnswerHandler
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
QUESTION, OPTIONS, ANSWER, CUSTOM_ID = range(4)
EDIT_SELECT, EDIT_QUESTION, EDIT_OPTIONS, EDIT_ANSWER = range(4, 8)
CLONE_URL, CLONE_MANUAL, POLL2Q_ID = range(8, 11)

# Get bot token from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# File paths
QUESTIONS_FILE = 'data/questions.json'
USERS_FILE = 'data/users.json'

# Store active timers
active_timers = {}

def load_questions():
    """Load questions from the JSON file"""
    try:
        if os.path.exists(QUESTIONS_FILE):
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as file:
                questions = json.load(file)
            logger.info(f"Loaded {len(questions)} questions")
            return questions
        else:
            # Create sample questions if file doesn't exist
            questions = [
                {
                    "id": 1,
                    "question": "What is the capital of France?",
                    "options": ["Berlin", "Madrid", "Paris", "Rome"],
                    "answer": 2,  # Paris (0-based index)
                    "category": "Geography"
                },
                {
                    "id": 2,
                    "question": "Which planet is known as the Red Planet?",
                    "options": ["Venus", "Mars", "Jupiter", "Saturn"],
                    "answer": 1,  # Mars (0-based index)
                    "category": "Science"
                }
            ]
            save_questions(questions)
            return questions
    except Exception as e:
        logger.error(f"Error loading questions: {e}")
        return []

def save_questions(questions):
    """Save questions to the JSON file"""
    try:
        with open(QUESTIONS_FILE, 'w', encoding='utf-8') as file:
            json.dump(questions, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {len(questions)} questions")
        return True
    except Exception as e:
        logger.error(f"Error saving questions: {e}")
        return False

def get_next_question_id():
    """Get the next available question ID"""
    questions = load_questions()
    if not questions:
        return 1
    return max(q.get("id", 0) for q in questions) + 1

def get_question_by_id(question_id):
    """Get a question by its ID"""
    questions = load_questions()
    for question in questions:
        if question.get("id") == question_id:
            return question
    return None

def delete_question_by_id(question_id):
    """Delete a question by its ID"""
    questions = load_questions()
    updated_questions = [q for q in questions if q.get("id") != question_id]
    if len(updated_questions) < len(questions):
        save_questions(updated_questions)
        return True
    return False

def load_users():
    """Load user data from file"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as file:
                return json.load(file)
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(users):
    """Save user data to file"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as file:
            json.dump(users, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def get_user_data(user_id):
    """Get data for a specific user"""
    users = load_users()
    return users.get(str(user_id), {"quizzes_taken": 0, "correct_answers": 0})

def update_user_data(user_id, data):
    """Update data for a specific user"""
    users = load_users()
    users[str(user_id)] = data
    save_users(users)

def create_countdown_animation(seconds, total=15):
    """Create a text-based animated countdown timer"""
    # Full block and empty block for visual timer
    full_block = "■"
    empty_block = "□"
    
    # Calculate percentage and blocks
    percentage = seconds / total
    num_blocks = 10
    filled_blocks = int(percentage * num_blocks)
    
    # Create progress bar
    progress_bar = full_block * filled_blocks + empty_block * (num_blocks - filled_blocks)
    
    # Create timer text
    # Format: [■■■■■□□□□□] 5s
    timer_text = f"[{progress_bar}] {seconds}s"
    return timer_text

async def update_countdown_timer(bot, chat_id, message_id, duration=15):
    """Update a countdown timer message at regular intervals"""
    timer_id = f"{chat_id}_{message_id}"
    active_timers[timer_id] = True
    
    # Initial full timer
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=create_countdown_animation(duration, duration)
    )
    
    # Update timer every second
    for remaining in range(duration-1, 0, -1):
        # Check if timer was cancelled
        if timer_id not in active_timers:
            return
            
        await asyncio.sleep(1)
        
        # Check again if timer was cancelled during sleep
        if timer_id not in active_timers:
            return
            
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=create_countdown_animation(remaining, duration)
            )
        except Exception as e:
            logger.error(f"Error updating timer: {e}")
            break

def cancel_timer(chat_id, message_id):
    """Cancel an active timer"""
    timer_id = f"{chat_id}_{message_id}"
    if timer_id in active_timers:
        del active_timers[timer_id]

def parse_telegram_quiz_url(url):
    """Parse a Telegram quiz URL to extract question and options"""
    try:
        # Basic URL validation
        if not url or "t.me" not in url:
            logger.error(f"Not a valid Telegram URL: {url}")
            return None
        
        # Try different methods to extract quiz content
        logger.info(f"Attempting to extract quiz from URL: {url}")
        
        # Method 1: Try to use Telegram API (Pyrogram) if credentials are available
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if api_id and api_hash and bot_token:
            try:
                from pyrogram import Client
                import asyncio
                
                # Extract channel username and message ID from URL
                channel_pattern = r't\.me/([^/]+)/(\d+)'
                channel_match = re.search(channel_pattern, url)
                
                if channel_match:
                    channel_name = channel_match.group(1)
                    message_id = int(channel_match.group(2))
                    
                    # Function to get message using Pyrogram
                    async def get_quiz_message():
                        logger.info(f"Trying to fetch message from {channel_name}, ID: {message_id}")
                        async with Client(
                            "quiz_bot_client",
                            api_id=api_id,
                            api_hash=api_hash,
                            bot_token=bot_token,
                            in_memory=True
                        ) as app:
                            try:
                                message = await app.get_messages(channel_name, message_id)
                                if message:
                                    # If it's a poll message
                                    if message.poll:
                                        return {
                                            "question": message.poll.question,
                                            "options": [opt.text for opt in message.poll.options],
                                            "answer": 0  # Default, user will select correct answer
                                        }
                                    # If it's a text message that might contain quiz info
                                    elif message.text:
                                        # Try to parse text as quiz (question + options format)
                                        lines = message.text.strip().split('\n')
                                        if len(lines) >= 3:  # At least 1 question and 2 options
                                            question = lines[0]
                                            options = []
                                            
                                            # Extract options (look for numbered/lettered options)
                                            for line in lines[1:]:
                                                line = line.strip()
                                                # Remove common option prefixes
                                                line = re.sub(r'^[a-z][\.\)]\s*', '', line)
                                                line = re.sub(r'^\d+[\.\)]\s*', '', line)
                                                if line:
                                                    options.append(line)
                                            
                                            if len(options) >= 2:
                                                return {
                                                    "question": question,
                                                    "options": options,
                                                    "answer": 0
                                                }
                            except Exception as e:
                                logger.error(f"Error getting message with Pyrogram: {e}")
                                return None
                        return None
                    
                    # Run the async function
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(get_quiz_message())
                    loop.close()
                    
                    if result:
                        logger.info(f"Successfully extracted quiz via Pyrogram: {result['question']}")
                        return result
            except Exception as e:
                logger.error(f"Pyrogram method failed: {e}")
        
        # Method 2: Enhanced web scraping with multiple patterns
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        # Try to get both the regular URL and the embedded version
        try:
            response = requests.get(url, headers=headers)
            content = response.text
            
            # First, look for standard poll format
            poll_q_match = re.search(r'<div class="tgme_widget_message_poll_question">([^<]+)</div>', content)
            poll_options = re.findall(r'<div class="tgme_widget_message_poll_option_text">([^<]+)</div>', content)
            
            if poll_q_match and poll_options and len(poll_options) >= 2:
                question = poll_q_match.group(1).strip()
                return {
                    "question": question,
                    "options": poll_options,
                    "answer": 0
                }
            
            # If not a direct poll, try embedded view
            if "rajsthangk" in url or "gk" in url.lower() or "quiz" in url.lower():
                # Try to extract channel and message_id
                channel_pattern = r't\.me/([^/]+)/(\d+)'
                channel_match = re.search(channel_pattern, url)
                
                if channel_match:
                    channel_name = channel_match.group(1)
                    message_id = channel_match.group(2)
                    
                    # Try embedded view
                    embed_url = f"https://t.me/{channel_name}/{message_id}?embed=1"
                    try:
                        embed_response = requests.get(embed_url, headers=headers)
                        embed_content = embed_response.text
                        
                        # Try to find quiz in embedded view
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(embed_content, 'html.parser')
                        
                        # Look for message text that might contain quiz
                        message_text = soup.select_one('.tgme_widget_message_text')
                        if message_text:
                            text = message_text.get_text().strip()
                            lines = [line.strip() for line in text.split('\n') if line.strip()]
                            
                            if lines and len(lines) >= 3:  # At least question + 2 options
                                question = lines[0]
                                
                                # Check if this looks like a quiz (has options with A), B), 1., 2., etc.)
                                option_pattern = re.compile(r'^[A-Za-z0-9][\.\)]')
                                options = []
                                for line in lines[1:]:
                                    # Remove option markers
                                    clean_line = re.sub(r'^[A-Za-z0-9][\.\)]\s*', '', line)
                                    if clean_line:
                                        options.append(clean_line)
                                
                                if len(options) >= 2:
                                    logger.info(f"Extracted quiz from message text with {len(options)} options")
                                    return {
                                        "question": question,
                                        "options": options,
                                        "answer": 0
                                    }
                        
                        # For RAJ GK QUIZ HOUSE format, look for quiz title
                        page_title = soup.select_one('meta[property="og:title"]')
                        if page_title and "quiz" in page_title.get('content', '').lower():
                            title = page_title.get('content', '').strip()
                            
                            # Try to extract options from the page
                            lines = []
                            for p in soup.select('.tgme_widget_message_text p'):
                                lines.append(p.get_text().strip())
                            
                            # If we have potential options
                            if lines and len(lines) >= 2:
                                return {
                                    "question": title,
                                    "options": lines,
                                    "answer": 0
                                }
                    except Exception as e:
                        logger.error(f"Error with embedded view: {e}")
        except Exception as e:
            logger.error(f"Error with web request: {e}")
        
        # If we reached here, we couldn't extract quiz data
        return None
    except Exception as e:
        logger.error(f"Error parsing quiz URL: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}! Welcome to the Quiz Bot.\n\n"
        f"I can help you create and take quizzes. Here are some commands:\n\n"
        f"• /start - Show this welcome message\n"
        f"• /help - Show detailed help\n"
        f"• /add - Add a new quiz question\n"
        f"• /quiz - Start a quiz\n"
        f"• /category - Start a quiz from a specific category\n"
        f"• /delete - Delete a question\n"
        f"• /stats - Show your stats\n"
        f"• /poll2q - Convert a poll to a question\n"
        f"• /clone - Clone a quiz from a link\n\n"
        f"Let's start quizzing! 🎯"
    )
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "📚 *Quiz Bot Help*\n\n"
        "*Basic Commands:*\n"
        "• /start - Show welcome message\n"
        "• /help - Show this help message\n"
        "• /quiz - Start a quiz with random questions\n"
        "• /quiz 5 - Start a quiz with 5 random questions\n"
        "• /quiz id=123 - Start with specific question ID\n"
        "• /stats - Show your quiz statistics\n\n"
        
        "*Question Management:*\n"
        "• /add - Add a new question\n"
        "• /add id=123 - Add a new question with custom ID\n"
        "• /delete - Delete a question\n"
        "• /edit - Edit an existing question\n\n"
        
        "*Advanced Features:*\n"
        "• /category - Start a quiz from specific category\n"
        "• /clone - Clone a quiz from a link or message\n"
        "• /poll2q - Convert a Telegram poll to a question\n"
        "  (Reply to a poll with this command)\n\n"
        
        "*Poll2Q Options:*\n"
        "Reply to a poll with `/poll2q`\n\n"
        "With custom ID:\n"
        "• `/poll2q id=123` - Use specific ID #123\n"
        "• `/poll2q start=50` - Start from ID #50\n"
        "• `/poll2q batch` - Process multiple polls\n\n"
        
        "Send /quiz to start a quiz now!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    await update.message.reply_text(
        "Operation cancelled. What would you like to do next?",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the add question conversation."""
    # Check if a custom ID was provided
    custom_id = None
    if context.args:
        for arg in context.args:
            if arg.startswith("id="):
                try:
                    custom_id = int(arg.split('=')[1])
                    # Store the custom ID for later use
                    context.user_data['custom_id'] = custom_id
                except ValueError:
                    await update.message.reply_text("Invalid ID format. Please use numbers only.")
                    return ConversationHandler.END
    
    # If no custom ID in args, ask user if they want to use a custom ID or auto-generated ID
    if custom_id is None:
        keyboard = [
            [InlineKeyboardButton("Use auto-generated ID", callback_data="id_auto")],
            [InlineKeyboardButton("Specify custom ID", callback_data="id_custom")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "Would you like to use an auto-generated ID or specify a custom ID for this question?",
            reply_markup=reply_markup
        )
        return CUSTOM_ID
    else:
        # Custom ID was provided in command, proceed to question text
        await update.message.reply_text(
            f"Using custom ID: {custom_id}\n\n"
            "Please send me the question text."
        )
        return QUESTION

async def handle_id_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ID selection callback for add question."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "id_auto":
        # Use auto-generated ID
        next_id = get_next_question_id()
        context.user_data['custom_id'] = next_id
        await query.edit_message_text(
            f"Using auto-generated ID: {next_id}\n\n"
            "Please send me the question text."
        )
        return QUESTION
    elif query.data == "id_custom":
        # Ask for custom ID
        await query.edit_message_text(
            "Please enter a custom ID number for this question:"
        )
        return CUSTOM_ID
    
    return ConversationHandler.END

async def receive_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive custom ID for a new question."""
    try:
        custom_id = int(update.message.text.strip())
        
        # Check if ID already exists
        existing_question = get_question_by_id(custom_id)
        if existing_question:
            await update.message.reply_text(
                f"⚠️ ID {custom_id} already exists. Please choose a different ID or type /cancel to abort."
            )
            return CUSTOM_ID
        
        # Store the custom ID
        context.user_data['custom_id'] = custom_id
        await update.message.reply_text(
            f"Using custom ID: {custom_id}\n\n"
            "Now, please send me the question text."
        )
        return QUESTION
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Please enter a numeric ID or type /cancel to abort."
        )
        return CUSTOM_ID

async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the question text and ask for options."""
    question_text = update.message.text
    context.user_data["question_text"] = question_text
    context.user_data["options"] = []
    
    await update.message.reply_text(
        f"Question: {question_text}\n\n"
        f"Now, send me the first option for this question."
    )
    return OPTIONS

async def add_question_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the options and ask for the correct answer."""
    option = update.message.text
    context.user_data["options"].append(option)
    
    # Check if we have at least 2 options
    options_count = len(context.user_data["options"])
    
    if options_count < 2:
        await update.message.reply_text(
            f"Option {options_count}: {option}\n\n"
            f"Now, send me another option."
        )
        return OPTIONS
    
    # We have at least 2 options now
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(context.user_data["options"])])
    
    keyboard = [
        [InlineKeyboardButton("Add another option", callback_data="add_option")],
        [InlineKeyboardButton("Done adding options", callback_data="done_options")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Option {options_count}: {option}\n\n"
        f"Current options:\n{options_text}\n\n"
        f"Do you want to add another option or finish?",
        reply_markup=reply_markup
    )
    return OPTIONS

async def add_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the correct answer and finish adding the question."""
    try:
        answer = int(update.message.text) - 1  # Convert to 0-based index
        
        options = context.user_data.get("options", [])
        if answer < 0 or answer >= len(options):
            await update.message.reply_text(
                f"Invalid answer. Please enter a number between 1 and {len(options)}."
            )
            return ANSWER
        
        # Get question data
        question_text = context.user_data.get("question_text", "")
        category = context.user_data.get("category", "General")
        custom_id = context.user_data.get("custom_id", get_next_question_id())
        
        # Create the question object
        question = {
            "id": custom_id,
            "question": question_text,
            "options": options,
            "answer": answer,
            "category": category
        }
        
        # Load existing questions
        questions = load_questions()
        
        # Check for duplicate ID again (in case another process added a question)
        if any(q.get("id") == custom_id for q in questions):
            # Generate a new ID if duplicate
            new_id = get_next_question_id()
            question["id"] = new_id
            await update.message.reply_text(
                f"⚠️ ID {custom_id} was already taken. Using ID {new_id} instead."
            )
        
        # Add the new question
        questions.append(question)
        save_questions(questions)
        
        # Confirm to user
        await update.message.reply_text(
            f"✅ Question added successfully with ID {question['id']}!\n\n"
            f"Question: {question_text}\n"
            f"Options: {', '.join(options)}\n"
            f"Correct answer: {options[answer]}\n"
            f"Category: {category}\n\n"
            f"Use /add to add another question or /quiz to start a quiz."
        )
        
        # Clear conversation data
        context.user_data.clear()
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Please enter the number of the correct option."
        )
        return ANSWER

async def poll_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the poll to question conversation."""
    message = update.message
    
    # Check if the command was a reply to a poll message
    if not message.reply_to_message or not message.reply_to_message.poll:
        await message.reply_text(
            "⚠️ Please reply to a poll message with this command.\n\n"
            "For example:\n"
            "1. Find a poll/quiz in any Telegram chat\n"
            "2. Reply to it with the command /poll2q\n\n"
            "*Advanced Options:*\n"
            "• `/poll2q id=123` - Use specific ID #123\n"
            "• `/poll2q start=50` - Start from ID #50\n\n"
            "This will convert the poll to a saved quiz question.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    # Extract poll data
    poll = message.reply_to_message.poll
    question_text = poll.question
    options = [option.text for option in poll.options]
    
    # Store in context for later use
    context.user_data['poll_data'] = {
        'question': question_text,
        'options': options,
    }
    
    # Check if custom ID was specified in command
    custom_id = None
    for arg in context.args:
        if arg.startswith("id="):
            try:
                custom_id = int(arg.split('=')[1])
                context.user_data['custom_id'] = custom_id
                # Skip ID selection and go straight to answer selection
                break
            except ValueError:
                await message.reply_text("Invalid ID format. Please use numbers only.")
                return ConversationHandler.END
    
    # If no custom ID, ask user to choose
    if custom_id is None:
        keyboard = [
            [InlineKeyboardButton("Use auto-generated ID", callback_data="poll_id_auto")],
            [InlineKeyboardButton("Specify custom ID", callback_data="poll_id_custom")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            f"Converting poll to question:\n\n"
            f"*{question_text}*\n\n"
            f"Would you like to use an auto-generated ID or specify a custom ID?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return POLL2Q_ID
    else:
        # Custom ID was provided, proceed to answer selection
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
        
        # Create option buttons
        keyboard = []
        for i, option in enumerate(options):
            # Limit button text length
            button_text = option[:20] + ("..." if len(option) > 20 else "")
            keyboard.append([InlineKeyboardButton(
                f"{i+1}. {button_text}", 
                callback_data=f"poll_answer_{i}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            f"Using ID: {custom_id}\n\n"
            f"Please select the correct answer for:\n"
            f"*{question_text}*\n\n"
            f"Options:\n{options_text}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def poll_to_question_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the custom ID for poll2q command."""
    try:
        custom_id = int(update.message.text.strip())
        
        # Check if ID already exists
        existing_question = get_question_by_id(custom_id)
        if existing_question:
            await update.message.reply_text(
                f"⚠️ ID {custom_id} already exists. Please choose a different ID or type /cancel to abort."
            )
            return POLL2Q_ID
        
        # Store the custom ID
        context.user_data['custom_id'] = custom_id
        
        # Get stored poll data
        poll_data = context.user_data.get('poll_data', {})
        question_text = poll_data.get('question', '')
        options = poll_data.get('options', [])
        
        if not question_text or not options:
            await update.message.reply_text(
                "Error: Poll data not found. Please try again with /poll2q."
            )
            return ConversationHandler.END
        
        # Create option buttons for answer selection
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
        
        keyboard = []
        for i, option in enumerate(options):
            # Limit button text length
            button_text = option[:20] + ("..." if len(option) > 20 else "")
            keyboard.append([InlineKeyboardButton(
                f"{i+1}. {button_text}", 
                callback_data=f"poll_answer_{i}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Using ID: {custom_id}\n\n"
            f"Please select the correct answer for:\n"
            f"*{question_text}*\n\n"
            f"Options:\n{options_text}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Please enter a numeric ID or type /cancel to abort."
        )
        return POLL2Q_ID

async def handle_poll_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the selection of correct answer for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract selected answer index from callback data
    callback_data = query.data
    if not callback_data.startswith("poll_answer_"):
        await query.edit_message_text("Error: Invalid selection.")
        return
    
    try:
        answer_index = int(callback_data.split("_")[-1])
        
        # Get stored poll data
        poll_data = context.user_data.get('poll_data', {})
        question_text = poll_data.get('question', '')
        options = poll_data.get('options', [])
        
        if not question_text or not options or answer_index >= len(options):
            await query.edit_message_text("Error: Invalid poll data or selection.")
            return
        
        # Get custom ID or generate new one
        custom_id = context.user_data.get('custom_id', get_next_question_id())
        
        # Create the question object
        question = {
            "id": custom_id,
            "question": question_text,
            "options": options,
            "answer": answer_index,
            "category": "Poll Conversion"
        }
        
        # Load existing questions
        questions = load_questions()
        
        # Check for duplicate ID again (in case another process added a question)
        if any(q.get("id") == custom_id for q in questions):
            # Generate a new ID if duplicate
            new_id = get_next_question_id()
            question["id"] = new_id
            custom_id = new_id
        
        # Add the new question
        questions.append(question)
        save_questions(questions)
        
        # Confirm to user
        await query.edit_message_text(
            f"✅ Poll converted to question successfully with ID {custom_id}!\n\n"
            f"Question: {question_text}\n"
            f"Correct answer: {options[answer_index]}\n\n"
            f"Use /quiz to start a quiz with this question."
        )
        
        # Clear conversation data
        context.user_data.pop('poll_data', None)
        context.user_data.pop('custom_id', None)
    
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")
        await query.edit_message_text(f"Error: {str(e)}")

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz with all or specific questions."""
    # Default number of questions
    num_questions = 5
    
    # Check for command arguments
    specific_ids = []
    if context.args:
        for arg in context.args:
            if arg.isdigit():
                # If argument is a number, use it as the number of questions
                num_questions = int(arg)
            elif arg.startswith("id="):
                # If argument specifies IDs, add them to the list
                try:
                    id_value = int(arg.split("=")[1])
                    specific_ids.append(id_value)
                except (ValueError, IndexError):
                    await update.message.reply_text(f"Invalid ID format: {arg}")
    
    # Initialize quiz data
    context.user_data['quiz'] = {
        'questions': [],
        'current_index': 0,
        'participants': {},
        'start_time': datetime.now().timestamp()
    }
    
    # If specific IDs were provided, use those questions
    if specific_ids:
        selected_questions = []
        for question_id in specific_ids:
            question = get_question_by_id(question_id)
            if question:
                selected_questions.append(question)
        
        if not selected_questions:
            await update.message.reply_text("No valid questions found with the specified IDs.")
            del context.user_data['quiz']
            return
        
        context.user_data['quiz']['questions'] = selected_questions
        await update.message.reply_text(f"Starting quiz with {len(selected_questions)} specific questions...")
    else:
        # Otherwise, get random questions
        all_questions = load_questions()
        if not all_questions:
            await update.message.reply_text("No questions available. Add some questions first with /add.")
            del context.user_data['quiz']
            return
        
        # Randomly select questions
        available = min(num_questions, len(all_questions))
        context.user_data['quiz']['questions'] = random.sample(all_questions, available)
        await update.message.reply_text(f"Starting quiz with {available} random questions...")
    
    # Start the quiz
    await send_quiz_poll(
        chat_id=update.effective_chat.id,
        question_data=context.user_data['quiz']['questions'][0],
        context=context,
        message=update.message
    )

async def get_random_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a random quiz question."""
    # Load all questions
    all_questions = load_questions()
    if not all_questions:
        await update.message.reply_text("No questions available. Add some questions first with /add.")
        return
    
    # Select a random question
    question = random.choice(all_questions)
    
    # Send as a quiz poll
    await send_quiz_poll(
        chat_id=update.effective_chat.id,
        question_data=question,
        context=context,
        message=update.message,
        poll_duration=30  # longer duration for single questions
    )

async def send_quiz_poll(chat_id: int, question_data: dict, context: ContextTypes.DEFAULT_TYPE, 
                         message=None, poll_duration: int = 15) -> None:
    """Send a quiz poll with a countdown timer."""
    question_text = question_data['question']
    options = question_data['options']
    correct_option = question_data['answer']
    
    # Create and send the poll
    poll_message = await context.bot.send_poll(
        chat_id=chat_id,
        question=question_text,
        options=options,
        type='quiz',
        correct_option_id=correct_option,
        is_anonymous=False,
        explanation=None,
        open_period=poll_duration
    )
    
    # Store the poll data for tracking answers
    quiz_data = context.user_data.get('quiz', {})
    quiz_data['current_poll_id'] = poll_message.poll.id
    quiz_data['current_poll_message_id'] = poll_message.message_id
    context.user_data['quiz'] = quiz_data
    
    # Send countdown timer message
    timer_message = await context.bot.send_message(
        chat_id=chat_id,
        text=create_countdown_animation(poll_duration, poll_duration)
    )
    
    # Start the countdown timer in background
    asyncio.create_task(
        update_countdown_timer(
            bot=context.bot,
            chat_id=chat_id,
            message_id=timer_message.message_id,
            duration=poll_duration
        )
    )
    
    # Schedule next question or end quiz
    current_index = quiz_data.get('current_index', 0)
    questions = quiz_data.get('questions', [])
    
    # Increment the index for the next question
    quiz_data['current_index'] = current_index + 1
    context.user_data['quiz'] = quiz_data
    
    # If we're at the end or this is a single question, we're done
    if current_index >= len(questions) - 1 or len(questions) <= 1:
        # Wait for poll to close, then show results
        await asyncio.sleep(poll_duration + 2)  # Add 2 seconds buffer
        
        # Only call end_quiz if it's part of a quiz sequence
        if len(questions) > 1:
            await end_quiz(message, context)
    else:
        # Schedule next question
        await asyncio.sleep(poll_duration + 2)  # Add 2 seconds buffer
        
        # Check if we still have a quiz going (might have been cancelled)
        if 'quiz' in context.user_data:
            # Send next question
            next_index = quiz_data['current_index']
            if next_index < len(questions):
                await send_quiz_poll(
                    chat_id=chat_id,
                    question_data=questions[next_index],
                    context=context,
                    message=message,
                    poll_duration=poll_duration
                )

async def handle_quiz_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle when users answer the quiz poll."""
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    user = poll_answer.user
    
    # Get quiz data
    quiz_data = context.user_data.get('quiz', {})
    current_poll_id = quiz_data.get('current_poll_id')
    
    # Check if this is the current quiz poll
    if poll_id != current_poll_id:
        return
    
    # Get current question
    current_index = quiz_data.get('current_index', 0) - 1  # Adjusted for increment
    questions = quiz_data.get('questions', [])
    
    if 0 <= current_index < len(questions):
        question = questions[current_index]
        correct_option = question.get('answer')
        
        # Check if the answer is correct
        is_correct = selected_option == correct_option
        
        # Update participant data
        participants = quiz_data.get('participants', {})
        user_id = str(user.id)
        
        if user_id not in participants:
            participants[user_id] = {
                'name': user.first_name,
                'username': user.username,
                'correct': 0,
                'answered': 0
            }
        
        # Update the participant's score
        participants[user_id]['answered'] += 1
        if is_correct:
            participants[user_id]['correct'] += 1
        
        # Update user data in context
        quiz_data['participants'] = participants
        context.user_data['quiz'] = quiz_data

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the quiz poll when it closes."""
    quiz_data = context.user_data.get('quiz', {})
    
    if not quiz_data:
        await update.message.reply_text("No quiz in progress.")
        return
    
    questions = quiz_data.get('questions', [])
    participants = quiz_data.get('participants', {})
    
    # Calculate time taken
    start_time = quiz_data.get('start_time')
    time_taken = None
    if start_time:
        end_time = datetime.now().timestamp()
        time_taken = end_time - start_time
    
    # Format results
    if not participants:
        await update.message.reply_text(
            "🏁 The quiz has finished!\n\n"
            "No one participated in this quiz.\n\n"
            "Start a new quiz with /quiz"
        )
        return
    
    # Sort participants by score (correct answers) and then by speed
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: (x[1]['correct'], -x[1]['answered']),
        reverse=True
    )
    
    # Generate results text with checkered flag and trophy emojis
    results_text = "🏁 The quiz has finished!\n\n"
    
    # Add number of questions
    results_text += f"{len(questions)} questions answered\n\n"
    
    # Add winner announcement with trophy
    winner = sorted_participants[0][1]['name']
    winner_username = sorted_participants[0][1].get('username', '')
    if winner_username:
        winner_display = f"{winner} (@{winner_username})"
    else:
        winner_display = winner
        
    results_text += f"🏆 Congratulations to the winner: {winner_display}!\n\n"
    
    # Add each participant with medal and score
    for i, (user_id, data) in enumerate(sorted_participants):
        # Award medals for top performers
        if i == 0:
            medal = "🥇"  # Gold medal
        elif i == 1 and len(sorted_participants) > 1:
            medal = "🥈"  # Silver medal
        elif i == 2 and len(sorted_participants) > 2:
            medal = "🥉"  # Bronze medal
        else:
            medal = "🏅"  # Sports medal for others
        
        name = data.get('name', f"User {user_id}")
        username = data.get('username', '')
        if username:
            name_display = f"{name} (@{username})"
        else:
            name_display = name
            
        correct = data.get('correct', 0)
        total = len(questions)
        
        # Calculate score percentage
        percentage = (correct / total) * 100 if total > 0 else 0
        
        # Add participant result line
        results_text += f"{medal} {name_display}: {correct}/{total} ({percentage:.1f}%)\n"
    
    # Send results
    await update.message.reply_text(results_text)
    
    # Clear quiz data
    context.user_data.pop('quiz', None)

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Define conversation handler for adding questions
    add_question_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_question)],
        states={
            CUSTOM_ID: [
                CallbackQueryHandler(handle_id_selection, pattern=r"^id_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_id)
            ],
            QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_text)
            ],
            OPTIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_options),
                CallbackQueryHandler(lambda u, c: add_question_options(u, c), pattern="add_option"),
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.edit_message_text(
                        "Please enter the number of the correct option:"
                    ) or ANSWER,
                    pattern="done_options"
                )
            ],
            ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_answer)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Define conversation handler for poll to question
    poll2q_conv = ConversationHandler(
        entry_points=[CommandHandler("poll2q", poll_to_question)],
        states={
            POLL2Q_ID: [
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.edit_message_text(
                        "Please enter a custom ID number for this question:"
                    ) or POLL2Q_ID,
                    pattern="poll_id_custom"
                ),
                CallbackQueryHandler(
                    lambda u, c: handle_poll_answer_callback(u, c) or ConversationHandler.END,
                    pattern="poll_id_auto"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, poll_to_question_id)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Add handlers
    application.add_handler(add_question_conv)
    application.add_handler(poll2q_conv)
    
    # Add basic command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", start_quiz))
    application.add_handler(CommandHandler("random", get_random_quiz))
    
    # Add poll handlers
    application.add_handler(PollAnswerHandler(handle_quiz_poll_answer))
    application.add_handler(CallbackQueryHandler(handle_poll_answer_callback, pattern=r"^poll_answer_"))
    
    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()
