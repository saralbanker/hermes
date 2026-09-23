"""
notify.py — Desktop notifications via notify-send (KDE), with an optional sound
for urgent alerts.

Designed to work when invoked from a systemd --user service, where
DBUS_SESSION_BUS_ADDRESS is often unset: in that case it is derived from the
current UID before notify-send is invoked.

Never raises. Any failure is logged and notify() returns False.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Checked in order; the first one that exists on disk is used.
_SOUND_CANDIDATES = [
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
]

_TIMEOUT_SECONDS = 10


def _ensure_dbus_env() -> None:
    """systemd --user services don't inherit the login session's D-Bus address."""
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return
    uid = os.getuid()
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"


def _find_sound() -> str | None:
    for path in _SOUND_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _play_sound() -> None:
    sound_file = _find_sound()
    if not sound_file:
        logger.info("notify: no known sound file found, skipping urgent sound")
        return

    paplay = shutil.which("paplay")
    canberra = shutil.which("canberra-gtk-play")
    if not paplay and not canberra:
        logger.info("notify: neither paplay nor canberra-gtk-play on PATH, skipping sound")
        return

    try:
        if paplay:
            cmd = [paplay, sound_file]
        else:
            cmd = [canberra, "-f", sound_file]
        subprocess.run(
            cmd, check=False, timeout=_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("notify: sound playback failed: %s", e)


def notify(title: str, body: str, urgent: bool = False) -> bool:
    """
    Send a desktop notification via notify-send. For urgent notifications, also
    attempts to play a short sound.

    Never raises: any failure is logged and False is returned.
    """
    try:
        _ensure_dbus_env()

        notify_send = shutil.which("notify-send")
        if not notify_send:
            logger.warning("notify: notify-send not found on PATH")
            return False

        cmd = [notify_send, "--app-name=Hermes"]
        cmd += ["--urgency=critical", "--expire-time=0"] if urgent else ["--urgency=normal"]
        cmd += [title, body]

        result = subprocess.run(
            cmd, check=False, timeout=_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            logger.warning(
                "notify: notify-send exited %d: %s",
                result.returncode, result.stderr.decode(errors="ignore"),
            )
            return False

        if urgent:
            _play_sound()

        return True
    except Exception as e:
        logger.warning("notify: failed to send notification: %s", e)
        return False
