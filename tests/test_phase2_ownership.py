import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# Ensure src is on sys.path
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import browser_watchdog as bw
import indeed_apply as ia
import states as S


def test_allocate_endpoint_allocates_unique_and_unoccupied_ports():
    ep1, p1 = bw.allocate_endpoint()
    ep2, p2 = bw.allocate_endpoint()
    assert p1 != p2
    assert ep1.endswith(str(p1))
    assert ep2.endswith(str(p2))

    # Verify neither is occupied
    assert not bw.is_endpoint_occupied(ep1)
    assert not bw.is_endpoint_occupied(ep2)


def test_unique_profile_creation(tmp_path):
    p1 = bw.create_unique_profile(base_dir=tmp_path)
    p2 = bw.create_unique_profile(base_dir=tmp_path)
    assert p1.exists()
    assert p2.exists()
    assert p1 != p2


def test_process_identity_capture_for_current_process():
    ident = bw.get_process_identity(os.getpid())
    assert ident is not None
    assert ident.pid == os.getpid()
    assert ident.starttime > 0


def test_verify_browser_process_success_and_failure(tmp_path):
    profile = tmp_path / "test_prof"
    profile.mkdir()
    port = 9876
    endpoint = f"127.0.0.1:{port}"

    # Launch a mock background process with expected flags
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)", f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
    )
    try:
        ident = bw.verify_browser_process(proc.pid, endpoint, profile)
        assert ident.pid == proc.pid

        # Mismatched port must fail closed
        with pytest.raises(bw.BrowserOwnershipError, match="expected port 9999"):
            bw.verify_browser_process(proc.pid, "127.0.0.1:9999", profile)

        # Mismatched profile must fail closed
        with pytest.raises(bw.BrowserOwnershipError, match="expected profile"):
            bw.verify_browser_process(proc.pid, endpoint, tmp_path / "other_prof")
    finally:
        proc.kill()
        proc.wait()


def test_decoy_browser_on_default_endpoint_is_unaffected(tmp_path):
    # Start a decoy listening on default endpoint 9222 (or a designated decoy port)
    decoy_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    decoy_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    decoy_port = 9222
    try:
        decoy_server.bind(("127.0.0.1", decoy_port))
        decoy_server.listen(1)
    except OSError:
        pytest.skip(f"Port {decoy_port} in use on test machine")

    try:
        # Allocate an exclusive endpoint for an attempt
        ep, port = bw.allocate_endpoint()
        assert port != decoy_port
        assert ep != f"127.0.0.1:{decoy_port}"

        # An attempt will not bind to the decoy
        prof = bw.create_unique_profile(base_dir=tmp_path)

        # Start a dummy process on the attempt's endpoint
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)", f"--remote-debugging-port={port}", f"--user-data-dir={prof}"]
        )
        try:
            ident = bw.verify_browser_process(proc.pid, ep, prof)
            assert ident.pid == proc.pid

            # Terminating proc should leave decoy completely untouched
            proc.terminate()
            proc.wait()

            # Verify decoy socket is still alive and listening
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            assert test_sock.connect_ex(("127.0.0.1", decoy_port)) == 0
            test_sock.close()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    finally:
        decoy_server.close()


def test_profile_login_cache_does_not_mask_new_profile():
    ia._reset_session_cache()

    class FakePage:
        def __init__(self, is_login=False):
            self.is_login = is_login
            self.visited = []

        def get(self, url, timeout=30):
            self.visited.append(url)

    # Profile 1 is checked and logged in
    p1 = Path("/tmp/profile_1")
    page1 = FakePage(is_login=False)
    # Monkeypatch snapshot
    ia._snapshot = lambda p: (ia.MYJOBS_APPLIED_URL, "My jobs", "68 Applied", "<html></html>")
    detail1 = ia._check_indeed_login(page1, profile_path=p1)
    assert detail1 is None
    assert len(page1.visited) == 1

    # Second check with SAME profile should use cache (no second get)
    page1.visited.clear()
    assert ia._check_indeed_login(page1, profile_path=p1) is None
    assert len(page1.visited) == 0

    # Profile 2 is a NEW profile and shows a login wall:
    # Must NOT use cached result from Profile 1!
    p2 = Path("/tmp/profile_2")
    page2 = FakePage(is_login=True)
    ia._snapshot = lambda p: ("https://secure.indeed.com/account/login", "Sign in", "Sign in", '<input type="password">')
    detail2 = ia._check_indeed_login(page2, profile_path=p2)
    assert detail2 is not None
    assert "guest" in detail2.lower() or "not signed in" in detail2.lower()
    assert len(page2.visited) == 1


def test_cleanup_profile_safety(tmp_path):
    prof = bw.create_unique_profile(base_dir=tmp_path)
    # Launch a process holding an open file in the profile
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)", f"--user-data-dir={prof}"]
    )
    try:
        ident = bw.get_process_identity(proc.pid)
        # Cleanup must refuse to delete profile while process is alive
        cleaned = bw.cleanup_profile(prof, ident)
        assert cleaned is False
        assert prof.exists()

        # Kill process and wait
        proc.kill()
        proc.wait()
        time.sleep(0.1)

        # Now cleanup succeeds
        cleaned = bw.cleanup_profile(prof, ident)
        assert cleaned is True
        assert not prof.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
