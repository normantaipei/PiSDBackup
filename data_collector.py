import socket
import re
import psutil
import time
import os
import subprocess
from smbus2 import SMBus

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
            # Primary: psutil (works on systems with ACPI / standard battery support)
            battery = psutil.sensors_battery()
            if battery:
                return {
                    'percent': battery.percent,
                    'power_plugged': battery.power_plugged,
                    'secsleft': battery.secsleft,
                }

            # Fallback: try reading from sysfs (/sys/class/power_supply)
            ps_path = '/sys/class/power_supply'
            if os.path.isdir(ps_path):
                for name in os.listdir(ps_path):
                    p = os.path.join(ps_path, name)
                    cap_file = os.path.join(p, 'capacity')
                    status_file = os.path.join(p, 'status')
                    if os.path.isfile(cap_file):
                        try:
                            with open(cap_file, 'r') as f:
                                cap = f.read().strip()
                            percent = int(cap)
                        except:
                            continue

                        power_plugged = None
                        if os.path.isfile(status_file):
                            try:
                                with open(status_file, 'r') as f:
                                    st = f.read().strip().lower()
                                power_plugged = (st in ('charging', 'full'))
                            except:
                                power_plugged = None

                        return {
                            'percent': percent,
                            'power_plugged': power_plugged,
                            'secsleft': None,
                        }

            # Fallback 2: attempt to read common I2C fuel gauge (MAX1704x) at 0x36
            try:
                with SMBus(1) as bus:
                    addr = 0x36
                    # Read SOC register (0x04) - SMBus word needs byte-swap
                    raw = bus.read_word_data(addr, 0x04)
                    swapped = ((raw & 0xFF) << 8) | (raw >> 8)
                    percent = (swapped >> 8) & 0xFF
                    frac = (swapped & 0xFF) / 256.0
                    percent_float = percent + frac
                    return {
                        'percent': float(percent_float),
                        'power_plugged': None,
                        'secsleft': None,
                    }
            except Exception:
                pass

            return {}
        except Exception:
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

    def get_available_wifi_networks(self):
        """Scans for and returns a list of available WiFi SSIDs."""
        networks = []
        try:
            # Use iwlist to scan for networks. Requires the 'wireless-tools' package.
            # Ensure the interface 'wlan0' is correct for your Raspberry Pi.
            scan_output = subprocess.check_output(
                ['sudo', 'iwlist', 'wlan0', 'scan'],
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # Parse the output to find SSIDs
            # The regex looks for lines like 'ESSID:"MyNetwork"'
            essid_matches = re.findall(r'ESSID:"([^"]+)"', scan_output)
            
            # Return a list of unique, non-empty SSIDs
            if essid_matches:
                networks = sorted(list(set([name for name in essid_matches if name])))
        except subprocess.CalledProcessError as e:
            print(f"Error scanning for WiFi networks: {e.output}")
        except FileNotFoundError:
            print("Error: 'iwlist' command not found. Is 'wireless-tools' installed?")
        return networks
