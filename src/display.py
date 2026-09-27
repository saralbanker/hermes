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
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil

_proc: subprocess.Popen | None = None

HERMES_PROFILE_NAMES = {
    "chrome-indeed-profile",
    "chrome-ats-profile",
    "chrome-redirect-profile",
    "chrome-direct-profile",
}


class DisplayUnavailable(RuntimeError):
    """Xvfb is missing or failed to start."""


def _get_my_descendants() -> set[int]:
    """Return all descendant PIDs of the current process."""
    try:
        current_proc = psutil.Process(os.getpid())
        return {p.pid for p in current_proc.children(recursive=True)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return set()


def _is_hermes_xvfb(cmd_str: str) -> bool:
    """True if cmdline matches Hermes Xvfb (1366x900x24 on display :99 to :139)."""
    return "1366x900x24" in cmd_str and any(f":{n}" in cmd_str for n in range(99, 140))


def cleanup_orphan_browsers(root_dir: Path | None = None) -> dict:
    """Safely terminate orphan Chrome processes using Hermes profiles, clean up
    stale Singleton locks, and terminate orphaned Xvfb instances from crashed runs.

    Never touches the user's desktop browser, unrelated X11 servers, or active
    children/descendants of the current Hermes process.
    """
    cleaned = {"chrome_killed": 0, "locks_removed": 0, "xvfb_killed": 0}
    root = root_dir or Path(__file__).parent.parent
    output_dir = root / "output"

    my_pid = os.getpid()
    my_descendants = _get_my_descendants()
    active_hermes_pids = {my_pid} | my_descendants
    if _proc is not None and _proc.pid:
        active_hermes_pids.add(_proc.pid)

    # 1. Terminate orphaned Hermes Chrome and orphaned Hermes Xvfb instances
    running_hermes_procs: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
        try:
            if proc.pid in active_hermes_pids or proc.info.get("ppid") in active_hermes_pids:
                continue
            name = (proc.info["name"] or "").lower()
            cmdline = proc.info["cmdline"] or []
            cmd_str = " ".join(cmdline)

            # Check for Chrome using Hermes profiles
            if "chrome" in name or "chromium" in name:
                if any(p in cmd_str for p in HERMES_PROFILE_NAMES):
                    running_hermes_procs.append(proc)
            elif "xvfb" in name:
                # Hermes Xvfb uses private 1366x900x24 display on :99-:139
                if _is_hermes_xvfb(cmd_str):
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    cleaned["xvfb_killed"] += 1
                    # Clean up associated X11 socket and lock file
                    for n in range(99, 140):
                        if f":{n}" in cmd_str:
                            Path(f"/tmp/.X{n}-lock").unlink(missing_ok=True)
                            Path(f"/tmp/.X11-unix/X{n}").unlink(missing_ok=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    # Terminate orphaned Chrome and all their child processes safely
    for proc in running_hermes_procs:
        try:
            children = []
            try:
                children = proc.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except psutil.TimeoutExpired:
                proc.kill()
            for child in children:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            cleaned["chrome_killed"] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    # 2. Clean stale Singleton locks only after verifying owning process is dead
    for profile_name in HERMES_PROFILE_NAMES:
        prof_dir = output_dir / profile_name
        if not prof_dir.is_dir():
            continue
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_path = prof_dir / lock_name
            if not (lock_path.is_symlink() or lock_path.exists()):
                continue

            is_stale = False
            if lock_path.is_symlink():
                try:
                    target = os.readlink(str(lock_path))
                    # Usually formatted as hostname-PID
                    m = re.search(r"-(\d+)$", target)
                    if m:
                        owning_pid = int(m.group(1))
                        if not psutil.pid_exists(owning_pid):
                            is_stale = True
                    else:
                        # Cannot parse PID, check if any process has this profile in cmdline
                        is_stale = not any(
                            profile_name in " ".join(p.info.get("cmdline") or [])
                            for p in psutil.process_iter(["cmdline"])
                        )
                except OSError:
                    is_stale = True
            else:
                # Regular file or socket, check if any process has this profile in cmdline
                is_stale = not any(
                    profile_name in " ".join(p.info.get("cmdline") or [])
                    for p in psutil.process_iter(["cmdline"])
                )

            if is_stale:
                try:
                    lock_path.unlink(missing_ok=True)
                    cleaned["locks_removed"] += 1
                except OSError:
                    pass

    return cleaned


def _is_display_locked(num: int) -> bool:
    lock_file = Path(f"/tmp/.X{num}-lock")
    sock_file = Path(f"/tmp/.X11-unix/X{num}")
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            if not psutil.pid_exists(pid):
                lock_file.unlink(missing_ok=True)
                sock_file.unlink(missing_ok=True)
                return False
            return True
        except (ValueError, OSError):
            return True
    if sock_file.exists():
        return True
    return False


def _free_display() -> int:
    for num in range(99, 140):
        if not _is_display_locked(num):
            return num
    raise DisplayUnavailable("no free X display number in :99-:139")


def _stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()  # only our own child — never pkill by name
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def is_display_alive(display_str: str) -> bool:
    """Validate that the given DISPLAY string (e.g. ':99') has an active server and socket."""
    if not display_str or not display_str.startswith(":"):
        return False
    try:
        num = int(display_str.lstrip(":").split(".")[0])
    except ValueError:
        return False
    sock_file = Path(f"/tmp/.X11-unix/X{num}")
    lock_file = Path(f"/tmp/.X{num}-lock")
    if not sock_file.exists():
        return False
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            return psutil.pid_exists(pid)
        except (ValueError, OSError):
            pass
    return True


def ensure_virtual_display() -> str:
    global _proc

    # 1. If our own Xvfb child is already running and responsive, reuse it (strictly idempotent)
    if _proc is not None and _proc.poll() is None:
        current_disp = os.environ.get("DISPLAY", "")
        if is_display_alive(current_disp):
            return current_disp
        # If socket/server died unexpectedly, reset our handle
        _stop()

    # 2. If environment already provides a valid virtual display, reuse it
    if os.environ.get("HERMES_XVFB") == "1" and os.environ.get("DISPLAY"):
        if is_display_alive(os.environ["DISPLAY"]):
            return os.environ["DISPLAY"]

    if os.environ.get("HERMES_SHOW_BROWSER") == "1":
        return os.environ.get("DISPLAY", "")  # debugging: let windows appear on the desktop

    # 3. Only run orphan cleanup before spawning a new display
    cleanup_orphan_browsers()

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
