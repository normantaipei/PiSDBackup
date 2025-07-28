import os
import subprocess
import time
import pygame

class DisplayManager:
    """Display Manager - Handles various display environments"""

    def __init__(self):
        self.display_method = None
        self.setup_display()

    def setup_display(self):
        """Sets up the display environment"""
        print("Setting up display environment...")

        # Method 1: Check for physical display connection
        if self.setup_framebuffer():
            self.display_method = "framebuffer"
            return

        # Method 2: Use X11 (if available)
        if self.setup_x11():
            self.display_method = "x11"
            return

        # Method 3: Start a minimal X server
        if self.setup_minimal_x11():
            self.display_method = "minimal_x11"
            return

        # Last resort: Use a virtual display
        if self.setup_virtual_display():
            self.display_method = "virtual"
            return

        raise Exception("Could not set up display environment")

    def setup_framebuffer(self):
        """Sets up framebuffer display"""
        try:
            # Check for framebuffer device
            if not os.path.exists('/dev/fb0'):
                return False

            # Set SDL to use framebuffer
            os.environ['SDL_VIDEODRIVER'] = 'fbcon'
            os.environ['SDL_FBDEV'] = '/dev/fb0'
            os.environ['SDL_NOMOUSE'] = '1'  # Temporarily disable mouse

            # Test Pygame initialization
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()

            print("✓ Framebuffer display available")
            return True

        except Exception as e:
            print(f"✗ Framebuffer setup failed: {e}")
            return False

    def setup_x11(self):
        """Sets up X11 display"""
        try:
            # Check if X11 is running
            result = subprocess.run(['pgrep', 'X'], capture_output=True)
            if result.returncode != 0:
                return False

            os.environ['DISPLAY'] = ':0'
            os.environ['SDL_VIDEODRIVER'] = 'x11'

            # Test Pygame initialization
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()

            print("✓ X11 display available")
            return True

        except Exception as e:
            print(f"✗ X11 setup failed: {e}")
            return False

    def setup_minimal_x11(self):
        """Sets up minimal X11 environment"""
        try:
            print("Attempting to start minimal X11 environment...")

            # Start X server
            subprocess.run(['sudo', 'systemctl', 'start', 'lightdm'],
                         capture_output=True, timeout=10)
            time.sleep(3)

            # Set environment variables
            os.environ['DISPLAY'] = ':0'
            os.environ['SDL_VIDEODRIVER'] = 'x11'

            # Test Pygame initialization
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()

            print("✓ Minimal X11 environment started successfully")
            return True

        except Exception as e:
            print(f"✗ Minimal X11 environment setup failed: {e}")
            return False

    def setup_virtual_display(self):
        """Sets up virtual display"""
        try:
            # Install and use Xvfb
            subprocess.run(['sudo', 'apt', 'install', '-y', 'xvfb'],
                         capture_output=True)

            # Start virtual display
            subprocess.Popen(['Xvfb', ':99', '-screen', '0', '480x320x24'])
            time.sleep(2)

            os.environ['DISPLAY'] = ':99'
            os.environ['SDL_VIDEODRIVER'] = 'x11'

            # Test Pygame initialization
            pygame.init()
            screen = pygame.display.set_mode((480, 320))
            pygame.quit()

            print("✓ Virtual display started successfully")
            return True

        except Exception as e:
            print(f"✗ Virtual display setup failed: {e}")
            return False

