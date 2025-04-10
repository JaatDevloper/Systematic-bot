"""
Standalone web server for health checks
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting standalone web server on port {port}")
    app.run(host="0.0.0.0", port=port)