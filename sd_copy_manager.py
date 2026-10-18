"""Automatic, verified copying of media from removable cards to the backup drive.

Design goals (see README "設計說明"):

* the source card is **never written to** (detection is read-only);
* every file is copied to a temporary ``.part`` file, fsync'ed, optionally
  re-read and hash-verified, then atomically renamed into place, so a power
  loss can never leave a half-written file that looks like a photo;
* duplicates are detected cheaply (size + mtime) and only hashed when needed;
* devices are tracked by filesystem UUID, not mount path;
* cancelling really stops and does not auto-restart until the card is
  re-inserted;
* a per-session JSON-lines log with every error is written to the backup drive.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import devices as devmod
from config import Config
from media_dates import get_capture_date_folder

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
MTIME_TOLERANCE = 2.0  # FAT timestamps have 2-second resolution


@dataclass
class CopyStatus:
    is_copying: bool = False
    current_file: str = ""
    progress_percent: float = 0.0
    total_files: int = 0
    copied_files: int = 0
    skipped_files: int = 0
    error_files: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    status_message: str = "Starting..."
    ssd_present: bool = False
    active_source: Optional[str] = None
    last_result: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    # Compatibility alias used by older UI code.
    @property
    def active_usb_source(self):
        return self.active_source


class CopyCancelled(Exception):
    pass


class BackupDriveLost(Exception):
    pass


class SDCopyManager:
    def __init__(self, config: Optional[Config] = None,
                 device_lister: Callable[[], List[devmod.BlockDevice]] = devmod.list_mounted_devices):
        self.config = config or Config()
        self.backup_dir = self.config.backup_dir
        self._device_lister = device_lister

        self._lock = threading.RLock()
        self._status = CopyStatus()
        self._cancel = threading.Event()
        self._copy_thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable[[dict], None]] = []

        # device_id -> "done" | "cancelled" | "failed"; cleared when the device disappears
        self._processed: Dict[str, str] = {}
        self._known_device_ids: set = set()
        self._last_ssd_check = 0.0
        self._last_ssd_state = False
        self._session_log = None

        log.info("SDCopyManager initialised. Backup drive: %s", self.backup_dir)

    # ------------------------------------------------------------------ status
    def set_event_callback(self, callback: Callable[[dict], None]) -> None:
        """Registers a status listener (several may be registered)."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
        self._emit()

    add_event_callback = set_event_callback

    def get_status(self) -> dict:
        with self._lock:
            d = asdict(self._status)
        d["active_usb_source"] = d["active_source"]
        return d

    @property
    def is_copying(self) -> bool:
        return self._status.is_copying

    @property
    def status_message(self) -> str:
        return self._status.status_message

    def _set(self, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(self._status, k, v)

    def _emit(self) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        if not callbacks:
            return
        status = self.get_status()
        for cb in callbacks:
            try:
                cb(status)
            except Exception:  # UI errors must never kill the copy thread
                log.exception("Status callback failed")

    # ---------------------------------------------------------- backup drive
    def check_ssd_present(self, force: bool = False) -> bool:
        """Cheap check (no writes): is the backup directory a mounted, writable filesystem?"""
        now = time.monotonic()
        if not force and now - self._last_ssd_check < 1.0:
            return self._last_ssd_state
        present = False
        try:
            dev = devmod.find_backup_device(self.backup_dir, self._device_lister())
            present = (dev is not None and not dev.read_only
                       and os.path.isdir(self.backup_dir)
                       and os.access(self.backup_dir, os.W_OK | os.X_OK))
        except OSError as e:
            log.debug("Backup drive check failed: %s", e)
            present = False
        if present != self._last_ssd_state:
            log.info("Backup drive %s", "available" if present else "not available")
        self._last_ssd_state = present
        self._last_ssd_check = now
        self._set(ssd_present=present)
        return present

    def _write_test(self) -> bool:
        """One real write test per copy session (not per file)."""
        probe = Path(self.backup_dir) / f".write_test_{os.getpid()}"
        try:
            probe.write_text("ok")
            probe.unlink()
            return True
        except OSError as e:
            log.error("Backup drive is not writable: %s", e)
            return False

    def _free_bytes(self) -> int:
        try:
            st = os.statvfs(self.backup_dir)
            return st.f_bavail * st.f_frsize
        except OSError:
            return 0

    # --------------------------------------------------------------- sources
    def get_available_sources(self) -> List[devmod.BlockDevice]:
        try:
            return devmod.find_source_devices(self.backup_dir, self.config.source_mount_prefixes, self._device_lister())
        except Exception:
            log.exception("Device scan failed")
            return []

    def _unprocessed(self, sources: List[devmod.BlockDevice]) -> List[devmod.BlockDevice]:
        return [s for s in sources if s.device_id not in self._processed]

    # ------------------------------------------------------------ public API
    def start_copy(self, source: Optional[devmod.BlockDevice] = None) -> bool:
        with self._lock:
            if self._status.is_copying:
                log.info("Copy already running")
                return False
            if source is None:
                candidates = self._unprocessed(self.get_available_sources())
                if not candidates:
                    self._set(status_message="No new card to copy.")
                    self._emit()
                    return False
                source = candidates[0]
            self._cancel.clear()
            self._set(is_copying=True, active_source=source.display_name, status_message=f"Preparing {source.display_name}...",
                      current_file="", progress_percent=0.0, total_files=0, copied_files=0, skipped_files=0,
                      error_files=0, bytes_total=0, bytes_done=0, errors=[], last_result=None)
            self._copy_thread = threading.Thread(target=self._run_session, args=(source,), name="sd-copy", daemon=True)
            self._copy_thread.start()
        self._emit()
        return True

    def stop_copy(self) -> None:
        if self._status.is_copying:
            log.info("Copy cancellation requested")
            self._cancel.set()
            self._set(status_message="Cancelling...")
            self._emit()

    def forget_device(self, device_id: str) -> None:
        """Allows a processed/cancelled device to be copied again without re-inserting."""
        with self._lock:
            self._processed.pop(device_id, None)

    # ------------------------------------------------------------- the loop
    def main_loop(self, stop_event: Optional[threading.Event] = None) -> None:
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("Error in device poll loop")
            stop_event.wait(self.config.poll_interval)

    def _tick(self) -> None:
        sources = self.get_available_sources()
        current_ids = {s.device_id for s in sources}
        ssd_ok = self.check_ssd_present()

        # Forget devices that were removed so re-insertion triggers a new copy.
        for gone in self._known_device_ids - current_ids:
            if gone in self._processed:
                log.info("Card %s removed; it will be copied again when re-inserted", gone)
            self._processed.pop(gone, None)
        self._known_device_ids = current_ids

        if self._status.is_copying:
            return

        pending = self._unprocessed(sources)
        if not ssd_ok:
            self._set(status_message="Please insert the backup SSD.")
        elif not sources:
            self._set(status_message="Waiting for an SD card...")
        elif pending:
            self.start_copy(pending[0])
            return
        else:
            names = ", ".join(s.display_name for s in sources)
            last = self._status.last_result
            self._set(status_message=f"{names}: {last}" if last else f"{names} already backed up. Safe to remove.")
        self._emit()

    # ------------------------------------------------------------ a session
    def _run_session(self, source: devmod.BlockDevice) -> None:
        result = "failed"
        started = datetime.now()
        try:
            if not self.check_ssd_present(force=True) or not self._write_test():
                raise BackupDriveLost("Backup drive not present or not writable")
            self._open_session_log(source, started)
            files = self._collect_files(source.mountpoint)
            if not files:
                self._set(status_message=f"No media files on {source.display_name}.", progress_percent=100.0, last_result="no media files")
                result = "done"
                return

            total_bytes = sum(size for _, size in files)
            self._set(total_files=len(files), bytes_total=total_bytes, status_message="Checking free space...")
            self._emit()
            self._check_free_space(files)

            self._set(status_message="Copying...")
            self._emit()
            last_emit = 0.0
            for index, (src, size) in enumerate(files):
                if self._cancel.is_set():
                    raise CopyCancelled()
                if index % 20 == 0 and not self.check_ssd_present():
                    raise BackupDriveLost("Backup drive disconnected during copy")
                self._set(current_file=os.path.basename(src))
                self._copy_one(src, size)
                st = self._status
                self._set(progress_percent=(index + 1) / len(files) * 100.0)
                if time.monotonic() - last_emit > 0.2:
                    self._emit()
                    last_emit = time.monotonic()

            st = self._status
            summary = f"Copied {st.copied_files}, skipped {st.skipped_files}, errors {st.error_files}"
            result = "done" if st.error_files == 0 else "done_with_errors"
            self._set(status_message=("Backup complete. " if st.error_files == 0 else "Backup finished WITH ERRORS. ") + summary,
                      progress_percent=100.0, current_file="", last_result=summary)
        except CopyCancelled:
            result = "cancelled"
            st = self._status
            self._set(status_message=f"Cancelled. Copied {st.copied_files} of {st.total_files}. Re-insert the card to resume.",
                      last_result="cancelled (re-insert the card to resume)")
        except BackupDriveLost as e:
            result = "failed"
            self._set(status_message=f"{e}. Copy aborted.", last_result="aborted: backup drive lost")
        except Exception as e:
            log.exception("Copy session failed")
            result = "failed"
            self._set(status_message=f"Copy failed: {e}", last_result=f"failed: {e}")
        finally:
            with self._lock:
                self._processed[source.device_id] = result
                self._status.is_copying = False
                self._status.active_source = None
            self._close_session_log(result)
            self._emit()
            log.info("Session for %s finished: %s", source.display_name, result)

    def _collect_files(self, root: str) -> List[tuple]:
        exts = self.config.media_extension_set()
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in ("$recycle.bin", "system volume information")]
            for name in filenames:
                if name.startswith(".") or name.startswith("._"):
                    continue
                if exts and os.path.splitext(name)[1].lower() not in exts:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    size = os.stat(path).st_size
                except OSError as e:
                    self._record_error(path, f"stat failed: {e}")
                    continue
                files.append((path, size))
            if self._cancel.is_set():
                raise CopyCancelled()
        files.sort()
        return files

    def _check_free_space(self, files: List[tuple]) -> None:
        # Estimate what is actually new: files whose name+size already exist are free.
        needed = 0
        for src, size in files:
            dest = Path(self.backup_dir) / self._dest_folder(src) / os.path.basename(src)
            try:
                if dest.is_file() and dest.stat().st_size == size:
                    continue
            except OSError:
                pass
            needed += size
        reserve = self.config.min_free_mib * 1024 * 1024
        free = self._free_bytes()
        if needed + reserve > free:
            raise RuntimeError(f"Not enough space: need {needed / 1e9:.1f} GB, free {free / 1e9:.1f} GB")

    def _dest_folder(self, src: str) -> str:
        try:
            return get_capture_date_folder(src)
        except OSError:
            return "unknown-date"

    # -------------------------------------------------------------- one file
    def _copy_one(self, src: str, size: int) -> None:
        name = os.path.basename(src)
        dest_dir = Path(self.backup_dir) / self._dest_folder(src)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._cleanup_partials(dest_dir)
            dest = dest_dir / name
            if dest.exists():
                outcome = self._compare_existing(src, dest, size)
                if outcome == "same":
                    self._bump("skipped_files", bytes_done=size)
                    self._log_event("skip", src, str(dest))
                    return
                dest = self._unique_name(dest_dir, name)
            self._atomic_copy(src, dest, size)
            self._bump("copied_files")
            self._log_event("copy", src, str(dest))
        except CopyCancelled:
            raise
        except OSError as e:
            if not self.check_ssd_present(force=True):
                raise BackupDriveLost("Backup drive disconnected during copy") from e
            self._record_error(src, str(e))
        except Exception as e:
            self._record_error(src, f"{type(e).__name__}: {e}")

    def _compare_existing(self, src: str, dest: Path, size: int) -> str:
        try:
            s_st, d_st = os.stat(src), dest.stat()
        except OSError:
            return "different"
        if s_st.st_size != d_st.st_size:
            return "different"
        if abs(s_st.st_mtime - d_st.st_mtime) <= MTIME_TOLERANCE:
            return "same"
        # Same size, different timestamp: hash both to be sure.
        return "same" if self._hash_file(src) == self._hash_file(dest) else "different"

    @staticmethod
    def _unique_name(dest_dir: Path, name: str) -> Path:
        base, ext = os.path.splitext(name)
        n = 1
        while True:
            candidate = dest_dir / f"{base}_{n}{ext}"
            if not candidate.exists():
                return candidate
            n += 1

    def _atomic_copy(self, src: str, dest: Path, size: int) -> None:
        tmp = dest.with_name(f".{dest.name}.part")
        hasher = hashlib.sha256()
        try:
            with open(src, "rb") as fin, open(tmp, "wb") as fout:
                while True:
                    if self._cancel.is_set():
                        raise CopyCancelled()
                    chunk = fin.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    fout.write(chunk)
                    self._bump(bytes_done=len(chunk))
                fout.flush()
                os.fsync(fout.fileno())
            written = tmp.stat().st_size
            if written != size:
                raise IOError(f"size mismatch after copy: {written} != {size}")
            if self.config.verify_after_copy and self._hash_file(tmp) != hasher.hexdigest():
                raise IOError("checksum mismatch after copy (bad media or cable?)")
            try:
                os.utime(tmp, ns=(os.stat(src).st_atime_ns, os.stat(src).st_mtime_ns))
            except OSError:
                pass
            os.replace(tmp, dest)
            self._fsync_dir(dest.parent)
        except BaseException:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    def _hash_file(self, path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                if self._cancel.is_set():
                    raise CopyCancelled()
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    @staticmethod
    def _cleanup_partials(dest_dir: Path) -> None:
        try:
            for p in dest_dir.glob(".*.part"):
                log.warning("Removing stale partial file %s", p)
                p.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------- bookkeeping
    def _bump(self, counter: Optional[str] = None, bytes_done: int = 0) -> None:
        with self._lock:
            if counter:
                setattr(self._status, counter, getattr(self._status, counter) + 1)
            if bytes_done:
                self._status.bytes_done += bytes_done

    def _record_error(self, src: str, message: str) -> None:
        log.error("Failed: %s: %s", src, message)
        with self._lock:
            self._status.error_files += 1
            self._status.errors.append(f"{os.path.basename(src)}: {message}")
            if len(self._status.errors) > 200:
                del self._status.errors[:-200]
        self._log_event("error", src, None, message)

    def _open_session_log(self, source: devmod.BlockDevice, started: datetime) -> None:
        try:
            log_dir = self.config.state_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source.display_name)[:40]
            path = log_dir / f"{started:%Y%m%d-%H%M%S}_{safe}.jsonl"
            self._session_log = open(path, "a", encoding="utf-8")
            self._log_event("start", source.mountpoint, None, json.dumps({
                "device": source.device, "device_id": source.device_id, "label": source.label}))
        except OSError as e:
            log.warning("Cannot open session log on backup drive: %s", e)
            self._session_log = None

    def _log_event(self, kind: str, src: str, dest: Optional[str], message: Optional[str] = None) -> None:
        if not self._session_log:
            return
        try:
            self._session_log.write(json.dumps({
                "t": datetime.now().isoformat(timespec="seconds"), "event": kind,
                "src": src, "dest": dest, "msg": message}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _close_session_log(self, result: str) -> None:
        if not self._session_log:
            return
        st = self.get_status()
        self._log_event("end", "", None, json.dumps({
            "result": result, "copied": st["copied_files"], "skipped": st["skipped_files"],
            "errors": st["error_files"], "bytes": st["bytes_done"]}))
        try:
            self._session_log.flush()
            os.fsync(self._session_log.fileno())
            self._session_log.close()
        except OSError:
            pass
        self._session_log = None


if __name__ == "__main__":
    import sys
    from config import load_config, setup_logging

    cfg = load_config()
    setup_logging(cfg)
    manager = SDCopyManager(cfg)
    manager.set_event_callback(lambda d: print(f"[{d['progress_percent']:5.1f}%] {d['status_message']}  {d['current_file']}", file=sys.stderr))
    stop = threading.Event()
    try:
        manager.main_loop(stop)
    except KeyboardInterrupt:
        stop.set()
        manager.stop_copy()
