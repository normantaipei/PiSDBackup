"""Central configuration for PiSDBackup.

All tunables live here instead of being hard-coded across modules.  Values are
loaded from (in order of precedence):

1. environment variables prefixed with ``PISD_`` (e.g. ``PISD_BACKUP_DIR``)
2. a JSON file pointed to by ``PISD_CONFIG`` or found at one of the default
   locations (``./config.json``, ``~/.config/pisdbackup/config.json``,
   ``/etc/pisdbackup/config.json``)
3. the defaults below
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

# Image / video extensions that are considered "media" and therefore backed up.
DEFAULT_MEDIA_EXTENSIONS: List[str] = [
    # JPEG / HEIF
    ".jpg", ".jpeg", ".jpe", ".heic", ".heif", ".hif", ".png", ".tif", ".tiff",
    # RAW
    ".arw", ".cr2", ".cr3", ".crw", ".dng", ".nef", ".nrw", ".orf", ".rw2", ".raf",
    ".pef", ".srw", ".kdc", ".mos", ".3fr", ".erf", ".mef", ".qtk", ".x3f", ".iiq",
    ".rwl", ".srf", ".sr2", ".gpr",
    # Video
    ".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".avi", ".mxf", ".mkv", ".braw", ".insv",
    # Audio (field recorders)
    ".wav", ".mp3",
]

RAW_EXTENSIONS: List[str] = [
    ".arw", ".cr2", ".cr3", ".crw", ".dng", ".nef", ".nrw", ".orf", ".rw2", ".raf",
    ".pef", ".srw", ".kdc", ".mos", ".3fr", ".erf", ".mef", ".qtk", ".x3f", ".iiq",
    ".rwl", ".srf", ".sr2", ".gpr",
]

DEFAULT_CONFIG_PATHS = [
    Path.cwd() / "config.json",
    Path(__file__).resolve().parent / "config.json",
    Path.home() / ".config" / "pisdbackup" / "config.json",
    Path("/etc/pisdbackup/config.json"),
]


@dataclass
class Config:
    # Where backups are written.  Must be a mount point when the drive is present.
    backup_dir: str = "/mnt/backup_drive"
    # Sub-directory of backup_dir used for PiSDBackup's own state (logs, thumbs).
    state_dirname: str = ".pisdbackup"
    # Only files with these extensions are copied.  Empty list = copy everything.
    media_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_MEDIA_EXTENSIONS))
    # Mount point prefixes under which removable sources are looked for.
    source_mount_prefixes: List[str] = field(default_factory=lambda: ["/media", "/mnt", "/run/media"])
    # Re-read every copied file and compare its hash with the source.
    verify_after_copy: bool = True
    # Seconds between device scans.
    poll_interval: float = 3.0
    # Minimum free space (MiB) that must remain on the backup drive.
    min_free_mib: int = 512

    # Web server
    web_host: str = "0.0.0.0"
    web_port: int = 5000
    web_auth: bool = True
    # Shared secret used in the URL/QR code and stored in a cookie.  Generated on
    # first run and persisted to token_file if empty.
    web_token: str = ""
    token_file: str = "~/.config/pisdbackup/web_token"
    thumbnail_size: int = 320
    preview_size: int = 1600
    file_list_cache_seconds: int = 30

    # Networking
    wifi_interface: str = "wlan0"

    # UI
    debug_mode: bool = False
    fullscreen: bool = True

    # Logging
    log_level: str = "INFO"
    log_file: str = ""  # empty -> stderr only

    # ------------------------------------------------------------------ helpers
    @property
    def state_dir(self) -> Path:
        return Path(self.backup_dir) / self.state_dirname

    def media_extension_set(self) -> set:
        return {e.lower() for e in self.media_extensions}

    def ensure_token(self) -> str:
        """Returns the web token, generating and persisting one if necessary."""
        if self.web_token:
            return self.web_token
        token_path = Path(os.path.expanduser(self.token_file))
        try:
            if token_path.is_file():
                tok = token_path.read_text().strip()
                if tok:
                    self.web_token = tok
                    return tok
        except OSError as e:
            log.warning("Could not read token file %s: %s", token_path, e)
        tok = secrets.token_urlsafe(12)
        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(tok)
            os.chmod(token_path, 0o600)
        except OSError as e:
            log.warning("Could not persist token to %s: %s (token is in-memory only)", token_path, e)
        self.web_token = tok
        return tok

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce(value: str, target):
    if isinstance(target, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(target, int):
        return int(value)
    if isinstance(target, float):
        return float(value)
    if isinstance(target, list):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


def load_config(path: Optional[str] = None) -> Config:
    cfg = Config()

    candidates = []
    env_path = os.environ.get("PISD_CONFIG")
    if path:
        candidates.append(Path(path))
    elif env_path:
        candidates.append(Path(env_path))
    else:
        candidates.extend(DEFAULT_CONFIG_PATHS)

    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text())
                unknown = set(data) - set(cfg.__dataclass_fields__)
                if unknown:
                    log.warning("Ignoring unknown config keys in %s: %s", candidate, sorted(unknown))
                for key, value in data.items():
                    if key in cfg.__dataclass_fields__:
                        setattr(cfg, key, value)
                log.info("Loaded config from %s", candidate)
                break
        except (OSError, ValueError) as e:
            log.error("Failed to read config %s: %s", candidate, e)

    for key in cfg.__dataclass_fields__:
        env_key = "PISD_" + key.upper()
        if env_key in os.environ:
            try:
                setattr(cfg, key, _coerce(os.environ[env_key], getattr(cfg, key)))
            except ValueError as e:
                log.error("Bad value for %s: %s", env_key, e)

    cfg.backup_dir = os.path.expanduser(cfg.backup_dir)
    return cfg


def setup_logging(cfg: Config) -> None:
    handlers = [logging.StreamHandler()]
    if cfg.log_file:
        try:
            Path(cfg.log_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(os.path.expanduser(cfg.log_file)))
        except OSError as e:
            print(f"Could not open log file {cfg.log_file}: {e}")
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
