#!/usr/bin/env bash
# Hermes overnight pipeline runner.
# Keeps laptop awake (lid closed OK), auto-starts Ollama, logs everything.
#
# Usage:
#   bash scripts/run_pipeline.sh               # full pipeline
#   bash scripts/run_pipeline.sh --apply-only  # apply only (243 tailored jobs)
#   bash scripts/run_pipeline.sh --limit 20    # cap per stage

set -e
cd "$(dirname "$0")/.."

LOG="output/pipeline_run.log"
mkdir -p output screenshots output/tailored

echo "" | tee -a "$LOG"
echo "═══════════════════════════════════════" | tee -a "$LOG"
echo "[hermes] Starting at $(date)" | tee -a "$LOG"
echo "[hermes] PID: $$" | tee -a "$LOG"

# ── Start Ollama if not running ──────────────────────────────────────────────
if ! pgrep -x ollama > /dev/null 2>&1; then
    echo "[hermes] Starting Ollama..." | tee -a "$LOG"
    ollama serve >> output/ollama.log 2>&1 &
    OLLAMA_PID=$!
    sleep 6  # wait for Ollama to be ready
    echo "[hermes] Ollama started (PID $OLLAMA_PID)" | tee -a "$LOG"
else
    echo "[hermes] Ollama already running" | tee -a "$LOG"
fi

# ── Verify model is available ─────────────────────────────────────────────────
MODEL="qwen3:4b"
if ! ollama list 2>/dev/null | grep -q "$MODEL"; then
    echo "[hermes] Pulling $MODEL (one-time download)..." | tee -a "$LOG"
    ollama pull "$MODEL" | tee -a "$LOG"
fi

echo "[hermes] Model $MODEL ready" | tee -a "$LOG"

# ── Run pipeline (systemd-inhibit prevents sleep while lid is closed) ────────
exec systemd-inhibit \
  --what=sleep:idle:handle-lid-switch \
  --who="Hermes Job Pipeline" \
  --why="Automated job applications running overnight" \
  --mode=block \
  python src/pipeline.py "$@" 2>&1 | tee -a "$LOG"
