"""
Flask application module for the Telegram Quiz Bot
This is imported by gunicorn and wsgi entry points
"""
import os
import logging
from flask import Flask, jsonify

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask application
app = Flask(__name__)

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        "status": "online",
        "message": "Telegram Quiz Bot API is running",
        "version": "1.0.0"
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy"
    })