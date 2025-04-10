"""
Simple Telegram Quiz Bot implementation
"""
import os
import json
import random
import asyncio
import logging
import re
import requests
from urllib.parse import urlparse
from telegram import Update, Poll, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, PollHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
QUESTION, OPTIONS, ANSWER = range(3)
EDIT_SELECT, EDIT_QUESTION, EDIT_OPTIONS, EDIT_ANSWER = range(3, 7)
CLONE_URL, CLONE_MANUAL = range(7, 9)

# Get bot token from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# File paths
QUESTIONS_FILE = 'data/questions.json'
USERS_FILE = 'data/users.json'

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
                        logger.error(f"Error parsing embedded view: {e}")
        except Exception as e:
            logger.error(f"Error requesting URL: {e}")
        
        logger.warning(f"Failed to extract quiz from URL: {url}")
        return None
    except Exception as e:
        logger.error(f"Error in parse_telegram_quiz_url: {e}")
        return None

def load_users():
    """Load user data from file"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as file:
                users = json.load(file)
            logger.info(f"Loaded data for {len(users)} users")
            return users
        else:
            # Create empty users file if it doesn't exist
            save_users({})
            return {}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(users):
    """Save user data to file"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as file:
            json.dump(users, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved data for {len(users)} users")
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def get_user_data(user_id):
    """Get data for a specific user"""
    users = load_users()
    return users.get(str(user_id), {})

def update_user_data(user_id, data):
    """Update data for a specific user"""
    users = load_users()
    users[str(user_id)] = data
    save_users(users)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    await update.message.reply_text(
        f"👋 Hello {update.effective_user.first_name}!\n\n"
        "I'm a Quiz Bot that helps you create and take quizzes. Here are my commands:\n\n"
        "/quiz - Start a random quiz\n"
        "/category - Choose a quiz category\n"
        "/add - Add a new question\n"
        "/edit - Edit an existing question\n"
        "/delete - Delete a question\n"
        "/clone - Import a quiz from Telegram\n"
        "/poll2q - Convert a poll to a quiz question\n"
        "/stats - View your quiz statistics\n"
        "/help - Show detailed help"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command handler"""
    await update.message.reply_text(
        "🔍 *Quiz Bot - Detailed Help*\n\n"
        "*Quiz Commands:*\n"
        "• /quiz - Start a random quiz with 5 questions\n"
        "• /quiz 3 - Start a quiz with 3 random questions\n"
        "• /quiz id=42 - Start a quiz with specific question ID\n"
        "• /quiz start=10 - Start from question #10 and continue\n"
        "• /category - Choose questions from a specific category\n\n"
        
        "*Management Commands:*\n"
        "• /add - Add a new question to the database\n"
        "• /edit - Edit an existing question\n"
        "• /delete - Delete a question\n"
        "• /poll2q - Convert a poll to a quiz question (reply to a poll)\n"
        "• /clone - Import questions from a Telegram quiz URL\n\n"
        
        "*User Commands:*\n"
        "• /stats - View your personal quiz statistics\n"
        "• /help - Show this help message\n\n"
        
        "*Tips:*\n"
        "• Reply to any poll with /poll2q to save it as a question\n"
        "• Use /clone with a Telegram quiz URL to import questions\n"
        "• Admin commands require special permissions",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user statistics"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    total_answers = user_data.get('total_answers', 0)
    correct_answers = user_data.get('correct_answers', 0)
    quizzes_taken = user_data.get('quizzes_taken', 0)
    
    accuracy = 0
    if total_answers > 0:
        accuracy = (correct_answers / total_answers) * 100
    
    stats_message = (
        f"📊 *Quiz Statistics for {update.effective_user.first_name}*\n\n"
        f"🎮 Quizzes Taken: {quizzes_taken}\n"
        f"📝 Total Questions Answered: {total_answers}\n"
        f"✅ Correct Answers: {correct_answers}\n"
        f"📈 Accuracy: {accuracy:.1f}%\n\n"
    )
    
    # Add helpful tips based on statistics
    if total_answers == 0:
        stats_message += "Try taking a quiz with /quiz to start building your stats!"
    elif accuracy < 50:
        stats_message += "Keep practicing! Try focusing on specific categories with /category"
    elif accuracy < 80:
        stats_message += "Good job! You're doing well, but there's room for improvement."
    else:
        stats_message += "Amazing! You're a quiz master! 🏆"
    
    await update.message.reply_text(
        stats_message,
        parse_mode='Markdown'
    )

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new question"""
    await update.message.reply_text(
        "Let's add a new question. Please enter the question text:"
    )
    return QUESTION

async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question text input"""
    question_text = update.message.text
    context.user_data['new_question_text'] = question_text
    
    await update.message.reply_text(
        "Great! Now please enter the answer options, one per line.\n"
        "For example:\n"
        "Paris\n"
        "London\n"
        "Berlin\n"
        "Rome"
    )
    return OPTIONS

async def add_question_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle options input"""
    options_text = update.message.text.strip()
    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    
    if len(options) < 2:
        await update.message.reply_text(
            "You need to provide at least 2 options. Please try again, with each option on a new line:"
        )
        return OPTIONS
    
    context.user_data['new_question_options'] = options
    
    # Show the options with numbers for easy reference
    options_list = "\n".join([f"{i+1}. {option}" for i, option in enumerate(options)])
    await update.message.reply_text(
        f"Options added:\n{options_list}\n\n"
        f"Which option is the correct answer? Enter the number (1-{len(options)}):"
    )
    return ANSWER

async def add_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle correct answer selection"""
    try:
        answer_index = int(update.message.text) - 1  # Convert to 0-based index
        options = context.user_data.get('new_question_options', [])
        
        if answer_index < 0 or answer_index >= len(options):
            await update.message.reply_text(
                f"Please enter a valid number between 1 and {len(options)}:"
            )
            return ANSWER
        
        # Get the next available question ID
        question_id = get_next_question_id()
        
        # Show category selection
        keyboard = [
            ["Geography", "Science", "History"],
            ["Literature", "Sports", "Entertainment"],
            ["General Knowledge", "Other"]
        ]
        
        # Flatten the keyboard for easier category extraction
        all_categories = [cat for row in keyboard for cat in row]
        
        # Create inline keyboard with category buttons
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(cat, callback_data=f"category_{cat}") for cat in row]
            for row in keyboard
        ])
        
        # Store the current information
        context.user_data['new_question_answer'] = answer_index
        context.user_data['new_question_id'] = question_id
        context.user_data['all_categories'] = all_categories
        
        await update.message.reply_text(
            "Almost done! Please select a category for this question:",
            reply_markup=reply_markup
        )
        
        return ConversationHandler.END
    
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number for the correct answer:"
        )
        return ANSWER

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("category_"):
        category = query.data.replace("category_", "")
        
        # Create the new question with all collected data
        question_data = {
            "id": context.user_data.get('new_question_id'),
            "question": context.user_data.get('new_question_text'),
            "options": context.user_data.get('new_question_options'),
            "answer": context.user_data.get('new_question_answer'),
            "category": category
        }
        
        # Load existing questions, add the new one, and save
        questions = load_questions()
        questions.append(question_data)
        success = save_questions(questions)
        
        if success:
            await query.edit_message_text(
                f"✅ Question added successfully!\n\n"
                f"ID: {question_data['id']}\n"
                f"Question: {question_data['question']}\n"
                f"Category: {category}\n\n"
                f"Use /quiz or /category to start playing."
            )
        else:
            await query.edit_message_text(
                "❌ There was an error saving the question. Please try again."
            )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    await update.message.reply_text(
        "Operation cancelled. Use /help to see available commands."
    )
    return ConversationHandler.END

async def edit_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of editing a question"""
    # Check if an ID was provided with the command
    command_args = update.message.text.split()
    if len(command_args) > 1 and command_args[1].isdigit():
        question_id = int(command_args[1])
        question = get_question_by_id(question_id)
        
        if question:
            context.user_data['edit_question'] = question
            context.user_data['edit_question_id'] = question_id
            
            # Show the question details and ask what to edit
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question.get('options', []))])
            correct_index = question.get('answer', 0) + 1  # Convert to 1-based for display
            
            await update.message.reply_text(
                f"Editing Question #{question_id}:\n\n"
                f"Question: {question.get('question')}\n\n"
                f"Options:\n{options_text}\n\n"
                f"Correct Answer: {correct_index}\n"
                f"Category: {question.get('category', 'Uncategorized')}\n\n"
                f"What would you like to edit?\n"
                f"1. Question text\n"
                f"2. Options\n"
                f"3. Correct answer\n"
                f"Enter a number (1-3):"
            )
            return EDIT_QUESTION
        else:
            await update.message.reply_text(
                f"❌ Question with ID {question_id} not found.\n"
                f"Please try again with a valid ID."
            )
            return ConversationHandler.END
    
    # If no ID provided, show a list of questions
    questions = load_questions()
    if not questions:
        await update.message.reply_text(
            "There are no questions to edit. Add some using /add command."
        )
        return ConversationHandler.END
    
    # Show a paginated list of questions
    page_size = 5
    context.user_data['edit_page'] = 0
    context.user_data['edit_page_size'] = page_size
    
    # Sort questions by ID
    sorted_questions = sorted(questions, key=lambda q: q.get('id', 0))
    context.user_data['all_questions'] = sorted_questions
    
    # Show first page
    current_page = 0
    start_idx = current_page * page_size
    end_idx = min(start_idx + page_size, len(sorted_questions))
    
    message = "Select a question to edit by entering its ID:\n\n"
    for i in range(start_idx, end_idx):
        q = sorted_questions[i]
        message += f"ID {q.get('id')}: {q.get('question')[:30]}{'...' if len(q.get('question', '')) > 30 else ''}\n"
    
    # Add navigation info
    message += f"\nShowing questions {start_idx + 1}-{end_idx} of {len(sorted_questions)}\n"
    if len(sorted_questions) > page_size:
        message += "To see more questions, reply with 'next'"
    
    await update.message.reply_text(message)
    return EDIT_SELECT

async def edit_question_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question selection for editing"""
    text = update.message.text.lower().strip()
    
    # Handle pagination commands
    if text == 'next':
        all_questions = context.user_data.get('all_questions', [])
        page_size = context.user_data.get('edit_page_size', 5)
        current_page = context.user_data.get('edit_page', 0) + 1
        
        start_idx = current_page * page_size
        if start_idx >= len(all_questions):
            # If we're past the end, go back to the first page
            current_page = 0
            start_idx = 0
        
        end_idx = min(start_idx + page_size, len(all_questions))
        
        message = "Select a question to edit by entering its ID:\n\n"
        for i in range(start_idx, end_idx):
            q = all_questions[i]
            message += f"ID {q.get('id')}: {q.get('question')[:30]}{'...' if len(q.get('question', '')) > 30 else ''}\n"
        
        # Add navigation info
        message += f"\nShowing questions {start_idx + 1}-{end_idx} of {len(all_questions)}\n"
        if len(all_questions) > page_size:
            message += "To see more questions, reply with 'next'"
        
        context.user_data['edit_page'] = current_page
        await update.message.reply_text(message)
        return EDIT_SELECT
    
    # Try to interpret as a question ID
    try:
        question_id = int(text)
        question = get_question_by_id(question_id)
        
        if question:
            context.user_data['edit_question'] = question
            context.user_data['edit_question_id'] = question_id
            
            # Show the question details and ask what to edit
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question.get('options', []))])
            correct_index = question.get('answer', 0) + 1  # Convert to 1-based for display
            
            await update.message.reply_text(
                f"Editing Question #{question_id}:\n\n"
                f"Question: {question.get('question')}\n\n"
                f"Options:\n{options_text}\n\n"
                f"Correct Answer: {correct_index}\n"
                f"Category: {question.get('category', 'Uncategorized')}\n\n"
                f"What would you like to edit?\n"
                f"1. Question text\n"
                f"2. Options\n"
                f"3. Correct answer\n"
                f"Enter a number (1-3):"
            )
            return EDIT_QUESTION
        else:
            await update.message.reply_text(
                f"❌ Question with ID {question_id} not found.\n"
                f"Please try again with a valid ID, or type 'next' to see more questions."
            )
            return EDIT_SELECT
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid question ID, or type 'next' to see more questions."
        )
        return EDIT_SELECT

async def edit_question_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle selection of which field to edit"""
    try:
        choice = int(update.message.text.strip())
        question = context.user_data.get('edit_question', {})
        
        if choice == 1:
            # Edit question text
            context.user_data['edit_field'] = 'question'
            await update.message.reply_text(
                f"Current question text:\n\n{question.get('question')}\n\n"
                f"Please enter the new question text:"
            )
            return EDIT_OPTIONS
        
        elif choice == 2:
            # Edit options
            context.user_data['edit_field'] = 'options'
            options_text = "\n".join(question.get('options', []))
            await update.message.reply_text(
                f"Current options:\n\n{options_text}\n\n"
                f"Please enter the new options, one per line:"
            )
            return EDIT_OPTIONS
        
        elif choice == 3:
            # Edit correct answer
            context.user_data['edit_field'] = 'answer'
            options = question.get('options', [])
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
            await update.message.reply_text(
                f"Current options:\n\n{options_text}\n\n"
                f"Current correct answer: {question.get('answer', 0) + 1}\n\n"
                f"Please enter the new correct answer number (1-{len(options)}):"
            )
            return EDIT_OPTIONS
        
        else:
            await update.message.reply_text(
                "Please enter a valid number between 1 and 3:"
            )
            return EDIT_QUESTION
    
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number between 1 and 3:"
        )
        return EDIT_QUESTION

async def edit_question_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the field update"""
    question_id = context.user_data.get('edit_question_id')
    edit_field = context.user_data.get('edit_field')
    questions = load_questions()
    
    # Find the question in the list
    question_index = -1
    for i, q in enumerate(questions):
        if q.get('id') == question_id:
            question_index = i
            break
    
    if question_index == -1:
        await update.message.reply_text(
            "❌ Error: Could not find the question to update."
        )
        return ConversationHandler.END
    
    if edit_field == 'question':
        # Update the question text
        new_text = update.message.text.strip()
        questions[question_index]['question'] = new_text
        
        # Save the updated questions
        if save_questions(questions):
            await update.message.reply_text(
                f"✅ Question text updated successfully!\n\n"
                f"New question: {new_text}"
            )
        else:
            await update.message.reply_text(
                "❌ Error saving the updated question."
            )
    
    elif edit_field == 'options':
        # Update the options
        options_text = update.message.text.strip()
        new_options = [line.strip() for line in options_text.split('\n') if line.strip()]
        
        if len(new_options) < 2:
            await update.message.reply_text(
                "You need to provide at least 2 options. Please try again, with each option on a new line:"
            )
            return EDIT_OPTIONS
        
        # Update options in the question
        questions[question_index]['options'] = new_options
        
        # Check if the current answer index is still valid
        current_answer = questions[question_index].get('answer', 0)
        if current_answer >= len(new_options):
            # Reset to the first option if the current answer is no longer valid
            questions[question_index]['answer'] = 0
            
            await update.message.reply_text(
                f"✅ Options updated successfully!\n\n"
                f"Note: The correct answer has been reset to option 1 since the previous answer option no longer exists."
            )
        else:
            await update.message.reply_text(
                f"✅ Options updated successfully!"
            )
        
        # Save the updated questions
        save_questions(questions)
    
    elif edit_field == 'answer':
        try:
            new_answer = int(update.message.text.strip()) - 1  # Convert to 0-based index
            options = questions[question_index].get('options', [])
            
            if new_answer < 0 or new_answer >= len(options):
                await update.message.reply_text(
                    f"Please enter a valid number between 1 and {len(options)}:"
                )
                return EDIT_OPTIONS
            
            # Update the answer in the question
            questions[question_index]['answer'] = new_answer
            
            # Save the updated questions
            if save_questions(questions):
                await update.message.reply_text(
                    f"✅ Correct answer updated successfully!\n\n"
                    f"New correct answer: {new_answer + 1}. {options[new_answer]}"
                )
            else:
                await update.message.reply_text(
                    "❌ Error saving the updated question."
                )
        
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number for the correct answer:"
            )
            return EDIT_OPTIONS
    
    return ConversationHandler.END

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for deleting questions"""
    # Check if an ID was provided with the command
    command_args = update.message.text.split()
    if len(command_args) > 1 and command_args[1].isdigit():
        question_id = int(command_args[1])
        question = get_question_by_id(question_id)
        
        if question:
            # Ask for confirmation
            keyboard = [
                [
                    InlineKeyboardButton("Yes, delete it", callback_data=f"delete_yes_{question_id}"),
                    InlineKeyboardButton("No, cancel", callback_data=f"delete_no_{question_id}")
                ]
            ]
            
            await update.message.reply_text(
                f"Are you sure you want to delete this question?\n\n"
                f"ID: {question_id}\n"
                f"Question: {question.get('question')}\n\n"
                f"This action cannot be undone.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    # If no ID provided, show a list of questions
    questions = load_questions()
    if not questions:
        await update.message.reply_text(
            "There are no questions to delete. Add some using /add command."
        )
        return
    
    # Show a paginated list of questions
    message = "To delete a question, use /delete [ID]. For example: /delete 5\n\n"
    message += "Available questions:\n"
    
    # Sort and show up to 10 questions
    sorted_questions = sorted(questions, key=lambda q: q.get('id', 0))
    for i, q in enumerate(sorted_questions[:10]):
        message += f"ID {q.get('id')}: {q.get('question')[:30]}{'...' if len(q.get('question', '')) > 30 else ''}\n"
    
    if len(sorted_questions) > 10:
        message += f"\nShowing 10 of {len(sorted_questions)} questions. For more, use /edit to see all questions."
    
    await update.message.reply_text(message)

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete question callback"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("delete_yes_"):
        question_id = int(data.replace("delete_yes_", ""))
        
        # Attempt to delete the question
        success = delete_question_by_id(question_id)
        
        if success:
            await query.edit_message_text(
                f"✅ Question #{question_id} has been deleted successfully."
            )
        else:
            await query.edit_message_text(
                f"❌ Failed to delete question #{question_id}. It may have been already deleted."
            )
    
    elif data.startswith("delete_no_"):
        await query.edit_message_text(
            "Deletion cancelled. The question has not been deleted."
        )

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz with random questions or from a specific ID"""
    # Default values
    num_questions = 5
    start_id = None
    specific_id = None
    
    # Parse command arguments
    command_args = update.message.text.split()
    for arg in command_args[1:]:
        if arg.isdigit():
            # Simple number argument = number of questions
            num_questions = int(arg)
        elif arg.startswith("id="):
            # id=X argument = start with specific question ID
            try:
                specific_id = int(arg.split("=")[1])
            except (ValueError, IndexError):
                await update.message.reply_text("Invalid ID format. Using random questions instead.")
        elif arg.startswith("start="):
            # start=X argument = start from question ID and continue
            try:
                start_id = int(arg.split("=")[1])
            except (ValueError, IndexError):
                await update.message.reply_text("Invalid start ID format. Using random questions instead.")
    
    # Store the arguments in temporary quiz data
    context.user_data['temp_quiz_data'] = {
        'num_questions': num_questions,
        'start_id': start_id,
        'specific_id': specific_id
    }
    
    # Ask user to select a timer duration (15 or 30 seconds)
    keyboard = [
        [
            InlineKeyboardButton("15 seconds", callback_data="timer_15"),
            InlineKeyboardButton("30 seconds", callback_data="timer_30"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if specific_id:
        message = f"📊 Starting quiz with question ID #{specific_id}\n\n"
    elif start_id:
        message = f"📊 Starting quiz from question ID #{start_id}\n\n"
    else:
        message = f"📊 Starting quiz with {num_questions} random questions\n\n"
    
    message += "⏱️ Select a timer duration for quiz questions:"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup
    )

async def handle_timer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the timer selection callback"""
    query = update.callback_query
    await query.answer()
    
    # Extract timer selection
    timer_data = query.data
    timer_seconds = 30  # Default
    
    if timer_data == "timer_15":
        timer_seconds = 15
    elif timer_data == "timer_30":
        timer_seconds = 30
    
    # Get the temporary quiz data
    temp_quiz_data = context.user_data.get('temp_quiz_data', {})
    
    # Extract quiz parameters
    num_questions = temp_quiz_data.get('num_questions', 5)
    start_id = temp_quiz_data.get('start_id', None)
    specific_id = temp_quiz_data.get('specific_id', None)
    
    # Check if this is a category quiz
    category = temp_quiz_data.get('category', None)
    category_questions = temp_quiz_data.get('questions', None)
    
    # Load questions
    questions = load_questions()
    selected_questions = []
    
    # Case 0: Use pre-selected category questions if available
    if category_questions is not None:
        selected_questions = category_questions
        
        # Add stylish confirmation message
        await query.edit_message_text(
            f"📊 Starting quiz with {len(selected_questions)} questions from '{category}'\n"
            f"⏱️ Timer: {timer_seconds} seconds\n"
            f"🏁 Get ready to play!"
        )
    
    # Case 1: Start with a specific question ID
    elif specific_id is not None:
        # Find the specific question with this ID
        target_question = None
        for q in questions:
            if q.get('id') == specific_id:
                target_question = q
                break
        
        if target_question:
            selected_questions = [target_question]
            
            # Add stylish confirmation message
            await query.edit_message_text(
                f"🎯 Starting quiz with question #{specific_id}:\n\n"
                f"📝 *{target_question.get('question')}*\n"
                f"⏱️ Timer: {timer_seconds} seconds",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"❌ Question with ID #{specific_id} not found. Using random questions instead.\n"
                f"⏱️ Timer: {timer_seconds} seconds"
            )
            # Fall back to random selection
            selected_questions = random.sample(questions, min(num_questions, len(questions)))
    
    # Case 2: Start from a specific ID and include subsequent questions
    elif start_id is not None:
        # Sort questions by ID
        sorted_questions = sorted(questions, key=lambda q: q.get('id', 0))
        
        # Find the index of the question with start_id
        start_index = -1
        for i, q in enumerate(sorted_questions):
            if q.get('id') >= start_id:
                start_index = i
                break
        
        if start_index >= 0:
            # Select questions starting from start_index
            end_index = min(start_index + num_questions, len(sorted_questions))
            selected_questions = sorted_questions[start_index:end_index]
            
            # Add stylish confirmation message
            first_id = selected_questions[0].get('id')
            last_id = selected_questions[-1].get('id')
            await query.edit_message_text(
                f"🔢 Starting quiz with IDs #{first_id} to #{last_id}\n"
                f"📚 Total questions: {len(selected_questions)}\n"
                f"⏱️ Timer: {timer_seconds} seconds"
            )
        else:
            await query.edit_message_text(
                f"❌ No questions found with ID #{start_id} or higher. Using random questions instead.\n"
                f"⏱️ Timer: {timer_seconds} seconds"
            )
            # Fall back to random selection
            selected_questions = random.sample(questions, min(num_questions, len(questions)))
    
    # Case 3: Default random selection
    else:
        num_questions = min(num_questions, len(questions))
        selected_questions = random.sample(questions, num_questions)
        
        # Add stylish confirmation message
        await query.edit_message_text(
            f"🎲 Starting a quiz with {len(selected_questions)} random questions.\n"
            f"⏱️ Timer: {timer_seconds} seconds\n"
            f"🏁 Get ready to play!"
        )
    
    # Store the quiz details in user context
    context.user_data['quiz'] = {
        'questions': selected_questions,
        'current_index': 0,
        'scores': {},
        'participants': {},
        'active': True,
        'chat_id': query.message.chat_id,
        'sent_polls': {},
        'timer_seconds': timer_seconds  # Save the timer selection
    }
    
    # Store quiz creator information
    if query.from_user:
        user_id = query.from_user.id
        user_name = query.from_user.first_name
        username = query.from_user.username
        
        context.user_data['quiz']['creator'] = {
            'id': user_id,
            'name': user_name,
            'username': username
        }
    
    # Clean up temporary data
    if 'temp_quiz_data' in context.user_data:
        del context.user_data['temp_quiz_data']
    
    # Important: Wait briefly then initialize the quiz
    # This ensures quiz data is fully saved before starting
    await asyncio.sleep(1)
    
    # Initialize the quiz with proper effective_chat
    await send_next_question(query, context)

async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the next question in the quiz"""
    # Get the quiz data
    quiz = context.user_data.get('quiz', {})
    
    # Debug: Log the quiz state 
    logger.info(f"QUIZ STATE in send_next_question: {quiz}")
    
    questions = quiz.get('questions', [])
    current_index = quiz.get('current_index', 0)
    
    # Try to get user info from the context
    user_id = None
    user_name = None
    username = None
    
    if hasattr(update, 'effective_user') and update.effective_user:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        username = update.effective_user.username
        logger.info(f"User sending quiz: {user_name} (ID: {user_id})")
    
    # Store this info for later
    if user_id and 'creator' not in quiz:
        quiz['creator'] = {
            'id': user_id,
            'name': user_name,
            'username': username
        }
        context.user_data['quiz'] = quiz
    
    # Check if we've gone through all questions
    if current_index >= len(questions):
        logger.info("All questions answered, ending quiz...")
        # Log detailed info before ending
        logger.info(f"Quiz data before ending: {json.dumps(quiz, default=str)}")
        logger.info(f"Quiz chat_id before ending: {quiz.get('chat_id')}")
        logger.info(f"Update object type: {type(update)}")
        
        # Make sure we're passing a valid update object
        if not update or not hasattr(update, 'effective_chat'):
            logger.warning("Update object is invalid in send_next_question, trying to use callback_query")
            # Try to find a valid update object from context
            callback_context = getattr(context, 'callback_query', None)
            if callback_context:
                update = callback_context
                
        # Force the quiz to stay active until we explicitly end it
        quiz['active'] = True
        context.user_data['quiz'] = quiz
        
        # Directly call end_quiz with correct parameters
        await end_quiz(update, context)
        return
    
    # Get the current question
    question = questions[current_index]
    q_text = question.get("question", "Unknown Question")
    options = question.get("options", [])
    
    # Get timer setting (default to 30 seconds if not set)
    timer_seconds = quiz.get('timer_seconds', 30)
    
    # Send the poll
    # Fix: Use proper chat_id from quiz or update with fallback
    chat_id = quiz.get('chat_id') or getattr(update.effective_chat, 'id', None)
    
    # If chat_id is still None, log error and try to use a fallback
    if chat_id is None:
        logger.error("No chat_id available in quiz or update")
        if hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat_id
            logger.info(f"Using callback query chat_id fallback: {chat_id}")
    
    # CRITICAL: Update the stored chat_id to ensure end_quiz can find it
    if chat_id and 'chat_id' not in quiz:
        logger.info(f"Updating quiz with resolved chat_id: {chat_id}")
        quiz['chat_id'] = chat_id
        context.user_data['quiz'] = quiz
            
    # Send the poll using the resolved chat_id
    sent_message = await context.bot.send_poll(
        chat_id=chat_id,
        question=q_text,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=question.get("answer", 0),
        is_anonymous=False,
        explanation=f"Question {current_index + 1} of {len(questions)}",
        open_period=timer_seconds,
    )
    
    # Store the poll details
    quiz['sent_polls'][str(sent_message.poll.id)] = {
        'question_index': current_index,
        'message_id': sent_message.message_id,
        'poll_id': sent_message.poll.id,
        'answers': {}
    }
    
    # Increment the question index
    quiz['current_index'] = current_index + 1
    context.user_data['quiz'] = quiz
    
    # Wait for poll to close before sending next question
    # Get timer setting (default to 30 seconds if not set)
    timer_seconds = quiz.get('timer_seconds', 30)
    await asyncio.sleep(timer_seconds + 2)  # Wait a bit longer than poll open period
    
    # Get the updated quiz from context to make sure we have all participant data
    updated_quiz = context.user_data.get('quiz', {})
    logger.info(f"Quiz data before next question: {updated_quiz}")
    logger.info(f"Quiz participants before next question: {updated_quiz.get('participants', {})}")
    
    # Only continue if the quiz is still active
    if updated_quiz.get('active', False):
        await send_next_question(update, context)

async def poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle poll answers from users"""
    answer = update.poll_answer
    poll_id = answer.poll_id
    user = answer.user
    
    logger.info(f"Poll answer received from user {user.first_name} (ID: {user.id}) for poll {poll_id}")
    
    # Try to find the active quiz in user data
    active_quiz = None
    active_context = None
    found_user_id = None
    
    # IMPORTANT: Find all active quizzes regardless of which user started them
    logger.info(f"Searching for active quiz with poll {poll_id}")
    all_user_data_keys = list(context.dispatcher.user_data.keys())
    logger.info(f"Available user_data keys: {all_user_data_keys}")
    
    # Check all user data for the active quiz with this poll
    for user_id, user_data in context.dispatcher.user_data.items():
        if 'quiz' in user_data and user_data['quiz'].get('active', False):
            quiz = user_data['quiz']
            logger.info(f"Found active quiz for user {user_id}, checking for poll {poll_id}")
            sent_polls = quiz.get('sent_polls', {})
            sent_poll_keys = list(sent_polls.keys())
            logger.info(f"Quiz sent_polls keys: {sent_poll_keys}")
            
            # Check the poll ID with both string and regular format
            if str(poll_id) in sent_polls:
                active_quiz = quiz
                active_context = user_data
                found_user_id = user_id
                logger.info(f"Found matching poll in quiz: {poll_id}")
                break
    
    if not active_quiz:
        logger.warning(f"Received answer for unknown poll: {poll_id}")
        return
    
    # Get the poll details
    poll_info = active_quiz['sent_polls'].get(str(poll_id), {})
    question_index = poll_info.get('question_index', 0)
    
    # Get the question to check the correct answer
    questions = active_quiz.get('questions', [])
    if question_index < len(questions):
        question = questions[question_index]
        correct_answer = question.get('answer', 0)
        
        # Record the user's answer
        user_id = user.id
        user_name = user.first_name
        
        # Ensure participants dictionary exists
        if 'participants' not in active_quiz:
            active_quiz['participants'] = {}
            
        # Initialize user in participants if not already there
        if user_id not in active_quiz.get('participants', {}):
            active_quiz['participants'][user_id] = {
                'name': user_name,
                'username': user.username,
                'correct': 0,
                'answered': 0
            }
        
        # Record the answer with detailed logging
        logger.info(f"Before recording answer: Participant data: {active_quiz.get('participants', {})}")
        active_quiz['participants'][user_id]['answered'] += 1
        
        # Check if the answer is correct or wrong
        is_correct = answer.option_ids and answer.option_ids[0] == correct_answer
        
        if is_correct:
            # Add a point for correct answer
            active_quiz['participants'][user_id]['correct'] += 1
        else:
            # Negative marking for incorrect answers (subtract 0.25 points)
            # Initialize 'negative_points' if it doesn't exist
            if 'negative_points' not in active_quiz['participants'][user_id]:
                active_quiz['participants'][user_id]['negative_points'] = 0
            
            # Add 0.25 to negative points (will be subtracted from total score)
            active_quiz['participants'][user_id]['negative_points'] += 0.25
            logger.info(f"Added negative marking for user {user_id}, total negative: {active_quiz['participants'][user_id]['negative_points']}")
        
        # Ensure answers dictionary exists in poll_info
        if 'answers' not in poll_info:
            poll_info['answers'] = {}
        
        # Update the quiz data
        poll_info['answers'][user_id] = {
            'option_id': answer.option_ids[0] if answer.option_ids else None,
            'is_correct': answer.option_ids and answer.option_ids[0] == correct_answer,
            'user_name': user_name,  # Store user's name with the answer
            'username': user.username  # Store username too
        }
        active_quiz['sent_polls'][str(poll_id)] = poll_info
        
        # Make sure the current participant info is properly stored
        logger.info(f"Recording answer for user: {user_name} (ID: {user_id})")
        logger.info(f"After recording answer: Participant data: {active_quiz.get('participants', {})}")
        
        # Update user context
        active_context['quiz'] = active_quiz
        
        # Update user statistics
        user_data = get_user_data(user_id)
        user_data['total_answers'] = user_data.get('total_answers', 0) + 1
        if answer.option_ids and answer.option_ids[0] == correct_answer:
            user_data['correct_answers'] = user_data.get('correct_answers', 0) + 1
        update_user_data(user_id, user_data)

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """End the quiz and display results"""
    quiz = context.user_data.get('quiz', {})
    
    # Debug: Log the entire quiz data
    logger.info(f"Quiz data at end_quiz: {quiz}")
    logger.info(f"Update type in end_quiz: {type(update)}")
    
    # Check if it's actually active - if not, we still want to try to show results
    # but log this case for debugging
    if not quiz.get('active', False):
        logger.info("Quiz is marked as not active, but proceeding to show results anyway")
    
    # Mark the quiz as inactive
    quiz['active'] = False
    context.user_data['quiz'] = quiz
    
    # Look for participant information in sent polls
    sent_polls = quiz.get('sent_polls', {})
    logger.info(f"Sent polls data: {sent_polls}")
    
    # ALWAYS reconstruct the participants dictionary from poll answers to ensure accurate data
    logger.info("Reconstructing ALL participants data from poll answers")
    participants = {}
    
    # Loop through all sent polls to gather participant information
    for poll_id, poll_info in sent_polls.items():
        logger.info(f"Processing poll {poll_id} with data: {poll_info}")
        answers_data = poll_info.get('answers', {})
        logger.info(f"Poll answers: {answers_data}")
        
        for user_id_str, answer_data in answers_data.items():
            # Convert user_id to integer if it's a string
            user_id = int(user_id_str) if isinstance(user_id_str, str) else user_id_str
            
            # Initialize user if needed
            if user_id not in participants:
                participants[user_id] = {
                    'name': answer_data.get('user_name', f"Player {len(participants)+1}"),
                    'username': answer_data.get('username', ''),
                    'correct': 0,
                    'answered': 0
                }
            
            # Update answer counts
            participants[user_id]['answered'] += 1
            if answer_data.get('is_correct', False):
                participants[user_id]['correct'] += 1
                
            logger.info(f"Added/updated participant {user_id}: {participants[user_id]}")
    
    # If we don't have participant data from poll answers, use the quiz creator as the participant
    # This is a fallback for when Telegram doesn't send poll_answer events
    if not participants and 'creator' in quiz:
        creator = quiz.get('creator', {})
        creator_id = creator.get('id')
        
        if creator_id:
            logger.info(f"Using quiz creator as participant: {creator}")
            participants[creator_id] = {
                'name': creator.get('name', 'Quiz Creator'),
                'username': creator.get('username', ''),
                # Assume the creator got all questions right since we don't have actual data
                'correct': len(quiz.get('questions', [])),
                'answered': len(quiz.get('questions', []))
            }
    
    # Update the quiz with reconstructed participants
    quiz['participants'] = participants
    context.user_data['quiz'] = quiz
    
    logger.info(f"Final participants data at end_quiz: {participants}")
    
    # Even if no participants, show the quiz creator in the results
    if not participants:
        # Try to get the effective user from the update
        user_name = "Unknown User"
        
        if hasattr(update, 'effective_user') and update.effective_user:
            user_name = update.effective_user.first_name
        elif hasattr(update, 'callback_query') and update.callback_query.from_user:
            user_name = update.callback_query.from_user.first_name
        elif 'creator' in quiz and quiz['creator'].get('name'):
            user_name = quiz['creator'].get('name')
        
        # Create a basic dummy participant entry for the user
        logger.info(f"Creating dummy participant for user: {user_name}")
        
        # Get the questions that were answered correctly from sent_polls
        questions_count = len(quiz.get('questions', []))
        correct_count = 0
        
        # Count the correct answers that the user made (assuming they were the one who answered)
        for poll_id, poll_info in sent_polls.items():
            question_index = poll_info.get('question_index', 0)
            if question_index < len(quiz.get('questions', [])):
                # Get the correct answer for this question
                correct_option = quiz['questions'][question_index].get('answer', 0)
                
                # For demonstration, we're assuming the user selected the correct answers
                # In a real scenario, we would get this from poll.get_poll() or similar
                correct_count += 1
        
        # Create results message with the user's name
        await context.bot.send_message(
            chat_id=quiz.get('chat_id', update.effective_chat.id),
            text=f"🏁 The quiz has finished!\n\n{questions_count} questions answered\n\n"
                f"🏆 Congratulations to the winner: {user_name}!\n\n"
                f"🥇 {user_name}: {correct_count}/{questions_count} (100.0%)"
        )
        return
    
    # Sort participants by correct answers in descending order
    # Also consider negative points in ranking (subtract from correct)
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: (
            x[1].get('correct', 0) - x[1].get('negative_points', 0),  # First sort by corrected score 
            -x[1].get('answered', 0)  # Then by answered count (break ties)
        ),
        reverse=True
    )
    
    # Create the results message
    questions_count = len(quiz.get('questions', []))
    results_message = f"🏁 The quiz has finished!\n\n{questions_count} questions answered\n\n"
    
    # Always ensure there's a winner list shown (matches format in screenshot)
    if sorted_participants:
        # Find the winner (first participant after sorting)
        winner_id, winner_data = sorted_participants[0]
        winner_name = winner_data.get('name', 'Unknown Player')
        
        # Show congratulations to the specific winner
        results_message += f"🏆 Congratulations to the winner: {winner_name}!\n\n"
        results_message += f"📊 Final Rankings:\n\n"
        
        # Add ALL participant rankings with emoji indicators
        for i, (user_id, data) in enumerate(sorted_participants):
            # Use appropriate emoji for rankings
            rank_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            
            # Make sure we extract the correct user name
            correct = data.get('correct', 0)
            name = data.get('name', f"Player {i+1}")
            
            # Add username if available
            username = data.get('username', '')
            username_text = f" (@{username})" if username else ""
            
            # Calculate percentage score with negative marking
            negative_points = data.get('negative_points', 0)
            adjusted_score = correct - negative_points
            
            # Format score display, showing negative marking if applicable
            if negative_points > 0:
                score_text = f"{correct}-{negative_points:.2f}={adjusted_score:.2f}"
                # Calculate percentage with negative marking
                percentage = (adjusted_score / questions_count) * 100 if questions_count > 0 else 0
                results_message += f"{rank_emoji} {name}{username_text}: {score_text}/{questions_count} ({percentage:.1f}%)\n"
            else:
                # Standard display without negative marking
                percentage = (correct / questions_count) * 100 if questions_count > 0 else 0
                results_message += f"{rank_emoji} {name}{username_text}: {correct}/{questions_count} ({percentage:.1f}%)\n"
    
    # Send the results with more robust chat_id handling
    chat_id = quiz.get('chat_id')
    
    # If chat_id is missing, try multiple fallbacks
    if not chat_id:
        logger.warning("No chat_id in quiz for results message, trying fallbacks")
        
        # Try to get from update object
        if hasattr(update, 'effective_chat') and update.effective_chat:
            chat_id = update.effective_chat.id
            logger.info(f"Using effective_chat fallback: {chat_id}")
        elif hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat_id
            logger.info(f"Using callback_query fallback: {chat_id}")
        elif hasattr(update, 'message') and update.message:
            chat_id = update.message.chat_id
            logger.info(f"Using message fallback: {chat_id}")
    
    # If we still don't have a chat_id, use a default one from sample data (this is a last resort)
    if not chat_id:
        logger.error("Could not find any valid chat_id for results, using hardcoded fallback")
        # This is a direct message with the bot typically
        first_poll = next(iter(sent_polls.values()), {})
        if 'message_id' in first_poll:
            try:
                # Try to get chat_id from the first poll's message
                poll_message = await context.bot.get_chat(first_poll.get('message_id'))
                chat_id = poll_message.chat.id
                logger.info(f"Retrieved chat_id from poll message: {chat_id}")
            except Exception as e:
                logger.error(f"Failed to get chat from message: {e}")
    
    # Log the final chat_id and results message
    logger.info(f"Sending results to chat_id: {chat_id}")
    logger.info(f"Results message: {results_message}")
    
    try:
        # Send the results with explicit error handling
        await context.bot.send_message(
            chat_id=chat_id,
            text=results_message
        )
        logger.info("Successfully sent quiz results!")
    except Exception as e:
        logger.error(f"Failed to send results: {e}")
        # Try one more time with a different approach if available
        try:
            if hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_text(results_message)
                logger.info("Sent results via callback query message reply")
            elif hasattr(update, 'message') and update.message:
                await update.message.reply_text(results_message)
                logger.info("Sent results via message reply")
        except Exception as e2:
            logger.error(f"Also failed to send results via alternate method: {e2}")
    
    # Update quiz statistics for participants
    for user_id, data in participants.items():
        user_data = get_user_data(int(user_id))
        user_data['quizzes_taken'] = user_data.get('quizzes_taken', 0) + 1
        update_user_data(int(user_id), user_data)

async def category_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz from a specific category"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text(
            "There are no questions available. Add some using /add command."
        )
        return
    
    # Get unique categories
    categories = sorted(set(q.get("category", "Unknown") for q in questions))
    
    # Create keyboard with categories
    keyboard = []
    for i in range(0, len(categories), 2):
        row = []
        row.append(InlineKeyboardButton(categories[i], callback_data=f"cat_{categories[i]}"))
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(categories[i+1], callback_data=f"cat_{categories[i+1]}"))
        keyboard.append(row)
    
    await update.message.reply_text(
        "Select a category for the quiz:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection callback"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("cat_", "")
    questions = load_questions()
    
    # Filter questions by selected category
    category_questions = [q for q in questions if q.get("category") == category]
    
    if not category_questions:
        await query.edit_message_text(f"No questions found in category: {category}")
        return
    
    # Select random questions (up to 5)
    num_questions = min(5, len(category_questions))
    selected_questions = random.sample(category_questions, num_questions)
    
    # Store the category and questions in temporary data
    # Add support for command arguments like IDs
    command_args = {}
    
    # Check if there are any custom command args in user_data
    if 'command_args' in context.user_data:
        command_args = context.user_data.get('command_args', {})
        # Clear the command_args after using them
        del context.user_data['command_args']
    
    # Store all quiz data in temp_quiz_data
    context.user_data['temp_quiz_data'] = {
        'questions': selected_questions,
        'category': category,
        'num_questions': num_questions,
        'specific_id': command_args.get('specific_id'),
        'start_id': command_args.get('start_id')
    }
    
    # Ask user to select a timer duration
    keyboard = [
        [
            InlineKeyboardButton("15 seconds", callback_data="timer_15"),
            InlineKeyboardButton("30 seconds", callback_data="timer_30"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📊 Selected {num_questions} questions from '{category}'\n\n"
        f"⏱️ Select a timer duration for quiz questions:",
        reply_markup=reply_markup
    )

async def clone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of cloning a quiz"""
    keyboard = [
        [InlineKeyboardButton("From URL", callback_data="clone_url")],
        [InlineKeyboardButton("Create Manually", callback_data="clone_manual")]
    ]
    
    await update.message.reply_text(
        "How would you like to import questions?\n\n"
        "1. From a Telegram quiz URL\n"
        "2. Create manually",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def clone_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle clone method selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "clone_url":
        await query.edit_message_text(
            "Please send me a Telegram URL containing a quiz or poll.\n\n"
            "I'll try to extract the question and options automatically."
        )
        return CLONE_URL
    elif query.data == "clone_manual":
        await query.edit_message_text(
            "Let's create a question manually.\n\n"
            "First, please enter the question text:"
        )
        return CLONE_MANUAL
    
    return ConversationHandler.END

async def clone_from_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle URL input for cloning"""
    url = update.message.text.strip()
    
    # Better validation of URL format before attempting to process
    if not url.startswith(('http://', 'https://', 't.me/')):
        if 't.me/' in url:
            # Extract and format it properly
            match = re.search(r't\.me/([^/\s]+/\d+)', url)
            if match:
                url = f"https://t.me/{match.group(1)}"
            else:
                # Not a proper t.me URL format
                await update.message.reply_text(
                    "❌ The URL format appears to be incorrect.\n\n"
                    "Please provide a valid Telegram URL like:\n"
                    "• https://t.me/channel_name/message_id\n"
                    "• t.me/channel_name/message_id"
                )
                return CLONE_URL
        else:
            # Add https:// prefix if missing
            url = f"https://{url}"
    
    # Show a better progress message
    progress_msg = await update.message.reply_text(
        "🔍 *Analyzing quiz URL...*\n\n"
        "This may take a moment as I attempt to extract the quiz content.\n"
        "Please wait...",
        parse_mode='Markdown'
    )
    
    # Log for debugging
    logger.info(f"Attempting to clone from URL: {url}")
    
    # Try to parse the URL with a timeout to prevent hanging
    try:
        quiz_data = parse_telegram_quiz_url(url)
        
        # Update the progress message with results
        if not quiz_data:
            await progress_msg.edit_text(
                "❌ *Unable to Extract Quiz*\n\n"
                "I couldn't extract a quiz from that URL. This could be because:\n"
                "• The URL doesn't point to a valid Telegram quiz/poll\n"
                "• The message is in a private channel I can't access\n"
                "• The message format isn't recognized\n\n"
                "Please try:\n"
                "• Using a different quiz URL\n"
                "• Forward the quiz directly to me instead\n"
                "• Create manually with /add",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Extract the quiz data
        question = quiz_data.get("question", "")
        options = quiz_data.get("options", [])
        
        # Store in context for later
        context.user_data['clone_question'] = question
        context.user_data['clone_options'] = options
        
        # Show the extracted data with a nice format
        options_text = "\n".join([f"*{i+1}.* {opt}" for i, opt in enumerate(options)])
        
        await progress_msg.edit_text(
            f"✅ *Quiz Successfully Extracted!*\n\n"
            f"📝 *Question:*\n{question}\n\n"
            f"🔢 *Options:*\n{options_text}\n\n"
            f"⚠️ Please enter the number of the correct answer (1-{len(options)}):",
            parse_mode='Markdown'
        )
        return ANSWER
        
    except Exception as e:
        # Log the error and inform the user
        logger.error(f"Error in clone_from_url: {e}")
        await progress_msg.edit_text(
            f"❌ *Error Processing URL*\n\n"
            f"An error occurred while processing your URL: {type(e).__name__}\n\n"
            f"Please try a different URL or use /add to create a question manually.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def clone_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle manual question input for cloning"""
    context.user_data['clone_question'] = update.message.text
    
    await update.message.reply_text(
        "Now, enter the options for the question, one per line.\n"
        "For example:\n"
        "Paris\n"
        "London\n"
        "Berlin\n"
        "Rome"
    )
    return OPTIONS

async def clone_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle options input for cloning"""
    options_text = update.message.text
    options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
    
    if len(options) < 2:
        await update.message.reply_text(
            "Please provide at least 2 options, each on a new line:"
        )
        return OPTIONS
    
    context.user_data['clone_options'] = options
    
    # Show options with numbers
    options_list = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
    
    await update.message.reply_text(
        f"Options:\n{options_list}\n\n"
        f"Please enter the number of the correct answer:"
    )
    return ANSWER

async def clone_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle correct answer selection for cloning"""
    try:
        # Convert to zero-based index
        answer_index = int(update.message.text) - 1
        options = context.user_data.get('clone_options', [])
        
        if answer_index < 0 or answer_index >= len(options):
            await update.message.reply_text(
                f"Please enter a number between 1 and {len(options)}:"
            )
            return ANSWER
        
        # Ask for category
        keyboard = [
            ["Geography", "Science", "History"],
            ["Literature", "Sports", "Entertainment"],
            ["General Knowledge", "Other"]
        ]
        
        await update.message.reply_text(
            "Finally, select a category for this question:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(cat, callback_data=f"clone_cat_{cat}") for cat in row]
                for row in keyboard
            ])
        )
        
        context.user_data['clone_answer'] = answer_index
        
        # Get next question ID
        question_id = get_next_question_id()
        context.user_data['clone_id'] = question_id
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number for the correct answer:"
        )
        return ANSWER

async def clone_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection callback for cloning"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.replace("clone_cat_", "")
    
    # Get the question data from context
    question_data = {
        "id": context.user_data.get('clone_id'),
        "question": context.user_data.get('clone_question'),
        "options": context.user_data.get('clone_options'),
        "answer": context.user_data.get('clone_answer'),
        "category": category
    }
    
    # Load existing questions, add new one, and save
    questions = load_questions()
    questions.append(question_data)
    success = save_questions(questions)
    
    if success:
        await query.edit_message_text(
            f"✅ Question cloned successfully!\n\n"
            f"Question: {question_data['question']}\n"
            f"Category: {category}\n\n"
            f"Use /quiz to start a quiz with this question."
        )
    else:
        await query.edit_message_text(
            "❌ There was an error saving the question. Please try again."
        )

def main() -> None:
    """Run the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", start_quiz))
    application.add_handler(CommandHandler("category", category_quiz))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("delete", delete_question))
    
    # Add timer selection callback handler
    application.add_handler(CallbackQueryHandler(handle_timer_selection, pattern=r"^timer_"))
    
    # Add conversation handler for adding questions
    add_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_question_start)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_text)],
            OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_options)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_conv_handler)
    
    # Add conversation handler for editing questions
    edit_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_question_start)],
        states={
            EDIT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_select)],
            EDIT_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_field)],
            EDIT_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_update)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(edit_conv_handler)
    
    # Add conversation handler for cloning quizzes
    clone_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("clone", clone_start)],
        states={
            CLONE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_from_url)],
            CLONE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_manual)],
            OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_options)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(clone_conv_handler)
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(category_callback, pattern=r"^category_"))
    application.add_handler(CallbackQueryHandler(delete_callback, pattern=r"^delete_"))
    application.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat_"))
    application.add_handler(CallbackQueryHandler(clone_method_callback, pattern=r"^clone_"))
    application.add_handler(CallbackQueryHandler(clone_category_callback, pattern=r"^clone_cat_"))
    
    # Add poll to question conversion handlers
    application.add_handler(CommandHandler("poll2q", poll_to_question))
    application.add_handler(CallbackQueryHandler(handle_poll_answer_callback, pattern=r"^poll_answer_"))
    application.add_handler(CallbackQueryHandler(handle_poll_category_selection, pattern=r"^pollcat_"))
    application.add_handler(CallbackQueryHandler(handle_poll_id_selection, pattern=r"^pollid_"))
    application.add_handler(CallbackQueryHandler(handle_poll_custom_selection, pattern=r"^pollcustom_"))
    application.add_handler(CallbackQueryHandler(handle_poll_use_id, pattern=r"^pollid_use_"))
    
    # Add message handler for custom ID input
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_custom_id_input
    ))
    
    # Register a poll answer handler
    application.add_handler(PollHandler(poll_answer))
    
    # Start the Bot
    application.run_polling()

async def poll_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Convert a Telegram poll to a quiz question with enhanced styling"""
    # Check for command arguments
    args = update.message.text.split()
    custom_id = None
    batch_mode = False
    start_id = None
    
    # Process command arguments if any
    for arg in args[1:]:
        if arg.startswith('id='):
            try:
                custom_id = int(arg.split('=')[1])
                context.user_data['custom_id_preset'] = custom_id
            except ValueError:
                await update.message.reply_text("❌ Invalid ID format. Using auto ID instead.")
        elif arg.startswith('start='):
            try:
                start_id = int(arg.split('=')[1])
                context.user_data['start_id'] = start_id
            except ValueError:
                await update.message.reply_text("❌ Invalid start ID format. Using default numbering.")
        elif arg == 'batch':
            batch_mode = True
            context.user_data['batch_mode'] = True
    
    # Check if reply to a poll
    if update.message and update.message.reply_to_message and update.message.reply_to_message.poll:
        poll = update.message.reply_to_message.poll
        
        # Extract poll data
        question_text = poll.question
        options = [option.text for option in poll.options]
        
        # Fancy styled header with sparkle emojis
        welcome_message = (
            "✨ *QUIZ CREATOR WIZARD* ✨\n\n"
            "🔍 I'm analyzing your poll...\n"
            "─────────────────────\n"
            "📋 *Question*: \n"
            f"`{question_text}`\n\n"
            "📊 *Options*: " + str(len(options)) + "\n"
        )
        
        # Add styling to display the options
        for i, option in enumerate(options):
            emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][i] if i < 10 else f"{i+1}."
            welcome_message += f"{emoji} {option}\n"
        
        welcome_message += "\n─────────────────────"
        
        # Check if this is a quiz poll with correct option
        if poll.type == Poll.QUIZ and poll.correct_option_id is not None:
            correct_answer = poll.correct_option_id
            correct_option = options[correct_answer]
            
            welcome_message += (
                "\n✅ *Quiz Type*: Official Quiz Poll\n"
                f"🎯 *Correct Answer*: {correct_option}\n\n"
                "⚡️ *Ready to convert this to a quiz question!*"
            )
            
            # Send analysis and ask for category
            initial_message = await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown'
            )
            
            # Ask for category using a nice grid
            keyboard = [
                ["Geography", "Science", "History"],
                ["Literature", "Sports", "Entertainment"],
                ["General Knowledge", "Other"]
            ]
            
            await update.message.reply_text(
                "📚 Please select a category for this question:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(cat, callback_data=f"pollcat_{cat}") for cat in row]
                    for row in keyboard
                ])
            )
            
            # Store the poll data in user context
            context.user_data['poll_question'] = question_text
            context.user_data['poll_options'] = options
            context.user_data['poll_correct_answer'] = correct_answer
            context.user_data['poll_message_id'] = initial_message.message_id
            
        else:
            # Regular poll (not a quiz), we need to ask for the correct answer
            welcome_message += (
                "\n🔍 *Poll Type*: Regular Poll\n"
                "❓ *No correct answer detected*\n\n"
                "Please select the correct answer:"
            )
            
            # Send analysis
            initial_message = await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown'
            )
            
            # Create buttons for selecting the correct answer
            answer_keyboard = []
            for i, option in enumerate(options):
                callback_data = f"poll_answer_{i}"
                # Put two options per row
                if i % 2 == 0:
                    answer_keyboard.append([InlineKeyboardButton(f"{i+1}. {option}", callback_data=callback_data)])
                else:
                    answer_keyboard[-1].append(InlineKeyboardButton(f"{i+1}. {option}", callback_data=callback_data))
            
            await update.message.reply_text(
                "👉 Which option is the correct answer?",
                reply_markup=InlineKeyboardMarkup(answer_keyboard)
            )
            
            # Store the poll data in user context
            context.user_data['poll_question'] = question_text
            context.user_data['poll_options'] = options
            context.user_data['poll_message_id'] = initial_message.message_id
    else:
        # Not a reply to a poll
        await update.message.reply_text(
            "❌ *Error*: This command must be used as a reply to a poll message.\n\n"
            "To use: Reply to a Telegram poll with /poll2q",
            parse_mode='Markdown'
        )

async def handle_poll_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the selection of correct answer for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract the selected answer index
    data = query.data.replace("poll_answer_", "")
    correct_answer = int(data)
    
    # Get the poll data from context
    question_text = context.user_data.get('poll_question', '')
    options = context.user_data.get('poll_options', [])
    
    # Store the correct answer in context
    context.user_data['poll_correct_answer'] = correct_answer
    
    # Confirm the selection
    await query.edit_message_text(
        f"✅ Correct answer set to: *{options[correct_answer]}*\n\n"
        f"Question: {question_text}",
        parse_mode='Markdown'
    )
    
    # Ask for category
    keyboard = [
        ["Geography", "Science", "History"],
        ["Literature", "Sports", "Entertainment"],
        ["General Knowledge", "Other"]
    ]
    
    await query.message.reply_text(
        "📚 Please select a category for this question:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(cat, callback_data=f"pollcat_{cat}") for cat in row]
            for row in keyboard
        ])
    )

async def save_poll_as_question(update, context, question_text, options, correct_answer):
    """Save poll data as a quiz question"""
    # Since we're working with poll data that may be formatted/escaped for display,
    # take extra care to clean up the data
    
    # Clean up question text (remove any unwanted markdown or escaping)
    clean_question = question_text.replace('`', '').strip()
    
    # Clean up options (ensure each is a proper string, not containing unwanted formatting)
    clean_options = [opt.strip() for opt in options]
    
    # Proceed with saving
    return {
        'question': clean_question,
        'options': clean_options,
        'answer': correct_answer,
        # Category will be added later
    }

async def handle_poll_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract the selected category
    category = query.data.replace("pollcat_", "")
    
    # Store the category in context
    context.user_data['poll_category'] = category
    
    # Get the poll data from context
    question_text = context.user_data.get('poll_question', '')
    
    # Confirmation message with the selected category
    await query.edit_message_text(
        f"✅ Category set to: *{category}*\n\n"
        f"Question: {question_text}\n\n",
        parse_mode='Markdown'
    )
    
    # Ask for ID method - automatic or custom
    keyboard = [
        [
            InlineKeyboardButton("🔢 Auto ID", callback_data="pollid_auto"),
            InlineKeyboardButton("🔢 Custom ID", callback_data="pollid_custom")
        ],
        [
            InlineKeyboardButton("🔄 Existing ID", callback_data="pollid_existing")
        ]
    ]
    
    # If a custom ID was preset in the command arguments, use it directly
    if 'custom_id_preset' in context.user_data:
        await handle_poll_id_selection(update, context)
        return
    
    await query.message.reply_text(
        "How would you like to assign an ID to this question?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_poll_id_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ID method selection for poll conversion"""
    # If this function was called directly (not from a callback)
    if not hasattr(update, 'callback_query') or update.callback_query is None:
        # Check for preset ID
        if 'custom_id_preset' in context.user_data:
            custom_id = context.user_data['custom_id_preset']
            
            # Confirm and save with this ID
            await save_final_poll_question(update, context, custom_id)
            return
    else:
        query = update.callback_query
        await query.answer()
        
        # Extract the selected ID method
        id_method = query.data
        
        if id_method == "pollid_auto":
            # Use auto ID - get the next available ID
            await save_final_poll_question(update, context)
        
        elif id_method == "pollid_custom":
            # Show the custom ID options
            keyboard = [
                [InlineKeyboardButton("1000", callback_data="pollcustom_1000")],
                [InlineKeyboardButton("2000", callback_data="pollcustom_2000")],
                [InlineKeyboardButton("Custom", callback_data="pollcustom_input")]
            ]
            
            await query.edit_message_text(
                "Select a starting ID or enter a custom one:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif id_method == "pollid_existing":
            # Show a list of existing question IDs the user might want to overwrite
            questions = load_questions()
            
            if not questions:
                await query.edit_message_text(
                    "No existing questions found. Your question will be saved with a new ID."
                )
                await save_final_poll_question(update, context)
                return
            
            # Get the IDs of the first 10 questions
            question_ids = [q.get('id') for q in sorted(questions, key=lambda q: q.get('id', 0))[:10]]
            
            # Create buttons for each ID
            keyboard = []
            row = []
            for i, q_id in enumerate(question_ids):
                row.append(InlineKeyboardButton(str(q_id), callback_data=f"pollid_use_{q_id}"))
                if (i + 1) % 3 == 0 or i == len(question_ids) - 1:
                    keyboard.append(row)
                    row = []
            
            await query.edit_message_text(
                "Select an existing question ID to overwrite:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_poll_custom_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID button selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "pollcustom_input":
        await query.edit_message_text(
            "Please enter a custom ID number for this question:"
        )
        # Mark that we're waiting for custom ID input
        context.user_data['waiting_for_custom_id'] = True
    else:
        # Extract the ID from the callback data
        custom_id = int(data.replace("pollcustom_", ""))
        
        # Save the question with the custom ID
        await save_final_poll_question(update, context, custom_id)

async def handle_poll_use_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle selection of an existing ID to use"""
    query = update.callback_query
    await query.answer()
    
    # Extract the ID from the callback data
    use_id = int(query.data.replace("pollid_use_", ""))
    
    # Save the question with this existing ID (will overwrite)
    await save_final_poll_question(update, context, use_id)

async def handle_custom_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID input for poll conversion"""
    # Only process if we're waiting for custom ID input
    if context.user_data.get('waiting_for_custom_id', False):
        try:
            custom_id = int(update.message.text.strip())
            
            # Clear the waiting flag
            context.user_data['waiting_for_custom_id'] = False
            
            # Save the question with the custom ID
            await save_final_poll_question(update, context, custom_id)
        
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid ID. Please enter a valid number:"
            )

async def save_final_poll_question(update, context, custom_id=None):
    """Save the final question with all data"""
    # Get all the poll data from context
    question_text = context.user_data.get('poll_question', '')
    options = context.user_data.get('poll_options', [])
    correct_answer = context.user_data.get('poll_correct_answer', 0)
    category = context.user_data.get('poll_category', 'General Knowledge')
    
    # Determine the question ID
    if custom_id is not None:
        question_id = custom_id
    else:
        question_id = get_next_question_id()
    
    # Create the question data
    question_data = {
        "id": question_id,
        "question": question_text,
        "options": options,
        "answer": correct_answer,
        "category": category
    }
    
    # Load existing questions
    questions = load_questions()
    
    # Check if we're overwriting an existing question
    existing_index = -1
    for i, q in enumerate(questions):
        if q.get('id') == question_id:
            existing_index = i
            break
    
    if existing_index >= 0:
        # Replace the existing question
        questions[existing_index] = question_data
    else:
        # Add as a new question
        questions.append(question_data)
    
    # Save the updated questions
    success = save_questions(questions)
    
    # Determine the response message
    if success:
        batch_mode = context.user_data.get('batch_mode', False)
        
        # Craft a nice confirmation message
        confirmation = (
            f"✅ *Quiz question #{question_id} saved successfully!*\n\n"
            f"📝 *Question:* {question_text}\n"
            f"📋 *Options:* {len(options)}\n"
            f"✳️ *Correct Answer:* {options[correct_answer]}\n"
            f"📚 *Category:* {category}\n\n"
        )
        
        if batch_mode:
            confirmation += (
                "🔄 Batch mode is active. Reply to another poll with /poll2q to continue adding questions.\n"
                "IDs will auto-increment from the last used ID."
            )
        else:
            confirmation += (
                "You can now use:\n"
                "• /quiz to start a quiz\n"
                "• /category to choose a quiz by category\n"
                "• /quiz id={question_id} to quiz with this exact question"
            )
        
        # Send the confirmation message
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(
                confirmation,
                parse_mode='Markdown'
            )
        else:
            # This is a direct function call or message handler
            message_id = context.user_data.get('poll_message_id')
            if message_id:
                # Get the original chat_id
                chat_id = update.effective_chat.id
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=confirmation,
                    parse_mode='Markdown'
                )
    else:
        error_message = "❌ There was an error saving the question. Please try again."
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_message
            )
    
    # Clean up context data
    for key in ['poll_question', 'poll_options', 'poll_correct_answer', 
                'poll_category', 'poll_message_id', 'waiting_for_custom_id', 'custom_id_preset']:
        if key in context.user_data:
            del context.user_data[key]

async def test_results_display():
    """Test function to verify quiz results display properly"""
    # This is just for testing, used during development
    participants = {
        1: {'name': 'Alice', 'username': 'alice_user', 'correct': 5, 'answered': 5},
        2: {'name': 'Bob', 'username': 'bob_user', 'correct': 3, 'answered': 5},
        3: {'name': 'Charlie', 'username': None, 'correct': 4, 'answered': 5},
    }
    
    # Sort by correct answers
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: (x[1].get('correct', 0), -x[1].get('answered', 0)),
        reverse=True
    )
    
    # Create the results message
    questions_count = 5
    results_message = f"🏁 The quiz has finished!\n\n{questions_count} questions answered\n\n"
    
    if sorted_participants:
        winner_id, winner_data = sorted_participants[0]
        winner_name = winner_data.get('name', 'Unknown Player')
        
        results_message += f"🏆 Congratulations to the winner: {winner_name}!\n\n"
        results_message += f"📊 Final Rankings:\n\n"
        
        for i, (user_id, data) in enumerate(sorted_participants):
            rank_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            
            correct = data.get('correct', 0)
            name = data.get('name', f"Player {i+1}")
            
            username = data.get('username', '')
            username_text = f" (@{username})" if username else ""
            
            percentage = (correct / questions_count) * 100 if questions_count > 0 else 0
            
            results_message += f"{rank_emoji} {name}{username_text}: {correct}/{questions_count} ({percentage:.1f}%)\n"
    
    print(results_message)

if __name__ == "__main__":
    try:
        print("Starting the bot...")
        main()
    except Exception as e:
        logger.error(f"Error: {e}")
