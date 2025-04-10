"""
WSGI entry point for the web application
"""
from app_module import app as application

# This allows the app to be imported as wsgi:application
if __name__ == "__main__":
    application.run()