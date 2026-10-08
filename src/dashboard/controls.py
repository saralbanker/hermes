"""Timer controls for the dashboard. Only ever touches the hermes.timer unit."""
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

TIMER_UNIT = "hermes.timer"
_SYSTEMCTL = ["systemctl", "--user"]
_TIMEOUT_SECONDS = 15
_EMPTY_NEXT_RUN = {"", "0", "n/a"}


class TimerControlError(RuntimeError):
    """Raised when systemctl fails; the message is short and safe to show."""


def _run_systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run systemctl --user with a fixed argv; log stderr and raise on failure."""
    argv = [*_SYSTEMCTL, *args]
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=True
        )
    except subprocess.CalledProcessError as exc:
        logger.error("systemctl %s failed (rc=%s): %s", args[0], exc.returncode, exc.stderr)
        raise TimerControlError(f"systemctl {args[0]} failed (exit {exc.returncode})") from exc
    except subprocess.TimeoutExpired as exc:
        logger.error("systemctl %s timed out after %ss", args[0], _TIMEOUT_SECONDS)
        raise TimerControlError(f"systemctl {args[0]} timed out") from exc
    except OSError as exc:
        logger.error("systemctl could not be executed: %s", exc)
        raise TimerControlError("systemctl could not be executed") from exc


def _parse_properties(output: str) -> dict[str, str]:
    """Parse `key=value` lines from `systemctl show`."""
    props: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    return props


def timer_status() -> dict[str, object]:
    """Return active state, enabled flag, paused flag and next run of hermes.timer."""
    result = _run_systemctl(
        [
            "show",
            TIMER_UNIT,
            "--property=ActiveState,UnitFileState,NextElapseUSecRealtime",
        ]
    )
    props = _parse_properties(result.stdout)
    enabled = props.get("UnitFileState", "") == "enabled"
    next_run = props.get("NextElapseUSecRealtime", "")
    return {
        "active_state": props.get("ActiveState", "unknown"),
        "enabled": enabled,
        "paused": not enabled,
        "next_run": None if next_run.lower() in _EMPTY_NEXT_RUN else next_run,
    }


def pause_timer() -> None:
    """Disable and stop hermes.timer (a running apply run is not interrupted)."""
    _run_systemctl(["disable", "--now", TIMER_UNIT])


def resume_timer() -> None:
    """Enable and start hermes.timer."""
    _run_systemctl(["enable", "--now", TIMER_UNIT])
