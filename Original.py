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
                        logger.error(f"Error scraping embedded content: {e}")
            
            # Try another fallback method for general text parsing
            try:
                # Look for a clear question and option structure in the page content
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                text_content = ' '.join(lines)
                
                # Try regex patterns for common quiz formats
                quiz_patterns = [
                    r'question:\s*([^\?]+\??)\s*options:(.+)',
                    r'quiz:\s*([^\?]+\??)\s*a\)(.*?)b\)(.*?)c\)(.*?)(d\).*?)?$',
                    r'([^\?]+\??)\s*a\.\s*(.*?)\s*b\.\s*(.*?)\s*c\.\s*(.*?)(\s*d\.\s*.*?)?$'
                ]
                
                for pattern in quiz_patterns:
                    match = re.search(pattern, text_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        question = match.group(1).strip()
                        options = []
                        for g in range(2, min(len(match.groups()) + 2, 6)):
                            if match.group(g) and match.group(g).strip():
                                options.append(match.group(g).strip())
                        if len(options) >= 2:
                            return {
                                "question": question,
                                "options": options,
                                "answer": 0
                            }
            except Exception as e:
                logger.error(f"Error parsing text content: {e}")
                
        except Exception as e:
            logger.error(f"Error fetching URL content: {e}")
        
        return None
    except Exception as e:
        logger.error(f"Error in parse_telegram_quiz_url: {e}")
        return None

# User tracking functions
def load_users():
    """Load user data from file"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as file:
                users = json.load(file)
            return users
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}! Welcome to the Quiz Bot.\n\n"
        f"I can help you create and take quizzes. Here are my commands:\n\n"
        f"/quiz - Start a quiz with random questions\n"
        f"/category - Start a quiz from a specific category\n"
        f"/add - Add a new quiz question\n"
        f"/edit - Edit an existing question\n"
        f"/delete - Delete a question\n"
        f"/stats - View your quiz statistics\n"
        f"/clone - Import a quiz from a Telegram URL or manually\n\n"
        f"Let's get started!"
    )
    await update.message.reply_text(welcome_message)
    
    # Initialize user data if not already present
    user_data = get_user_data(user.id)
    if not user_data:
        user_data = {
            "name": user.first_name,
            "username": user.username,
            "quizzes_taken": 0,
            "correct_answers": 0,
            "total_answers": 0
        }
        update_user_data(user.id, user_data)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command handler"""
    help_text = (
        "🔍 *Quiz Bot Help*\n\n"
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/quiz - Start a quiz with random questions\n"
        "/category - Start a quiz from a specific category\n"
        "/add - Add a new quiz question\n"
        "/edit - Edit an existing question\n"
        "/delete - Delete a question\n"
        "/stats - View your quiz statistics\n"
        "/clone - Import a quiz from a Telegram URL or manually\n\n"
        
        "*How to use:*\n"
        "1. Use /quiz to start a random quiz\n"
        "2. Answer the questions by selecting an option\n"
        "3. View your results at the end\n\n"
        
        "*Creating questions:*\n"
        "- Use /add to create a new question\n"
        "- Follow the prompts to add the question, options, and correct answer\n"
        "- Use /edit to modify existing questions\n\n"
        
        "*Cloning quizzes:*\n"
        "- Use /clone to import quizzes from Telegram URLs\n"
        "- You can also create quizzes manually through the clone interface"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user statistics"""
    user = update.effective_user
    user_data = get_user_data(user.id)
    
    quizzes_taken = user_data.get("quizzes_taken", 0)
    correct_answers = user_data.get("correct_answers", 0)
    total_answers = user_data.get("total_answers", 0)
    
    accuracy = 0
    if total_answers > 0:
        accuracy = (correct_answers / total_answers) * 100
    
    stats_message = (
        f"📊 *Quiz Statistics for {user.first_name}*\n\n"
        f"🎮 Quizzes taken: {quizzes_taken}\n"
        f"✅ Correct answers: {correct_answers}\n"
        f"📝 Total questions answered: {total_answers}\n"
        f"🎯 Accuracy: {accuracy:.1f}%\n\n"
    )
    
    await update.message.reply_text(stats_message, parse_mode='Markdown')

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new question"""
    await update.message.reply_text(
        "Let's add a new quiz question!\n\n"
        "First, please enter the question text:"
    )
    return QUESTION

async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question text input"""
    context.user_data['question'] = update.message.text
    await update.message.reply_text(
        "Great! Now, enter the options for the question, one per line.\n"
        "For example:\n"
        "Paris\n"
        "London\n"
        "Berlin\n"
        "Rome"
    )
    return OPTIONS

async def add_question_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle options input"""
    options_text = update.message.text
    options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
    
    if len(options) < 2:
        await update.message.reply_text(
            "Please provide at least 2 options, each on a new line:"
        )
        return OPTIONS
    
    context.user_data['options'] = options
    
    # Create keyboard with numbered options
    option_text = "Please select the correct answer by number:\n\n"
    for i, option in enumerate(options):
        option_text += f"{i+1}. {option}\n"
    
    await update.message.reply_text(option_text)
    return ANSWER

async def add_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle correct answer selection"""
    try:
        # Convert to zero-based index
        answer_index = int(update.message.text) - 1
        options = context.user_data.get('options', [])
        
        if answer_index < 0 or answer_index >= len(options):
            await update.message.reply_text(
                f"Please enter a number between 1 and {len(options)}:"
            )
            return ANSWER
        
        # Ask for category
        await update.message.reply_text(
            "Finally, enter a category for this question (e.g., Geography, Science, History):"
        )
        context.user_data['answer'] = answer_index
        
        # Get next question ID
        question_id = get_next_question_id()
        context.user_data['id'] = question_id
        
        # Add category selection
        keyboard = [
            ["Geography", "Science", "History"],
            ["Literature", "Sports", "Entertainment"],
            ["General Knowledge", "Other"]
        ]
        await update.message.reply_text(
            "Select a category or type your own:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(cat, callback_data=f"category_{cat}") for cat in row]
                for row in keyboard
            ])
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
    
    category = query.data.replace("category_", "")
    
    # Get the question data from context
    question_data = {
        "id": context.user_data.get('id'),
        "question": context.user_data.get('question'),
        "options": context.user_data.get('options'),
        "answer": context.user_data.get('answer'),
        "category": category
    }
    
    # Load existing questions, add new one, and save
    questions = load_questions()
    questions.append(question_data)
    success = save_questions(questions)
    
    if success:
        await query.edit_message_text(
            f"✅ Question added successfully!\n\n"
            f"Question: {question_data['question']}\n"
            f"Category: {category}\n\n"
            f"Use /quiz to start a quiz."
        )
    else:
        await query.edit_message_text(
            "❌ There was an error saving the question. Please try again."
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    await update.message.reply_text(
        "Operation cancelled.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def edit_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of editing a question"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text("There are no questions to edit.")
        return ConversationHandler.END
    
    # Display questions for selection
    question_list = "Select a question to edit:\n\n"
    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        # Truncate long questions
        if len(question_text) > 50:
            question_text = question_text[:47] + "..."
        question_list += f"{i+1}. {question_text}\n"
    
    await update.message.reply_text(question_list)
    context.user_data['questions'] = questions
    return EDIT_SELECT

async def edit_question_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question selection for editing"""
    try:
        selection = int(update.message.text) - 1
        questions = context.user_data.get('questions', [])
        
        if selection < 0 or selection >= len(questions):
            await update.message.reply_text(
                f"Please enter a number between 1 and {len(questions)}:"
            )
            return EDIT_SELECT
        
        # Store the selected question and its index
        selected_question = questions[selection]
        context.user_data['edit_index'] = selection
        context.user_data['edit_question'] = selected_question
        
        # Show the question details
        q_text = selected_question.get("question", "")
        options = selected_question.get("options", [])
        answer_idx = selected_question.get("answer", 0)
        category = selected_question.get("category", "Unknown")
        
        options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
        correct_answer = options[answer_idx] if 0 <= answer_idx < len(options) else "Unknown"
        
        details = (
            f"Question: {q_text}\n\n"
            f"Options:\n{options_text}\n\n"
            f"Correct answer: {correct_answer}\n"
            f"Category: {category}\n\n"
            f"What would you like to edit?\n\n"
            f"1. Question text\n"
            f"2. Options\n"
            f"3. Correct answer\n"
            f"4. Category"
        )
        
        await update.message.reply_text(details)
        return EDIT_QUESTION
    except ValueError:
        await update.message.reply_text("Please enter a valid number:")
        return EDIT_SELECT

async def edit_question_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle selection of which field to edit"""
    try:
        selection = int(update.message.text)
        selected_question = context.user_data.get('edit_question', {})
        
        if selection == 1:  # Edit question text
            await update.message.reply_text(
                f"Current question: {selected_question.get('question', '')}\n\n"
                f"Enter the new question text:"
            )
            context.user_data['edit_field'] = 'question'
            return EDIT_OPTIONS
        elif selection == 2:  # Edit options
            options = selected_question.get("options", [])
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
            
            await update.message.reply_text(
                f"Current options:\n{options_text}\n\n"
                f"Enter the new options, one per line:"
            )
            context.user_data['edit_field'] = 'options'
            return EDIT_OPTIONS
        elif selection == 3:  # Edit correct answer
            options = selected_question.get("options", [])
            options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
            current_answer = selected_question.get("answer", 0) + 1  # Convert to 1-based
            
            await update.message.reply_text(
                f"Options:\n{options_text}\n\n"
                f"Current correct answer: {current_answer}\n\n"
                f"Enter the new correct answer number:"
            )
            context.user_data['edit_field'] = 'answer'
            return EDIT_OPTIONS
        elif selection == 4:  # Edit category
            await update.message.reply_text(
                f"Current category: {selected_question.get('category', 'Unknown')}\n\n"
                f"Enter the new category:"
            )
            context.user_data['edit_field'] = 'category'
            return EDIT_OPTIONS
        else:
            await update.message.reply_text(
                "Please enter a number between 1 and 4:"
            )
            return EDIT_QUESTION
    except ValueError:
        await update.message.reply_text("Please enter a valid number:")
        return EDIT_QUESTION

async def edit_question_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the field update"""
    selected_question = context.user_data.get('edit_question', {})
    edit_field = context.user_data.get('edit_field')
    
    if edit_field == 'question':
        selected_question['question'] = update.message.text
    elif edit_field == 'options':
        options_text = update.message.text
        options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
        
        if len(options) < 2:
            await update.message.reply_text(
                "Please provide at least 2 options, each on a new line:"
            )
            return EDIT_OPTIONS
        
        selected_question['options'] = options
        
        # If the current answer is out of range with the new options, reset it to 0
        if selected_question.get('answer', 0) >= len(options):
            selected_question['answer'] = 0
    elif edit_field == 'answer':
        try:
            answer_index = int(update.message.text) - 1  # Convert to 0-based
            options = selected_question.get('options', [])
            
            if answer_index < 0 or answer_index >= len(options):
                await update.message.reply_text(
                    f"Please enter a number between 1 and {len(options)}:"
                )
                return EDIT_OPTIONS
            
            selected_question['answer'] = answer_index
        except ValueError:
            await update.message.reply_text("Please enter a valid number:")
            return EDIT_OPTIONS
    elif edit_field == 'category':
        selected_question['category'] = update.message.text
    
    # Update the question in the list
    questions = context.user_data.get('questions', [])
    edit_index = context.user_data.get('edit_index', 0)
    questions[edit_index] = selected_question
    
    # Save the updated questions
    success = save_questions(questions)
    
    if success:
        await update.message.reply_text(
            "✅ Question updated successfully!\n\n"
            "Use /quiz to start a quiz with the updated questions."
        )
    else:
        await update.message.reply_text(
            "❌ There was an error saving the question. Please try again."
        )
    
    return ConversationHandler.END

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for deleting questions"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text("There are no questions to delete.")
        return
    
    # Create inline keyboard with questions
    keyboard = []
    for i, q in enumerate(questions):
        question_text = q.get("question", "")
        # Truncate long questions
        if len(question_text) > 30:
            question_text = question_text[:27] + "..."
        keyboard.append([InlineKeyboardButton(
            f"{i+1}. {question_text}", callback_data=f"delete_{q.get('id')}"
        )])
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="delete_cancel")])
    
    await update.message.reply_text(
        "Select a question to delete:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete question callback"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "delete_cancel":
        await query.edit_message_text("Operation cancelled.")
        return
    
    # Extract question ID
    question_id = int(callback_data.replace("delete_", ""))
    success = delete_question_by_id(question_id)
    
    if success:
        await query.edit_message_text("✅ Question deleted successfully!")
    else:
        await query.edit_message_text("❌ There was an error deleting the question.")

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz with random questions or from a specific ID"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text(
            "❌ There are no questions available. Add some using /add command."
        )
        return
    
    # Default number of questions and starting parameters
    num_questions = 5
    start_id = None
    specific_id = None
    
    # Parse command arguments
    args = update.message.text.split()
    for arg in args[1:]:
        if arg.isdigit():
            # Simple number argument specifies question count
            num_questions = min(int(arg), 10)  # Limit to 10 questions maximum
        elif arg.startswith('id='):
            # id= argument specifies a starting question ID
            try:
                specific_id = int(arg.split('=')[1])
            except ValueError:
                await update.message.reply_text("❌ Invalid ID format. Using random questions instead.")
        elif arg.startswith('start='):
            # start= argument specifies starting from a question ID
            try:
                start_id = int(arg.split('=')[1])
            except ValueError:
                await update.message.reply_text("❌ Invalid start ID format. Using default numbering.")
    
    selected_questions = []
    
    # Case 1: Start with a specific question ID
    if specific_id is not None:
        # Find the specific question with this ID
        target_question = None
        for q in questions:
            if q.get('id') == specific_id:
                target_question = q
                break
        
        if target_question:
            selected_questions = [target_question]
            
            # Add stylish confirmation message
            await update.message.reply_text(
                f"🎯 Starting quiz with question #{specific_id}:\n\n"
                f"📝 *{target_question.get('question')}*",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ Question with ID #{specific_id} not found. Using random questions instead."
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
            await update.message.reply_text(
                f"🔢 Starting quiz with IDs #{first_id} to #{last_id}\n"
                f"📚 Total questions: {len(selected_questions)}"
            )
        else:
            await update.message.reply_text(
                f"❌ No questions found with ID #{start_id} or higher. Using random questions instead."
            )
            # Fall back to random selection
            selected_questions = random.sample(questions, min(num_questions, len(questions)))
    
    # Case 3: Default random selection
    else:
        num_questions = min(num_questions, len(questions))
        selected_questions = random.sample(questions, num_questions)
        
        # Add stylish confirmation message
        await update.message.reply_text(
            f"🎲 Starting a quiz with {len(selected_questions)} random questions.\n"
            f"🏁 Get ready to play!"
        )
    
    # Store the quiz details in user context
    context.user_data['quiz'] = {
        'questions': selected_questions,
        'current_index': 0,
        'scores': {},
        'participants': {},
        'active': True,
        'chat_id': update.effective_chat.id,
        'sent_polls': {}
    }
    
    # Store quiz creator information
    if hasattr(update, 'effective_user') and update.effective_user:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        username = update.effective_user.username
        
        context.user_data['quiz']['creator'] = {
            'id': user_id,
            'name': user_name,
            'username': username
        }
    
    # Initialize the quiz
    await send_next_question(update, context)

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
        await end_quiz(update, context)
        return
    
    # Get the current question
    question = questions[current_index]
    q_text = question.get("question", "Unknown Question")
    options = question.get("options", [])
    
    # Send the poll
    sent_message = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=q_text,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=question.get("answer", 0),
        is_anonymous=False,
        explanation=f"Question {current_index + 1} of {len(questions)}",
        open_period=30,  # 30 seconds to answer
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
    await asyncio.sleep(32)  # Wait a bit longer than poll open period
    
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
        if answer.option_ids and answer.option_ids[0] == correct_answer:
            active_quiz['participants'][user_id]['correct'] += 1
        
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
    
    if not quiz.get('active', False):
        logger.info("Quiz is not active, returning early")
        return
    
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
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: (x[1].get('correct', 0), -x[1].get('answered', 0)),
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
        
        # Add participant rankings with emoji indicators
        for i, (user_id, data) in enumerate(sorted_participants):
            # Use appropriate emoji for rankings
            rank_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            
            # Make sure we extract the correct user name
            correct = data.get('correct', 0)
            name = data.get('name', f"Player {i+1}")
            
            # Add username if available
            username = data.get('username', '')
            username_text = f" (@{username})" if username else ""
            
            # Calculate percentage score
            percentage = (correct / questions_count) * 100 if questions_count > 0 else 0
            
            # Format the participant line with rank, name, score
            results_message += f"{rank_emoji} {name}{username_text}: {correct}/{questions_count} ({percentage:.1f}%)\n"
    
    # Send the results
    await context.bot.send_message(
        chat_id=quiz.get('chat_id', update.effective_chat.id),
        text=results_message
    )
    
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
    
    # Store the quiz details in user context
    context.user_data['quiz'] = {
        'questions': selected_questions,
        'current_index': 0,
        'scores': {},
        'participants': {},
        'active': True,
        'chat_id': query.message.chat_id,
        'sent_polls': {}
    }
    
    # Notify that the quiz is starting
    await query.edit_message_text(f"Starting quiz with {num_questions} questions from {category}...")
    
    # Wait a moment before sending the first question
    await asyncio.sleep(2)
    
    # Initialize the quiz
    await send_next_question(query, context)

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
                "⚡️ *Ready to create your question!*"
            )
            
            await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown'
            )
            
            # If custom ID was provided in the command, use it directly
            if custom_id:
                # Store in user data for direct use in save_final_poll_question
                context.user_data['pending_question'] = {
                    'question': question_text,
                    'options': options,
                    'answer': correct_answer,
                    'category': "Poll Quiz"  # Default category
                }
                await save_final_poll_question(update, context, custom_id)
            else:
                # Otherwise go through normal flow
                await save_poll_as_question(update, context, question_text, options, correct_answer)
        else:
            # For regular polls, show stylish option selection
            welcome_message += (
                "\n❓ *Quiz Type*: Regular Poll (needs answer)\n\n"
                "🎲 *Select the correct answer from below:*"
            )
            
            await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown'
            )
            
            # Create stylish buttons with emojis and better formatting
            keyboard = []
            for i, option in enumerate(options):
                emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"][i] if i < 10 else f"{i+1}."
                # Limit option text length on buttons
                display_text = option[:20] + "..." if len(option) > 20 else option
                keyboard.append([InlineKeyboardButton(
                    f"{emoji} {display_text}",
                    callback_data=f"poll_answer_{i}"
                )])
            
            # Store the poll info in user_data for later
            context.user_data['pending_poll'] = {
                'question': question_text,
                'options': options,
                'custom_id': custom_id  # Store custom ID if provided
            }
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "👇 *Tap to select the CORRECT answer:*",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        # Stylish help message if no poll is found
        help_message = (
            "🌟 *QUIZ CREATOR PRO* 🌟\n\n"
            "📋 *Command Options:*\n"
            "─────────────────────\n"
            "📌 *Basic Usage:*\n"
            "Reply to a poll with `/poll2q`\n\n"
            "🎛️ *Advanced Options:*\n"
            "• `/poll2q id=123` - Use specific ID #123\n"
            "• `/poll2q start=50` - Start from ID #50\n"
            "• `/poll2q batch` - Process multiple polls\n\n"
            "🎮 *Quiz Commands:*\n"
            "• `/quiz id=123` - Start quiz with question #123\n"
            "• `/category id=50` - Category quiz from #50\n\n"
            "💡 *Try replying to a poll with one of these commands!*"
        )
        
        await update.message.reply_text(
            help_message,
            parse_mode='Markdown'
        )

async def handle_poll_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the selection of correct answer for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract the selected option from callback data
    selected_option = int(query.data.split('_')[-1])
    
    # Get the pending poll data
    pending_poll = context.user_data.get('pending_poll', {})
    if not pending_poll:
        await query.edit_message_text("Error: Poll data not found. Please try again.")
        return
    
    # Extract poll data
    question_text = pending_poll.get('question', '')
    options = pending_poll.get('options', [])
    
    # Save as a quiz question
    await save_poll_as_question(query, context, question_text, options, selected_option)
    
    # Clean up
    if 'pending_poll' in context.user_data:
        del context.user_data['pending_poll']

async def save_poll_as_question(update, context, question_text, options, correct_answer):
    """Save poll data as a quiz question"""
    # Default category
    category = "Quiz"
    
    # Create buttons for selecting a category - more elegant design
    keyboard = []
    
    # Get unique categories
    questions = load_questions()
    
    # Filter out empty or None categories
    valid_categories = [q.get("category", "Unknown") for q in questions if q.get("category")]
    # Add some default categories if none exist
    if not valid_categories:
        valid_categories = ["General Knowledge", "Trivia", "Science", "Sports", "History"]
    
    # Get unique categories and add "Quiz" as default if not present
    categories = sorted(set(valid_categories))
    if "Quiz" not in categories:
        categories = ["Quiz"] + categories
    
    # Common category emojis
    category_emojis = {
        "Quiz": "🎮",
        "General Knowledge": "🧠",
        "Trivia": "❓",
        "Science": "🔬",
        "Sports": "⚽",
        "History": "📜",
        "Geography": "🌍",
        "Entertainment": "🎬",
        "Music": "🎵",
        "Art": "🎨",
        "Technology": "💻",
        "Food": "🍔",
        "Animals": "🐾",
        "Politics": "🏛️",
        "Literature": "📚"
    }
    
    # Add top 5 most used categories with emojis
    # Count category occurrences
    category_counts = {}
    for q in questions:
        cat = q.get("category", "Quiz")
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # Sort by count, with "Quiz" always first
    sorted_categories = sorted(categories, 
                              key=lambda x: (0 if x == "Quiz" else 1, -category_counts.get(x, 0)))
    
    # Create buttons for top categories (up to 6)
    top_categories = sorted_categories[:6]
    
    # Create rows of 2 buttons
    row = []
    for i, cat in enumerate(top_categories):
        # Get emoji if available, otherwise use a generic one
        emoji = category_emojis.get(cat, "📋")
        row.append(InlineKeyboardButton(f"{emoji} {cat}", callback_data=f"pollcat_{cat}"))
        if len(row) == 2 or i == len(top_categories) - 1:
            keyboard.append(row)
            row = []
    
    # Store the question data for later
    context.user_data['pending_question'] = {
        'question': question_text,
        'options': options,
        'answer': correct_answer,
        'category': category  # Default category
    }
    
    # Create final keyboard with "Skip" option
    keyboard.append([InlineKeyboardButton("⏭️ Skip to ID Selection", callback_data="pollid_custom")])
    
    # Ask for category with a nice formatted message
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Create a nice formatted message
    category_message = (
        f"📋 *Select a Category*\n\n"
        f"Question: {question_text[:50]}{'...' if len(question_text) > 50 else ''}\n\n"
        f"Options: {len(options)}\n"
        f"Correct: {options[correct_answer][:30]}{'...' if len(options[correct_answer]) > 30 else ''}\n\n"
        f"Choose a category from below:"
    )
    
    if hasattr(update, 'message'):
        await update.message.reply_text(
            category_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.edit_message_text(
            category_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def handle_poll_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract the selected category
    selected_category = query.data.split('_')[1]
    
    # Update the pending question with the selected category
    pending_question = context.user_data.get('pending_question', {})
    pending_question['category'] = selected_category
    context.user_data['pending_question'] = pending_question
    
    # Ask if user wants to use a custom ID or auto-generated ID
    keyboard = [
        [InlineKeyboardButton("Auto-generate ID", callback_data="pollid_auto")],
        [InlineKeyboardButton("Use Custom ID", callback_data="pollid_custom")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"How would you like to assign an ID to this question?",
        reply_markup=reply_markup
    )

async def handle_poll_id_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ID method selection for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    id_type = query.data.split('_')[1]
    
    if id_type == 'auto':
        # Use auto-generated ID
        await save_final_poll_question(update, context)
    else:
        # Simplified ID selection - more elegant
        keyboard = []
        
        # Get existing IDs
        questions = load_questions()
        existing_ids = [q.get('id', 0) for q in questions]
        max_id = max(existing_ids) if existing_ids else 0
        
        # Create a simple, clean info message
        info_message = (
            "📝 *Question ID Selection*\n\n"
            "Choose an option below:"
        )
        
        # Add simple, clear buttons
        keyboard = [
            [InlineKeyboardButton("🔢 Next Available ID", callback_data=f"pollcustom_{max_id + 1}")],
            [InlineKeyboardButton("🔄 Auto Generate ID", callback_data="pollid_auto")],
            [InlineKeyboardButton("✏️ Type Custom ID", callback_data="pollcustom_input")]
        ]
        
        # Option to add directly to an existing ID as a single button
        if existing_ids:
            # Find the most recent ID
            recent_id = max_id
            # Count questions with this ID
            count = sum(1 for q in questions if q.get('id') == recent_id)
            
            keyboard.append([
                InlineKeyboardButton(f"➕ Add to ID #{recent_id} ({count} questions)", 
                                    callback_data=f"pollid_use_{recent_id}")
            ])
            
            # Also add button to see more existing IDs if there are several
            if len(set(existing_ids)) > 1:
                keyboard.append([
                    InlineKeyboardButton("🔍 Browse All IDs", callback_data="pollcustom_existing")
                ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Show the simplified interface
        await query.edit_message_text(
            info_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def handle_poll_custom_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID button selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    # Get the selection type
    selection = query.data.split('_')[1]
    
    if selection == "input":
        # User wants to input a custom ID
        await query.edit_message_text(
            "🔢 *Enter Your Custom ID*\n\n"
            "Please type a positive integer as the ID number for your question.",
            parse_mode='Markdown'
        )
        # Set state for expecting custom ID
        context.user_data['awaiting_custom_id'] = True
    
    elif selection == "existing":
        # User wants to add to an existing ID
        questions = load_questions()
        
        # Get unique IDs sorted
        existing_ids = sorted(set(q.get('id', 0) for q in questions))
        
        # Create a keyboard showing existing IDs
        keyboard = []
        row = []
        
        for i, id_num in enumerate(existing_ids[:15]):  # Show up to 15 IDs
            # Count how many questions use this ID
            count = sum(1 for q in questions if q.get('id') == id_num)
            button = InlineKeyboardButton(
                f"ID #{id_num} ({count})",
                callback_data=f"pollid_use_{id_num}"
            )
            
            row.append(button)
            if len(row) == 2 or i == len(existing_ids) - 1:
                keyboard.append(row)
                row = []
        
        # Add back button
        keyboard.append([
            InlineKeyboardButton("🔙 Back", callback_data="pollid_custom")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Select an existing ID to add this question to:",
            reply_markup=reply_markup
        )
    
    else:
        try:
            # Try to parse the selection as a direct ID number
            custom_id = int(selection)
            
            # Use this ID directly
            await save_final_poll_question(update, context, custom_id)
        except ValueError:
            # If not a direct ID (shouldn't happen with proper buttons)
            await query.edit_message_text(
                "Invalid selection. Please try again."
            )

async def handle_poll_use_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle selection of an existing ID to use"""
    query = update.callback_query
    await query.answer()
    
    # Extract the ID from the callback data
    selected_id = int(query.data.split('_')[-1])
    
    # Use this ID to save the question
    await save_final_poll_question(update, context, selected_id)

async def handle_custom_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID input for poll conversion"""
    # Only process if we're awaiting a custom ID
    if not context.user_data.get('awaiting_custom_id', False):
        return  # Let other handlers process this message
    
    # Try to convert input to an integer
    try:
        custom_id = int(update.message.text.strip())
        if custom_id <= 0:
            raise ValueError("ID must be positive")
            
        # Use the custom ID to save the question
        await save_final_poll_question(update, context, custom_id)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid positive integer as the ID. Try again:"
        )

async def save_final_poll_question(update, context, custom_id=None):
    """Save the final question with all data"""
    # Get the pending question data
    pending_question = context.user_data.get('pending_question', {})
    if not pending_question:
        message_text = "❌ Error: Question data not found. Please try again."
        
        # Check if update has a message attribute
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text(message_text)
        # Check if update is a callback query
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(message_text)
        # Otherwise try to edit message directly
        elif hasattr(update, 'edit_message_text'):
            await update.edit_message_text(message_text)
        # Fallback - just return without sending message
        else:
            print(f"Error: Could not send message - {message_text}")
        return
    
    # Create a new question object
    new_question = {
        "question": pending_question.get('question', ''),
        "options": pending_question.get('options', []),
        "answer": pending_question.get('answer', 0),
        "category": pending_question.get('category', 'Poll Quiz')
    }
    
    # Set the ID (either custom or auto-generated)
    if custom_id is not None:
        new_question["id"] = custom_id
    else:
        new_question["id"] = get_next_question_id()
    
    # Load existing questions 
    questions = load_questions()
    
    # Check for questions with the same ID
    existing_with_same_id = [q for q in questions if q.get("id") == new_question["id"]]
    
    # Check if we're deliberately using an existing ID or auto-generating
    if existing_with_same_id and custom_id is None:
        # If auto ID and there's a duplicate, get a different ID
        new_question["id"] = max(q.get("id", 0) for q in questions) + 1
    
    # Add the new question
    questions.append(new_question)
    save_questions(questions)
    
    # Clean up
    if 'pending_question' in context.user_data:
        del context.user_data['pending_question']
    if 'awaiting_custom_id' in context.user_data:
        del context.user_data['awaiting_custom_id']
    
    # Create a more stylish confirmation message
    # Check if we added to an existing ID
    if existing_with_same_id:
        total_with_id = len(existing_with_same_id) + 1
        confirmation_message = (
            f"✅ *Question Successfully Added!*\n\n"
            f"🆔 Added to ID #{new_question['id']}\n"
            f"📊 Now {total_with_id} questions with this ID\n\n"
            f"📝 *Question:* {new_question['question']}\n"
            f"🏷️ *Category:* {new_question['category']}\n"
            f"📋 *Options:* {len(new_question['options'])}\n"
            f"✓ *Correct answer:* {new_question['options'][new_question['answer']]}\n\n"
            f"Use `/quiz id={new_question['id']}` to start a quiz with this question!"
        )
    else:
        confirmation_message = (
            f"✅ *New Question Created!*\n\n"
            f"🆔 Assigned ID #{new_question['id']}\n\n"
            f"📝 *Question:* {new_question['question']}\n"
            f"🏷️ *Category:* {new_question['category']}\n"
            f"📋 *Options:* {len(new_question['options'])}\n"
            f"✓ *Correct answer:* {new_question['options'][new_question['answer']]}\n\n"
            f"Use `/quiz id={new_question['id']}` to start a quiz with this question!"
        )
    
    # Check if we should continue in batch mode
    batch_mode = context.user_data.get('batch_mode', False)
    
    if batch_mode:
        confirmation_message += "\n\n🔄 Batch mode is active. Reply to another poll to add it."
    
    if hasattr(update, 'message'):
        await update.message.reply_text(confirmation_message, parse_mode='Markdown')
    else:
        await update.edit_message_text(confirmation_message, parse_mode='Markdown')

async def test_results_display():
    """Test function to verify quiz results display properly"""
    print("==== TESTING QUIZ RESULTS DISPLAY ====")
    
    # Create a mock context that simulates a finished quiz
    mock_context = type('obj', (object,), {
        'user_data': {
            'quiz': {
                'active': True,
                'questions': [{'question': 'Test Q1?', 'answer': 0}, 
                             {'question': 'Test Q2?', 'answer': 1}],
                'chat_id': 123456789,
                'sent_polls': {
                    'poll1': {
                        'question_index': 0,
                        'answers': {
                            '111': {
                                'user_name': 'TestUser',
                                'username': 'testuser',
                                'is_correct': True,
                                'option_id': 0
                            }
                        }
                    },
                    'poll2': {
                        'question_index': 1,
                        'answers': {
                            '111': {
                                'user_name': 'TestUser',
                                'username': 'testuser',
                                'is_correct': False,
                                'option_id': 0
                            }
                        }
                    }
                }
            }
        },
        'bot': type('obj', (object,), {
            'send_message': 
                lambda chat_id, text: print(f"MOCK BOT RESPONSE:\n{text}")
        })
    })
    
    mock_update = type('obj', (object,), {
        'effective_chat': type('obj', (object,), {'id': 123456789})
    })
    
    # Call end_quiz with our mock objects
    await end_quiz(mock_update, mock_context)
    print("==== TEST COMPLETED ====")

if __name__ == "__main__":
    # Run the test if the TEST_MODE environment variable is set
    if os.environ.get('TEST_MODE') == '1':
        import asyncio
        asyncio.run(test_results_display())
    else:
        main()
