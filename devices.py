"""Block-device discovery for removable sources and the backup drive.

Devices are identified by a stable *device id* (filesystem UUID when available,
otherwise the device node) so that swapping two cards that mount to the same
path (e.g. both labelled ``NO NAME``) is detected correctly.  Discovery never
writes to the candidate devices.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import psutil

log = logging.getLogger(__name__)

SYSTEM_MOUNT_PREFIXES = ("/boot", "/etc", "/dev", "/proc", "/sys", "/run", "/tmp", "/var", "/usr", "/snap")


@dataclass(frozen=True)
class BlockDevice:
    device_id: str      # UUID or device node, stable across mount points
    device: str         # /dev/sda1
    mountpoint: str
    fstype: str
    label: str = ""
    removable: bool = False
    read_only: bool = False

    @property
    def display_name(self) -> str:
        return self.label or os.path.basename(self.device) or self.mountpoint


def _lsblk_mounted() -> Optional[List[BlockDevice]]:
    """Returns mounted filesystems via lsblk, or None if lsblk is unavailable."""
    if not shutil.which("lsblk"):
        return None
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-p", "-o", "NAME,MOUNTPOINT,UUID,FSTYPE,LABEL,RM,RO,TYPE"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        log.debug("lsblk failed: %s", e)
        return None

    devices: List[BlockDevice] = []

    def walk(nodes: Iterable[dict], parent_rm: bool = False):
        for node in nodes:
            rm = bool(node.get("rm")) or parent_rm
            mountpoints = node.get("mountpoints") or ([node.get("mountpoint")] if node.get("mountpoint") else [])
            for mp in mountpoints:
                if not mp or mp.startswith("[SWAP]"):
                    continue
                devices.append(BlockDevice(
                    device_id=node.get("uuid") or node.get("name") or "",
                    device=node.get("name") or "",
                    mountpoint=mp,
                    fstype=node.get("fstype") or "",
                    label=node.get("label") or "",
                    removable=rm,
                    read_only=bool(node.get("ro")),
                ))
            walk(node.get("children") or [], rm)

    walk(data.get("blockdevices", []))
    return devices


def _psutil_mounted() -> List[BlockDevice]:
    devices = []
    for part in psutil.disk_partitions(all=False):
        devices.append(BlockDevice(
            device_id=part.device,
            device=part.device,
            mountpoint=part.mountpoint,
            fstype=part.fstype,
            read_only="ro" in (part.opts or "").split(","),
        ))
    return devices


def list_mounted_devices() -> List[BlockDevice]:
    devices = _lsblk_mounted()
    if devices is None:
        devices = _psutil_mounted()
    return devices


def _is_system_mount(mountpoint: str) -> bool:
    if mountpoint == "/":
        return True
    return any(mountpoint == p or mountpoint.startswith(p + os.sep) for p in SYSTEM_MOUNT_PREFIXES)


def find_backup_device(backup_dir: str, devices: Optional[List[BlockDevice]] = None) -> Optional[BlockDevice]:
    backup_dir = os.path.normpath(backup_dir)
    for dev in devices if devices is not None else list_mounted_devices():
        if os.path.normpath(dev.mountpoint) == backup_dir:
            return dev
    return None


def find_source_devices(backup_dir: str, source_prefixes: Iterable[str],
                        devices: Optional[List[BlockDevice]] = None) -> List[BlockDevice]:
    """Returns mounted, readable, non-system filesystems that could be backup sources.

    The backup drive itself (and any other partition of the same physical disk)
    is excluded.  No write test is performed: a write-protected card is a valid
    source.
    """
    devices = devices if devices is not None else list_mounted_devices()
    backup_dir = os.path.normpath(backup_dir)
    backup_dev = find_backup_device(backup_dir, devices)
    backup_disk = _parent_disk(backup_dev.device) if backup_dev else None
    prefixes = [os.path.normpath(p) for p in source_prefixes]

    sources: List[BlockDevice] = []
    for dev in devices:
        mp = os.path.normpath(dev.mountpoint)
        if mp == backup_dir or mp.startswith(backup_dir + os.sep):
            continue
        if prefixes:
            # Explicit whitelist of automount locations wins over the generic system-mount filter.
            if not any(mp == p or mp.startswith(p + os.sep) for p in prefixes):
                continue
        elif _is_system_mount(mp):
            continue
        if "mmcblk0" in dev.device:          # the Pi's own boot card
            continue
        if backup_disk and _parent_disk(dev.device) == backup_disk:
            continue
        if dev.fstype in ("squashfs", "tmpfs", "devtmpfs", "overlay", "fuse.gvfsd-fuse", "nfs", "cifs", "fuse.sshfs"):
            continue
        if os.path.isdir(mp) and not os.access(mp, os.R_OK | os.X_OK):
            log.debug("Skipping unreadable mount %s", mp)
            continue
        sources.append(dev)
    return sources


def _parent_disk(device: str) -> str:
    """'/dev/sda1' -> '/dev/sda', '/dev/nvme0n1p1' -> '/dev/nvme0n1', '/dev/mmcblk1p1' -> '/dev/mmcblk1'."""
    base = os.path.basename(device)
    if base.startswith(("nvme", "mmcblk")) and "p" in base:
        base = base.rsplit("p", 1)[0]
    else:
        base = base.rstrip("0123456789")
    return os.path.join(os.path.dirname(device), base)


def disk_usage_gib(mountpoint: str) -> Optional[Dict[str, float]]:
    try:
        usage = shutil.disk_usage(mountpoint)
    except OSError:
        return None
    gib = 1024 ** 3
    return {
        "total": usage.total / gib,
        "used": usage.used / gib,
        "free": usage.free / gib,
        "percent": (usage.used / usage.total * 100) if usage.total else 0.0,
    }
