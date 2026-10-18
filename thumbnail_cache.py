"""On-disk thumbnail / preview cache for the web browser.

Cache layout mirrors the backup tree so that pruning and batch generation are
trivial::

    <backup>/.pisdbackup/cache/thumbs/2024-05-01/DSC001.JPG.jpg
    <backup>/.pisdbackup/cache/previews/2024-05-01/DSC001.JPG.jpg

A cached file is valid when it is at least as new as its source.  At most
``max_concurrent`` images are decoded at the same time (Pillow decoding a 24 MP
JPEG costs tens of MB and a CPU core; six waitress threads doing it at once is
what made the Pi fall over).  ``warm()`` generates missing thumbnails in the
background after a backup, pausing while a copy is running, so the first page
load does not trigger thousands of decodes.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from config import Config

log = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".jpe", ".png")


class ThumbnailCache:
    def __init__(self, cfg: Config, max_concurrent: int = 2):
        self.cfg = cfg
        self.base = Path(cfg.backup_dir)
        self.root = cfg.state_dir / "cache"
        self._decode_slots = threading.BoundedSemaphore(max_concurrent)
        self._warm_lock = threading.Lock()
        self._warm_thread: Optional[threading.Thread] = None
        self._warm_cancel = threading.Event()
        self.last_warm_stats: dict = {}

    # ----------------------------------------------------------------- paths
    def _size_for(self, kind: str) -> int:
        return self.cfg.thumbnail_size if kind == "thumbs" else self.cfg.preview_size

    def cache_path(self, full: Path, kind: str) -> Path:
        rel = full.resolve().relative_to(self.base.resolve())
        return self.root / kind / rel.parent / (rel.name + ".jpg")

    def _is_valid(self, cached: Path, source_stat: os.stat_result) -> bool:
        try:
            cst = cached.stat()
        except OSError:
            return False
        return cst.st_size > 0 and cst.st_mtime >= source_stat.st_mtime

    # ------------------------------------------------------------------- get
    def get(self, full: Path, kind: str):
        """Returns a Path to a cached JPEG, a BytesIO when the drive is not writable, or None."""
        try:
            st = full.stat()
        except OSError:
            return None
        cached = self.cache_path(full, kind)
        if self._is_valid(cached, st):
            return cached
        with self._decode_slots:
            if self._is_valid(cached, st):  # another thread finished it meanwhile
                return cached
            return self._render(full, cached, self._size_for(kind))

    def _render(self, full: Path, cached: Path, max_px: int):
        from io import BytesIO
        try:
            from PIL import Image, ImageOps
        except ImportError:
            log.error("Pillow is required for thumbnails")
            return None
        try:
            with Image.open(full) as img:
                img.draft("RGB", (max_px, max_px))      # decode JPEGs at reduced size
                img = ImageOps.exif_transpose(img)
                img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                try:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_name(f".{cached.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                    img.save(tmp, "JPEG", quality=82, optimize=True)
                    os.replace(tmp, cached)
                    return cached
                except OSError as e:               # read-only or full drive: serve from memory
                    log.debug("Cannot write cache for %s: %s", full, e)
                    buf = BytesIO()
                    img.save(buf, "JPEG", quality=82)
                    buf.seek(0)
                    return buf
        except Exception as e:
            log.warning("Failed to render %s: %s", full, e)
            return None

    # ------------------------------------------------------------------ warm
    def is_warming(self) -> bool:
        return self._warm_thread is not None and self._warm_thread.is_alive()

    def start_warm(self, pause_while: Optional[Callable[[], bool]] = None) -> bool:
        """Starts background batch generation of all missing thumbnails (one at a time)."""
        with self._warm_lock:
            if self.is_warming():
                return False
            self._warm_cancel.clear()
            self._warm_thread = threading.Thread(target=self.warm, args=(pause_while,), name="thumb-warm", daemon=True)
            self._warm_thread.start()
            return True

    def stop_warm(self) -> None:
        self._warm_cancel.set()

    def warm(self, pause_while: Optional[Callable[[], bool]] = None, delay: float = 0.02) -> dict:
        stats = {"generated": 0, "skipped": 0, "failed": 0, "pruned": 0, "started": time.time()}
        log.info("Thumbnail warm-up started")
        try:
            for full in self.iter_images():
                if self._warm_cancel.is_set():
                    break
                while pause_while and pause_while() and not self._warm_cancel.is_set():
                    time.sleep(1.0)              # a copy is running: do not compete for the SSD
                try:
                    st = full.stat()
                except OSError:
                    continue
                cached = self.cache_path(full, "thumbs")
                if self._is_valid(cached, st):
                    stats["skipped"] += 1
                    continue
                with self._decode_slots:
                    result = self._render(full, cached, self.cfg.thumbnail_size)
                stats["generated" if isinstance(result, Path) else "failed"] += 1
                if delay:
                    time.sleep(delay)
            if not self._warm_cancel.is_set():
                stats["pruned"] = self.prune()
        except Exception:
            log.exception("Thumbnail warm-up crashed")
        stats["seconds"] = round(time.time() - stats["started"], 1)
        self.last_warm_stats = stats
        log.info("Thumbnail warm-up finished: %s", stats)
        return stats

    def iter_images(self) -> Iterable[Path]:
        if not self.base.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(self.base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in sorted(filenames):
                if not name.startswith(".") and name.lower().endswith(IMAGE_EXTS):
                    yield Path(dirpath) / name

    # ----------------------------------------------------------------- prune
    def prune(self) -> int:
        """Removes cache entries whose source is gone, stale temp files, and keeps the
        preview cache under ``preview_cache_max_mib`` (least recently used first)."""
        removed = 0
        for kind in ("thumbs", "previews"):
            kind_root = self.root / kind
            if not kind_root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(kind_root, topdown=False):
                for name in filenames:
                    cached = Path(dirpath) / name
                    try:
                        if name.startswith(".") and name.endswith(".tmp"):
                            if time.time() - cached.stat().st_mtime > 3600:
                                cached.unlink(); removed += 1
                            continue
                        if not name.endswith(".jpg"):
                            continue
                        rel = Path(dirpath).relative_to(kind_root) / name[:-4]
                        if not (self.base / rel).is_file():
                            cached.unlink(); removed += 1
                    except OSError:
                        pass
                try:
                    if not os.listdir(dirpath) and Path(dirpath) != kind_root:
                        os.rmdir(dirpath)
                except OSError:
                    pass
        removed += self._enforce_size_cap(self.root / "previews", self.cfg.preview_cache_max_mib * 1024 * 1024)
        return removed

    @staticmethod
    def _enforce_size_cap(root: Path, max_bytes: int) -> int:
        if max_bytes <= 0 or not root.is_dir():
            return 0
        entries = []
        total = 0
        for p in root.rglob("*.jpg"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((max(st.st_atime, st.st_mtime), st.st_size, p))
            total += st.st_size
        removed = 0
        for _, size, p in sorted(entries):
            if total <= max_bytes:
                break
            try:
                p.unlink()
                total -= size
                removed += 1
            except OSError:
                pass
        return removed
