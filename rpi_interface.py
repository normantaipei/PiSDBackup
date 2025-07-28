import pygame
import time
from datetime import datetime
import threading
import subprocess
import qrcode # Added for QR code generation
import io     # Added for handling image data in memory
from data_collector import DataCollector

class RPiProductInterface:
    """Raspberry Pi Product Interface - Main application class"""

    def __init__(self, display_manager, debug_mode):
        self.display_manager = display_manager
        self.debug_mode = debug_mode
        self.running = True
        self.data_collector = DataCollector() # Initialize data collector
        self.setup_pygame()
        self.qrcode_surface = None # Initialize QR code surface
        self.setup_ui()
        self.setup_data_updates()


    def setup_pygame(self):
        """Pygame initialization and fullscreen display setup"""
        pygame.init()
        pygame.font.init()

        # Get display info to determine optimal fullscreen resolution
        info_object = pygame.display.Info()
        self.width = info_object.current_w
        self.height = info_object.current_h

        # Set screen to fullscreen mode
        self.screen = pygame.display.set_mode((self.width, self.height), pygame.FULLSCREEN)

        pygame.display.set_caption("Raspberry Pi Monitoring System")

        # Hide mouse cursor (product mode)
        pygame.mouse.set_visible(False)

        print(f"✓ Screen initialized and set to fullscreen: {self.width}x{self.height}")

    def setup_ui(self):
        """UI element setup"""
        # Fonts - try common system fonts as fallback
        font_names = [
            "DejaVuSans",
            "FreeSans",
            "Arial",
            None
        ]

        def get_font(size):
            for name in font_names:
                try:
                    font = pygame.font.SysFont(name, size)
                    if font.render("A", True, (0,0,0)).get_width() > 0:
                        # print(f"Using font: {name} (Size: {size})") # Debugging info, optional
                        return font
                except Exception:
                    pass # Ignore if font loading fails
            # Fallback to Pygame's default font if all attempts fail
            print(f"Falling back to Pygame default font (Size: {size})")
            return pygame.font.SysFont(None, size)

        # Font sizes dynamically adjusted based on fullscreen resolution
        self.font_large = get_font(int(self.height * 0.08))
        self.font_medium = get_font(int(self.height * 0.06))
        self.font_small = get_font(int(self.height * 0.04))
        self.font_tiny = get_font(int(self.height * 0.03))

        # Color theme
        self.colors = {
            'bg': (30, 30, 30),           # Dark grey background
            'card': (45, 45, 45),         # Card background
            'accent': (0, 150, 255),      # Main accent color
            'success': (0, 200, 100),     # Success state
            'warning': (255, 180, 0),     # Warning state
            'error': (255, 80, 80),       # Error state
            'text': (255, 255, 255),      # Main text
            'text_dim': (180, 180, 180),  # Secondary text
        }

        # Layout calculations - dynamically adjusted based on screen size
        self.layout = {
            'header_height': int(self.height * 0.12),
            'card_margin': int(self.width * 0.02),
            'card_padding': int(self.height * 0.03),
            'line_spacing_small': int(self.height * 0.05),  # Increased for more spacing
            'line_spacing_medium': int(self.height * 0.07), # Increased for more spacing
        }

        # Touch areas (for operations like restart) - only visible in DEBUG_MODE, dynamically positioned
        self.touch_areas = {
            'restart': pygame.Rect(self.width - int(self.width * 0.12) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),
            'refresh': pygame.Rect(self.width - int(self.width * 0.25) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),
        }

    def generate_qrcode(self):
        """Generates the QR code for the Raspberry Pi's IP address."""
        ip_address = self.data_collector.data.get('ip_address', 'N/A')
        # Only generate QR code if IP is available and not the default "IP Unavailable"
        if ip_address and ip_address != 'IP Unavailable':
            try:
                # The web server runs on port 5000
                qr_data = f"http://{ip_address}:5000"

                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10, # Default box size
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)

                # Using a dark background for the QR code to fit the UI theme
                img = qr.make_image(fill_color="white", back_color=(60, 60, 60))

                # Convert PIL Image to Pygame Surface
                # Using BytesIO to avoid saving to disk
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG') # PNG for better quality, can use JPEG
                img_byte_arr.seek(0)

                self.qrcode_surface = pygame.image.load(img_byte_arr)
            except Exception as e:
                print(f"Error generating QR code: {e}")
                self.qrcode_surface = None
        else:
            self.qrcode_surface = None

    def setup_data_updates(self):
        """Sets up data updates"""
        # Start data update thread
        self.data_thread = threading.Thread(target=self.data_update_loop, daemon=True)
        self.data_thread.start()

        # Update immediately once
        self.update_all_data()

    def update_all_data(self):
        """Updates all data"""
        self.data_collector.update_data()

    def data_update_loop(self):
        """Data update loop"""
        last_ip = None # To track IP changes for QR code regeneration
        while self.running:
            try:
                self.update_all_data()
                current_ip = self.data_collector.data.get('ip_address', 'N/A')
                if current_ip != last_ip: # Regenerate QR code only if IP changes
                    self.generate_qrcode()
                    last_ip = current_ip
                time.sleep(3)  # Update every 3 seconds
            except Exception as e:
                # print(f"Data update loop error: {e}")
                time.sleep(5)

    def draw_header(self):
        """Draws the top header bar"""
        header_rect = pygame.Rect(0, 0, self.width, self.layout['header_height'])
        pygame.draw.rect(self.screen, self.colors['card'], header_rect)

        # Current date and time
        current_datetime = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        datetime_text = self.font_tiny.render(current_datetime, True, self.colors['text_dim'])
        datetime_rect = datetime_text.get_rect()
        self.screen.blit(datetime_text, (self.width - datetime_rect.width - self.layout['card_margin'],
                                        self.layout['header_height'] // 2 - datetime_rect.height // 2))

        # Show buttons only in debug mode
        if self.debug_mode:
            # Refresh button
            pygame.draw.rect(self.screen, self.colors['accent'], self.touch_areas['refresh'], border_radius=5)
            refresh_text = self.font_small.render("Refresh", True, self.colors['text'])
            refresh_rect = refresh_text.get_rect(center=self.touch_areas['refresh'].center)
            self.screen.blit(refresh_text, refresh_rect)

            # Restart button
            pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['restart'], border_radius=5)
            restart_text = self.font_small.render("Restart", True, self.colors['text'])
            restart_rect = restart_text.get_rect(center=self.touch_areas['restart'].center)
            self.screen.blit(restart_text, restart_rect)


    def draw_network_card(self):
        """Draws the network info card and the QR code next to it."""
        y_start = self.layout['header_height'] + self.layout['card_margin']

        # Calculate the required height for the text content
        text_content_height = self.font_medium.get_height() + \
                              self.layout['line_spacing_medium'] + \
                              self.font_small.get_height() * 3 + \
                              self.layout['line_spacing_small'] * 2
        card_height = self.layout['card_padding'] * 2 + text_content_height

        # Determine QR code size based on card height, leaving some padding
        qrcode_target_size = card_height - (self.layout['card_padding'] * 2)

        # Adjust card width to accommodate both text and QR code
        # We need to consider space for the QR code and additional margin
        # Approximately leaving 1/3 of the width for the QR code and its internal padding
        text_card_width = int((self.width - 2 * self.layout['card_margin']) * 0.6) # Allocate ~60% for text
        
        # Calculate the total width of the card, including space for QR code if it exists
        # This will be the full width available for the network card area
        total_card_width = self.width - 2 * self.layout['card_margin']

        # Determine the width of the main text area of the network card
        # This ensures the text part of the card doesn't overlap with the QR code.
        # We'll subtract the QR code's potential width and some extra space.
        qrcode_area_width = int(qrcode_target_size * 1.1) if self.qrcode_surface else 0 # Add a small buffer
        
        # The width of the rectangle for network info text
        network_text_rect_width = total_card_width - qrcode_area_width - (self.layout['card_padding'] * 2)

        card_rect = pygame.Rect(self.layout['card_margin'], y_start, total_card_width, card_height)
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        # Card title
        title = self.font_medium.render("Network Status", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_medium'] # Use layout for consistent spacing

        # IP Address
        ip_text = self.font_small.render(f"IP: {self.data_collector.data['ip_address']}", True, self.colors['text'])
        self.screen.blit(ip_text, (x, y))
        y += self.layout['line_spacing_small'] # Use layout for consistent spacing

        # WiFi Name
        wifi_text = self.font_small.render(f"WiFi: {self.data_collector.data['wifi_ssid']}", True, self.colors['text'])
        self.screen.blit(wifi_text, (x, y))
        y += self.layout['line_spacing_small'] # Use layout for consistent spacing

        # Connection Status
        status_color = self.colors['success'] if self.data_collector.data['connection_status'] == "Connected" else self.colors['error']
        status_text = self.font_small.render(f"Status: {self.data_collector.data['connection_status']}", True, status_color)
        self.screen.blit(status_text, (x, y))

        # Draw QR Code if available, to the right of the network info
        if self.qrcode_surface:
            scaled_qrcode = pygame.transform.scale(self.qrcode_surface, (int(qrcode_target_size), int(qrcode_target_size)))
            # Position QR code to the right of the text content, centered vertically within the card
            qrcode_x = card_rect.x + card_rect.width - self.layout['card_padding'] - scaled_qrcode.get_width()
            qrcode_y = card_rect.y + (card_rect.height - scaled_qrcode.get_height()) // 2
            self.screen.blit(scaled_qrcode, (qrcode_x, qrcode_y))
        else:
            # If no IP for QR, display a small message in the QR code's area
            no_ip_text = self.font_tiny.render("No IP for QR", True, self.colors['text_dim'])
            # Center the "No IP for QR" text within the potential QR code area
            no_ip_x = card_rect.x + card_rect.width - self.layout['card_padding'] - (qrcode_target_size // 2) - (no_ip_text.get_width() // 2)
            no_ip_y = card_rect.y + (card_rect.height - no_ip_text.get_height()) // 2
            self.screen.blit(no_ip_text, (no_ip_x, no_ip_y))

    def draw_system_card(self):
        """Draws the system info card (temperature and battery only)"""
        # Position below the network card
        network_card_bottom = self.layout['header_height'] + self.layout['card_margin'] + \
                              (self.layout['card_padding'] * 2 + \
                              self.font_medium.get_height() + \
                              self.layout['line_spacing_medium'] + \
                              self.font_small.get_height() * 3 + \
                              self.layout['line_spacing_small'] * 2) # Height of the text content area

        y_start = network_card_bottom + self.layout['card_margin']

        # Card height dynamically adjusted based on content and line spacing
        card_height = self.layout['card_padding'] * 2 + \
                      self.font_small.get_height() + \
                      self.layout['line_spacing_small'] + \
                      self.font_small.get_height() + \
                      self.layout['line_spacing_small'] + \
                      self.font_small.get_height()

        card_rect = pygame.Rect(self.layout['card_margin'], y_start,
                               self.width // 2 - self.layout['card_margin'] * 1.5, card_height)

        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        # System Info
        title = self.font_small.render("System", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_small'] # Use layout for consistent spacing

        if self.data_collector.data['system_info']:
            sys_info = self.data_collector.data['system_info']
            temp_text = self.font_small.render(f"Temp: {sys_info.get('temp', 'N/A')}", True, self.colors['text'])
            self.screen.blit(temp_text, (x, y))
            y += self.layout['line_spacing_small'] # Use layout for consistent spacing

        # Battery Info
        if self.data_collector.data['battery_info']:
            battery_info = self.data_collector.data['battery_info']
            battery_percent = battery_info.get('percent', 'N/A')
            battery_text = self.font_small.render(f"Battery: {battery_percent:.1f}%", True, self.colors['text'])
            self.screen.blit(battery_text, (x, y))
        else:
            no_battery_text = self.font_small.render("Battery: N/A", True, self.colors['text_dim'])
            self.screen.blit(no_battery_text, (x, y))


    def draw_usb_card(self):
        """Draws the USB device card"""
        # Position below the network card, alongside the system card
        network_card_bottom = self.layout['header_height'] + self.layout['card_margin'] + \
                              (self.layout['card_padding'] * 2 + \
                              self.font_medium.get_height() + \
                              self.layout['line_spacing_medium'] + \
                              self.font_small.get_height() * 3 + \
                              self.layout['line_spacing_small'] * 2) # Height of the text content area

        y_start = network_card_bottom + self.layout['card_margin']

        # Initial card height (will be adjusted if more content)
        card_height = self.layout['card_padding'] * 2 + \
                      self.font_small.get_height() + \
                      self.layout['line_spacing_small'] + \
                      self.font_small.get_height() * 2 + self.layout['line_spacing_small'] # For one device entry

        card_rect = pygame.Rect(self.width // 2 + self.layout['card_margin'] * 0.5, y_start,
                               self.width // 2 - self.layout['card_margin'] * 1.5, card_height)

        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        # USB Devices
        title = self.font_small.render("USB Devices", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_small'] # Use layout for consistent spacing

        if self.data_collector.data['usb_devices']:
            usb_content_height = 0
            current_y_for_calc = y # Use a temporary y for content calculation before redrawing

            for device in self.data_collector.data['usb_devices'][:2]:  # Display max 2
                name_text_surface = self.font_small.render(device['name'], True, self.colors['text'])
                current_y_for_calc += name_text_surface.get_height()
                usb_content_height += name_text_surface.get_height()

                size_text_surface = self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB",
                                                 True, self.colors['text_dim'])
                current_y_for_calc += size_text_surface.get_height()
                usb_content_height += size_text_surface.get_height()

                current_y_for_calc += self.layout['line_spacing_small'] # Spacing between device entries
                usb_content_height += self.layout['line_spacing_small']

            # Adjust card's actual drawn height if content exceeds initial estimate
            required_card_height = self.layout['card_padding'] * 2 + \
                                   self.font_small.get_height() + \
                                   self.layout['line_spacing_small'] + \
                                   usb_content_height

            # Only redraw if height needs adjustment to avoid flickering for small changes
            # (Adding a small threshold for height difference)
            if abs(card_rect.height - required_card_height) > 5:
                 card_rect.height = required_card_height
                 pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10) # Redraw background

            # Now draw the actual content on the potentially resized card
            x = card_rect.x + self.layout['card_padding']
            y = card_rect.y + self.layout['card_padding']
            self.screen.blit(self.font_small.render("USB Devices", True, self.colors['accent']), (x, y))
            y += self.layout['line_spacing_small']

            for device in self.data_collector.data['usb_devices'][:2]:
                self.screen.blit(self.font_small.render(device['name'], True, self.colors['text']), (x, y))
                y += self.font_small.get_height() # Move down by font height for next line
                self.screen.blit(self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB", True, self.colors['text_dim']), (x, y))
                y += self.font_small.get_height() + self.layout['line_spacing_small'] # Move down for next device entry
        else:
            no_usb_text = self.font_small.render("No USB Devices", True, self.colors['text_dim'])
            self.screen.blit(no_usb_text, (x, y))


    def draw_status_bar(self):
        """Draws the bottom status bar with update time and QR code"""
        status_bar_height = int(self.height * 0.08)
        y_start = self.height - status_bar_height
        status_rect = pygame.Rect(0, y_start, self.width, status_bar_height)
        pygame.draw.rect(self.screen, self.colors['card'], status_rect)

        # Update Time
        update_time = datetime.fromtimestamp(self.data_collector.data['last_update']).strftime("%H:%M:%S")
        update_text = self.font_small.render(f"Updated: {update_time}", True, self.colors['text_dim'])
        self.screen.blit(update_text, (self.layout['card_margin'], y_start + (status_bar_height - update_text.get_height()) // 2))

        # Running status indicator
        status_color = self.colors['success']
        pygame.draw.circle(self.screen, status_color, (self.width - self.layout['card_margin'] - int(status_bar_height * 0.35),
                                                        y_start + status_bar_height // 2),
                                                       int(status_bar_height * 0.2))

    def handle_touch(self, pos):
        """Handles touch events"""
        if self.debug_mode: # Only handle buttons in DEBUG_MODE
            if self.touch_areas['refresh'].collidepoint(pos):
                print("Manually updating data...")
                threading.Thread(target=self.update_all_data, daemon=True).start()
            elif self.touch_areas['restart'].collidepoint(pos):
                print("Restarting system...")
                subprocess.run(['sudo', 'reboot'])

    def run(self):
        """Main execution loop"""
        clock = pygame.time.Clock()

        print("✓ Product interface started.")
        print(f"Display method: {self.display_manager.display_method}")
        print(f"Resolution: {self.width}x{self.height}")

        try:
            while self.running:
                # Event processing
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE: # Allow ESC key to exit
                            self.running = False
                        elif event.key == pygame.K_F5: # Allow F5 to refresh
                            self.update_all_data()
                    elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN]:
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            self.handle_touch(event.pos)
                        else:
                            touch_pos = (int(event.x * self.width), int(event.y * self.height))
                            self.handle_touch(touch_pos)

                # Clear screen
                self.screen.fill(self.colors['bg'])

                # Draw interface
                self.draw_header()
                self.draw_network_card()
                self.draw_system_card()
                self.draw_usb_card()
                self.draw_status_bar()

                # Update display
                pygame.display.flip()
                clock.tick(30)  # 30 FPS

        except KeyboardInterrupt:
            print("\nProgram interrupted by user (Ctrl+C).")
            self.running = False # Set running to False to ensure loop exits
        finally:
            self.running = False # Ensure loop terminates
            pygame.quit() # Always quit pygame