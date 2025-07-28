import pygame
import time
from datetime import datetime
import threading
import subprocess
import qrcode
import io
from data_collector import DataCollector

class RPiProductInterface:
    """Raspberry Pi Product Interface - Main application class"""

    def __init__(self, display_manager, debug_mode):
        self.display_manager = display_manager
        self.debug_mode = debug_mode
        self.running = True
        self.data_collector = DataCollector()
        self.setup_pygame()
        self.qrcode_surface = None
        self.setup_ui()
        self.setup_data_updates()


    def setup_pygame(self):
        """Pygame initialization and fullscreen display setup"""
        pygame.init()
        pygame.font.init()

        info_object = pygame.display.Info()
        self.width = info_object.current_w
        self.height = info_object.current_h

        self.screen = pygame.display.set_mode((self.width, self.height), pygame.FULLSCREEN)

        pygame.display.set_caption("Raspberry Pi Monitoring System")
        pygame.mouse.set_visible(False)

        print(f"✓ Screen initialized and set to fullscreen: {self.width}x{self.height}")

    def setup_ui(self):
        """UI element setup"""
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
                        return font
                except Exception:
                    pass
            print(f"Falling back to Pygame default font (Size: {size})")
            return pygame.font.SysFont(None, size)

        self.font_large = get_font(int(self.height * 0.08))
        self.font_medium = get_font(int(self.height * 0.06))
        self.font_small = get_font(int(self.height * 0.04))
        self.font_tiny = get_font(int(self.height * 0.03))

        self.colors = {
            'bg': (30, 30, 30),
            'card': (45, 45, 45),
            'accent': (0, 150, 255),
            'success': (0, 200, 100),
            'warning': (255, 180, 0),
            'error': (255, 80, 80),
            'text': (255, 255, 255),
            'text_dim': (180, 180, 180),
        }

        self.layout = {
            'header_height': int(self.height * 0.12),
            'card_margin': int(self.width * 0.02),
            'card_padding': int(self.height * 0.03),
            'line_spacing_small': int(self.height * 0.05),
            'line_spacing_medium': int(self.height * 0.07),
        }

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
        if ip_address and ip_address != 'IP Unavailable':
            try:
                qr_data = f"http://{ip_address}:5000"
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)

                img = qr.make_image(fill_color="white", back_color=(60, 60, 60))

                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)

                self.qrcode_surface = pygame.image.load(img_byte_arr)
            except Exception as e:
                print(f"Error generating QR code: {e}")
                self.qrcode_surface = None
        else:
            self.qrcode_surface = None

    def setup_data_updates(self):
        """Sets up data updates"""
        self.data_thread = threading.Thread(target=self.data_update_loop, daemon=True)
        self.data_thread.start()

        self.update_all_data()

    def update_all_data(self):
        """Updates all data"""
        self.data_collector.update_data()

    def data_update_loop(self):
        """Data update loop"""
        last_ip = None
        while self.running:
            try:
                self.update_all_data()
                current_ip = self.data_collector.data.get('ip_address', 'N/A')
                if current_ip != last_ip:
                    self.generate_qrcode()
                    last_ip = current_ip
                time.sleep(3)
            except Exception as e:
                time.sleep(5)

    def draw_header(self):
        """Draws the top header bar with system info and current date/time"""
        header_rect = pygame.Rect(0, 0, self.width, self.layout['header_height'])
        pygame.draw.rect(self.screen, self.colors['card'], header_rect)

        # System Info (Temperature and Battery) - LEFT ALIGNED
        system_info_x = self.layout['card_margin']
        system_info_y = self.layout['header_height'] // 2 - (self.font_tiny.get_height() // 2)

        if self.data_collector.data['system_info']:
            sys_info = self.data_collector.data['system_info']
            temp_text = self.font_tiny.render(f"Temp: {sys_info.get('temp', 'N/A')}", True, self.colors['text_dim'])
            self.screen.blit(temp_text, (system_info_x, system_info_y))
            system_info_x += temp_text.get_width() + self.layout['card_padding'] # Add spacing

        if self.data_collector.data['battery_info']:
            battery_info = self.data_collector.data['battery_info']
            battery_percent = battery_info.get('percent', 'N/A')
            battery_text = self.font_tiny.render(f"Battery: {battery_percent:.1f}%", True, self.colors['text_dim'])
            self.screen.blit(battery_text, (system_info_x, system_info_y))
        else:
            no_battery_text = self.font_tiny.render("Battery: N/A", True, self.colors['text_dim'])
            self.screen.blit(no_battery_text, (system_info_x, system_info_y))


        # Current date and time - RIGHT ALIGNED
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

        # Calculate the total width of the card, including space for QR code if it exists
        total_card_width = self.width - 2 * self.layout['card_margin']

        # Determine the width of the main text area of the network card
        qrcode_area_width = int(qrcode_target_size * 1.1) if self.qrcode_surface else 0 # Add a small buffer

        card_rect = pygame.Rect(self.layout['card_margin'], y_start, total_card_width, card_height)
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        # Card title
        title = self.font_medium.render("Network Status", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_medium']

        # IP Address
        ip_text = self.font_small.render(f"IP: {self.data_collector.data['ip_address']}", True, self.colors['text'])
        self.screen.blit(ip_text, (x, y))
        y += self.layout['line_spacing_small']

        # WiFi Name
        wifi_text = self.font_small.render(f"WiFi: {self.data_collector.data['wifi_ssid']}", True, self.colors['text'])
        self.screen.blit(wifi_text, (x, y))
        y += self.layout['line_spacing_small']

        # Connection Status
        status_color = self.colors['success'] if self.data_collector.data['connection_status'] == "Connected" else self.colors['error']
        status_text = self.font_small.render(f"Status: {self.data_collector.data['connection_status']}", True, status_color)
        self.screen.blit(status_text, (x, y))

        # Draw QR Code if available, to the right of the network info
        if self.qrcode_surface:
            scaled_qrcode = pygame.transform.scale(self.qrcode_surface, (int(qrcode_target_size), int(qrcode_target_size)))
            qrcode_x = card_rect.x + card_rect.width - self.layout['card_padding'] - scaled_qrcode.get_width()
            qrcode_y = card_rect.y + (card_rect.height - scaled_qrcode.get_height()) // 2
            self.screen.blit(scaled_qrcode, (qrcode_x, qrcode_y))
        else:
            no_ip_text = self.font_tiny.render("No IP for QR", True, self.colors['text_dim'])
            no_ip_x = card_rect.x + card_rect.width - self.layout['card_padding'] - (qrcode_target_size // 2) - (no_ip_text.get_width() // 2)
            no_ip_y = card_rect.y + (card_rect.height - no_ip_text.get_height()) // 2
            self.screen.blit(no_ip_text, (no_ip_x, no_ip_y))


    def draw_system_card(self):
        """Draws the system info card (now empty as info is moved to header)"""
        # This function can now be empty or removed, as system info is in the header.
        pass


    def draw_usb_card(self):
        """Draws the USB device card"""
        # Position below the network card, alongside where the system card used to be.
        # This calculation needs to be updated since system card is removed.
        network_card_height = self.layout['card_padding'] * 2 + \
                              self.font_medium.get_height() + \
                              self.layout['line_spacing_medium'] + \
                              self.font_small.get_height() * 3 + \
                              self.layout['line_spacing_small'] * 2
        network_card_bottom = self.layout['header_height'] + self.layout['card_margin'] + network_card_height

        y_start = network_card_bottom + self.layout['card_margin']

        # Make USB card take up full remaining width since System card is gone
        card_rect = pygame.Rect(self.layout['card_margin'], y_start,
                               self.width - 2 * self.layout['card_margin'], # Full width
                               self.height - y_start - self.layout['card_margin'] - int(self.height * 0.08)) # To status bar

        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        # USB Devices
        title = self.font_small.render("USB Devices", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_small']

        if self.data_collector.data['usb_devices']:
            usb_content_height = 0
            for device in self.data_collector.data['usb_devices']:  # Display all available devices
                name_text_surface = self.font_small.render(device['name'], True, self.colors['text'])
                usb_content_height += name_text_surface.get_height()

                size_text_surface = self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB",
                                                 True, self.colors['text_dim'])
                usb_content_height += size_text_surface.get_height()

                usb_content_height += self.layout['line_spacing_small']

            # Ensure card height accommodates content, up to remaining space
            max_usb_card_height = self.height - y_start - self.layout['card_margin'] - int(self.height * 0.08) # Max height before status bar
            required_card_height = self.layout['card_padding'] * 2 + \
                                   self.font_small.get_height() + \
                                   self.layout['line_spacing_small'] + \
                                   usb_content_height
            card_rect.height = min(required_card_height, max_usb_card_height) # Take min to fit

            # Redraw background if height changed
            if abs(card_rect.height - (self.screen.get_height() - y_start - self.layout['card_margin'] - int(self.height * 0.08))) > 5: # Compare to original computed height
                 pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

            # Now draw the actual content on the potentially resized card
            x = card_rect.x + self.layout['card_padding']
            y = card_rect.y + self.layout['card_padding']
            self.screen.blit(self.font_small.render("USB Devices", True, self.colors['accent']), (x, y))
            y += self.layout['line_spacing_small']

            # Only draw devices that fit within the new card height
            current_device_y = y
            for device in self.data_collector.data['usb_devices']:
                # Check if device info will fit before drawing
                if current_device_y + self.font_small.get_height() * 2 + self.layout['line_spacing_small'] < card_rect.y + card_rect.height - self.layout['card_padding']:
                    self.screen.blit(self.font_small.render(device['name'], True, self.colors['text']), (x, current_device_y))
                    current_device_y += self.font_small.get_height()
                    self.screen.blit(self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB", True, self.colors['text_dim']), (x, current_device_y))
                    current_device_y += self.font_small.get_height() + self.layout['line_spacing_small']
                else:
                    break # Stop drawing if next device won't fit
        else:
            no_usb_text = self.font_small.render("No USB Devices", True, self.colors['text_dim'])
            self.screen.blit(no_usb_text, (x, y))


    def draw_status_bar(self):
        """Draws the bottom status bar with update time and running status"""
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
        if self.debug_mode:
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
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            self.running = False
                        elif event.key == pygame.K_F5:
                            self.update_all_data()
                    elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN]:
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            self.handle_touch(event.pos)
                        else:
                            touch_pos = (int(event.x * self.width), int(event.y * self.height))
                            self.handle_touch(touch_pos)

                self.screen.fill(self.colors['bg'])

                self.draw_header()
                self.draw_network_card()
                # self.draw_system_card() # Removed call as content moved
                self.draw_usb_card()
                self.draw_status_bar()

                pygame.display.flip()
                clock.tick(30)

        except KeyboardInterrupt:
            print("\nProgram interrupted by user (Ctrl+C).")
            self.running = False
        finally:
            self.running = False
            pygame.quit()