import pygame
import time
from datetime import datetime
import threading
import subprocess
import qrcode
import io
from data_collector import DataCollector
from sd_copy_manager import SDCopyManager

class RPiProductInterface:
    """Raspberry Pi Product Interface - Main application class"""

    def __init__(self, display_manager, debug_mode):
        self.display_manager = display_manager
        self.debug_mode = debug_mode
        self.running = True
        self.data_collector = DataCollector()
        
        # Initialize SDCopyManager
        self.sd_copy_manager = SDCopyManager()
        self.sd_copy_manager.set_event_callback(self.update_copy_status)
        self.copy_status_data = {'status_message': 'Initializing...', 'ssd_present': False}
        
        self.setup_pygame()
        self.qrcode_surface = None
        self.setup_ui()
        self.setup_data_updates()
        
        # Start the SD card detection loop in a separate thread
        self.sd_detection_thread = threading.Thread(target=self.sd_copy_manager.main_loop, daemon=True)
        self.sd_detection_thread.start()
        print("SD card detection thread started.")


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
            'progress_bg': (60, 60, 60),
            'progress_fill': (0, 180, 255)
        }

        self.layout = {
            'header_height': int(self.height * 0.12),
            'card_margin': int(self.width * 0.02),
            'card_padding': int(self.height * 0.02),
            'line_spacing_small': int(self.height * 0.05),
            'line_spacing_medium': int(self.height * 0.07),
        }

        # touch_areas now correctly defined without border_radius
        self.touch_areas = {
            'restart': pygame.Rect(self.width - int(self.width * 0.12) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),
            'refresh': pygame.Rect(self.width - int(self.width * 0.25) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),
            # This 'copy_stop' will be re-assigned dynamically in draw_progress_bar_card
            'copy_stop': pygame.Rect(0, 0, 0, 0) # Initialize as an empty rect
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

    def update_copy_status(self, data):
        """Callback function to receive copy status updates from SDCopyManager."""
        self.copy_status_data = data

    def draw_header(self):
        """Draws the top header bar with system info and current date/time"""
        header_rect = pygame.Rect(0, 0, self.width, self.layout['header_height'])
        pygame.draw.rect(self.screen, self.colors['card'], header_rect)

        # System Info (Temperature and Battery) - LEFT ALIGNED
        system_info_x = self.layout['card_margin']
        system_info_y = self.layout['header_height'] // 2 - (self.font_tiny.get_height() // 2)

        temp_str = f"Temp: {self.data_collector.data['system_info'].get('temp', 'N/A')}" if self.data_collector.data['system_info'] else "Temp: N/A"
        temp_text = self.font_tiny.render(temp_str, True, self.colors['text_dim'])
        self.screen.blit(temp_text, (system_info_x, system_info_y))
        system_info_x += temp_text.get_width() + self.layout['card_padding']

        battery_str = f"Battery: {self.data_collector.data['battery_info'].get('percent', 'N/A'):.1f}%" if self.data_collector.data['battery_info'] else "Battery: N/A"
        battery_text = self.font_tiny.render(battery_str, True, self.colors['text_dim'])
        self.screen.blit(battery_text, (system_info_x, system_info_y))


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
        """Draws the network info card and the QR code next to it. Returns its bottom Y coordinate."""
        y_start = self.layout['header_height'] + self.layout['card_margin']

        text_content_base_height = self.font_medium.get_height() + \
                                   self.layout['line_spacing_medium'] + \
                                   self.font_small.get_height() * 3 + \
                                   self.layout['line_spacing_small'] * 2
        
        card_height = (self.layout['card_padding'] * 2 + text_content_base_height) * 0.7 # 縮小 0.7 倍

        qrcode_target_size = (card_height - (self.layout['card_padding'] * 2)) * 0.8 # QR Code 縮小 0.8 倍
        
        total_card_width = self.width - 2 * self.layout['card_margin']
        
        card_rect = pygame.Rect(self.layout['card_margin'], y_start, total_card_width, card_height)
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        title = self.font_medium.render("Network Status", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_medium']

        ip_text = self.font_small.render(f"IP: {self.data_collector.data['ip_address']}", True, self.colors['text'])
        self.screen.blit(ip_text, (x, y))
        y += self.layout['line_spacing_small']

        wifi_text = self.font_small.render(f"WiFi: {self.data_collector.data['wifi_ssid']}", True, self.colors['text'])
        self.screen.blit(wifi_text, (x, y))
        y += self.layout['line_spacing_small']

        status_color = self.colors['success'] if self.data_collector.data['connection_status'] == "Connected" else self.colors['error']
        status_text = self.font_small.render(f"Status: {self.data_collector.data['connection_status']}", True, status_color)
        self.screen.blit(status_text, (x, y))

        if self.qrcode_surface:
            scaled_qrcode = pygame.transform.scale(self.qrcode_surface, (int(qrcode_target_size), int(qrcode_target_size)))
            qrcode_x = card_rect.x + card_rect.width - self.layout['card_padding'] - scaled_qrcode.get_width()
            qrcode_y = card_rect.y + (card_rect.height - scaled_qrcode.get_height()) // 2
            self.screen.blit(scaled_qrcode, (qrcode_x, qrcode_y))
        else:
            no_ip_text = self.font_tiny.render("No IP for QR", True, self.colors['text_dim'])
            no_ip_x = card_rect.x + card_rect.width - self.layout['card_padding'] - (qrcode_target_size / 2) - (no_ip_text.get_width() / 2)
            no_ip_y = card_rect.y + (card_rect.height - no_ip_text.get_height()) // 2
            self.screen.blit(no_ip_text, (no_ip_x, no_ip_y))
        
        return card_rect.bottom # Return the bottom Y coordinate of this card

    # draw_usb_card now accepts y_start as a parameter
    def draw_usb_card(self, y_start):
        """Draws the USB device card at a given y_start position. Returns its bottom Y coordinate."""
        # Estimate for progress bar section (simplified to a fixed height for consistency)
        status_bar_height = int(self.height * 0.08)
        progress_bar_height_estimate = self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2
        
        # Max height for USB card, before the estimated progress bar area and status bar
        max_usb_card_height = self.height - y_start - self.layout['card_margin'] - progress_bar_height_estimate - status_bar_height

        # Ensure a minimum height for the USB card even if no devices, so it's always visible
        min_usb_card_height = self.font_small.get_height() * 2 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] # Title + "No USB Devices"
        card_rect = pygame.Rect(self.layout['card_margin'], y_start,
                               self.width - 2 * self.layout['card_margin'], max(min_usb_card_height, max_usb_card_height))

        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        title = self.font_small.render("USB Devices", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_small']

        if self.data_collector.data['usb_devices']:
            current_device_y = y
            for device in self.data_collector.data['usb_devices']:
                device_entry_height = self.font_small.get_height() * 2 + self.layout['line_spacing_small']
                
                if current_device_y + device_entry_height < card_rect.y + card_rect.height - self.layout['card_padding']:
                    self.screen.blit(self.font_small.render(device['name'], True, self.colors['text']), (x, current_device_y))
                    current_device_y += self.font_small.get_height()
                    self.screen.blit(self.font_small.render(f"{device['used']:.1f}/{device['total']:.1f}GB", True, self.colors['text_dim']), (x, current_device_y))
                    current_device_y += self.font_small.get_height() + self.layout['line_spacing_small']
                else:
                    if self.data_collector.data['usb_devices'].index(device) < len(self.data_collector.data['usb_devices']) -1:
                        more_text = self.font_tiny.render("...more", True, self.colors['text_dim'])
                        self.screen.blit(more_text, (x, current_device_y))
                    break
        else:
            no_usb_text = self.font_small.render("No USB Devices", True, self.colors['text_dim'])
            self.screen.blit(no_usb_text, (x, y))

        return card_rect.bottom # Return the bottom Y coordinate of this card

    # Helper function to calculate network card's bottom Y without drawing it again
    def _calculate_network_card_bottom_y(self):
        y_start = self.layout['header_height'] + self.layout['card_margin']
        text_content_base_height = self.font_medium.get_height() + \
                                   self.layout['line_spacing_medium'] + \
                                   self.font_small.get_height() * 3 + \
                                   self.layout['line_spacing_small'] * 2
        card_height = (self.layout['card_padding'] * 2 + text_content_base_height) * 0.7
        return y_start + card_height

    # Helper function to calculate USB card's bottom Y without drawing it
    def _calculate_usb_card_bottom_y(self, y_start_for_calc):
        status_bar_height = int(self.height * 0.08)
        progress_bar_height_estimate = self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2
        max_usb_card_height = self.height - y_start_for_calc - self.layout['card_margin'] - progress_bar_height_estimate - status_bar_height
        min_usb_card_height = self.font_small.get_height() * 2 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small']
        
        usb_content_height_ideal = 0
        if self.data_collector.data['usb_devices']:
            # This loop only for calculation, not actual drawing
            for device in self.data_collector.data['usb_devices']:
                usb_content_height_ideal += self.font_small.get_height() * 2 + self.layout['line_spacing_small']
        else:
            usb_content_height_ideal = self.font_small.get_height() * 2 + self.layout['line_spacing_small']

        calculated_card_height = usb_content_height_ideal + self.font_small.get_height() + self.layout['line_spacing_small'] + self.layout['card_padding'] * 2

        final_card_height = max(min_usb_card_height, min(calculated_card_height, max_usb_card_height))
        
        return y_start_for_calc + final_card_height


    def draw_progress_bar_card(self, y_start):
        """Draws the SD card copy progress bar card."""
        fixed_progress_card_height = self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2
        
        ssd_present = self.copy_status_data.get('ssd_present', False)
        card_height = fixed_progress_card_height
        if not ssd_present:
            card_height = self.font_medium.get_height() + self.layout['card_padding'] * 2 + self.layout['line_spacing_medium'] * 2 

        card_rect = pygame.Rect(self.layout['card_margin'], y_start,
                               self.width - 2 * self.layout['card_margin'], card_height)
        pygame.draw.rect(self.screen, self.colors['card'], card_rect, border_radius=10)

        x = card_rect.x + self.layout['card_padding']
        y = card_rect.y + self.layout['card_padding']

        title = self.font_small.render("SD Card Copy Progress", True, self.colors['accent'])
        self.screen.blit(title, (x, y))
        y += self.layout['line_spacing_small']

        status_message = self.copy_status_data.get('status_message', 'Initializing...')
        is_copying = self.copy_status_data.get('is_copying', False)

        if not ssd_present:
            insert_ssd_text = self.font_medium.render("Please Insert SSD!", True, self.colors['error'])
            insert_ssd_rect = insert_ssd_text.get_rect(center=(card_rect.centerx, card_rect.centery))
            self.screen.blit(insert_ssd_text, insert_ssd_rect)
            return

        status_text = self.font_small.render(f"Status: {status_message}", True, self.colors['text_dim'])
        self.screen.blit(status_text, (x, y))
        y += self.layout['line_spacing_small']

        progress_percent = self.copy_status_data.get('progress_percent', 0.0)
        bar_width = card_rect.width - 2 * self.layout['card_padding']
        bar_height = int(self.font_small.get_height() * 0.8)
        bar_x = x
        bar_y = y

        pygame.draw.rect(self.screen, self.colors['progress_bg'], (bar_x, bar_y, bar_width, bar_height), border_radius=5)
        pygame.draw.rect(self.screen, self.colors['progress_fill'], (bar_x, bar_y, bar_width * (progress_percent / 100), bar_height), border_radius=5)

        progress_label = f"{progress_percent:.1f}% ({self.copy_status_data.get('copied_files', 0)}/{self.copy_status_data.get('total_files', 0)})"
        progress_text = self.font_tiny.render(progress_label, True, self.colors['text'])
        progress_text_rect = progress_text.get_rect(center=(bar_x + bar_width / 2, bar_y + bar_height / 2))
        self.screen.blit(progress_text, progress_text_rect)
        y += bar_height + self.layout['line_spacing_small']

        current_file = self.copy_status_data.get('current_file', '')
        if current_file:
            current_file_text = self.font_tiny.render(f"File: {current_file}", True, self.colors['text_dim'])
            self.screen.blit(current_file_text, (x, y))

        if is_copying:
            stop_button_width = int(self.width * 0.12)
            stop_button_height = int(self.height * 0.06)
            stop_button_x = card_rect.x + card_rect.width - stop_button_width - self.layout['card_padding']
            stop_button_y = card_rect.y + card_rect.height - stop_button_height - self.layout['card_padding']
            
            # Re-assign touch area rect for the stop button
            self.touch_areas['copy_stop'] = pygame.Rect(stop_button_x, stop_button_y, stop_button_width, stop_button_height)

            pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['copy_stop'], border_radius=5)
            stop_text = self.font_small.render("Stop", True, self.colors['text'])
            stop_rect = stop_text.get_rect(center=self.touch_areas['copy_stop'].center)
            self.screen.blit(stop_text, stop_rect)


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
            # Handle copy stop button, only if copying AND SSD is present
            elif self.copy_status_data.get('ssd_present', False) and self.copy_status_data.get('is_copying', False) and self.touch_areas['copy_stop'].collidepoint(pos):
                print("Copy stop button pressed.")
                self.sd_copy_manager.stop_copy()


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
                
                # Draw network card first, and get its bottom Y for subsequent elements
                network_card_bottom_y = self.draw_network_card() 
                
                # Calculate USB card's y_start based on network card's bottom
                usb_card_y_start = network_card_bottom_y + self.layout['card_margin']
                # Draw USB card and get its bottom Y
                usb_card_bottom_y = self.draw_usb_card(usb_card_y_start) 
                
                # Calculate progress bar's y_start based on USB card's bottom
                progress_bar_y_start = usb_card_bottom_y + self.layout['card_margin']
                self.draw_progress_bar_card(progress_bar_y_start)
                
                self.draw_status_bar()

                pygame.display.flip()
                clock.tick(30)

        except KeyboardInterrupt:
            print("\nProgram interrupted by user (Ctrl+C).")
            self.running = False
        finally:
            self.running = False
            pygame.quit()
            if self.sd_copy_manager.is_copying:
                self.sd_copy_manager.stop_copy()