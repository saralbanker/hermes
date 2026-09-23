#!/usr/bin/env bash
# Hermes — one-command job application runner.
#
# Works from any directory. Install once:
#   ln -sf /mnt/data/rj/hermes/scripts/run_pipeline.sh ~/.local/bin/hermes
#
# Usage:
#   hermes                  full pipeline (background, lid-close safe)
#   hermes --apply-only     apply to already-tailored jobs
#   hermes --dry-run        test run, no real submissions (foreground)
#   hermes --limit 10       cap each stage at 10 jobs

set -euo pipefail

# ── Resolve project root from this script's real location (works via symlink) ──
SCRIPT_REAL=$(readlink -f "${BASH_SOURCE[0]}")
PROJECT_ROOT=$(cd "$(dirname "$SCRIPT_REAL")/.." && pwd)

cd "$PROJECT_ROOT"

LOG="output/pipeline_run.log"
mkdir -p output screenshots
chmod 700 output/

echo ""                                                         | tee -a "$LOG"
echo "═══════════════════════════════════════════════════════" | tee -a "$LOG"
echo "  HERMES  |  $(date '+%Y-%m-%d %H:%M:%S')"              | tee -a "$LOG"
echo "  Root: $PROJECT_ROOT"                                   | tee -a "$LOG"
echo "═══════════════════════════════════════════════════════" | tee -a "$LOG"

# ── Check Python ──────────────────────────────────────────────────────────────
PYTHON=$(command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    echo "[hermes] ERROR: python3 not found in PATH" | tee -a "$LOG"
    exit 1
fi

# ── Start Ollama if not running ───────────────────────────────────────────────
if ! pgrep -x ollama > /dev/null 2>&1; then
    echo "[hermes] Starting Ollama..." | tee -a "$LOG"
    ollama serve >> output/ollama.log 2>&1 &
    OLLAMA_PID=$!
    echo "[hermes] Waiting for Ollama to be ready..." | tee -a "$LOG"
    for i in {1..12}; do
        sleep 2
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "[hermes] Ollama ready (PID $OLLAMA_PID)" | tee -a "$LOG"
            break
        fi
        if [[ $i -eq 12 ]]; then
            echo "[hermes] ERROR: Ollama did not start within 24s" | tee -a "$LOG"
            exit 1
        fi
    done
else
    echo "[hermes] Ollama already running" | tee -a "$LOG"
fi

# ── Pull models if not present ────────────────────────────────────────────────
for MODEL in "qwen3:4b" "qwen2.5:3b"; do
    if ! ollama list 2>/dev/null | grep -q "^${MODEL}"; then
        echo "[hermes] Pulling $MODEL (one-time, ~2-3 GB)..." | tee -a "$LOG"
        ollama pull "$MODEL" 2>&1 | tee -a "$LOG"
        echo "[hermes] $MODEL ready" | tee -a "$LOG"
    else
        echo "[hermes] $MODEL already present" | tee -a "$LOG"
    fi
done

# ── First-time Indeed session setup ──────────────────────────────────────────
if [[ ! -f "output/indeed_session.json" ]]; then
    echo "[hermes] No Indeed session found — running first-time login..." | tee -a "$LOG"
    "$PYTHON" scripts/indeed_setup.py
    if [[ ! -f "output/indeed_session.json" ]]; then
        echo "[hermes] ERROR: Session setup failed." | tee -a "$LOG"
        exit 1
    fi
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
SKIP_PREFLIGHT=0
for arg in "$@"; do
    [[ "$arg" == "--skip-preflight" ]] && SKIP_PREFLIGHT=1
done

if [[ $SKIP_PREFLIGHT -eq 0 ]]; then
    echo "[hermes] Running pre-flight checks..." | tee -a "$LOG"
    if ! "$PYTHON" scripts/preflight.py 2>&1 | tee -a "$LOG"; then
        echo "[hermes] Pre-flight failed — fix the issues above and re-run." | tee -a "$LOG"
        exit 1
    fi
else
    echo "[hermes] Pre-flight skipped (--skip-preflight)" | tee -a "$LOG"
fi

echo "[hermes] Pre-flight passed — starting pipeline" | tee -a "$LOG"
echo "[hermes] Log: $PROJECT_ROOT/$LOG" | tee -a "$LOG"

# ── Strip --skip-preflight before forwarding args ─────────────────────────────
PIPELINE_ARGS=()
for arg in "$@"; do
    [[ "$arg" != "--skip-preflight" ]] && PIPELINE_ARGS+=("$arg")
done

# ── Determine run mode ────────────────────────────────────────────────────────
# --dry-run or --interactive: stay foreground (user is watching)
# Everything else: detach from terminal (lid-close safe overnight mode)
DRY_RUN=0
for arg in "${PIPELINE_ARGS[@]:-}"; do
    [[ "$arg" == "--dry-run" || "$arg" == "--interactive" ]] && DRY_RUN=1
done

if [[ $DRY_RUN -eq 1 ]]; then
    # ── Foreground mode (dry-run / test) ──────────────────────────────────────
    echo "[hermes] Running in foreground (dry-run/interactive mode)" | tee -a "$LOG"
    if command -v systemd-inhibit > /dev/null 2>&1; then
        exec systemd-inhibit \
          --what=sleep:idle:handle-lid-switch \
          --who="Hermes" \
          --why="Job application pipeline" \
          --mode=block \
          "$PYTHON" src/pipeline.py "${PIPELINE_ARGS[@]}" 2>&1 | tee -a "$LOG"
    else
        exec "$PYTHON" src/pipeline.py "${PIPELINE_ARGS[@]}" 2>&1 | tee -a "$LOG"
    fi
else
    # ── Background / overnight mode (default) ─────────────────────────────────
    # nohup + new session: survives terminal close AND lid close
    echo "[hermes] Starting overnight mode — detached from terminal" | tee -a "$LOG"
    echo "[hermes] You can safely close the terminal or laptop lid." | tee -a "$LOG"

    # Kill any existing pipeline before starting fresh
    pkill -f "python3 src/pipeline.py" 2>/dev/null || true
    sleep 1

    nohup systemd-inhibit \
      --what=sleep:idle:handle-lid-switch \
      --who="Hermes" \
      --why="Overnight job applications" \
      --mode=block \
      "$PYTHON" src/pipeline.py "${PIPELINE_ARGS[@]}" \
      >> "$LOG" 2>&1 &

    PIPELINE_PID=$!
    disown $PIPELINE_PID

    echo "[hermes] Pipeline PID: $PIPELINE_PID" | tee -a "$LOG"
    echo "[hermes] Watch live:  tail -f $PROJECT_ROOT/$LOG" | tee -a "$LOG"
    echo "[hermes] Status:      hermes-status" | tee -a "$LOG"
    echo ""
    echo "  Pipeline is running in background. You can:"
    echo "  • Close this terminal — pipeline keeps running"
    echo "  • Close laptop lid   — pipeline keeps running"
    echo "  • Watch output:  tail -f $PROJECT_ROOT/$LOG"
    echo "  • Check status:  hermes-status"
    echo ""

    # Tail the log for 30s so user sees it's working, then exit
    if [ -t 1 ]; then
        echo "  Showing live output for 30s (Ctrl+C to stop watching, pipeline continues)..."
        echo "  ────────────────────────────────────────"
        timeout 30 tail -f "$LOG" || true
        echo "  ────────────────────────────────────────"
        echo "  Pipeline continues running in background."
    fi
fi
