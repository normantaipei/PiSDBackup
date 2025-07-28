#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Raspberry Pi Touchscreen Product - Complete Solution
Product-grade interface, auto-runs on boot, displays directly on screen
"""

import sys
import signal
import threading # Import threading for running Flask in a separate thread
from display_manager import DisplayManager
from rpi_interface import RPiProductInterface
import pygame # Ensure pygame is imported here for signal handler

# Global variable to control DEBUG_MODE
DEBUG_MODE = False # Set to True to enable debug features

# Import the Flask app from web_file_manager
from web_file_manager import app as flask_app # Renamed to avoid conflict with local 'app' variable

def run_flask_app():
    """Function to run the Flask application"""
    print("🚀 Starting USB File Manager Web Server...")
    print("📱 Access it in your browser at: http://localhost:5000")
    print("🌐 Or from other devices at: http://[Raspberry Pi IP]:5000")
    print("⚠️  Ensure required packages are installed: pip install Flask Pillow psutil")
    
    # Run Flask app, allowing external access
    # Use threaded=True to ensure it handles multiple requests concurrently
    flask_app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

def main():
    """Main program entry point"""
    print("=" * 60)
    print("Raspberry Pi Monitoring System")
    print("=" * 60)

    # Signal handler for graceful shutdown (e.g., Ctrl+C)
    def signal_handler(sig, frame):
        print("\nShutting down...")
        # Attempt to shut down Flask gracefully (this is complex in threaded mode,
        # usually Ctrl+C on the main thread will kill all daemon threads).
        # For a more robust Flask shutdown, you'd need Werkzeug's dev server control or a custom signal.
        # However, for this use case, letting the main thread exit and daemon threads terminate is often sufficient.
        try:
            pygame.quit() # Ensure Pygame is quit
        except Exception:
            pass # Ignore if pygame is not imported or already quit
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start Flask app in a separate thread
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start() # Start the Flask web server
        
        # Initialize display manager
        display_manager = DisplayManager()

        # Start product interface
        app = RPiProductInterface(display_manager, DEBUG_MODE)
        app.run() # This is the main thread, blocking until Pygame app exits
        
    except Exception as e:
        print(f"Startup failed: {e}")
        print("Please check system settings and try again.")
        sys.exit(1)

if __name__ == "__main__":
    from utils import setup_system, install_dependencies
    
    # Perform initial setup before Pygame attempts display initialization
    install_dependencies()
    setup_system()
    
    main()
