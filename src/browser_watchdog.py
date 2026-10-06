"""
browser_watchdog.py — Per-attempt browser ownership, process tree verification,
authoritative monotonic deadline, and termination escalation.

Enforces:
1. Exclusive browser ownership: Verified DevTools endpoint + private profile directory.
2. Process generation identity: (pid, starttime) from /proc/<pid>/stat. Never signals
   a recycled PID or unverified process.
3. Authoritative timeout: Irreversible per-attempt signal set before termination.
4. Bounded termination escalation: SIGTERM -> 2-second grace -> SIGKILL on verified tree.
5. Safe profile cleanup: Profile is retained if live processes cannot be confirmed stopped.
"""
from __future__ import annotations

import os
import signal
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Set

import psutil

ROOT = Path(__file__).parent.parent


class BrowserOwnershipError(RuntimeError):
    """Raised when browser process ownership cannot be verified."""
    pass


class HardTimeoutError(Exception):
    """Authoritative per-attempt timeout exception."""
    pass


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    starttime: int

    def __str__(self) -> str:
        return f"Process(pid={self.pid}, starttime={self.starttime})"


def get_process_identity(pid: int) -> ProcessIdentity | None:
    """Read the process generation identity (pid, starttime) from /proc/<pid>/stat.
    Returns None if the process does not exist or cannot be read.
    """
    if pid <= 0:
        return None
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return None
        content = stat_path.read_text()
        # The comm field is parenthesised and may contain spaces or parens.
        # Everything after the last ')' contains the numeric fields.
        rparen_idx = content.rfind(")")
        if rparen_idx == -1:
            return None
        fields = content[rparen_idx + 2:].split()
        state = fields[0]
        if state == "Z":
            # Zombie process: already terminated
            return None
        # Field 22 (starttime) is at index 19 (0-indexed) after ')' (field 3 is state, index 0).
        starttime = int(fields[19])
        return ProcessIdentity(pid=pid, starttime=starttime)
    except (OSError, ValueError, IndexError):
        return None


def get_process_cmdline(pid: int) -> str | None:
    """Read null-separated command line from /proc/<pid>/cmdline."""
    if pid <= 0:
        return None
    try:
        cmd_path = Path(f"/proc/{pid}/cmdline")
        if not cmd_path.exists():
            return None
        raw = cmd_path.read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return None


def verify_browser_process(
    pid: int, expected_endpoint: str, expected_profile: Path | str
) -> ProcessIdentity:
    """Verify that `pid` exists and its command line contains the expected endpoint
    and profile. Fails closed without signaling if anything is mismatched.
    """
    ident = get_process_identity(pid)
    if ident is None:
        raise BrowserOwnershipError(f"Process {pid} does not exist or cannot be read")

    cmdline = get_process_cmdline(pid)
    if not cmdline:
        raise BrowserOwnershipError(f"Process {pid} has empty or unreadable cmdline")

    # Extract port from expected_endpoint (e.g. '127.0.0.1:9234' -> '9234')
    port = expected_endpoint.split(":")[-1]
    profile_str = str(expected_profile)

    if port not in cmdline:
        raise BrowserOwnershipError(
            f"Process {pid} command line does not contain expected port {port}: {cmdline[:200]}"
        )
    if profile_str not in cmdline and Path(profile_str).name not in cmdline:
        raise BrowserOwnershipError(
            f"Process {pid} command line does not contain expected profile {profile_str}: {cmdline[:200]}"
        )

    return ident


def allocate_endpoint() -> tuple[str, int]:
    """Allocate a unique local DevTools endpoint and verify it is not occupied."""
    # Find a free local port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = s.getsockname()[1]

    # Double check that no process is currently listening on that port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        res = s.connect_ex(("127.0.0.1", port))
        if res == 0:
            raise RuntimeError(f"Allocated endpoint port {port} was already occupied")

    return f"127.0.0.1:{port}", port


def is_endpoint_occupied(endpoint: str) -> bool:
    """Check if an endpoint address (ip:port) is actively accepting connections."""
    try:
        host, port_str = endpoint.split(":")
        port = int(port_str)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def create_unique_profile(base_dir: Path | None = None) -> Path:
    """Create a unique, private profile directory for one Indeed attempt."""
    if base_dir is None:
        base_dir = ROOT / "output" / "indeed_profiles"
    base_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="indeed-att-", dir=str(base_dir)))


def find_owned_process_tree(root_ident: ProcessIdentity) -> list[ProcessIdentity]:
    """Find the root and all currently living descendants of root whose identities
    match the process generation.
    """
    alive_tree: list[ProcessIdentity] = []
    current_root = get_process_identity(root_ident.pid)
    if current_root != root_ident:
        return alive_tree

    alive_tree.append(root_ident)
    try:
        proc = psutil.Process(root_ident.pid)
        for child in proc.children(recursive=True):
            child_ident = get_process_identity(child.pid)
            if child_ident is not None and child_ident.starttime >= root_ident.starttime:
                alive_tree.append(child_ident)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return alive_tree


class AttemptAbortContext:
    """Shared per-attempt abort context checked by browser operations and retry loops."""

    def __init__(self) -> None:
        self._timed_out = threading.Event()
        self._timeout_reason: str = ""

    def trigger_timeout(self, reason: str = "deadline exceeded") -> None:
        self._timeout_reason = reason
        self._timed_out.set()

    @property
    def is_timed_out(self) -> bool:
        return self._timed_out.is_set()

    @property
    def timeout_reason(self) -> str:
        return self._timeout_reason

    def check(self) -> None:
        """Raise HardTimeoutError immediately if the attempt has timed out."""
        if self._timed_out.is_set():
            raise HardTimeoutError(self._timeout_reason or "authoritative deadline exceeded")


class BrowserWatchdog:
    """Monotonic deadline controller for an exclusively owned browser process tree."""

    def __init__(
        self,
        root_pid: int,
        expected_endpoint: str,
        expected_profile: Path | str,
        deadline_seconds: float,
        abort_context: AttemptAbortContext | None = None,
        grace_period_seconds: float = 2.0,
    ) -> None:
        self.root_pid = root_pid
        self.expected_endpoint = expected_endpoint
        self.expected_profile = Path(expected_profile)
        self.deadline_seconds = deadline_seconds
        self.grace_period_seconds = grace_period_seconds
        self.abort_context = abort_context or AttemptAbortContext()

        # Verify initial ownership immediately before arming
        self.root_ident = verify_browser_process(root_pid, expected_endpoint, expected_profile)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._timed_out = False
        self._cleanup_confirmed = False

    def start(self) -> None:
        """Start the watchdog deadline thread."""
        self._thread = threading.Thread(
            target=self._run,
            name=f"watchdog-{self.root_pid}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        # Monotonic deadline
        finished_early = self._stop_event.wait(timeout=self.deadline_seconds)
        if finished_early:
            return

        # Deadline exceeded: authoritative irreversible timeout
        self._timed_out = True
        self.abort_context.trigger_timeout(
            f"exceeded apply budget of {self.deadline_seconds}s (watchdog)"
        )
        self._escalate_termination()

    def _escalate_termination(self) -> None:
        """Escalate: SIGTERM -> grace period -> SIGKILL on re-validated process identities."""
        # 1. Enumerate tree and verify identities
        tree = find_owned_process_tree(self.root_ident)
        tracked_identities = set(tree)
        if not tree:
            self._cleanup_confirmed = True
            return

        # Send SIGTERM to descendants first, then root
        for ident in reversed(tree):
            curr = get_process_identity(ident.pid)
            if curr == ident:
                try:
                    os.kill(ident.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        # 2. Grace period
        time.sleep(self.grace_period_seconds)

        # 3. Re-enumerate any living descendants plus re-check root tree
        remaining = find_owned_process_tree(self.root_ident)
        for ident in remaining:
            tracked_identities.add(ident)

        # For every tracked identity, check if still alive and kill with SIGKILL
        for ident in reversed(list(tracked_identities)):
            curr = get_process_identity(ident.pid)
            if curr == ident:
                try:
                    os.kill(ident.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # Verify all stopped
        time.sleep(0.5)
        alive_remaining = [
            ident for ident in tracked_identities
            if get_process_identity(ident.pid) == ident
        ]
        self._cleanup_confirmed = len(alive_remaining) == 0

    def stop(self, join_timeout: float = 5.0) -> bool:
        """Stop and join the watchdog. Returns True if the watchdog timed out."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        return self._timed_out

    @property
    def is_timed_out(self) -> bool:
        return self._timed_out

    @property
    def cleanup_confirmed(self) -> bool:
        return self._cleanup_confirmed


def cleanup_profile(profile_path: Path, root_ident: ProcessIdentity | None = None) -> bool:
    """Clean up a unique profile directory only if no owned processes remain running.
    If cleanup cannot be confirmed, retains the profile to avoid deleting data under a live process.
    """
    if not profile_path.exists():
        return True

    if root_ident is not None:
        alive = find_owned_process_tree(root_ident)
        if alive:
            # Process is still alive; retain profile and report cleanup failure
            return False

    # Check for any lingering chrome processes referencing this profile path
    profile_str = str(profile_path)
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if profile_str in cmd:
                # A process is still using this profile; do not delete
                return False
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    import shutil
    try:
        shutil.rmtree(profile_path, ignore_errors=False)
        return True
    except OSError:
        return False
