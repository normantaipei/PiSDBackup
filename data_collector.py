"""Collects system information shown on the touch screen."""

from __future__ import annotations

import logging
import os
import socket
import time
from typing import Dict, List, Optional

import psutil

import devices as devmod
from config import Config
from wifi_manager import WifiManager

log = logging.getLogger(__name__)

try:  # optional: only needed for the I2C fuel-gauge fallback
    from smbus2 import SMBus
except ImportError:  # pragma: no cover
    SMBus = None


class DataCollector:
    def __init__(self, config: Optional[Config] = None, wifi: Optional[WifiManager] = None):
        self.config = config or Config()
        self.wifi = wifi or WifiManager(self.config.wifi_interface)
        self.data: Dict = {
            "ip_address": "Loading...",
            "wifi_ssid": "Loading...",
            "connection_status": "Checking...",
            "usb_devices": [],
            "system_info": {},
            "battery_info": {},
            "last_update": time.time(),
        }

    # ----------------------------------------------------------------- network
    def get_local_ip(self) -> Optional[str]:
        # Prefer the address of the configured Wi-Fi interface; fall back to the default route.
        try:
            for addr in psutil.net_if_addrs().get(self.config.wifi_interface, []):
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    return addr.address
        except Exception as e:
            log.debug("net_if_addrs failed: %s", e)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(1)
                s.connect(("10.255.255.255", 1))  # no packets are sent for UDP connect
                return s.getsockname()[0]
        except OSError:
            return None

    # ----------------------------------------------------------------- storage
    def get_usb_devices(self) -> List[Dict]:
        result: List[Dict] = []
        try:
            mounted = devmod.list_mounted_devices()
        except Exception as e:
            log.debug("Device listing failed: %s", e)
            return result

        backup = devmod.find_backup_device(self.config.backup_dir, mounted)
        if backup:
            usage = devmod.disk_usage_gib(backup.mountpoint)
            if usage:
                result.append({"name": f"SSD {backup.display_name}", "mount": backup.mountpoint, "role": "backup", **usage})

        for dev in devmod.find_source_devices(self.config.backup_dir, self.config.source_mount_prefixes, mounted):
            usage = devmod.disk_usage_gib(dev.mountpoint)
            if usage:
                result.append({"name": dev.display_name, "mount": dev.mountpoint, "role": "source", **usage})
        return result

    # ------------------------------------------------------------------ system
    def get_system_info(self) -> Dict:
        temp = "N/A"
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = f"{int(f.read()) / 1000:.1f}°C"
        except (OSError, ValueError):
            pass
        return {"temp": temp}

    def get_battery_info(self) -> Dict:
        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery:
            return {"percent": battery.percent, "power_plugged": battery.power_plugged, "secsleft": battery.secsleft}

        ps_path = "/sys/class/power_supply"
        try:
            for name in sorted(os.listdir(ps_path)):
                cap_file = os.path.join(ps_path, name, "capacity")
                if not os.path.isfile(cap_file):
                    continue
                with open(cap_file) as f:
                    percent = int(f.read().strip())
                plugged = None
                status_file = os.path.join(ps_path, name, "status")
                if os.path.isfile(status_file):
                    with open(status_file) as f:
                        plugged = f.read().strip().lower() in ("charging", "full")
                return {"percent": percent, "power_plugged": plugged, "secsleft": None}
        except (OSError, ValueError):
            pass

        if SMBus is not None:
            try:
                with SMBus(1) as bus:  # MAX1704x fuel gauge, SOC register 0x04
                    raw = bus.read_word_data(0x36, 0x04)
                    swapped = ((raw & 0xFF) << 8) | (raw >> 8)
                    return {"percent": (swapped >> 8) + (swapped & 0xFF) / 256.0, "power_plugged": None, "secsleft": None}
            except Exception:
                pass
        return {}

    # ------------------------------------------------------------------ update
    def update_data(self) -> None:
        ip = self.get_local_ip()
        ssid = self.wifi.current_ssid()
        self.data["ip_address"] = ip or "IP Unavailable"
        self.data["wifi_ssid"] = ssid or "Not connected"
        self.data["usb_devices"] = self.get_usb_devices()
        self.data["system_info"] = self.get_system_info()
        self.data["battery_info"] = self.get_battery_info()
        self.data["connection_status"] = "Connected" if ip else "Disconnected"
        self.data["last_update"] = time.time()

    def get_available_wifi_networks(self) -> List[str]:
        return self.wifi.scan()
