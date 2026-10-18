"""Headless rendering/touch test of the pygame UI using SDL's dummy driver."""
import os
import threading

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
import pytest

from config import Config
from devices import BlockDevice
from sd_copy_manager import SDCopyManager


class FakeDisplay:
    display_method = "dummy"


class FakeWifi:
    backend = "fake"
    def __init__(self):
        self.connected = []
    def current_ssid(self):
        return "HomeNet"
    def scan(self):
        return ["HomeNet", "Studio-5G", "Café WiFi"]
    def connect(self, ssid, password):
        self.connected.append((ssid, password))
        return True, f"Connected to {ssid}."


@pytest.fixture
def ui(tmp_path, monkeypatch):
    from data_collector import DataCollector
    import rpi_interface

    backup = tmp_path / "backup"; backup.mkdir()
    cfg = Config(backup_dir=str(backup), source_mount_prefixes=[str(tmp_path / "media")], fullscreen=False,
                 web_token="abc123", poll_interval=0.1)
    devices = [BlockDevice("ssd", "/dev/sda1", str(backup), "ext4", "BACKUP")]
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    fake_wifi = FakeWifi()
    monkeypatch.setattr(rpi_interface, "WifiManager", lambda iface: fake_wifi)
    monkeypatch.setattr(pygame.display, "Info", lambda: type("I", (), {"current_w": 800, "current_h": 480})())
    dc = DataCollector(cfg, fake_wifi)
    app = rpi_interface.RPiProductInterface(FakeDisplay(), cfg, sd_copy_manager=mgr, data_collector=dc)
    app.wifi = fake_wifi
    yield app
    app.shutdown()


def test_all_views_render(ui):
    ui.data_collector.update_data()
    ui.copy_status = {**ui.copy_status, "ssd_present": True, "is_copying": True, "total_files": 10, "copied_files": 3,
                      "progress_percent": 30.0, "current_file": "DSC.JPG", "errors": ["X.JPG: boom"], "error_files": 1}
    for view in ("main", "wifi_list", "password_input"):
        ui.current_view = view
        ui.draw_frame()
    assert ui.touch_areas["copy_stop"].width > 0


def test_password_keyboard_supports_upper_and_symbols(ui):
    ui.current_view = "wifi_list"
    ui.wifi_scan_result = ui.wifi.scan()
    ui.draw_frame()
    item = ui.touch_areas["wifi_items"][1]
    ui.handle_touch(item["rect"].center)
    assert ui.current_view == "password_input" and ui.selected_ssid == "Studio-5G"

    def tap(char):
        ui.draw_frame()
        key = next(k for k in ui.touch_areas["keys"] if k["char"] == char)
        ui.handle_touch(key["rect"].center)

    for c in "pass": tap(c)
    tap("shift"); tap("W")          # single-shot shift
    tap("symbols"); tap("!"); tap("symbols")
    tap("1"); tap(" "); tap("x"); tap("backspace")
    assert ui.password_input == "passW!1 "
    ui.draw_frame()
    assert ui.password_visible is False
    ui.handle_touch(ui.touch_areas["password_toggle"].center)
    assert ui.password_visible is True

    ui.draw_frame()
    ui.handle_touch(ui.touch_areas["password_connect"].center)
    for _ in range(100):
        if ui.wifi.connected: break
        import time; time.sleep(0.02)
    assert ui.wifi.connected == [("Studio-5G", "passW!1 ")]
    assert ui.current_view == "main"
    assert "Connected" in ui._current_notice()


def test_stop_button_calls_manager(ui, monkeypatch):
    called = []
    monkeypatch.setattr(ui.sd_copy_manager, "stop_copy", lambda: called.append(True))
    ui.copy_status = {**ui.copy_status, "ssd_present": True, "is_copying": True, "total_files": 1}
    ui.current_view = "main"
    ui.draw_frame()
    ui.handle_touch(ui.touch_areas["copy_stop"].center)
    assert called == [True]
