#!/usr/bin/env bash
# hermes-status — show current state of the Hermes pipeline

DB=/mnt/data/rj/hermes/db/applications.db
LOG=/mnt/data/rj/hermes/output/pipeline_run.log

echo ""
echo "═══════════════════════════════════════════════════"
echo "  HERMES STATUS  |  $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════"

# ── Pipeline process ──────────────────────────────────
PIPELINE_PID=$(pgrep -f "python3 src/pipeline.py" 2>/dev/null | head -1)
if [[ -n "$PIPELINE_PID" ]]; then
    ELAPSED=$(ps -o etimes= -p "$PIPELINE_PID" 2>/dev/null | tr -d ' ')
    if [[ -n "$ELAPSED" ]]; then
        MINS=$((ELAPSED / 60))
        SECS=$((ELAPSED % 60))
        echo "  ✓ Pipeline RUNNING  (PID $PIPELINE_PID, running ${MINS}m${SECS}s)"
    else
        echo "  ✓ Pipeline RUNNING  (PID $PIPELINE_PID)"
    fi
else
    echo "  ✗ Pipeline NOT running"
fi

# ── Inhibit locks ─────────────────────────────────────
if systemd-inhibit --list 2>/dev/null | grep -q "Hermes"; then
    echo "  ✓ Lid-close inhibit  ACTIVE (system will not suspend)"
else
    echo "  ✗ Lid-close inhibit  NOT active"
fi

# ── Monitor ───────────────────────────────────────────
MONITOR_PID=$(pgrep -f "monitor.sh" 2>/dev/null | head -1)
if [[ -n "$MONITOR_PID" ]]; then
    echo "  ✓ Watchdog RUNNING   (PID $MONITOR_PID, checks every 2h)"
else
    echo "  ✗ Watchdog NOT running"
fi

# ── DB stats ──────────────────────────────────────────
echo ""
echo "  Job pipeline stats:"
if [[ -f "$DB" && -s "$DB" ]]; then
    python3 -c "
import sqlite3
conn = sqlite3.connect('$DB')
rows = conn.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY COUNT(*) DESC').fetchall()
total = sum(r[1] for r in rows)
for r in rows:
    bar = '█' * min(30, int(r[1] * 30 / max(total, 1)))
    print(f'  {r[0]:12s} {r[1]:4d}  {bar}')
print(f'  {\"─\" * 30}')
print(f'  TOTAL        {total:4d}')
conn.close()
" 2>/dev/null || echo "  (DB read error)"
else
    echo "  (DB empty or missing)"
fi

# ── Last 8 log lines ──────────────────────────────────
echo ""
echo "  Recent pipeline output:"
echo "  ──────────────────────────────────────────"
if [[ -f "$LOG" ]]; then
    tail -8 "$LOG" | sed 's/^/  /'
else
    echo "  (no log file)"
fi
echo "  ──────────────────────────────────────────"
echo ""
echo "  tail -f $LOG"
echo "  tail -f /mnt/data/rj/hermes/output/monitor.log"
echo ""
