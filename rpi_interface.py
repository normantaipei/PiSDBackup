"""Touch-screen interface (pygame)."""

from __future__ import annotations

import io
import logging
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

import pygame
import qrcode

from config import Config
from data_collector import DataCollector
from sd_copy_manager import SDCopyManager
from web_file_manager import web_url
from wifi_manager import WifiManager

log = logging.getLogger(__name__)

KEY_ROWS = {
    "lower": ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"],
    "upper": ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"],
    "symbols": ["!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?", "`~"],
}


class RPiProductInterface:
    def __init__(self, display_manager, config: Config, sd_copy_manager: Optional[SDCopyManager] = None,
                 data_collector: Optional[DataCollector] = None):
        self.display_manager = display_manager
        self.config = config
        self.debug_mode = config.debug_mode
        self.running = True
        self.stop_event = threading.Event()

        self.wifi = WifiManager(config.wifi_interface)
        self.data_collector = data_collector or DataCollector(config, self.wifi)
        self.sd_copy_manager = sd_copy_manager or SDCopyManager(config)
        self.copy_status: Dict = self.sd_copy_manager.get_status()
        self.sd_copy_manager.set_event_callback(self._on_copy_status)

        # UI state
        self.current_view = "main"          # main | wifi_list | password_input
        self.wifi_scan_result: List[str] = []
        self.wifi_scanning = False
        self.selected_ssid = ""
        self.password_input = ""
        self.password_visible = False
        self.keyboard_layout = "lower"
        self.wifi_list_page = 0
        self.wifi_busy = False
        self._notice: Optional[str] = None
        self._notice_until = 0.0
        self.qrcode_surface = None
        self._qr_for: Optional[str] = None

        self.setup_pygame()
        self.setup_ui()

        self.data_thread = threading.Thread(target=self.data_update_loop, name="data-update", daemon=True)
        self.data_thread.start()
        self.sd_detection_thread = threading.Thread(target=self.sd_copy_manager.main_loop, args=(self.stop_event,),
                                                    name="sd-detect", daemon=True)
        self.sd_detection_thread.start()

    # ------------------------------------------------------------------ setup
    def setup_pygame(self):
        pygame.init()
        pygame.font.init()
        info = pygame.display.Info()
        self.width, self.height = info.current_w, info.current_h
        if self.width <= 0 or self.height <= 0 or self.width > 4096:
            self.width, self.height = 800, 480
        flags = pygame.FULLSCREEN if self.config.fullscreen else 0
        self.screen = pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption("PiSDBackup")
        pygame.mouse.set_visible(False)
        log.info("Screen initialised: %dx%d", self.width, self.height)

    def setup_ui(self):
        def get_font(size):
            for name in ("DejaVuSans", "FreeSans", "Arial", None):
                try:
                    font = pygame.font.SysFont(name, size)
                    if font.render("A", True, (0, 0, 0)).get_width() > 0:
                        return font
                except Exception:
                    pass
            return pygame.font.Font(None, size)

        h = self.height
        self.font_large = get_font(int(h * 0.08))
        self.font_medium = get_font(int(h * 0.06))
        self.font_small = get_font(int(h * 0.04))
        self.font_tiny = get_font(int(h * 0.03))
        self.font_mono = get_font(int(h * 0.045))

        self.colors = {
            "bg": (30, 30, 30), "card": (45, 45, 45), "key": (60, 60, 60), "accent": (0, 150, 255),
            "success": (0, 200, 100), "warning": (255, 180, 0), "error": (255, 80, 80),
            "text": (255, 255, 255), "text_dim": (180, 180, 180), "progress_bg": (60, 60, 60), "progress_fill": (0, 180, 255),
        }
        self.layout = {
            "header_height": int(h * 0.12), "card_margin": int(self.width * 0.02), "card_padding": int(h * 0.02),
            "line_spacing_small": int(h * 0.05), "line_spacing_medium": int(h * 0.07), "status_bar_height": int(h * 0.08),
        }
        m = self.layout["card_margin"]
        self.touch_areas: Dict = {
            "restart": pygame.Rect(self.width - int(self.width * 0.12) - m, m // 2, int(self.width * 0.12), int(self.layout["header_height"] * 0.8)),
            "refresh": pygame.Rect(self.width - int(self.width * 0.25) - m, m // 2, int(self.width * 0.12), int(self.layout["header_height"] * 0.8)),
            "change_wifi": pygame.Rect(0, 0, 0, 0),
            "back": pygame.Rect(m, m, int(self.width * 0.15), int(h * 0.08)),
            "copy_stop": pygame.Rect(0, 0, 0, 0),
            "wifi_items": [], "wifi_page_prev": None, "wifi_page_next": None, "wifi_rescan": None,
            "keys": [], "password_connect": None, "password_toggle": None,
        }

    # ------------------------------------------------------------- callbacks
    def _on_copy_status(self, data: Dict):
        self.copy_status = data

    def notify(self, message: str, seconds: float = 8.0):
        self._notice = message
        self._notice_until = time.monotonic() + seconds

    def _current_notice(self) -> Optional[str]:
        if self._notice and time.monotonic() < self._notice_until:
            return self._notice
        return None

    # ----------------------------------------------------------- background
    def data_update_loop(self):
        while not self.stop_event.is_set():
            try:
                self.data_collector.update_data()
                ip = self.data_collector.data.get("ip_address")
                if ip != self._qr_for:
                    self.generate_qrcode(ip)
            except Exception:
                log.exception("Data update failed")
            self.stop_event.wait(3)

    def generate_qrcode(self, ip: Optional[str]):
        self._qr_for = ip
        if not ip or ip == "IP Unavailable":
            self.qrcode_surface = None
            return
        try:
            qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=6, border=2)
            qr.add_data(web_url(self.config, ip))
            qr.make(fit=True)
            img = qr.make_image(fill_color="white", back_color=(45, 45, 45))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            self.qrcode_surface = pygame.image.load(buf)
        except Exception:
            log.exception("QR code generation failed")
            self.qrcode_surface = None

    # ---------------------------------------------------------------- drawing
    def _text(self, font, text, color, pos):
        surf = font.render(text, True, color)
        self.screen.blit(surf, pos)
        return surf

    def _button(self, rect, label, color, font=None):
        pygame.draw.rect(self.screen, color, rect, border_radius=6)
        surf = (font or self.font_small).render(label, True, self.colors["text"])
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _fit(self, font, text, max_width):
        if font.size(text)[0] <= max_width:
            return text
        while len(text) > 3 and font.size(text + "…")[0] > max_width:
            text = text[:-1]
        return text + "…"

    def draw_header(self):
        L = self.layout
        pygame.draw.rect(self.screen, self.colors["card"], pygame.Rect(0, 0, self.width, L["header_height"]))
        y = L["header_height"] // 2 - self.font_tiny.get_height() // 2
        x = L["card_margin"]
        temp = self.data_collector.data.get("system_info", {}).get("temp", "N/A")
        x += self._text(self.font_tiny, f"Temp: {temp}", self.colors["text_dim"], (x, y)).get_width() + L["card_padding"]
        batt = self.data_collector.data.get("battery_info") or {}
        if batt.get("percent") is not None:
            plug = " ⚡" if batt.get("power_plugged") else ""
            self._text(self.font_tiny, f"Battery: {batt['percent']:.0f}%{plug}", self.colors["text_dim"], (x, y))
        now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        surf = self.font_tiny.render(now, True, self.colors["text_dim"])
        self.screen.blit(surf, (self.width - surf.get_width() - L["card_margin"], y))
        if self.debug_mode:
            self._button(self.touch_areas["refresh"], "Refresh", self.colors["accent"])
            self._button(self.touch_areas["restart"], "Restart", self.colors["error"])

    def draw_network_card(self) -> int:
        L, C = self.layout, self.colors
        y0 = L["header_height"] + L["card_margin"]
        card_h = int(L["card_padding"] * 2 + self.font_medium.get_height() + self.font_small.get_height() * 3 + L["line_spacing_small"] * 0.6)
        rect = pygame.Rect(L["card_margin"], y0, self.width - 2 * L["card_margin"], card_h)
        pygame.draw.rect(self.screen, C["card"], rect, border_radius=10)
        x, y = rect.x + L["card_padding"], rect.y + L["card_padding"]
        qr_size = card_h - 2 * L["card_padding"]
        text_w = rect.width - 2 * L["card_padding"] - qr_size - L["card_padding"]

        self._text(self.font_medium, "Network", C["accent"], (x, y))
        btn_w = self.font_small.size("Change WiFi")[0] + L["card_padding"] * 2
        btn_h = self.font_small.get_height() + L["card_padding"]
        self.touch_areas["change_wifi"] = pygame.Rect(x + text_w - btn_w, y, btn_w, btn_h)
        self._button(self.touch_areas["change_wifi"], "Change WiFi", C["accent"])
        y += self.font_medium.get_height() + L["card_padding"] // 2

        d = self.data_collector.data
        connected = d.get("connection_status") == "Connected"
        self._text(self.font_small, self._fit(self.font_small, f"WiFi: {d.get('wifi_ssid')}", text_w), C["text"], (x, y))
        y += self.font_small.get_height()
        self._text(self.font_small, f"IP: {d.get('ip_address')}", C["success"] if connected else C["error"], (x, y))
        y += self.font_small.get_height()
        if self.config.web_auth:
            self._text(self.font_small, f"Access code: {self.config.ensure_token()}", C["text_dim"], (x, y))
        else:
            self._text(self.font_small, f"http://{d.get('ip_address')}:{self.config.web_port}", C["text_dim"], (x, y))

        if self.qrcode_surface:
            qr = pygame.transform.smoothscale(self.qrcode_surface, (qr_size, qr_size))
            self.screen.blit(qr, (rect.right - L["card_padding"] - qr_size, rect.y + L["card_padding"]))
        else:
            surf = self.font_tiny.render("No network", True, C["text_dim"])
            self.screen.blit(surf, surf.get_rect(center=(rect.right - L["card_padding"] - qr_size // 2, rect.centery)))
        return rect.bottom

    def draw_usb_card(self, y0: int, max_bottom: int) -> int:
        L, C = self.layout, self.colors
        devices = self.data_collector.data.get("usb_devices") or []
        line_h = self.font_small.get_height()
        content_h = line_h + max(1, len(devices)) * line_h + L["card_padding"] * 2
        rect = pygame.Rect(L["card_margin"], y0, self.width - 2 * L["card_margin"], min(content_h, max_bottom - y0))
        pygame.draw.rect(self.screen, C["card"], rect, border_radius=10)
        x, y = rect.x + L["card_padding"], rect.y + L["card_padding"]
        self._text(self.font_small, "Drives", C["accent"], (x, y))
        y += line_h
        if not devices:
            self._text(self.font_small, "No SD card or SSD detected", C["text_dim"], (x, y))
        for dev in devices:
            if y + line_h > rect.bottom - L["card_padding"] // 2:
                self._text(self.font_tiny, "…more", C["text_dim"], (x, y))
                break
            role = "SSD" if dev.get("role") == "backup" else "Card"
            name = self._fit(self.font_small, f"{role}: {dev['name']}", rect.width * 0.55)
            self._text(self.font_small, name, C["text"], (x, y))
            usage = f"{dev['used']:.1f} / {dev['total']:.1f} GB ({dev['percent']:.0f}%)"
            surf = self.font_small.render(usage, True, C["text_dim"])
            self.screen.blit(surf, (rect.right - L["card_padding"] - surf.get_width(), y))
            y += line_h
        return rect.bottom

    def draw_progress_card(self, y0: int, bottom: int):
        L, C = self.layout, self.colors
        st = self.copy_status
        rect = pygame.Rect(L["card_margin"], y0, self.width - 2 * L["card_margin"], max(bottom - y0, self.font_small.get_height() * 3))
        pygame.draw.rect(self.screen, C["card"], rect, border_radius=10)
        x, y = rect.x + L["card_padding"], rect.y + L["card_padding"]
        self._text(self.font_small, "Backup", C["accent"], (x, y))
        y += self.font_small.get_height()

        if not st.get("ssd_present"):
            surf = self.font_medium.render("Please insert the backup SSD", True, C["error"])
            self.screen.blit(surf, surf.get_rect(center=rect.center))
            return

        msg = self._current_notice() or st.get("status_message", "")
        color = C["error"] if ("ERROR" in msg or "failed" in msg.lower() or "abort" in msg.lower()) else C["text_dim"]
        self._text(self.font_tiny, self._fit(self.font_tiny, msg, rect.width - 2 * L["card_padding"]), color, (x, y))
        y += self.font_tiny.get_height() + L["card_padding"] // 2

        if st.get("is_copying") or st.get("total_files"):
            bar_w = rect.width - 2 * L["card_padding"]
            if st.get("is_copying"):
                bar_w -= int(self.width * 0.14) + L["card_padding"]
            bar_h = int(self.font_small.get_height() * 0.8)
            pct = float(st.get("progress_percent", 0.0))
            pygame.draw.rect(self.screen, C["progress_bg"], (x, y, bar_w, bar_h), border_radius=5)
            pygame.draw.rect(self.screen, C["progress_fill"], (x, y, int(bar_w * pct / 100), bar_h), border_radius=5)
            done = st.get("copied_files", 0) + st.get("skipped_files", 0) + st.get("error_files", 0)
            gb = st.get("bytes_done", 0) / 1e9
            label = f"{pct:.0f}%  {done}/{st.get('total_files', 0)} files  {gb:.1f} GB"
            if st.get("error_files"):
                label += f"  ⚠ {st['error_files']} errors"
            surf = self.font_tiny.render(label, True, C["text"])
            self.screen.blit(surf, surf.get_rect(center=(x + bar_w // 2, y + bar_h // 2)))
            y += bar_h + L["card_padding"] // 2
            if st.get("current_file") and st.get("is_copying"):
                self._text(self.font_tiny, self._fit(self.font_tiny, f"File: {st['current_file']}", bar_w), C["text_dim"], (x, y))
            elif st.get("errors"):
                self._text(self.font_tiny, self._fit(self.font_tiny, f"Last error: {st['errors'][-1]}", bar_w), C["error"], (x, y))

        if st.get("is_copying"):
            w, h = int(self.width * 0.14), int(self.height * 0.07)
            self.touch_areas["copy_stop"] = pygame.Rect(rect.right - w - L["card_padding"], rect.bottom - h - L["card_padding"], w, h)
            self._button(self.touch_areas["copy_stop"], "Stop", C["error"])
        else:
            self.touch_areas["copy_stop"] = pygame.Rect(0, 0, 0, 0)

    def draw_status_bar(self):
        L, C = self.layout, self.colors
        h = L["status_bar_height"]
        y0 = self.height - h
        pygame.draw.rect(self.screen, C["card"], pygame.Rect(0, y0, self.width, h))
        t = datetime.fromtimestamp(self.data_collector.data.get("last_update", time.time())).strftime("%H:%M:%S")
        self._text(self.font_tiny, f"Updated {t}", C["text_dim"], (L["card_margin"], y0 + (h - self.font_tiny.get_height()) // 2))
        st = self.copy_status
        color = C["progress_fill"] if st.get("is_copying") else (C["success"] if st.get("ssd_present") else C["error"])
        pygame.draw.circle(self.screen, color, (self.width - L["card_margin"] - int(h * 0.35), y0 + h // 2), int(h * 0.2))

    def draw_main_view(self):
        self.screen.fill(self.colors["bg"])
        self.draw_header()
        bottom = self.height - self.layout["status_bar_height"] - self.layout["card_margin"]
        y = self.draw_network_card() + self.layout["card_margin"]
        progress_h = int(self.height * 0.26)
        y = self.draw_usb_card(y, bottom - progress_h - self.layout["card_margin"]) + self.layout["card_margin"]
        self.draw_progress_card(y, bottom)
        self.draw_status_bar()

    # ----------------------------------------------------------- wifi views
    def draw_wifi_list_view(self):
        L, C = self.layout, self.colors
        self.screen.fill(C["bg"])
        self._button(self.touch_areas["back"], "Back", C["error"])
        title = self.font_medium.render("Select a WiFi network", True, C["accent"])
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, L["card_margin"]))
        rescan_w = int(self.width * 0.15)
        self.touch_areas["wifi_rescan"] = pygame.Rect(self.width - L["card_margin"] - rescan_w, L["card_margin"], rescan_w, int(self.height * 0.08))
        self._button(self.touch_areas["wifi_rescan"], "Rescan", C["accent"])

        self.touch_areas["wifi_items"] = []
        self.touch_areas["wifi_page_prev"] = self.touch_areas["wifi_page_next"] = None
        if self.wifi_scanning or not self.wifi_scan_result:
            msg = "Scanning…" if self.wifi_scanning else "No networks found"
            surf = self.font_medium.render(msg, True, C["text_dim"])
            self.screen.blit(surf, surf.get_rect(center=(self.width // 2, self.height // 2)))
            return

        footer_h = int(self.height * 0.12)
        list_y = L["header_height"]
        list_h = self.height - list_y - footer_h - L["card_margin"]
        item_h = self.font_small.get_height() + L["card_padding"] * 3
        spacing = L["card_margin"] // 2
        per_page = max(1, list_h // (item_h + spacing))
        total_pages = max(1, (len(self.wifi_scan_result) + per_page - 1) // per_page)
        self.wifi_list_page = min(self.wifi_list_page, total_pages - 1)
        start = self.wifi_list_page * per_page
        y = list_y
        for ssid in self.wifi_scan_result[start:start + per_page]:
            rect = pygame.Rect(L["card_margin"], y, self.width - 2 * L["card_margin"], item_h)
            pygame.draw.rect(self.screen, C["card"], rect, border_radius=6)
            label = self._fit(self.font_small, ssid, rect.width * 0.7)
            self._text(self.font_small, label, C["text"], (rect.x + L["card_padding"], rect.y + (item_h - self.font_small.get_height()) // 2))
            self.touch_areas["wifi_items"].append({"ssid": ssid, "rect": rect})
            y += item_h + spacing

        fy = self.height - footer_h
        bw, bh = int(self.width * 0.2), int(footer_h * 0.7)
        if self.wifi_list_page > 0:
            self.touch_areas["wifi_page_prev"] = pygame.Rect(L["card_margin"], fy + (footer_h - bh) // 2, bw, bh)
            self._button(self.touch_areas["wifi_page_prev"], "Prev", C["accent"])
        if self.wifi_list_page < total_pages - 1:
            self.touch_areas["wifi_page_next"] = pygame.Rect(self.width - L["card_margin"] - bw, fy + (footer_h - bh) // 2, bw, bh)
            self._button(self.touch_areas["wifi_page_next"], "Next", C["accent"])
        page = self.font_small.render(f"Page {self.wifi_list_page + 1} / {total_pages}", True, C["text_dim"])
        self.screen.blit(page, page.get_rect(center=(self.width // 2, fy + footer_h // 2)))

    def draw_password_input_view(self):
        L, C = self.layout, self.colors
        self.screen.fill(C["bg"])
        self._button(self.touch_areas["back"], "Back", C["error"])
        title = self.font_small.render(self._fit(self.font_small, f"Password for {self.selected_ssid}", self.width * 0.6), True, C["accent"])
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, L["card_margin"] + (self.touch_areas["back"].height - title.get_height()) // 2))

        # Input box with show/hide toggle
        box_y = self.touch_areas["back"].bottom + L["card_padding"]
        box_h = int(self.height * 0.1)
        toggle_w = int(self.width * 0.12)
        box = pygame.Rect(L["card_margin"], box_y, self.width - 2 * L["card_margin"] - toggle_w - L["card_padding"], box_h)
        pygame.draw.rect(self.screen, C["card"], box, border_radius=6)
        shown = self.password_input if self.password_visible else "•" * len(self.password_input)
        surf = self.font_mono.render(shown, True, C["text"])
        if surf.get_width() > box.width - 2 * L["card_padding"]:
            clip = pygame.Surface((box.width - 2 * L["card_padding"], surf.get_height()), pygame.SRCALPHA)
            clip.blit(surf, (clip.get_width() - surf.get_width(), 0))
            surf = clip
        self.screen.blit(surf, (box.x + L["card_padding"], box.centery - surf.get_height() // 2))
        self.touch_areas["password_toggle"] = pygame.Rect(box.right + L["card_padding"], box_y, toggle_w, box_h)
        self._button(self.touch_areas["password_toggle"], "Hide" if self.password_visible else "Show", C["key"], self.font_tiny)

        # Keyboard
        rows = KEY_ROWS[self.keyboard_layout]
        avail_h = self.height - (box.bottom + L["card_padding"]) - L["card_margin"]
        key_margin = max(2, int(self.width * 0.006))
        key_w = (self.width - 2 * L["card_margin"] - 9 * key_margin) // 10
        key_h = min(key_w, (avail_h - 5 * key_margin) // 5)
        font = self.font_small if key_h >= self.font_small.get_height() + 4 else self.font_tiny
        y = box.bottom + L["card_padding"]
        self.touch_areas["keys"] = []

        def add_key(rect, char, label=None, color=None):
            self.touch_areas["keys"].append({"char": char, "rect": rect})
            self._button(rect, label if label is not None else char, color or C["key"], font)

        for row in rows:
            x = (self.width - (len(row) * key_w + (len(row) - 1) * key_margin)) // 2
            if len(row) <= 7:  # last letter row: leave room for shift/backspace
                x = L["card_margin"] + int(1.5 * (key_w + key_margin))
            for ch in row:
                add_key(pygame.Rect(x, y, key_w, key_h), ch)
                x += key_w + key_margin
            y += key_h + key_margin

        # Row 4 extras (on the same line as the last letter row)
        last_y = y - key_h - key_margin
        wide = int(1.5 * key_w) + key_margin // 2
        shift_label = {"lower": "ABC", "upper": "abc", "symbols": "abc"}[self.keyboard_layout]
        add_key(pygame.Rect(L["card_margin"], last_y, wide, key_h), "shift", shift_label, C["accent"])
        add_key(pygame.Rect(self.width - L["card_margin"] - wide, last_y, wide, key_h), "backspace", "⌫", C["warning"])

        # Row 5: symbols, space, connect
        sym_w = int(1.5 * key_w) + key_margin // 2
        connect_w = int(2.5 * key_w) + key_margin
        add_key(pygame.Rect(L["card_margin"], y, sym_w, key_h), "symbols", "abc" if self.keyboard_layout == "symbols" else "#+=", C["accent"])
        space_x = L["card_margin"] + sym_w + key_margin
        space_w = self.width - L["card_margin"] - connect_w - key_margin - space_x
        add_key(pygame.Rect(space_x, y, space_w, key_h), " ", "space")
        self.touch_areas["password_connect"] = pygame.Rect(self.width - L["card_margin"] - connect_w, y, connect_w, key_h)
        label = "Connecting…" if self.wifi_busy else "Connect"
        self._button(self.touch_areas["password_connect"], label, C["success"] if not self.wifi_busy else C["key"], font)

    # ---------------------------------------------------------------- wifi ops
    def start_wifi_scan(self):
        if self.wifi_scanning:
            return
        self.wifi_scanning = True
        self.wifi_scan_result = []
        self.wifi_list_page = 0

        def scan():
            try:
                self.wifi_scan_result = self.data_collector.get_available_wifi_networks()
            finally:
                self.wifi_scanning = False

        threading.Thread(target=scan, name="wifi-scan", daemon=True).start()

    def connect_to_wifi(self):
        if self.wifi_busy:
            return
        ssid, password = self.selected_ssid, self.password_input
        self.wifi_busy = True
        self.notify(f"Connecting to {ssid}…", 60)

        def work():
            try:
                ok, message = self.wifi.connect(ssid, password)
                self.notify(message, 10 if ok else 15)
                if ok:
                    self.current_view = "main"
                    self.password_input = ""
                    self.data_collector.update_data()
                else:
                    self.current_view = "password_input"
            finally:
                self.wifi_busy = False

        self.current_view = "main"
        threading.Thread(target=work, name="wifi-connect", daemon=True).start()

    # -------------------------------------------------------------- touch
    def handle_touch(self, pos):
        T = self.touch_areas
        if self.current_view == "main":
            if self.debug_mode and T["refresh"].collidepoint(pos):
                threading.Thread(target=self.data_collector.update_data, daemon=True).start()
            elif self.debug_mode and T["restart"].collidepoint(pos):
                log.warning("Restart requested from debug UI")
                subprocess.run(["sudo", "-n", "systemctl", "reboot"], check=False)
            elif T["change_wifi"].collidepoint(pos):
                self.current_view = "wifi_list"
                self.start_wifi_scan()
            elif self.copy_status.get("is_copying") and T["copy_stop"].collidepoint(pos):
                self.sd_copy_manager.stop_copy()

        elif self.current_view == "wifi_list":
            if T["back"].collidepoint(pos):
                self.current_view = "main"
            elif T["wifi_rescan"] and T["wifi_rescan"].collidepoint(pos):
                self.start_wifi_scan()
            elif T["wifi_page_prev"] and T["wifi_page_prev"].collidepoint(pos):
                self.wifi_list_page = max(0, self.wifi_list_page - 1)
            elif T["wifi_page_next"] and T["wifi_page_next"].collidepoint(pos):
                self.wifi_list_page += 1
            else:
                for item in T["wifi_items"]:
                    if item["rect"].collidepoint(pos):
                        self.selected_ssid = item["ssid"]
                        self.password_input = ""
                        self.password_visible = False
                        self.keyboard_layout = "lower"
                        self.current_view = "password_input"
                        break

        elif self.current_view == "password_input":
            if T["back"].collidepoint(pos):
                self.current_view = "wifi_list"
            elif T["password_toggle"] and T["password_toggle"].collidepoint(pos):
                self.password_visible = not self.password_visible
            elif T["password_connect"] and T["password_connect"].collidepoint(pos):
                self.connect_to_wifi()
            else:
                for key in T["keys"]:
                    if key["rect"].collidepoint(pos):
                        self.press_key(key["char"])
                        break

    def press_key(self, char: str):
        if char == "backspace":
            self.password_input = self.password_input[:-1]
        elif char == "shift":
            self.keyboard_layout = "upper" if self.keyboard_layout == "lower" else "lower"
        elif char == "symbols":
            self.keyboard_layout = "lower" if self.keyboard_layout == "symbols" else "symbols"
        elif len(self.password_input) < 63:
            self.password_input += char
            if self.keyboard_layout == "upper":  # single-shot shift
                self.keyboard_layout = "lower"

    # ---------------------------------------------------------------- loop
    def draw_frame(self):
        if self.current_view == "wifi_list":
            self.draw_wifi_list_view()
        elif self.current_view == "password_input":
            self.draw_password_input_view()
        else:
            self.draw_main_view()

    def run(self):
        clock = pygame.time.Clock()
        log.info("UI started (display: %s, %dx%d)", getattr(self.display_manager, "display_method", "?"), self.width, self.height)
        try:
            while self.running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE and self.debug_mode:
                            self.running = False
                        elif event.key == pygame.K_F5:
                            threading.Thread(target=self.data_collector.update_data, daemon=True).start()
                        elif self.current_view == "password_input":
                            self._keyboard_event(event)
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        self.handle_touch(event.pos)
                    elif event.type == pygame.FINGERDOWN:
                        self.handle_touch((int(event.x * self.width), int(event.y * self.height)))
                self.draw_frame()
                pygame.display.flip()
                clock.tick(15)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _keyboard_event(self, event):
        """Physical keyboard support for the password screen (handy with a USB keyboard)."""
        if event.key == pygame.K_BACKSPACE:
            self.press_key("backspace")
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.connect_to_wifi()
        elif event.unicode and event.unicode.isprintable():
            self.press_key(event.unicode)

    def shutdown(self):
        if self.stop_event.is_set():
            return
        self.running = False
        self.stop_event.set()
        if self.sd_copy_manager.is_copying:
            self.sd_copy_manager.stop_copy()
            if self.sd_copy_manager._copy_thread:
                self.sd_copy_manager._copy_thread.join(timeout=10)
        pygame.quit()
