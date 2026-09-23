#!/usr/bin/env bash
# monitor.sh — 2-hour watchdog for the Hermes pipeline
# Runs in background, checks every 2 hours, appends to monitor.log
# Usage: bash scripts/monitor.sh &

LOG=/mnt/data/rj/hermes/output/pipeline_run.log
MONITOR_LOG=/mnt/data/rj/hermes/output/monitor.log
DB=/mnt/data/rj/hermes/db/applications.db
CHECK_INTERVAL=7200  # 2 hours

check() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local line="══════════════════════════════════════"
    echo "" >> "$MONITOR_LOG"
    echo "$line" >> "$MONITOR_LOG"
    echo "  MONITOR CHECK — $ts" >> "$MONITOR_LOG"
    echo "$line" >> "$MONITOR_LOG"

    # 1. Process alive?
    if pgrep -f "pipeline.py" > /dev/null; then
        local pid
        pid=$(pgrep -f "pipeline.py")
        echo "  ✓ Pipeline running (PID $pid)" >> "$MONITOR_LOG"
    else
        echo "  ✗ Pipeline NOT running — restarting..." >> "$MONITOR_LOG"
        notify-send "Hermes" "Pipeline died — restarting" 2>/dev/null
        cd /mnt/data/rj/hermes || exit 1
        python3 -c "
import subprocess, os
log = open('/mnt/data/rj/hermes/output/pipeline_run.log', 'a')
proc = subprocess.Popen(
    ['systemd-inhibit',
     '--what=sleep:idle:handle-lid-switch',
     '--who=Hermes',
     '--why=Overnight job applications',
     '--mode=block',
     'python3', 'src/pipeline.py'],
    stdout=log, stderr=log,
    cwd='/mnt/data/rj/hermes',
    start_new_session=True,
)
log.close()
print(f'Restarted PID:{proc.pid}')
" >> "$MONITOR_LOG" 2>&1
    fi

    # 2. DB status
    if [ -f "$DB" ]; then
        python3 -c "
import sqlite3
conn = sqlite3.connect('$DB')
rows = conn.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY COUNT(*) DESC').fetchall()
for r in rows: print(f'  DB  {r[0]:12s}: {r[1]}')
conn.close()
" >> "$MONITOR_LOG" 2>/dev/null
    fi

    # 3. Last 5 lines of pipeline log
    echo "  Last pipeline output:" >> "$MONITOR_LOG"
    tail -5 "$LOG" | sed 's/^/    /' >> "$MONITOR_LOG"

    # 4. Desktop notification summary
    local submitted
    submitted=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB')
r = conn.execute(\"SELECT COUNT(*) FROM jobs WHERE status='submitted'\").fetchone()
print(r[0])
conn.close()
" 2>/dev/null || echo "?")
    notify-send "Hermes ♥ alive" "Submitted: $submitted | Check monitor.log" 2>/dev/null

    echo "$line" >> "$MONITOR_LOG"
}

echo "Hermes monitor started — checking every $((CHECK_INTERVAL/3600))h" | tee -a "$MONITOR_LOG"

# Run forever, checking every 2 hours
while true; do
    sleep "$CHECK_INTERVAL"
    check
done
