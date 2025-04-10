"""
Enhanced Telegram Quiz Bot implementation
Features:
- Display all participants in quiz results
- Negative marking for incorrect answers
- Configurable timer functionality
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
TIMER_SELECT = 9

# Get bot token from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# File paths
QUESTIONS_FILE = 'data/questions.json'
USERS_FILE = 'data/users.json'

# Constants
DEFAULT_TIMER = 0  # No timer by default
TIMER_OPTIONS = [0, 15, 30]  # 0 means no timer

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
                        logger.error(f"Error parsing embedded Telegram URL: {e}")
        except Exception as e:
            logger.error(f"Error parsing Telegram URL: {e}")
    except Exception as e:
        logger.error(f"Unexpected error parsing Telegram URL: {e}")
    
    return None

def load_user_data():
    """Load user data from the JSON file"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as file:
                users = json.load(file)
            return users
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading user data: {e}")
        return {}

def save_user_data(users):
    """Save user data to the JSON file"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as file:
            json.dump(users, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        return False

def update_user_score(user_id, user_name, points):
    """Update a user's score"""
    users = load_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        users[user_id_str] = {
            "name": user_name,
            "score": 0,
            "questions_answered": 0,
            "correct_answers": 0
        }
    
    # Update the user's score
    users[user_id_str]["score"] = users[user_id_str].get("score", 0) + points
    users[user_id_str]["questions_answered"] = users[user_id_str].get("questions_answered", 0) + 1
    
    if points > 0:
        users[user_id_str]["correct_answers"] = users[user_id_str].get("correct_answers", 0) + 1
    
    save_user_data(users)
    return users[user_id_str]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued"""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! I'm the Quiz Bot.\n\n"
        "Use /quiz to start a new quiz\n"
        "Use /add to add a new question\n"
        "Use /list to list all questions\n"
        "Use /mystats to check your statistics\n"
        "Use /leaderboard to see the top players"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued"""
    await update.message.reply_text(
        "Quiz Bot commands:\n\n"
        "/quiz - Start a new quiz (random question)\n"
        "/quiz [category] - Start a quiz from a specific category\n"
        "/add - Add a new question\n"
        "/edit - Edit an existing question\n"
        "/delete - Delete a question\n"
        "/list - List all questions\n"
        "/import - Import questions from a Telegram quiz link\n"
        "/mystats - Check your statistics\n"
        "/leaderboard - See the top players"
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a quiz when the command /quiz is issued"""
    # Check if the quiz should focus on a specific category
    category = None
    if context.args and context.args[0]:
        category = context.args[0].strip()
    
    # Load questions
    questions = load_questions()
    if not questions:
        await update.message.reply_text("No questions available. Add some with /add first!")
        return
    
    # Filter by category if specified
    if category:
        category_questions = [q for q in questions if q.get("category", "").lower() == category.lower()]
        if category_questions:
            questions = category_questions
        else:
            await update.message.reply_text(f"No questions found for category '{category}'. Using all questions.")
    
    # Randomly select a question
    question_data = random.choice(questions)
    question = question_data.get("question", "Unknown question")
    options = question_data.get("options", [])
    correct_option_id = question_data.get("answer", 0)
    
    # Check if we have valid options
    if not options or len(options) < 2:
        await update.message.reply_text("This question has invalid options. Please fix it with /edit.")
        return
    
    # Create a keyboard for timer options
    keyboard = [
        [
            InlineKeyboardButton("No Timer", callback_data=f"timer_0_{question_data['id']}"),
        ],
        [
            InlineKeyboardButton("15 seconds ⏱️", callback_data=f"timer_15_{question_data['id']}"),
        ],
        [
            InlineKeyboardButton("30 seconds ⏱️", callback_data=f"timer_30_{question_data['id']}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Ask user to select a timer
    await update.message.reply_text(
        "⏱️ Please select a timer for the quiz:\n\n"
        "• No Timer: Quiz stays open until closed manually\n"
        "• 15 seconds: Quick quiz with limited time\n"
        "• 30 seconds: Standard quiz with more thinking time",
        reply_markup=reply_markup
    )

async def handle_timer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the timer selection callback"""
    query = update.callback_query
    await query.answer()
    
    # Parse the callback data
    _, timer_value, question_id = query.data.split("_")
    timer_value = int(timer_value)
    question_id = int(question_id)
    
    # Get the question data
    question_data = get_question_by_id(question_id)
    if not question_data:
        await query.edit_message_text("Question not found. Please try /quiz again.")
        return
    
    # Send the quiz with the selected timer
    timer_text = ""
    if timer_value == 0:
        timer_text = "No timer"
    elif timer_value == 15:
        timer_text = "15-second ⏱️ timer"
    elif timer_value == 30:
        timer_text = "30-second ⏱️ timer"
    
    message = await query.edit_message_text(
        f"Starting quiz with {timer_text}..."
    )
    
    # Setup the quiz
    chat_id = update.effective_chat.id
    question = question_data.get("question", "Unknown question")
    options = question_data.get("options", [])
    correct_option_id = question_data.get("answer", 0)
    
    # Save the correct answer in context.bot_data
    quiz_data = {
        "correct_option": correct_option_id,
        "participants": {},
        "negative_marking": True,  # Enable negative marking
        "timer": timer_value,
        "question_id": question_id,
        "message_id": message.message_id
    }
    
    # Use a unique key for this specific quiz
    quiz_key = f"quiz_{chat_id}_{message.message_id}"
    context.bot_data[quiz_key] = quiz_data
    
    # Send the actual quiz poll
    sent_message = await context.bot.send_poll(
        chat_id=chat_id,
        question=question,
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_option_id,
        is_anonymous=False,
        explanation="Select the correct answer!",
        open_period=timer_value if timer_value > 0 else None
    )
    
    # Update the quiz data with the poll message ID
    quiz_data["poll_message_id"] = sent_message.message_id
    
    # If timer is set, schedule end_quiz after timer expires
    if timer_value > 0:
        # Schedule the task to end the quiz after the timer
        context.job_queue.run_once(
            end_quiz_callback,
            timer_value,
            data={
                "chat_id": chat_id,
                "quiz_key": quiz_key
            }
        )

async def end_quiz_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback to end the quiz when timer expires"""
    # Get the data
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    quiz_key = job_data["quiz_key"]
    
    # Get the quiz data
    quiz_data = context.bot_data.get(quiz_key)
    if not quiz_data:
        return
    
    # Get the quiz results
    participants = quiz_data.get("participants", {})
    
    # Generate and send results
    await send_quiz_results(context, chat_id, quiz_key)

async def send_quiz_results(context: ContextTypes.DEFAULT_TYPE, chat_id: int, quiz_key: str) -> None:
    """Send the quiz results to the chat"""
    # Get the quiz data
    quiz_data = context.bot_data.get(quiz_key)
    if not quiz_data:
        return
    
    # Get the participants and their scores
    participants = quiz_data.get("participants", {})
    question_id = quiz_data.get("question_id", "Unknown")
    
    # If no participants, just send a simple message
    if not participants:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Quiz ended! No one participated."
        )
        return
    
    # Sort participants by score (descending)
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: x[1]["score"],
        reverse=True
    )
    
    # Generate the results message showing all participants
    question = get_question_by_id(question_id)
    question_text = question.get("question", "Unknown question") if question else "Unknown question"
    
    results_message = f"📊 Quiz Results 📊\n*Question:* {question_text}\n\n"
    
    # Add information on number of participants
    total_participants = len(sorted_participants)
    results_message += f"*Total Participants:* {total_participants}\n\n"
    
    # Add each participant with their rank
    for i, (user_id, data) in enumerate(sorted_participants, 1):
        # Add medal emoji for top 3
        medal = ""
        if i == 1:
            medal = "🥇 "
        elif i == 2:
            medal = "🥈 "
        elif i == 3:
            medal = "🥉 "
        
        results_message += f"{medal}#{i}: {data['name']} - {data['score']} points"
        
        # Add answer info (correct/wrong)
        if data.get("correct"):
            results_message += " ✅"
        elif "correct" in data:  # User answered but was wrong
            results_message += " ❌"
        
        results_message += "\n"
    
    # Send the results with Markdown formatting
    await context.bot.send_message(
        chat_id=chat_id,
        text=results_message,
        parse_mode="Markdown"
    )
    
    # Clear the quiz data to free up memory
    if quiz_key in context.bot_data:
        del context.bot_data[quiz_key]

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quiz answer"""
    # Get the answer data
    user = update.poll_answer.user
    selected_option = update.poll_answer.option_ids[0] if update.poll_answer.option_ids else None
    poll_id = update.poll_answer.poll_id
    
    # Find the quiz data for this poll
    quiz_key = None
    for key, data in context.bot_data.items():
        if key.startswith("quiz_") and data.get("poll_message_id") and data.get("poll_message_id") == int(poll_id):
            quiz_key = key
            break
    
    if not quiz_key:
        logger.warning(f"Quiz data not found for poll {poll_id}")
        return
    
    # Get the quiz data
    quiz_data = context.bot_data[quiz_key]
    correct_option = quiz_data.get("correct_option")
    
    # Add user to participants if not already there
    if str(user.id) not in quiz_data["participants"]:
        quiz_data["participants"][str(user.id)] = {
            "name": user.first_name,
            "score": 0,
            "correct": False
        }
    
    # Check if the answer is correct and update score
    negative_marking_enabled = quiz_data.get("negative_marking", True)  # Default to True if not specified
    
    if selected_option == correct_option:
        # Correct answer: +1 point
        points = 1
        quiz_data["participants"][str(user.id)]["correct"] = True
    else:
        # Incorrect answer: -0.5 points if negative marking is enabled
        points = -0.5 if negative_marking_enabled else 0
        quiz_data["participants"][str(user.id)]["correct"] = False
    
    # Update the user's score for this quiz
    quiz_data["participants"][str(user.id)]["score"] = points
    
    # Update the user's overall score in the database
    update_user_score(user.id, user.first_name, points)
    
    # If timer is not set, we should check if all users have answered
    if not quiz_data.get("timer", 0):
        # Check if this is a private chat (only one user)
        chat_id = int(quiz_key.split("_")[1])
        chat = await context.bot.get_chat(chat_id)
        
        if chat.type == "private":
            # In private chat, end the quiz immediately after answer
            # This is a job to be executed after a short delay
            context.job_queue.run_once(
                end_quiz_callback,
                2.0,  # Short delay to allow the Telegram UI to update
                data={
                    "chat_id": chat_id,
                    "quiz_key": quiz_key
                }
            )

async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the add question conversation"""
    await update.message.reply_text(
        "Let's add a new question. First, send me the question text.\n"
        "Or send /cancel to abort."
    )
    return QUESTION

async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the question text and ask for options"""
    context.user_data["question"] = update.message.text
    await update.message.reply_text(
        "Now, send me the options, one per line.\n"
        "Send at least 2 options and at most 10 options.\n"
        "Or send /cancel to abort."
    )
    return OPTIONS

async def add_question_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the options and ask for the correct answer index"""
    options_text = update.message.text
    options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
    
    if len(options) < 2 or len(options) > 10:
        await update.message.reply_text(
            f"You provided {len(options)} options. Please provide between 2 and 10 options.\n"
            "Send the options again, one per line."
        )
        return OPTIONS
    
    context.user_data["options"] = options
    
    options_with_index = '\n'.join([f"{i}. {opt}" for i, opt in enumerate(options)])
    await update.message.reply_text(
        f"Select the correct answer by sending its number (0-{len(options)-1}):\n\n"
        f"{options_with_index}\n\n"
        "Or send /cancel to abort."
    )
    return ANSWER

async def add_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the correct answer and complete the add question process"""
    try:
        answer_index = int(update.message.text)
        options = context.user_data.get("options", [])
        
        if answer_index < 0 or answer_index >= len(options):
            await update.message.reply_text(
                f"Invalid index. Please provide a number between 0 and {len(options)-1}."
            )
            return ANSWER
        
        # Ask for category
        await update.message.reply_text(
            "Finally, send a category for this question (e.g., Geography, Science, etc.).\n"
            "Or send 'General' for no specific category."
        )
        context.user_data["answer"] = answer_index
        
        # Store answer and ask for category
        return EDIT_SELECT  # Reuse the EDIT_SELECT state for category input
        
    except ValueError:
        await update.message.reply_text(
            "That's not a valid number. Please send a number."
        )
        return ANSWER

async def add_question_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the category and save the question"""
    category = update.message.text.strip()
    
    # Use default category if none provided
    if not category or category.lower() == "general":
        category = "General"
    
    # Create the new question
    new_question = {
        "id": get_next_question_id(),
        "question": context.user_data.get("question", ""),
        "options": context.user_data.get("options", []),
        "answer": context.user_data.get("answer", 0),
        "category": category
    }
    
    # Load existing questions, add the new one, and save
    questions = load_questions()
    questions.append(new_question)
    success = save_questions(questions)
    
    if success:
        await update.message.reply_text(
            f"Question added successfully with ID {new_question['id']}!\n\n"
            f"Question: {new_question['question']}\n"
            f"Category: {category}\n"
            f"Correct answer: {new_question['options'][new_question['answer']]}"
        )
    else:
        await update.message.reply_text(
            "Failed to save the question. Please try again later."
        )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

async def list_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all questions"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text("No questions available. Add some with /add first!")
        return
    
    # Group questions by category
    categories = {}
    for q in questions:
        category = q.get("category", "General")
        if category not in categories:
            categories[category] = []
        categories[category].append(q)
    
    # Generate a reply with all questions grouped by category
    reply = "📚 Available Questions:\n\n"
    
    for category, cat_questions in sorted(categories.items()):
        reply += f"📂 {category} ({len(cat_questions)})\n"
        for q in cat_questions:
            # Truncate long questions
            question_text = q.get("question", "Unknown")
            if len(question_text) > 30:
                question_text = question_text[:27] + "..."
            
            reply += f"  ID {q.get('id')}: {question_text}\n"
        reply += "\n"
    
    reply += "Use /quiz to start a random quiz\n"
    reply += "Use /quiz [category] to quiz from a specific category\n"
    reply += "Use /edit [id] to edit a question"
    
    await update.message.reply_text(reply)

async def delete_question_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a question by ID"""
    # Check if an ID was provided
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Please provide a question ID to delete.\n"
            "Example: /delete 42\n"
            "Use /list to see all questions and their IDs."
        )
        return
    
    question_id = int(context.args[0])
    question = get_question_by_id(question_id)
    
    if not question:
        await update.message.reply_text(f"Question with ID {question_id} not found.")
        return
    
    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("Yes, delete it", callback_data=f"delete_confirm_{question_id}"),
            InlineKeyboardButton("No, keep it", callback_data="delete_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Show question details and ask for confirmation
    await update.message.reply_text(
        f"Are you sure you want to delete this question?\n\n"
        f"ID: {question_id}\n"
        f"Question: {question.get('question')}\n"
        f"Category: {question.get('category', 'General')}\n",
        reply_markup=reply_markup
    )

async def delete_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the deletion confirmation button"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "delete_cancel":
        await query.edit_message_text("Deletion cancelled.")
        return
    
    # Extract the question ID from the callback data
    _, _, question_id = query.data.partition("_confirm_")
    if not question_id.isdigit():
        await query.edit_message_text("Invalid question ID.")
        return
    
    question_id = int(question_id)
    success = delete_question_by_id(question_id)
    
    if success:
        await query.edit_message_text(f"Question with ID {question_id} has been deleted.")
    else:
        await query.edit_message_text(f"Failed to delete question with ID {question_id}.")

async def start_edit_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the edit question conversation"""
    # Check if an ID was provided
    if context.args and context.args[0].isdigit():
        question_id = int(context.args[0])
        question = get_question_by_id(question_id)
        
        if question:
            context.user_data["edit_question"] = question
            return await show_edit_options(update, context)
    
    # If no valid ID provided, ask user to select from list
    questions = load_questions()
    if not questions:
        await update.message.reply_text("No questions available to edit. Add some with /add first!")
        return ConversationHandler.END
    
    # Show a list of questions for user to select
    reply = "Select a question to edit by sending its ID:\n\n"
    for q in questions[:15]:  # Limit to 15 questions to avoid message size limits
        question_text = q.get("question", "Unknown")
        if len(question_text) > 30:
            question_text = question_text[:27] + "..."
        
        reply += f"ID {q.get('id')}: {question_text}\n"
    
    if len(questions) > 15:
        reply += f"\n...and {len(questions) - 15} more. Use /list to see all questions."
    
    reply += "\n\nOr send /cancel to abort."
    
    await update.message.reply_text(reply)
    return EDIT_SELECT

async def select_question_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question selection for editing"""
    try:
        question_id = int(update.message.text)
        question = get_question_by_id(question_id)
        
        if not question:
            await update.message.reply_text(
                f"Question with ID {question_id} not found. Please try again."
            )
            return EDIT_SELECT
        
        # Store the question for editing
        context.user_data["edit_question"] = question
        return await show_edit_options(update, context)
        
    except ValueError:
        await update.message.reply_text(
            "That's not a valid number. Please send a question ID."
        )
        return EDIT_SELECT

async def show_edit_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show options for what to edit in the question"""
    question = context.user_data.get("edit_question", {})
    
    # Format and show the current question
    options_text = '\n'.join([f"{i}. {opt}" for i, opt in enumerate(question.get("options", []))])
    correct_answer = question.get("options", [])[question.get("answer", 0)] if question.get("options") else "Unknown"
    
    await update.message.reply_text(
        f"Editing Question ID {question.get('id')}:\n\n"
        f"Current question: {question.get('question')}\n\n"
        f"Current options:\n{options_text}\n\n"
        f"Correct answer: {correct_answer}\n\n"
        f"Category: {question.get('category', 'General')}\n\n"
        "What would you like to edit?\n"
        "1. Edit question text\n"
        "2. Edit options\n"
        "3. Change correct answer\n"
        "4. Edit category\n"
        "5. Save and exit\n\n"
        "Send the number of your choice, or /cancel to abort."
    )
    
    return EDIT_SELECT

async def handle_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the editing option selection"""
    try:
        choice = int(update.message.text.strip())
        
        if choice == 1:
            # Edit question text
            await update.message.reply_text(
                "Send the new question text.\n"
                "Or send /cancel to abort."
            )
            return EDIT_QUESTION
            
        elif choice == 2:
            # Edit options
            await update.message.reply_text(
                "Send the new options, one per line.\n"
                "Send at least 2 options and at most 10 options.\n"
                "Or send /cancel to abort."
            )
            return EDIT_OPTIONS
            
        elif choice == 3:
            # Change correct answer
            question = context.user_data.get("edit_question", {})
            options = question.get("options", [])
            
            if not options:
                await update.message.reply_text("This question has no options yet. Please edit options first.")
                return await show_edit_options(update, context)
            
            options_with_index = '\n'.join([f"{i}. {opt}" for i, opt in enumerate(options)])
            await update.message.reply_text(
                f"Select the correct answer by sending its number (0-{len(options)-1}):\n\n"
                f"{options_with_index}\n\n"
                "Or send /cancel to abort."
            )
            return EDIT_ANSWER
            
        elif choice == 4:
            # Edit category
            await update.message.reply_text(
                "Send the new category for this question.\n"
                "Or send 'General' for no specific category."
            )
            context.user_data["edit_field"] = "category"
            return EDIT_QUESTION
            
        elif choice == 5:
            # Save and exit
            return await save_edited_question(update, context)
            
        else:
            await update.message.reply_text("Invalid choice. Please select a number from 1 to 5.")
            return EDIT_SELECT
            
    except ValueError:
        await update.message.reply_text("That's not a valid number. Please select a number from 1 to 5.")
        return EDIT_SELECT

async def edit_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Edit the question text"""
    edit_field = context.user_data.get("edit_field")
    
    if edit_field == "category":
        # Editing category
        context.user_data["edit_question"]["category"] = update.message.text.strip()
        # Clear edit_field
        if "edit_field" in context.user_data:
            del context.user_data["edit_field"]
    else:
        # Editing question text
        context.user_data["edit_question"]["question"] = update.message.text
    
    return await show_edit_options(update, context)

async def edit_question_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Edit the question options"""
    options_text = update.message.text
    options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
    
    if len(options) < 2 or len(options) > 10:
        await update.message.reply_text(
            f"You provided {len(options)} options. Please provide between 2 and 10 options.\n"
            "Send the options again, one per line."
        )
        return EDIT_OPTIONS
    
    # Update the options
    context.user_data["edit_question"]["options"] = options
    
    # If current correct answer index is out of bounds, reset it to 0
    current_answer = context.user_data["edit_question"].get("answer", 0)
    if current_answer >= len(options):
        context.user_data["edit_question"]["answer"] = 0
    
    return await show_edit_options(update, context)

async def edit_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Edit the correct answer index"""
    try:
        answer_index = int(update.message.text)
        options = context.user_data["edit_question"].get("options", [])
        
        if answer_index < 0 or answer_index >= len(options):
            await update.message.reply_text(
                f"Invalid index. Please provide a number between 0 and {len(options)-1}."
            )
            return EDIT_ANSWER
        
        # Update the answer
        context.user_data["edit_question"]["answer"] = answer_index
        
        return await show_edit_options(update, context)
        
    except ValueError:
        await update.message.reply_text(
            "That's not a valid number. Please send a number."
        )
        return EDIT_ANSWER

async def save_edited_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the edited question"""
    edited_question = context.user_data.get("edit_question", {})
    
    if not edited_question or "id" not in edited_question:
        await update.message.reply_text("Error: No question to save.")
        return ConversationHandler.END
    
    # Load all questions
    questions = load_questions()
    
    # Find and update the question
    updated = False
    for i, question in enumerate(questions):
        if question.get("id") == edited_question["id"]:
            questions[i] = edited_question
            updated = True
            break
    
    if not updated:
        # If not found, append it as a new question
        questions.append(edited_question)
    
    # Save the updated questions
    success = save_questions(questions)
    
    if success:
        await update.message.reply_text(
            f"Question with ID {edited_question['id']} has been updated successfully!"
        )
    else:
        await update.message.reply_text(
            "Failed to save the edited question. Please try again later."
        )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    await update.message.reply_text(
        "Operation cancelled.", 
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

async def start_import_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the import quiz conversation"""
    await update.message.reply_text(
        "Let's import quiz questions!\n\n"
        "You can:\n"
        "1. Send a Telegram quiz link (t.me/...)\n"
        "2. Type 'manual' to add questions manually\n"
        "Or send /cancel to abort."
    )
    return CLONE_URL

async def handle_import_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the quiz import choice"""
    text = update.message.text.strip().lower()
    
    if text == "manual":
        context.user_data["import_method"] = "manual"
        await update.message.reply_text(
            "Let's add questions manually!\n\n"
            "Send me the question text.\n"
            "Or send /cancel to abort."
        )
        return CLONE_MANUAL
    
    elif text.startswith("t.me/") or "t.me/" in text:
        # It's a Telegram URL, try to parse it
        context.user_data["import_method"] = "url"
        context.user_data["import_url"] = text
        
        # Show loading message
        loading_message = await update.message.reply_text("Processing the quiz link...")
        
        # Try to parse the quiz from the URL
        quiz_data = parse_telegram_quiz_url(text)
        
        if quiz_data:
            # Store the extracted quiz data
            context.user_data["import_quiz"] = quiz_data
            
            # Show the extracted data to the user
            options_text = '\n'.join([f"{i}. {opt}" for i, opt in enumerate(quiz_data.get("options", []))])
            
            await loading_message.edit_text(
                "I found a quiz with the following details:\n\n"
                f"Question: {quiz_data.get('question')}\n\n"
                f"Options:\n{options_text}\n\n"
                "Please select the correct answer by sending its number (0-based index).\n"
                "Or send /cancel to abort."
            )
            return CLONE_MANUAL
        else:
            await loading_message.edit_text(
                "I couldn't extract a quiz from that link.\n"
                "Please try a different link or type 'manual' to add questions manually.\n"
                "Or send /cancel to abort."
            )
            return CLONE_URL
    
    else:
        await update.message.reply_text(
            "I didn't recognize that as a Telegram quiz link or 'manual' option.\n"
            "Please send a Telegram quiz link (starting with t.me/) or type 'manual'.\n"
            "Or send /cancel to abort."
        )
        return CLONE_URL

async def handle_manual_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the manual quiz import flow"""
    import_method = context.user_data.get("import_method", "")
    
    if import_method == "url":
        # We're importing from URL and need to set the correct answer
        try:
            correct_option = int(update.message.text.strip())
            quiz_data = context.user_data.get("import_quiz", {})
            
            if not quiz_data or "options" not in quiz_data:
                await update.message.reply_text("Error: Quiz data not found. Please try again.")
                return ConversationHandler.END
            
            if correct_option < 0 or correct_option >= len(quiz_data.get("options", [])):
                await update.message.reply_text(
                    f"Invalid index. Please provide a number between 0 and {len(quiz_data.get('options', [])) - 1}."
                )
                return CLONE_MANUAL
            
            # Update the correct answer in the quiz data
            quiz_data["answer"] = correct_option
            
            # Ask for category
            await update.message.reply_text(
                "Finally, send a category for this question (e.g., Geography, Science, etc.).\n"
                "Or send 'General' for no specific category."
            )
            
            # Update the import state to indicate we're now expecting a category
            context.user_data["import_state"] = "category"
            return CLONE_MANUAL
            
        except ValueError:
            await update.message.reply_text(
                "That's not a valid number. Please send a number for the correct answer."
            )
            return CLONE_MANUAL
    
    elif import_method == "manual":
        # Manual import flow
        if "import_state" not in context.user_data:
            # First message - question text
            context.user_data["import_quiz"] = {"question": update.message.text}
            context.user_data["import_state"] = "options"
            
            await update.message.reply_text(
                "Now, send me the options, one per line.\n"
                "Send at least 2 options and at most 10 options.\n"
                "Or send /cancel to abort."
            )
            return CLONE_MANUAL
            
        elif context.user_data["import_state"] == "options":
            # Options received
            options_text = update.message.text
            options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
            
            if len(options) < 2 or len(options) > 10:
                await update.message.reply_text(
                    f"You provided {len(options)} options. Please provide between 2 and 10 options.\n"
                    "Send the options again, one per line."
                )
                return CLONE_MANUAL
            
            # Update the quiz data with options
            context.user_data["import_quiz"]["options"] = options
            context.user_data["import_state"] = "answer"
            
            # Ask for the correct answer
            options_with_index = '\n'.join([f"{i}. {opt}" for i, opt in enumerate(options)])
            await update.message.reply_text(
                f"Select the correct answer by sending its number (0-{len(options)-1}):\n\n"
                f"{options_with_index}\n\n"
                "Or send /cancel to abort."
            )
            return CLONE_MANUAL
            
        elif context.user_data["import_state"] == "answer":
            # Correct answer received
            try:
                answer_index = int(update.message.text)
                options = context.user_data["import_quiz"].get("options", [])
                
                if answer_index < 0 or answer_index >= len(options):
                    await update.message.reply_text(
                        f"Invalid index. Please provide a number between 0 and {len(options)-1}."
                    )
                    return CLONE_MANUAL
                
                # Update the quiz data with the correct answer
                context.user_data["import_quiz"]["answer"] = answer_index
                context.user_data["import_state"] = "category"
                
                # Ask for category
                await update.message.reply_text(
                    "Finally, send a category for this question (e.g., Geography, Science, etc.).\n"
                    "Or send 'General' for no specific category."
                )
                return CLONE_MANUAL
                
            except ValueError:
                await update.message.reply_text(
                    "That's not a valid number. Please send a number."
                )
                return CLONE_MANUAL
    
    # Handle category input (common for both URL and manual imports)
    if context.user_data.get("import_state") == "category":
        category = update.message.text.strip()
        
        # Use default category if none provided
        if not category or category.lower() == "general":
            category = "General"
        
        # Get the quiz data
        quiz_data = context.user_data.get("import_quiz", {})
        
        if not quiz_data or "question" not in quiz_data or "options" not in quiz_data or "answer" not in quiz_data:
            await update.message.reply_text("Error: Incomplete quiz data. Please try again.")
            return ConversationHandler.END
        
        # Create a complete question object
        new_question = {
            "id": get_next_question_id(),
            "question": quiz_data.get("question", ""),
            "options": quiz_data.get("options", []),
            "answer": quiz_data.get("answer", 0),
            "category": category
        }
        
        # Save the new question
        questions = load_questions()
        questions.append(new_question)
        success = save_questions(questions)
        
        if success:
            await update.message.reply_text(
                f"Question imported successfully with ID {new_question['id']}!\n\n"
                f"Question: {new_question['question']}\n"
                f"Category: {category}\n"
                f"Correct answer: {new_question['options'][new_question['answer']]}\n\n"
                "Send another link to import more questions, type 'manual' to add manually,\n"
                "or send /cancel to finish."
            )
        else:
            await update.message.reply_text(
                "Failed to save the question. Please try again later."
            )
        
        # Reset the import state to allow for another import
        context.user_data.clear()
        context.user_data["import_method"] = None
        context.user_data["import_state"] = None
        
        # Go back to the URL/manual choice state
        return CLONE_URL
    
    # If we got here, something went wrong
    await update.message.reply_text("Error in the import flow. Please try again.")
    return ConversationHandler.END

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's statistics"""
    user_id = update.effective_user.id
    user_data = load_user_data().get(str(user_id))
    
    if not user_data:
        await update.message.reply_text(
            "You haven't participated in any quizzes yet.\n"
            "Use /quiz to start playing!"
        )
        return
    
    # Calculate statistics
    total_score = user_data.get("score", 0)
    questions_answered = user_data.get("questions_answered", 0)
    correct_answers = user_data.get("correct_answers", 0)
    
    accuracy = 0
    if questions_answered > 0:
        accuracy = (correct_answers / questions_answered) * 100
    
    await update.message.reply_text(
        f"📊 Your Quiz Statistics 📊\n\n"
        f"Total Score: {total_score} points\n"
        f"Questions Answered: {questions_answered}\n"
        f"Correct Answers: {correct_answers}\n"
        f"Accuracy: {accuracy:.1f}%\n\n"
        "Use /quiz to play more!"
    )

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the global leaderboard"""
    users = load_user_data()
    
    if not users:
        await update.message.reply_text(
            "No quiz data available yet.\n"
            "Be the first to play with /quiz!"
        )
        return
    
    # Convert to list and sort by score
    users_list = [(int(user_id), data) for user_id, data in users.items()]
    users_list.sort(key=lambda x: x[1].get("score", 0), reverse=True)
    
    # Generate the leaderboard message
    reply = "🏆 Global Leaderboard 🏆\n\n"
    
    for i, (user_id, data) in enumerate(users_list[:10], 1):
        # Add medal emoji for top 3
        medal = ""
        if i == 1:
            medal = "🥇 "
        elif i == 2:
            medal = "🥈 "
        elif i == 3:
            medal = "🥉 "
        
        name = data.get("name", f"User {user_id}")
        score = data.get("score", 0)
        questions = data.get("questions_answered", 0)
        
        reply += f"{medal}#{i}: {name} - {score} points ({questions} questions)\n"
    
    # Add a note if there are more users
    if len(users_list) > 10:
        reply += f"\n...and {len(users_list) - 10} more users."
    
    await update.message.reply_text(reply)

def main() -> None:
    """Set up and run the bot"""
    if not BOT_TOKEN:
        print("Error: No bot token provided. Set the TELEGRAM_BOT_TOKEN environment variable.")
        return
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handlers
    add_question_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_question_start)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_text)],
            OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_options)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_answer)],
            EDIT_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_category)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    edit_question_handler = ConversationHandler(
        entry_points=[CommandHandler("edit", start_edit_question)],
        states={
            EDIT_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_selection),
                CommandHandler("edit", start_edit_question)
            ],
            EDIT_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_text)],
            EDIT_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_options)],
            EDIT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_question_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    import_quiz_handler = ConversationHandler(
        entry_points=[CommandHandler("import", start_import_quiz)],
        states={
            CLONE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_import_choice)],
            CLONE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_import)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_questions))
    application.add_handler(CommandHandler("mystats", show_user_stats))
    application.add_handler(CommandHandler("leaderboard", show_leaderboard))
    application.add_handler(CommandHandler("delete", delete_question_command))
    application.add_handler(CommandHandler("quiz", quiz))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(delete_button_callback, pattern=r"^delete_"))
    application.add_handler(CallbackQueryHandler(handle_timer_selection, pattern=r"^timer_"))
    
    # Add conversation handlers
    application.add_handler(add_question_handler)
    application.add_handler(edit_question_handler)
    application.add_handler(import_quiz_handler)
    
    # Add poll answer handler
    application.add_handler(PollHandler(handle_quiz_answer))
    
    # Add job queue for timer-based quizzes
    job_queue = application.job_queue
    
    # Run the bot
    print("Starting the bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
