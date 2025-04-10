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
    ConversationHandler, MessageHandler, filters, PollAnswerHandler
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
            "total_questions": 0
        }
        update_user_data(user.id, user_data)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command handler"""
    help_message = (
        "🔍 *Quiz Bot Help*\n\n"
        "*Available Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/quiz - Start a quiz with random questions\n"
        "/category - Start a quiz from a specific category\n"
        "/add - Add a new quiz question\n"
        "/edit - Edit an existing question\n"
        "/delete - Delete a question\n"
        "/stats - View your quiz statistics\n"
        "/clone - Import a quiz from a Telegram URL or manually\n"
        "/poll2q - Convert a poll to a quiz question\n\n"
        "*How to Play:*\n"
        "1. Start a quiz with /quiz\n"
        "2. Answer the questions\n"
        "3. See your results at the end\n\n"
        "*Special Features:*\n"
        "• Convert any Telegram poll to a quiz question\n"
        "• Create quizzes from scratch\n"
        "• Track your performance\n"
    )
    await update.message.reply_text(help_message, parse_mode='Markdown')

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new question"""
    await update.message.reply_text(
        "Let's add a new quiz question!\n\n"
        "First, please enter the question:"
    )
    return QUESTION

async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the question text and ask for options"""
    context.user_data['question'] = update.message.text
    await update.message.reply_text(
        "Great! Now please enter the options, one per message.\n"
        "When you're done, type /done"
    )
    context.user_data['options'] = []
    return OPTIONS

async def receive_option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive an option for the question"""
    if update.message.text == '/done':
        if len(context.user_data['options']) < 2:
            await update.message.reply_text(
                "You need to provide at least 2 options. Please continue:"
            )
            return OPTIONS
        
        # Display the options with numbers
        options_text = "\n".join([
            f"{i+1}. {option}" for i, option in enumerate(context.user_data['options'])
        ])
        
        await update.message.reply_text(
            f"Here are your options:\n\n{options_text}\n\n"
            f"Please send the number of the correct answer (1-{len(context.user_data['options'])}):"
        )
        return ANSWER
    
    context.user_data['options'].append(update.message.text)
    await update.message.reply_text(
        f"Option {len(context.user_data['options'])} added. Add another or type /done when finished."
    )
    return OPTIONS

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the correct answer and save the question"""
    try:
        answer = int(update.message.text) - 1  # Convert to 0-based index
        if 0 <= answer < len(context.user_data['options']):
            # Get next ID
            question_id = get_next_question_id()
            
            # Create new question
            new_question = {
                "id": question_id,
                "question": context.user_data['question'],
                "options": context.user_data['options'],
                "answer": answer,
                "category": "General"  # Default category
            }
            
            # Load existing questions
            questions = load_questions()
            questions.append(new_question)
            
            # Save updated questions
            if save_questions(questions):
                await update.message.reply_text(
                    f"✅ Question #{question_id} added successfully!\n\n"
                    f"Q: {new_question['question']}\n"
                    f"Options: {', '.join(new_question['options'])}\n"
                    f"Answer: {new_question['options'][answer]}"
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to save the question. Please try again later."
                )
        else:
            await update.message.reply_text(
                f"Invalid answer number. Please provide a number between 1 and {len(context.user_data['options'])}:"
            )
            return ANSWER
    except ValueError:
        await update.message.reply_text(
            "Invalid input. Please provide a number:"
        )
        return ANSWER
    
    # Clear user data
    context.user_data.pop('question', None)
    context.user_data.pop('options', None)
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    await update.message.reply_text(
        "Operation cancelled. What would you like to do next?",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Clear user data
    context.user_data.pop('question', None)
    context.user_data.pop('options', None)
    
    return ConversationHandler.END

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz"""
    # Check if a specific question ID was requested
    custom_id = None
    start_from = 0
    
    if context.args:
        for arg in context.args:
            if arg.startswith("id="):
                try:
                    custom_id = int(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("start="):
                try:
                    start_from = int(arg.split("=")[1])
                except ValueError:
                    pass
    
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text(
            "No questions available. Add some questions first with /add"
        )
        return
    
    # Filter questions to start from a specific ID if requested
    if start_from > 0:
        questions = [q for q in questions if q.get("id", 0) >= start_from]
        
        if not questions:
            await update.message.reply_text(
                f"No questions found with ID {start_from} or higher."
            )
            return
    
    # If a specific question ID was requested, find it
    if custom_id is not None:
        question = get_question_by_id(custom_id)
        if question:
            selected_questions = [question]
        else:
            await update.message.reply_text(
                f"Question with ID {custom_id} not found."
            )
            return
    else:
        # Otherwise select 5 random questions
        num_questions = min(5, len(questions))
        selected_questions = random.sample(questions, num_questions)
    
    # Store the quiz details in user context
    context.user_data['quiz'] = {
        'questions': selected_questions,
        'current_index': 0,
        'scores': {},
        'participants': {},
        'active': True,
        'chat_id': update.effective_chat.id
    }
    
    # Start the quiz
    await update.message.reply_text(
        f"Starting quiz with {len(selected_questions)} question(s)...\n"
        "Answer the following questions:"
    )
    
    # Send the first question
    await send_question(update, context)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a quiz question"""
    quiz_data = context.user_data.get('quiz', {})
    questions = quiz_data.get('questions', [])
    current_index = quiz_data.get('current_index', 0)
    
    if not questions or current_index >= len(questions):
        # No more questions, end the quiz
        logger.info("All questions answered, ending quiz...")
        await end_quiz(update, context)
        return
    
    # Get the current question
    question = questions[current_index]
    question_text = question.get('question', 'No question text')
    options = question.get('options', [])
    correct_option = question.get('answer', 0)
    
    # Format the question number display
    question_num = current_index + 1
    total_questions = len(questions)
    
    # Send the question as a poll
    message = await context.bot.send_poll(
        chat_id=quiz_data.get('chat_id', update.effective_chat.id),
        question=f"Question {question_num}/{total_questions}: {question_text}",
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_option,
        is_anonymous=False,
        explanation=f"This is question #{question.get('id', 'unknown')}"
    )
    
    # Store the message ID for this poll
    if 'sent_polls' not in quiz_data:
        quiz_data['sent_polls'] = {}
    
    quiz_data['sent_polls'][str(current_index)] = message.message_id
    
    # Save updated quiz data
    context.user_data['quiz'] = quiz_data

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle answers to quiz polls"""
    quiz_data = context.user_data.get('quiz', {})
    
    if not quiz_data.get('active', False):
        return
    
    # Get the answer
    answer = update.poll_answer
    user_id = answer.user.id
    user_name = answer.user.first_name
    option_ids = answer.option_ids
    
    # Store the user's answer
    if 'participants' not in quiz_data:
        quiz_data['participants'] = {}
    
    if str(user_id) not in quiz_data['participants']:
        quiz_data['participants'][str(user_id)] = {
            'name': user_name,
            'answers': {}
        }
    
    current_index = quiz_data.get('current_index', 0)
    quiz_data['participants'][str(user_id)]['answers'][str(current_index)] = option_ids[0] if option_ids else -1
    
    # Count participants who have answered
    poll_id = str(current_index)
    participants_answered = sum(1 for p in quiz_data['participants'].values() 
                              if poll_id in p.get('answers', {}))
    
    # Check if everyone has answered
    if participants_answered >= len(quiz_data['participants']):
        # Wait a moment to allow everyone to see the result
        await asyncio.sleep(3)
        
        # Move to the next question
        quiz_data['current_index'] += 1
        context.user_data['quiz'] = quiz_data
        
        # Send the next question or end the quiz
        if quiz_data['current_index'] < len(quiz_data.get('questions', [])):
            await send_question(update, context)
        else:
            await end_quiz(update, context)

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """End the quiz and show results"""
    quiz_data = context.user_data.get('quiz', {})
    
    if not quiz_data:
        return
    
    # Mark the quiz as inactive
    quiz_data['active'] = False
    
    questions = quiz_data.get('questions', [])
    participants = quiz_data.get('participants', {})
    
    # Calculate scores
    scores = {}
    for user_id, user_data in participants.items():
        score = 0
        for q_idx, user_answer in user_data.get('answers', {}).items():
            q_idx = int(q_idx)
            if q_idx < len(questions):
                correct_answer = questions[q_idx].get('answer', 0)
                if user_answer == correct_answer:
                    score += 1
        
        # Store the score
        scores[user_id] = {
            'name': user_data.get('name', 'Unknown'),
            'score': score,
            'total': len(questions)
        }
        
        # Update user statistics
        user_stats = get_user_data(int(user_id))
        user_stats['quizzes_taken'] = user_stats.get('quizzes_taken', 0) + 1
        user_stats['correct_answers'] = user_stats.get('correct_answers', 0) + score
        user_stats['total_questions'] = user_stats.get('total_questions', 0) + len(questions)
        update_user_data(int(user_id), user_stats)
    
    # Sort scores by score (descending)
    sorted_scores = sorted(
        scores.items(),
        key=lambda x: x[1]['score'],
        reverse=True
    )
    
    # Generate results message
    if sorted_scores:
        results_message = "🏁 *Quiz Results* 🏁\n\n"
        
        # Show total participants
        results_message += f"👥 *Participants*: {len(sorted_scores)}\n"
        results_message += f"📝 *Questions*: {len(questions)}\n\n"
        
        results_message += "🏆 *Leaderboard*:\n"
        
        for i, (user_id, data) in enumerate(sorted_scores):
            # Add medal emoji for top 3
            position_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            
            # Calculate percentage
            percentage = (data['score'] / data['total']) * 100 if data['total'] > 0 else 0
            
            # Add user result to message
            results_message += f"{position_emoji} {data['name']}: {data['score']}/{data['total']} ({percentage:.1f}%)\n"
    else:
        results_message = "No participants in this quiz."
    
    # Send results
    chat_id = quiz_data.get('chat_id', update.effective_chat.id if update else None)
    if chat_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text=results_message,
            parse_mode='Markdown'
        )
    
    # Clear the quiz data
    context.user_data.pop('quiz', None)

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a question"""
    if not context.args:
        questions = load_questions()
        if not questions:
            await update.message.reply_text(
                "No questions available to delete."
            )
            return
        
        # Show list of questions with IDs
        question_list = "\n".join([
            f"ID {q.get('id', 'unknown')}: {q.get('question', 'No question text')[:30]}..."
            for q in questions[:10]  # Limit to 10 questions to avoid too long message
        ])
        
        await update.message.reply_text(
            "Please specify the ID of the question to delete:\n\n"
            f"{question_list}\n\n"
            "Use /delete ID to delete a specific question."
        )
        return
    
    try:
        question_id = int(context.args[0])
        question = get_question_by_id(question_id)
        
        if not question:
            await update.message.reply_text(
                f"Question with ID {question_id} not found."
            )
            return
        
        # Confirm deletion
        keyboard = [
            [
                InlineKeyboardButton("Yes, delete it", callback_data=f"delete_confirm_{question_id}"),
                InlineKeyboardButton("No, keep it", callback_data="delete_cancel")
            ]
        ]
        
        await update.message.reply_text(
            f"Are you sure you want to delete this question?\n\n"
            f"ID: {question_id}\n"
            f"Question: {question.get('question', 'No question text')}\n"
            f"Options: {', '.join(question.get('options', []))}\n"
            f"Answer: {question.get('options', [])[question.get('answer', 0)] if question.get('options', []) else 'Unknown'}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except ValueError:
        await update.message.reply_text(
            "Invalid ID. Please provide a valid question ID."
        )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete confirmation callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "delete_cancel":
        await query.edit_message_text(
            "Deletion cancelled."
        )
        return
    
    if query.data.startswith("delete_confirm_"):
        try:
            question_id = int(query.data.split("_")[-1])
            if delete_question_by_id(question_id):
                await query.edit_message_text(
                    f"✅ Question #{question_id} deleted successfully."
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to delete question #{question_id}."
                )
        except ValueError:
            await query.edit_message_text(
                "Invalid question ID."
            )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user statistics"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    quizzes_taken = user_data.get('quizzes_taken', 0)
    correct_answers = user_data.get('correct_answers', 0)
    total_questions = user_data.get('total_questions', 0)
    
    # Calculate accuracy
    accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0
    
    # Create a stylish stats message
    stats_message = (
        "📊 *Your Quiz Statistics* 📊\n\n"
        f"🎮 *Quizzes Taken*: {quizzes_taken}\n"
        f"✅ *Correct Answers*: {correct_answers}\n"
        f"📝 *Total Questions*: {total_questions}\n"
        f"🎯 *Accuracy*: {accuracy:.1f}%\n\n"
    )
    
    # Add a performance rating based on accuracy
    if accuracy >= 90:
        stats_message += "🌟 *Rating*: Quiz Master! Excellent work!"
    elif accuracy >= 75:
        stats_message += "🏆 *Rating*: Quiz Pro! Great job!"
    elif accuracy >= 60:
        stats_message += "👍 *Rating*: Quiz Enthusiast! Good progress!"
    elif accuracy >= 40:
        stats_message += "🔍 *Rating*: Quiz Apprentice! Keep practicing!"
    else:
        stats_message += "🌱 *Rating*: Quiz Beginner! You'll improve with time!"
    
    await update.message.reply_text(
        stats_message,
        parse_mode='Markdown'
    )

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz from a specific category"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text(
            "No questions available. Add some questions first with /add"
        )
        return
    
    # Extract all unique categories
    categories = set()
    for question in questions:
        category = question.get("category")
        if category:
            categories.add(category)
    
    if not categories:
        await update.message.reply_text(
            "No categories available. All questions are uncategorized."
        )
        return
    
    # Create keyboard with categories
    keyboard = []
    row = []
    for i, category in enumerate(sorted(categories)):
        row.append(InlineKeyboardButton(category, callback_data=f"cat_{category}"))
        
        # 2 buttons per row
        if (i + 1) % 2 == 0 or i == len(categories) - 1:
            keyboard.append(row)
            row = []
    
    await update.message.reply_text(
        "Please select a category:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the next question in the quiz"""
    quiz_data = context.user_data.get('quiz', {})
    questions = quiz_data.get('questions', [])
    current_index = quiz_data.get('current_index', 0)
    
    if not questions or current_index >= len(questions):
        # No more questions, end the quiz
        await end_quiz(update, context)
        return
    
    # Get the current question
    question = questions[current_index]
    question_text = question.get('question', 'No question text')
    options = question.get('options', [])
    correct_option = question.get('answer', 0)
    
    # Format the question number display
    question_num = current_index + 1
    total_questions = len(questions)
    
    # Send the question as a poll
    message = await context.bot.send_poll(
        chat_id=quiz_data.get('chat_id', update.effective_chat.id),
        question=f"Question {question_num}/{total_questions}: {question_text}",
        options=options,
        type=Poll.QUIZ,
        correct_option_id=correct_option,
        is_anonymous=False,
        explanation=f"This is question #{question.get('id', 'unknown')}"
    )
    
    # Store the message ID for this poll
    if 'sent_polls' not in quiz_data:
        quiz_data['sent_polls'] = {}
    
    quiz_data['sent_polls'][str(current_index)] = message.message_id
    
    # Save updated quiz data
    context.user_data['quiz'] = quiz_data

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

# Main function to run the bot
def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add conversation handler for adding questions
    add_question_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_question)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)],
            OPTIONS: [MessageHandler(filters.TEXT, receive_option)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(add_question_handler)
    
    # Add basic command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("delete", delete_question))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("category", category))
    application.add_handler(CommandHandler("clone", clone_start))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(delete_callback, pattern=r"^delete_"))
    application.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat_"))
    
    # Add poll answer handler
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Start the bot
    application.run_polling()

async def test_results_display():
    """Test function for results display"""
    # This is just a test function to ensure proper formatting of quiz results
    print("==== TEST STARTED ====")
    
    # Sample data
    quiz_data = {
        'questions': [
            {'question': 'Test Q1?', 'answer': 0}, 
            {'question': 'Test Q2?', 'answer': 1},
            {'question': 'Test Q3?', 'answer': 2}
        ],
        'participants': {
            '123': {
                'name': 'User 1',
                'answers': {'0': 0, '1': 1, '2': 2}  # all correct
            },
            '456': {
                'name': 'User 2',
                'answers': {'0': 1, '1': 1, '2': 0}  # 1 correct
            },
            '789': {
                'name': 'User 3',
                'answers': {'0': 0, '1': 0, '2': 1}  # 1 correct
            }
        }
    }
    
    # Calculate scores
    scores = {}
    for user_id, user_data in quiz_data['participants'].items():
        score = 0
        for q_idx, user_answer in user_data.get('answers', {}).items():
            q_idx = int(q_idx)
            if q_idx < len(quiz_data['questions']):
                correct_answer = quiz_data['questions'][q_idx].get('answer', 0)
                if user_answer == correct_answer:
                    score += 1
        
        # Store the score
        scores[user_id] = {
            'name': user_data.get('name', 'Unknown'),
            'score': score,
            'total': len(quiz_data['questions'])
        }
    
    # Sort scores
    sorted_scores = sorted(
        scores.items(),
        key=lambda x: x[1]['score'],
        reverse=True
    )
    
    # Generate results message
    results_message = "🏁 *Quiz Results* 🏁\n\n"
    results_message += f"👥 *Participants*: {len(sorted_scores)}\n"
    results_message += f"📝 *Questions*: {len(quiz_data['questions'])}\n\n"
    results_message += "🏆 *Leaderboard*:\n"
    
    for i, (user_id, data) in enumerate(sorted_scores):
        position_emoji = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        percentage = (data['score'] / data['total']) * 100
        results_message += f"{position_emoji} {data['name']}: {data['score']}/{data['total']} ({percentage:.1f}%)\n"
    
    print(results_message)
    print("==== TEST COMPLETED ====")

if __name__ == "__main__":
    # Run the test if the TEST_MODE environment variable is set
    if os.environ.get('TEST_MODE') == '1':
        import asyncio
        asyncio.run(test_results_display())
    else:
        main()
