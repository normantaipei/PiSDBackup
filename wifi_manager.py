"""Wi-Fi scanning and connection.

Uses NetworkManager (``nmcli``), which is the default on Raspberry Pi OS
Bookworm and later.  Falls back to ``wpa_cli`` on older images.  Never
restarts the supplicant and never shells out through ``shell=True``.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


class WifiManager:
    def __init__(self, interface: str = "wlan0"):
        self.interface = interface
        self.backend = "nmcli" if shutil.which("nmcli") else ("wpa_cli" if shutil.which("wpa_cli") else None)
        log.info("Wi-Fi backend: %s", self.backend or "none")

    # ------------------------------------------------------------- queries
    def current_ssid(self) -> Optional[str]:
        try:
            if self.backend == "nmcli":
                out = self._run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list", "ifname", self.interface], timeout=8)
                for line in out.splitlines():
                    active, _, ssid = line.partition(":")
                    if active == "yes" and ssid:
                        return ssid.replace("\\:", ":")
                return None
            if shutil.which("iwgetid"):
                out = self._run(["iwgetid", "-r", self.interface], timeout=5)
                return out.strip() or None
            if shutil.which("iw"):
                out = self._run(["iw", "dev", self.interface, "link"], timeout=5)
                m = re.search(r"^\s*SSID:\s*(.+)$", out, re.M)
                return m.group(1).strip() if m else None
        except (subprocess.SubprocessError, OSError) as e:
            log.debug("current_ssid failed: %s", e)
        return None

    def scan(self) -> List[str]:
        """Returns unique SSIDs sorted by signal strength (strongest first)."""
        try:
            if self.backend == "nmcli":
                out = self._run(["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi", "list", "ifname", self.interface, "--rescan", "yes"], timeout=20)
                seen = {}
                for line in out.splitlines():
                    ssid, _, signal = line.rpartition(":")
                    ssid = ssid.replace("\\:", ":")
                    if ssid and ssid != "--":
                        try:
                            seen[ssid] = max(seen.get(ssid, 0), int(signal))
                        except ValueError:
                            seen.setdefault(ssid, 0)
                return [s for s, _ in sorted(seen.items(), key=lambda kv: -kv[1])]
            if self.backend == "wpa_cli":
                self._run(["sudo", "-n", "wpa_cli", "-i", self.interface, "scan"], timeout=10)
                import time
                time.sleep(3)
                out = self._run(["sudo", "-n", "wpa_cli", "-i", self.interface, "scan_results"], timeout=10)
                rows = []
                for line in out.splitlines()[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 5 and parts[4]:
                        try:
                            rows.append((parts[4], int(parts[2])))
                        except ValueError:
                            rows.append((parts[4], -100))
                best = {}
                for ssid, sig in rows:
                    best[ssid] = max(best.get(ssid, -200), sig)
                return [s for s, _ in sorted(best.items(), key=lambda kv: -kv[1])]
        except (subprocess.SubprocessError, OSError) as e:
            log.error("Wi-Fi scan failed: %s", e)
        return []

    # ------------------------------------------------------------- connect
    def connect(self, ssid: str, password: str) -> Tuple[bool, str]:
        if not ssid:
            return False, "No network selected."
        if password and not 8 <= len(password) <= 63:
            return False, "WPA passwords must be 8-63 characters."
        try:
            if self.backend == "nmcli":
                return self._connect_nmcli(ssid, password)
            if self.backend == "wpa_cli":
                return self._connect_wpa_cli(ssid, password)
            return False, "No Wi-Fi tool available (install NetworkManager)."
        except subprocess.TimeoutExpired:
            return False, "Timed out while connecting."
        except (subprocess.SubprocessError, OSError) as e:
            log.error("Wi-Fi connect failed: %s", e)
            return False, "Connection failed."

    def _connect_nmcli(self, ssid: str, password: str) -> Tuple[bool, str]:
        # Remove a stale profile with the same name so a changed password takes effect.
        subprocess.run(["nmcli", "-t", "connection", "delete", "id", ssid], capture_output=True, text=True, timeout=10)
        cmd = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", self.interface]
        if password:
            cmd += ["password", password]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return True, f"Connected to {ssid}."
        err = (proc.stderr or proc.stdout).strip().splitlines()
        msg = err[-1] if err else "unknown error"
        if "Secrets were required" in msg or "802-11-wireless-security" in msg:
            msg = "Wrong password."
        log.warning("nmcli connect failed: %s", msg)
        return False, msg[:60]

    def _connect_wpa_cli(self, ssid: str, password: str) -> Tuple[bool, str]:
        def wpa(*args):
            return self._run(["sudo", "-n", "wpa_cli", "-i", self.interface, *args], timeout=15).strip()

        net_id = wpa("add_network")
        if not net_id.isdigit():
            return False, f"add_network failed: {net_id[:40]}"
        quoted_ssid = '"' + ssid.replace('\\', '\\\\').replace('"', '\\"') + '"'
        if wpa("set_network", net_id, "ssid", quoted_ssid) != "OK":
            wpa("remove_network", net_id)
            return False, "Could not set SSID."
        if password:
            quoted_psk = '"' + password.replace('\\', '\\\\').replace('"', '\\"') + '"'
            ok = wpa("set_network", net_id, "psk", quoted_psk) == "OK"
        else:
            ok = wpa("set_network", net_id, "key_mgmt", "NONE") == "OK"
        if not ok:
            wpa("remove_network", net_id)
            return False, "Could not set password."
        wpa("enable_network", net_id)
        wpa("select_network", net_id)
        wpa("save_config")
        import time
        for _ in range(20):
            time.sleep(1.5)
            status = wpa("status")
            if "wpa_state=COMPLETED" in status:
                return True, f"Connected to {ssid}."
        return False, "Could not associate (wrong password?)."

    @staticmethod
    def _run(cmd: List[str], timeout: float) -> str:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout
