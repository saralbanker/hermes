"""
display.py — Run every automated browser inside a private Xvfb display.

Why: Indeed/Cloudflare challenge headless Chrome, so appliers run headful Chrome.
On KDE Wayland a headful window cannot be hidden off-screen, so Hermes gives the
browsers their own virtual X display instead. Xvfb only isolates rendering from
the desktop; it is not an anti-bot measure.

    ensure_virtual_display() -> str   # returns the DISPLAY value in use

Idempotent: a display started earlier in this process (or by xvfb-run) is reused.
"""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import time
from pathlib import Path

_proc: subprocess.Popen | None = None


class DisplayUnavailable(RuntimeError):
    """Xvfb is missing or failed to start."""


def _free_display() -> int:
    for num in range(99, 140):
        if not Path(f"/tmp/.X11-unix/X{num}").exists() and not Path(f"/tmp/.X{num}-lock").exists():
            return num
    raise DisplayUnavailable("no free X display number in :99-:139")


def _stop() -> None:
    if _proc and _proc.poll() is None:
        _proc.terminate()  # only our own child — never pkill by name
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()


def ensure_virtual_display() -> str:
    global _proc
    if os.environ.get("HERMES_XVFB") == "1" and os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]
    if os.environ.get("HERMES_SHOW_BROWSER") == "1":
        return os.environ.get("DISPLAY", "")  # debugging: let windows appear on the desktop
    if not shutil.which("Xvfb"):
        raise DisplayUnavailable("Xvfb not installed: sudo pacman -S xorg-server-xvfb")
    num = _free_display()
    _proc = subprocess.Popen(
        ["Xvfb", f":{num}", "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if Path(f"/tmp/.X11-unix/X{num}").exists():
            break
        if _proc.poll() is not None:
            raise DisplayUnavailable(f"Xvfb exited with code {_proc.returncode}")
        time.sleep(0.1)
    else:
        _stop()
        raise DisplayUnavailable("Xvfb did not create its socket within 5 s")
    atexit.register(_stop)
    os.environ["DISPLAY"] = f":{num}"
    os.environ["HERMES_XVFB"] = "1"
    # Chrome prefers Wayland when WAYLAND_DISPLAY is set; remove it so it uses Xvfb.
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ["XDG_SESSION_TYPE"] = "x11"
    return os.environ["DISPLAY"]
