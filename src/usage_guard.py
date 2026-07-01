"""
usage_guard.py — Periodic status logging and auto-resume scheduling.

All LLM inference is local (Ollama) — no API cost tracking needed.
Provides:
  - check_due()      — returns True every 30 min (for periodic status log)
  - log_status()     — prints pipeline health
  - reset_session()  — resets session timer
  - schedule_resume() — schedules a bash one-shot to resume after a long pause
"""
from __future__ import annotations

import datetime
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
RESUME_SCRIPT = ROOT / "scripts" / "resume_apply.sh"
LOG_FILE = ROOT / "output" / "resume.log"

_session_start: float = time.time()
_last_check: float = 0.0


def reset_session():
    global _session_start
    _session_start = time.time()


def check_due(interval_seconds: int = 1800) -> bool:
    global _last_check
    now = time.time()
    if now - _last_check >= interval_seconds:
        _last_check = now
        return True
    return False


def log_status():
    elapsed_min = (time.time() - _session_start) / 60
    print(f"  [session] Running for {elapsed_min:.0f} min — local model, zero API cost")


def schedule_resume(remaining_jobs: int = 30, delay_seconds: int = 3600):
    """Schedule resume_apply.sh to run after delay_seconds via systemd-run or background sleep."""
    resume_at = datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds)
    RESUME_SCRIPT.parent.mkdir(parents=True, exist_ok=True)

    script = f"""#!/usr/bin/env bash
set -e
cd {ROOT}
echo "[resume] Woke up at $(date)" >> {LOG_FILE}
ollama serve &>/dev/null & sleep 5
python src/pipeline.py --apply-only --limit {remaining_jobs} >> {LOG_FILE} 2>&1
echo "[resume] Finished at $(date)" >> {LOG_FILE}
"""
    RESUME_SCRIPT.write_text(script)
    RESUME_SCRIPT.chmod(0o755)

    try:
        proc = subprocess.run(
            ["systemd-run", "--user", "--on-active", f"{delay_seconds}s",
             "--description", "Hermes pipeline resume",
             "/bin/bash", str(RESUME_SCRIPT)],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            print(f"  [session] Auto-resume scheduled via systemd at {resume_at:%H:%M}")
            return
    except FileNotFoundError:
        pass

    # Fallback: background sleep process
    wrapper = ROOT / "scripts" / "_resume_wrapper.sh"
    wrapper.write_text(f"#!/usr/bin/env bash\nsleep {delay_seconds}\nbash {RESUME_SCRIPT}\n")
    wrapper.chmod(0o755)
    subprocess.Popen(
        ["/bin/bash", str(wrapper)],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"  [session] Auto-resume scheduled via background sleep at {resume_at:%H:%M}")
