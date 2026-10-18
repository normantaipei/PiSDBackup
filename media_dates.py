"""Determine the capture date of a media file.

Order of preference: EXIF ``DateTimeOriginal`` (images), QuickTime/MP4
creation time (videos), then the filesystem modification time.
"""

from __future__ import annotations

import logging
import os
import re
import struct
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

_EXIF_DATETIME_ORIGINAL = 0x9003
_EXIF_DATETIME_DIGITIZED = 0x9004
_EXIF_DATETIME = 0x0132
_EXIF_IFD_POINTER = 0x8769

_EXIF_IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff", ".dng", ".nef", ".cr2", ".arw", ".pef", ".orf", ".rw2", ".srw", ".heic", ".heif", ".png"}
_MP4_EXTS = {".mp4", ".mov", ".m4v", ".3gp"}
_EXIF_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")


def _parse_exif_datetime(value) -> Optional[datetime]:
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    if not isinstance(value, str):
        return None
    m = _EXIF_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def _exif_date_pillow(path: str) -> Optional[datetime]:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            ifd = exif.get_ifd(_EXIF_IFD_POINTER) if hasattr(exif, "get_ifd") else {}
            for source, tag in ((ifd, _EXIF_DATETIME_ORIGINAL), (ifd, _EXIF_DATETIME_DIGITIZED), (exif, _EXIF_DATETIME)):
                dt = _parse_exif_datetime(source.get(tag)) if source else None
                if dt:
                    return dt
    except Exception as e:  # Pillow raises many different errors for odd files
        log.debug("EXIF read failed for %s: %s", path, e)
    return None


def _mp4_creation_time(path: str) -> Optional[datetime]:
    """Reads the 'mvhd' creation time from an MP4/MOV container (first ~2 MiB)."""
    try:
        with open(path, "rb") as f:
            data = f.read(2 * 1024 * 1024)
    except OSError:
        return None
    idx = data.find(b"mvhd")
    if idx < 0 or idx + 8 > len(data):
        return None
    version = data[idx + 4]
    try:
        if version == 1:
            secs = struct.unpack(">Q", data[idx + 8: idx + 16])[0]
        else:
            secs = struct.unpack(">I", data[idx + 8: idx + 12])[0]
    except struct.error:
        return None
    if secs == 0:
        return None
    # QuickTime epoch is 1904-01-01 UTC.  Cameras usually write local time as if UTC.
    epoch_diff = 2082844800
    try:
        return datetime.fromtimestamp(secs - epoch_diff, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def get_capture_datetime(path: str) -> datetime:
    ext = os.path.splitext(path)[1].lower()
    dt = None
    if ext in _EXIF_IMAGE_EXTS:
        dt = _exif_date_pillow(path)
    elif ext in _MP4_EXTS:
        dt = _mp4_creation_time(path)
    if dt is None:
        dt = datetime.fromtimestamp(os.stat(path).st_mtime)
    return dt


def get_capture_date_folder(path: str) -> str:
    """Returns 'YYYY-MM-DD' for the file's capture date."""
    return get_capture_datetime(path).strftime("%Y-%m-%d")
