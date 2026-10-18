#!/usr/bin/env python3
"""PiSDBackup entry point: touch UI + web browser + automatic card backup."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from config import load_config, setup_logging

log = logging.getLogger("main")


def main() -> int:
    cfg = load_config()
    setup_logging(cfg)
    log.info("PiSDBackup starting. Backup drive: %s", cfg.backup_dir)

    # Import after logging is configured so module-level warnings are captured.
    from display_manager import DisplayManager
    from rpi_interface import RPiProductInterface
    from sd_copy_manager import SDCopyManager
    from web_file_manager import create_app, run_server, web_url

    sd_copy_manager = SDCopyManager(cfg)
    app = create_app(cfg, copy_manager=sd_copy_manager)
    file_index = app.config["FILE_INDEX"]
    thumb_cache = app.config["THUMBNAIL_CACHE"]

    def on_copy_status(status: dict) -> None:
        # When a backup session ends: refresh the browser index and pre-generate the
        # new thumbnails in the background so the first page load stays cheap (issue #1).
        if status.get("is_copying"):
            return
        file_index.invalidate()
        if cfg.warm_thumbnails and status.get("last_result"):
            thumb_cache.start_warm(pause_while=lambda: sd_copy_manager.is_copying)

    sd_copy_manager.set_event_callback(on_copy_status)
    threading.Thread(target=run_server, args=(app,), name="web", daemon=True).start()
    if cfg.warm_thumbnails:
        def warm_at_startup():
            threading.Event().wait(20)  # let the system settle first
            if sd_copy_manager.check_ssd_present():
                thumb_cache.start_warm(pause_while=lambda: sd_copy_manager.is_copying)
        threading.Thread(target=warm_at_startup, name="thumb-warm-start", daemon=True).start()
    log.info("Web UI: %s", web_url(cfg, "<pi-ip>"))

    try:
        display_manager = DisplayManager()
    except RuntimeError as e:
        log.error("%s", e)
        return 2

    ui = RPiProductInterface(display_manager, cfg, sd_copy_manager=sd_copy_manager)

    def handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down", signum)
        ui.running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    ui.run()
    log.info("PiSDBackup stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
