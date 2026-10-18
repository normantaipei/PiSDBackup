"""Chooses an SDL video driver for the attached screen.

Order: an existing X11/Wayland session, then KMS/DRM (Raspberry Pi OS Lite),
then the legacy framebuffer.  It never installs packages or starts services:
that is the installer's job, and a virtual display makes no sense for a
touch-screen product.
"""

from __future__ import annotations

import logging
import os

import pygame

log = logging.getLogger(__name__)


class DisplayManager:
    def __init__(self):
        self.display_method = None
        self.setup_display()

    def setup_display(self):
        attempts = []
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            attempts.append(("x11", {"SDL_VIDEODRIVER": "x11"} if os.environ.get("DISPLAY") else {"SDL_VIDEODRIVER": "wayland"}))
        elif os.path.exists("/tmp/.X11-unix/X0"):
            attempts.append(("x11", {"SDL_VIDEODRIVER": "x11", "DISPLAY": ":0"}))
        if os.path.exists("/dev/dri/card0") or os.path.exists("/dev/dri/card1"):
            attempts.append(("kmsdrm", {"SDL_VIDEODRIVER": "kmsdrm"}))
        if os.path.exists("/dev/fb0"):
            attempts.append(("fbcon", {"SDL_VIDEODRIVER": "fbcon", "SDL_FBDEV": "/dev/fb0"}))
        if os.environ.get("PISD_ALLOW_DUMMY_DISPLAY"):
            attempts.append(("dummy", {"SDL_VIDEODRIVER": "dummy"}))

        for name, env in attempts:
            saved = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                pygame.display.init()
                pygame.display.quit()
                self.display_method = name
                log.info("Display driver: %s", name)
                return
            except pygame.error as e:
                log.debug("Display driver %s unavailable: %s", name, e)
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        raise RuntimeError("No usable display found. Is a screen attached? (Set PISD_ALLOW_DUMMY_DISPLAY=1 for headless tests.)")
