#!/bin/bash
# scripts/run_hermes.sh — Run Hermes automated pipeline in background

PROJECT_DIR="/mnt/data/rj/hermes"
LOG_FILE="$PROJECT_DIR/output/hermes_cron.log"

mkdir -p "$PROJECT_DIR/output"

echo "==========================================" >> "$LOG_FILE"
echo "[hermes] Auto-starting pipeline at $(date)" >> "$LOG_FILE"
echo "==========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR" || exit 1

# Run the Hermes pipeline in full mode (Discover -> Score -> Tailor -> Apply)
python3 src/pipeline.py >> "$LOG_FILE" 2>&1

echo "[hermes] Pipeline completed at $(date)" >> "$LOG_FILE"
