#!/usr/bin/env bash
# Hermes — one-command job application runner.
#
# Works from any directory. Install once:
#   ln -sf /mnt/data/rj/hermes/scripts/run_pipeline.sh ~/.local/bin/hermes
#
# Then just run:
#   hermes                  full pipeline
#   hermes --apply-only     apply to already-tailored jobs
#   hermes --dry-run        test run, no real submissions
#   hermes --limit 10       cap each stage at 10 jobs

set -euo pipefail

# ── Resolve project root from this script's real location (works via symlink) ──
SCRIPT_REAL=$(readlink -f "${BASH_SOURCE[0]}")
PROJECT_ROOT=$(cd "$(dirname "$SCRIPT_REAL")/.." && pwd)

cd "$PROJECT_ROOT"

LOG="output/pipeline_run.log"
mkdir -p output screenshots
chmod 700 output/  # owner-only: contains session cookies + cover letters

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
    echo "" | tee -a "$LOG"
    echo "[hermes] No Indeed session found." | tee -a "$LOG"
    echo "[hermes] Running first-time login setup..." | tee -a "$LOG"
    "$PYTHON" scripts/indeed_setup.py
    if [[ ! -f "output/indeed_session.json" ]]; then
        echo "[hermes] ERROR: Session setup failed or was cancelled." | tee -a "$LOG"
        exit 1
    fi
fi

# ── Pre-flight checks (2 tests: Ollama inference + Indeed session) ────────────
# Skip with: hermes --skip-preflight (e.g. for dry-run or when you know it works)
SKIP_PREFLIGHT=0
for arg in "$@"; do
    [[ "$arg" == "--skip-preflight" ]] && SKIP_PREFLIGHT=1
done

if [[ $SKIP_PREFLIGHT -eq 0 ]]; then
    echo "" | tee -a "$LOG"
    echo "[hermes] Running pre-flight checks..." | tee -a "$LOG"
    if ! "$PYTHON" scripts/preflight.py 2>&1 | tee -a "$LOG"; then
        echo "" | tee -a "$LOG"
        echo "[hermes] Pre-flight failed — fix the issues above and re-run." | tee -a "$LOG"
        exit 1
    fi
else
    echo "[hermes] Pre-flight skipped (--skip-preflight)" | tee -a "$LOG"
fi

# ── Run pipeline (systemd-inhibit keeps laptop awake, lid closed OK) ──────────
echo "" | tee -a "$LOG"
echo "[hermes] Pre-flight passed — starting pipeline" | tee -a "$LOG"
echo "[hermes] Log: $PROJECT_ROOT/$LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Strip --skip-preflight before passing args to pipeline.py
PIPELINE_ARGS=()
for arg in "$@"; do
    [[ "$arg" != "--skip-preflight" ]] && PIPELINE_ARGS+=("$arg")
done

if command -v systemd-inhibit > /dev/null 2>&1; then
    exec systemd-inhibit \
      --what=sleep:idle:handle-lid-switch \
      --who="Hermes Job Pipeline" \
      --why="Automated job applications running overnight" \
      --mode=block \
      "$PYTHON" src/pipeline.py "${PIPELINE_ARGS[@]}" 2>&1 | tee -a "$LOG"
else
    exec "$PYTHON" src/pipeline.py "${PIPELINE_ARGS[@]}" 2>&1 | tee -a "$LOG"
fi
