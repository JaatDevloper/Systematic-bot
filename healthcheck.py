"""
Health check for the Telegram Quiz Bot
This creates a simple HTTP endpoint for Koyeb to check the health of the service
"""
import os
import logging
import http.server
from http.server import BaseHTTPRequestHandler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Health check HTTP request handler"""
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/health':
            # Return 200 OK for health checks
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        elif self.path == '/':
            # Return a simple homepage
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "online", "message": "Telegram Quiz Bot Health Service"}')
        else:
            # Return 404 for other paths
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')

def start_health_server():
    """Start the health check server"""
    # Get the port from environment or default to 8080 (different from 5000)
    port = int(os.environ.get('HEALTH_PORT', 8080))
    server_address = ('', port)
    
    httpd = http.server.HTTPServer(server_address, HealthCheckHandler)
    logger.info(f"Starting health check server on port {port}")
    httpd.serve_forever()

if __name__ == "__main__":
    # Start the health check server directly
    start_health_server()