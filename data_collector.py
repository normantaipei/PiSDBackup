import socket
import re
import psutil
import time
import os
import subprocess

class DataCollector:
    """Class responsible for collecting various system information"""

    def __init__(self):
        self.data = {
            'ip_address': 'Loading...',
            'wifi_ssid': 'Loading...',
            'connection_status': 'Checking...',
            'usb_devices': [],
            'system_info': {},
            'battery_info': {}, # For battery info
            'last_update': time.time()
        }

    def get_local_ip(self):
        """Gets local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "IP Unavailable"

    def get_wifi_ssid(self):
        """Gets WiFi SSID"""
        try:
            result = subprocess.run(['iwconfig'], capture_output=True, text=True, timeout=5)
            match = re.search(r'ESSID:"([^"]*)"', result.stdout)
            if match:
                ssid = match.group(1)
                return ssid if ssid else "WiFi Not Connected"
            return "WiFi Not Connected"
        except:
            return "SSID Unavailable"

    def get_usb_devices(self):
        """Gets USB devices"""
        try:
            devices = []
            for partition in psutil.disk_partitions():
                if ('/media' in partition.mountpoint or
                    '/mnt' in partition.mountpoint or
                    partition.fstype in ['vfat', 'exfat', 'ntfs']):

                    try:
                        usage = psutil.disk_usage(partition.mountpoint)
                        devices.append({
                            'name': os.path.basename(partition.device),
                            'mount': partition.mountpoint,
                            'total': usage.total / (1024**3),
                            'used': usage.used / (1024**3),
                            'free': usage.free / (1024**3),
                            'percent': (usage.used / usage.total) * 100
                        })
                    except:
                        continue
            return devices
        except:
            return []

    def get_system_info(self):
        """Gets system information"""
        try:
            # Only keep temperature
            temp = "N/A"
            try:
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp = f"{int(f.read()) / 1000:.1f}°C"
            except:
                pass

            return {
                'temp': temp,
            }
        except:
            return {}

    def get_battery_info(self):
        """Gets battery information"""
        try:
            # Get battery info only if available
            # Typically works on Linux systems with ACPI available
            # May not be available on Raspberry Pi without dedicated hardware
            battery = psutil.sensors_battery()
            if battery:
                return {
                    'percent': battery.percent,
                    'power_plugged': battery.power_plugged,
                    'secsleft': battery.secsleft,
                }
            return {}
        except Exception as e:
            # print(f"Battery info error: {e}")
            return {}

    def update_data(self):
        """Updates all data"""
        self.data['ip_address'] = self.get_local_ip()
        self.data['wifi_ssid'] = self.get_wifi_ssid()
        self.data['usb_devices'] = self.get_usb_devices()
        self.data['system_info'] = self.get_system_info()
        self.data['battery_info'] = self.get_battery_info() # Update battery info

        # Update connection status
        if (self.data['ip_address'] != "IP Unavailable" and
            self.data['wifi_ssid'] not in ["WiFi Not Connected", "SSID Unavailable"]):
            self.data['connection_status'] = "Connected"
        else:
            self.data['connection_status'] = "Disconnected"

        self.data['last_update'] = time.time()

