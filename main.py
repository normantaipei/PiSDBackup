#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Raspberry Pi Touchscreen Product - Complete Solution
Product-grade interface, auto-runs on boot, displays directly on screen
"""

import sys
import signal
import threading # Import threading for running Flask in a separate thread
import pygame # Ensure pygame is imported here for signal handler
import time # Added for sleep in main loop (optional, but good for daemon threads)

from display_manager import DisplayManager
from rpi_interface import RPiProductInterface
from web_file_manager import app as flask_app # Renamed to avoid conflict with local 'app' variable

# Global variable to control DEBUG_MODE
DEBUG_MODE = False # Set to True to enable debug features

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
    # We will let RPiProductInterface's run() method handle pygame.quit()
    # and its internal daemon threads.
    def signal_handler(sig, frame):
        print("\nShutting down from signal handler...")
        # Signalling the main Pygame app to stop
        # A more robust way would be to pass a stop event to RPiProductInterface
        # For simplicity here, sys.exit() will terminate daemon threads.
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- 新增/修改的部分 ---
    flask_thread = None # Initialize to None
    display_manager = None
    app = None

    try:
        # Start Flask app in a separate thread
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start() # Start the Flask web server
        
        # Initialize display manager
        display_manager = DisplayManager()

        # Start product interface
        # RPiProductInterface now handles starting SDCopyManager's main_loop internally
        app = RPiProductInterface(display_manager, DEBUG_MODE)
        app.run() # This is the main thread, blocking until Pygame app exits
        
    except Exception as e:
        print(f"Startup or runtime failed: {e}")
        print("Please check system settings and try again.")
        sys.exit(1)
    finally:
        # This block ensures cleanup even if an exception occurs
        print("Main application finished. Attempting cleanup...")
        if app and hasattr(app, 'running'): # Check if app object exists and has 'running' attribute
            app.running = False # Signal the Pygame loop to stop if it hasn't
            if hasattr(app, 'data_thread') and app.data_thread.is_alive():
                print("Waiting for data thread to finish...")
                # In this case, data_thread is daemon, so main thread exit will kill it.
                # If it were not daemon, you'd call app.data_thread.join()
            if hasattr(app, 'sd_copy_manager') and app.sd_copy_manager.is_copying:
                print("Stopping SD copy manager if active...")
                app.sd_copy_manager.stop_copy()
            if hasattr(app, 'sd_detection_thread') and app.sd_detection_thread.is_alive():
                print("Waiting for SD detection thread to finish...")
                # Also a daemon thread, so will exit with main.
                # For non-daemon, app.sd_detection_thread.join()
        
        # Pygame.quit() is handled within RPiProductInterface.run()'s finally block,
        # but calling it here again as a fallback is harmless.
        try:
            pygame.quit()
            print("Pygame quit successfully.")
        except Exception as e:
            print(f"Error quitting Pygame: {e}")

        print("Application exited.")
        sys.exit(0) # Ensure a clean exit code

if __name__ == "__main__":
    from utils import setup_system, install_dependencies
    
    # Perform initial setup before Pygame attempts display initialization
    install_dependencies()
    setup_system()
    
    main()