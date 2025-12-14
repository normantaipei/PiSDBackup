import pygame
import time
from datetime import datetime
import threading
import re
import subprocess
import qrcode
import os
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

        # UI State Management
        self.current_view = 'main' # 'main', 'wifi_list', 'password_input'
        self.wifi_scan_result = []
        self.selected_ssid = ""
        self.password_input = ""
        self.wifi_list_page = 0
        
        self.sd_copy_manager = SDCopyManager()
        self.sd_copy_manager.set_event_callback(self.update_copy_status)
        self.copy_status_data = {'status_message': 'Initializing...', 'ssd_present': False}
        
        self.setup_pygame()
        self.qrcode_surface = None
        self.setup_ui()
        self.setup_data_updates()
        
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

        self.touch_areas = {
            'restart': pygame.Rect(self.width - int(self.width * 0.12) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),
            'refresh': pygame.Rect(self.width - int(self.width * 0.25) - self.layout['card_margin'],
                                   self.layout['card_margin'] * 0.5,
                                   int(self.width * 0.12),
                                   int(self.layout['header_height'] * 0.8)),                                   
            'change_wifi': pygame.Rect(0, 0, 0, 0), # Will be set in draw_network_card
            'wifi_list_back': pygame.Rect(self.layout['card_margin'], self.layout['card_margin'], int(self.width * 0.15), int(self.height * 0.08)),
            'password_back': pygame.Rect(self.layout['card_margin'], self.layout['card_margin'], int(self.width * 0.15), int(self.height * 0.08)),
            'password_connect': pygame.Rect(0, 0, 0, 0), # Will be set in draw_password_input_view
            'wifi_page_prev': pygame.Rect(0, 0, 0, 0), # Will be set in draw_wifi_list_view
            'wifi_page_next': pygame.Rect(0, 0, 0, 0), # Will be set in draw_wifi_list_view
            'copy_stop': pygame.Rect(0, 0, 0, 0)
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
        
        card_height = (self.layout['card_padding'] * 2 + text_content_base_height) * 0.7

        qrcode_target_size = (card_height - (self.layout['card_padding'] * 2)) * 0.8
        
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

        # Add "Change WiFi" button
        button_width = self.font_small.render("Change WiFi", True, self.colors['text']).get_width() + self.layout['card_padding'] * 2
        button_height = self.font_small.get_height() + self.layout['card_padding']
        button_x = x + ip_text.get_width() + self.layout['card_padding'] * 2
        button_y = card_rect.y + self.layout['line_spacing_medium']
        self.touch_areas['change_wifi'] = pygame.Rect(button_x, button_y, button_width, button_height)
        pygame.draw.rect(self.screen, self.colors['accent'], self.touch_areas['change_wifi'], border_radius=5)
        change_wifi_text = self.font_small.render("Change WiFi", True, self.colors['text'])
        self.screen.blit(change_wifi_text, (button_x + self.layout['card_padding'], button_y + (button_height - change_wifi_text.get_height()) // 2))

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
        
        return card_rect.bottom

    def draw_usb_card(self, y_start):
        """Draws the USB device card at a given y_start position. Returns its bottom Y coordinate."""
        status_bar_height = int(self.height * 0.08)
        
        # We need to use the scaled height of the progress bar for calculation here
        progress_bar_height_estimate = (self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2) * 0.7 # Scaled by 0.7
        
        max_usb_card_height = self.height - y_start - self.layout['card_margin'] - progress_bar_height_estimate - status_bar_height

        min_usb_card_height = self.font_small.get_height() * 2 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small']
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

        return card_rect.bottom

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
        # Use the scaled height for progress bar estimate
        progress_bar_height_estimate = (self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2) * 0.7
        
        max_usb_card_height = self.height - y_start_for_calc - self.layout['card_margin'] - progress_bar_height_estimate - status_bar_height
        min_usb_card_height = self.font_small.get_height() * 2 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small']
        
        usb_content_height_ideal = 0
        if self.data_collector.data['usb_devices']:
            for device in self.data_collector.data['usb_devices']:
                usb_content_height_ideal += self.font_small.get_height() * 2 + self.layout['line_spacing_small']
        else:
            usb_content_height_ideal = self.font_small.get_height() * 2 + self.layout['line_spacing_small']

        calculated_card_height = usb_content_height_ideal + self.font_small.get_height() + self.layout['line_spacing_small'] + self.layout['card_padding'] * 2

        final_card_height = max(min_usb_card_height, min(calculated_card_height, max_usb_card_height))
        
        return y_start_for_calc + final_card_height


    def draw_progress_bar_card(self, y_start):
        """Draws the SD card copy progress bar card at a given y_start position."""
        # Fixed height for progress card when SSD is present (now scaled)
        fixed_progress_card_height_scaled = (self.font_small.get_height() * 3 + self.layout['card_padding'] * 2 + self.layout['line_spacing_small'] * 2) * 0.7
        
        ssd_present = self.copy_status_data.get('ssd_present', False)
        card_height = fixed_progress_card_height_scaled
        if not ssd_present:
            # If SSD is not present, use a larger height for the "Please Insert SSD" message
            # This height is not scaled, as it needs to fit the text clearly
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
            
            self.touch_areas['copy_stop'] = pygame.Rect(stop_button_x, stop_button_y, stop_button_width, stop_button_height)

            pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['copy_stop'], border_radius=5)
            stop_text = self.font_small.render("Stop", True, self.colors['text'])
            stop_rect = stop_text.get_rect(center=self.touch_areas['copy_stop'].center)
            self.screen.blit(stop_text, stop_rect)

    def draw_wifi_list_view(self):
        """Draws the screen for selecting a WiFi network."""
        self.screen.fill(self.colors['bg'])
        
        # Back button
        pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['wifi_list_back'], border_radius=5)
        back_text = self.font_small.render("Back", True, self.colors['text'])
        self.screen.blit(back_text, (self.touch_areas['wifi_list_back'].x + 20, self.touch_areas['wifi_list_back'].y + 10))

        title_text = self.font_medium.render("Select a WiFi Network", True, self.colors['accent'])
        self.screen.blit(title_text, (self.width // 2 - title_text.get_width() // 2, self.layout['card_margin']))

        if not self.wifi_scan_result:
            info_text = self.font_medium.render("Scanning for WiFi...", True, self.colors['text_dim'])
            self.screen.blit(info_text, (self.width // 2 - info_text.get_width() // 2, self.height // 2 - info_text.get_height() // 2))
            return

        # --- Pagination Logic ---
        footer_height = int(self.height * 0.12)
        list_y_start = self.layout['header_height']
        list_height = self.height - list_y_start - footer_height - self.layout['card_margin']
        list_area_rect = pygame.Rect(self.layout['card_margin'], list_y_start, self.width - self.layout['card_margin']*2, list_height)

        item_height = self.font_small.get_height() + self.layout['card_padding'] * 3
        item_spacing = self.layout['card_margin']
        items_per_page = max(1, list_height // (item_height + item_spacing))
        total_pages = (len(self.wifi_scan_result) + items_per_page - 1) // items_per_page
        start_index = self.wifi_list_page * items_per_page
        end_index = start_index + items_per_page
        page_items = self.wifi_scan_result[start_index:end_index]

        self.touch_areas['wifi_items'] = []
        y_pos = 0
        for ssid in page_items:
            item_rect_on_screen = pygame.Rect(list_area_rect.x, list_area_rect.y + y_pos, list_area_rect.width, item_height)
            connect_button_width = self.font_small.render("Connect", True, self.colors['text']).get_width() + self.layout['card_padding'] * 2
            connect_button_height = item_height - self.layout['card_padding']
            connect_button_rect = pygame.Rect(
                item_rect_on_screen.right - connect_button_width - self.layout['card_padding'],
                item_rect_on_screen.y + (item_height - connect_button_height) // 2,
                connect_button_width,
                connect_button_height
            )
            
            pygame.draw.rect(self.screen, self.colors['card'], item_rect_on_screen, border_radius=5)
            
            # Draw SSID text
            ssid_text = self.font_small.render(ssid, True, self.colors['text'])
            self.screen.blit(ssid_text, (item_rect_on_screen.x + self.layout['card_padding'], item_rect_on_screen.y + (item_height - ssid_text.get_height()) // 2))

            # Draw Connect button
            pygame.draw.rect(self.screen, self.colors['accent'], connect_button_rect, border_radius=5)
            connect_text = self.font_small.render("Connect", True, self.colors['text'])
            self.screen.blit(connect_text, (connect_button_rect.centerx - connect_text.get_width() // 2, connect_button_rect.centery - connect_text.get_height() // 2))
            
            self.touch_areas['wifi_items'].append({'ssid': ssid, 'rect': item_rect_on_screen, 'connect_rect': connect_button_rect})
            y_pos += item_height + item_spacing

        # --- Draw Footer with Page Buttons ---
        footer_y = self.height - footer_height
        button_width = int(self.width * 0.2)
        button_height = int(footer_height * 0.7)
        
        # Previous Page Button
        if self.wifi_list_page > 0:
            prev_rect = pygame.Rect(self.layout['card_margin'], footer_y + (footer_height - button_height) // 2, button_width, button_height)
            self.touch_areas['wifi_page_prev'] = prev_rect
            pygame.draw.rect(self.screen, self.colors['accent'], prev_rect, border_radius=5)
            prev_text = self.font_small.render("Prev", True, self.colors['text'])
            self.screen.blit(prev_text, (prev_rect.centerx - prev_text.get_width() // 2, prev_rect.centery - prev_text.get_height() // 2))

        # Page Indicator
        page_indicator_text = f"Page {self.wifi_list_page + 1} / {total_pages}"
        page_text = self.font_small.render(page_indicator_text, True, self.colors['text_dim'])
        self.screen.blit(page_text, (self.width // 2 - page_text.get_width() // 2, footer_y + (footer_height - page_text.get_height()) // 2))

        # Next Page Button
        if self.wifi_list_page < total_pages - 1:
            next_rect = pygame.Rect(self.width - self.layout['card_margin'] - button_width, footer_y + (footer_height - button_height) // 2, button_width, button_height)
            self.touch_areas['wifi_page_next'] = next_rect
            pygame.draw.rect(self.screen, self.colors['accent'], next_rect, border_radius=5)
            next_text = self.font_small.render("Next", True, self.colors['text'])
            self.screen.blit(next_text, (next_rect.centerx - next_text.get_width() // 2, next_rect.centery - next_text.get_height() // 2))


    def draw_password_input_view(self):
        """Draws the on-screen keyboard for password input."""
        self.screen.fill(self.colors['bg'])

        # Back button
        pygame.draw.rect(self.screen, self.colors['error'], self.touch_areas['password_back'], border_radius=5)
        back_text = self.font_small.render("Back", True, self.colors['text'])
        self.screen.blit(back_text, (self.touch_areas['password_back'].x + 20, self.touch_areas['password_back'].y + 10))

        title_text = self.font_medium.render(f"Password for {self.selected_ssid}", True, self.colors['accent'])
        self.screen.blit(title_text, (self.width // 2 - title_text.get_width() // 2, self.layout['card_margin']))

        # Password display box
        input_box_y = self.layout['header_height']
        input_box_rect = pygame.Rect(self.layout['card_margin'], input_box_y, self.width - self.layout['card_margin']*2, 50)
        pygame.draw.rect(self.screen, self.colors['card'], input_box_rect, border_radius=5)
        password_display = self.password_input
        password_text = self.font_medium.render(password_display, True, self.colors['text'])
        self.screen.blit(password_text, (input_box_rect.x + 10, input_box_rect.y + 5))

        # Keyboard layout
        keys = [
            "1234567890",
            "qwertyuiop",
            "asdfghjkl",
            "zxcvbnm"
        ]
        key_size = int(self.width * 0.08)
        key_margin = int(self.width * 0.01)
        keyboard_y_start = input_box_y + 60

        self.touch_areas['keyboard_keys'] = []
        y = keyboard_y_start
        for row in keys:
            x = (self.width - (len(row) * (key_size + key_margin))) // 2
            for char in row:
                key_rect = pygame.Rect(x, y, key_size, key_size)
                self.touch_areas['keyboard_keys'].append({'char': char, 'rect': key_rect})
                pygame.draw.rect(self.screen, self.colors['card'], key_rect, border_radius=5)
                char_text = self.font_small.render(char, True, self.colors['text'])
                self.screen.blit(char_text, (key_rect.centerx - char_text.get_width()//2, key_rect.centery - char_text.get_height()//2))
                x += key_size + key_margin
            y += key_size + key_margin

        # Special keys (Backspace and Connect)
        backspace_rect = pygame.Rect(self.width - key_size*2 - key_margin*2, keyboard_y_start + (key_size + key_margin) * 2, key_size*2, key_size)
        self.touch_areas['keyboard_keys'].append({'char': 'backspace', 'rect': backspace_rect})
        pygame.draw.rect(self.screen, self.colors['warning'], backspace_rect, border_radius=5)
        backspace_text = self.font_small.render("<-", True, self.colors['text'])
        self.screen.blit(backspace_text, (backspace_rect.centerx - backspace_text.get_width()//2, backspace_rect.centery - backspace_text.get_height()//2))

        connect_rect = pygame.Rect(self.width - key_size*2 - key_margin*2, keyboard_y_start + (key_size + key_margin) * 3, key_size*2, key_size)
        self.touch_areas['password_connect'] = connect_rect
        pygame.draw.rect(self.screen, self.colors['success'], connect_rect, border_radius=5)
        connect_text = self.font_small.render("Connect", True, self.colors['text'])
        self.screen.blit(connect_text, (connect_rect.centerx - connect_text.get_width()//2, connect_rect.centery - connect_text.get_height()//2))

    def connect_to_wifi(self):
        """Attempts to connect to the selected WiFi network."""
        print(f"Attempting to connect to SSID: {self.selected_ssid}")
        self.current_view = 'main' # Go back to main view to show status
        self.sd_copy_manager.status_message = f"Connecting to {self.selected_ssid}..."

        def run_connection_logic():
            try:
                # Restart the wpa_supplicant service to ensure it's in a clean state.
                # This can resolve issues where wpa_cli fails to communicate with the service.
                print("Restarting wpa_supplicant service...")
                subprocess.run(['sudo', 'systemctl', 'restart', 'wpa_supplicant.service'], check=True)
                time.sleep(2) # Give the service a moment to restart

                # Ensure wpa_supplicant.conf allows updates via wpa_cli
                wpa_conf_dir = "/etc/wpa_supplicant"
                wpa_conf_path = os.path.join(wpa_conf_dir, "wpa_supplicant.conf")
                
                try:
                    # Check if the file exists. If not, create it with the required content.
                    if not os.path.exists(wpa_conf_path):
                        print(f"'{wpa_conf_path}' does not exist. Creating it.")
                        # Ensure the directory exists
                        subprocess.run(f'sudo mkdir -p {wpa_conf_dir}', shell=True, check=True)
                        # Create the file with initial config
                        initial_config = 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\n'
                        subprocess.run(f"echo '{initial_config}' | sudo tee {wpa_conf_path} > /dev/null", shell=True, check=True)
                    else:
                        # If file exists, ensure update_config=1 is present
                        conf_content = subprocess.check_output(['sudo', 'cat', wpa_conf_path], text=True)
                        if 'update_config=1' not in conf_content:
                            print(f"'{wpa_conf_path}' is missing 'update_config=1'. Adding it.")
                            subprocess.run(f"echo 'update_config=1' | sudo tee -a {wpa_conf_path} > /dev/null", shell=True, check=True)
                    subprocess.check_call(['sudo', 'wpa_cli', '-i', 'wlan0', 'reconfigure'])
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    print(f"Warning: Could not create or update {wpa_conf_path}: {e}")

                # Use wpa_cli for a more robust connection method
                # 1. Add a new network configuration
                add_net_output = subprocess.check_output(['sudo', 'wpa_cli', '-i', 'wlan0', 'add_network'], text=True)
                network_id = add_net_output.strip()
                if not network_id.isdigit():
                    raise ValueError(f"Failed to add network, received: {network_id}")
                print(f"Added new network with ID: {network_id}")

                # 2. Set the SSID and password for the new network
                subprocess.check_call(['sudo', 'wpa_cli', '-i', 'wlan0', 'set_network', network_id, 'ssid', f'"{self.selected_ssid}"'])
                subprocess.check_call(['sudo', 'wpa_cli', '-i', 'wlan0', 'set_network', network_id, 'psk', f'"{self.password_input}"'])

                # 3. Enable the network and save the configuration
                subprocess.check_call(['sudo', 'wpa_cli', '-i', 'wlan0', 'enable_network', network_id])
                subprocess.check_call(['sudo', 'wpa_cli', '-i', 'wlan0', 'save_config'])

                self.sd_copy_manager.status_message = "Connecting..."

                # 4. Wait for connection by polling for an IP address
                connected = False
                for _ in range(15): # Wait up to 30 seconds
                    time.sleep(2)
                    self.update_all_data()
                    if self.data_collector.data['connection_status'] == "Connected":
                        connected = True
                        break
                
                if connected:
                    self.sd_copy_manager.status_message = f"Connected to {self.selected_ssid}!"
                else:
                    self.sd_copy_manager.status_message = f"Failed to connect to {self.selected_ssid}."

            except (subprocess.CalledProcessError, ValueError) as e:
                print(f"Error connecting to WiFi: {e}")
                self.sd_copy_manager.status_message = "Error during connection."
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                self.sd_copy_manager.status_message = "Unexpected connection error."
            finally:
                self.password_input = ""
                self.selected_ssid = ""

        threading.Thread(target=run_connection_logic, daemon=True).start()


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
        
        if self.current_view == 'main':
            if self.touch_areas['change_wifi'].collidepoint(pos):
                print("Change WiFi button pressed. Scanning for networks...")
                self.current_view = 'wifi_list'
                self.wifi_list_page = 0 # Reset page on view change
                self.wifi_scan_result = [] # Clear previous results
                # Scan in a new thread to avoid freezing the UI
                threading.Thread(target=lambda: setattr(self, 'wifi_scan_result', self.data_collector.get_available_wifi_networks()), daemon=True).start()

        elif self.current_view == 'wifi_list':
            if self.touch_areas['wifi_list_back'].collidepoint(pos):
                self.current_view = 'main'
            
            if self.touch_areas.get('wifi_page_prev') and self.touch_areas['wifi_page_prev'].collidepoint(pos):
                if self.wifi_list_page > 0:
                    self.wifi_list_page -= 1
            elif self.touch_areas.get('wifi_page_next') and self.touch_areas['wifi_page_next'].collidepoint(pos):
                self.wifi_list_page += 1 # Boundary check is implicit in drawing logic

            for item in self.touch_areas.get('wifi_items', []):
                if item['connect_rect'].collidepoint(pos):
                    self.selected_ssid = item['ssid']
                    self.password_input = "" # Clear old password
                    self.current_view = 'password_input'
                    print(f"Selected SSID: {self.selected_ssid}")
                    break

        elif self.current_view == 'password_input':
            if self.touch_areas['password_back'].collidepoint(pos):
                self.current_view = 'wifi_list'
            elif self.touch_areas['password_connect'].collidepoint(pos):
                threading.Thread(target=self.connect_to_wifi, daemon=True).start()
            for key in self.touch_areas.get('keyboard_keys', []):
                if key['rect'].collidepoint(pos):
                    if key['char'] == 'backspace':
                        self.password_input = self.password_input[:-1]
                    else:
                        self.password_input += key['char']
                    break
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
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        self.handle_touch(event.pos)
                    elif event.type == pygame.FINGERDOWN:
                        touch_pos = (int(event.x * self.width), int(event.y * self.height))
                        self.handle_touch(touch_pos)
                    elif event.type == pygame.FINGERUP:
                        pass # FINGERUP is now only for ending a drag, which we removed.

                # View-based rendering
                if self.current_view == 'main':
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
                elif self.current_view == 'wifi_list':
                    self.draw_wifi_list_view()
                elif self.current_view == 'password_input':
                    self.draw_password_input_view()

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