#!/usr/bin/env bash
# hermes-status.sh — One-screen view of Hermes: timers, current run, today's numbers, last errors.
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT" || exit 1

echo "═══ HERMES STATUS  $(date '+%F %T') ═══"
if flock -n output/hermes.lock true 2>/dev/null; then
    echo "run: idle"
else
    echo "run: IN PROGRESS (lock held)"
fi
systemctl --user list-timers 'hermes*' --no-pager 2>/dev/null | head -5
echo
python3 - <<'PY'
import sqlite3, json
from datetime import date
c = sqlite3.connect("db/applications.db")
today = date.today().isoformat()
q = lambda s, *a: c.execute(s, a).fetchall()
print("status:", dict(q("SELECT status, COUNT(*) FROM jobs GROUP BY 1 ORDER BY 2 DESC")))
print("submitted today by tier:", dict(q("SELECT COALESCE(tier,'core'), COUNT(*) FROM jobs "
      "WHERE status='submitted' AND substr(applied_at,1,10)=? GROUP BY 1", today)))
print("submitted today by channel:", dict(q("SELECT COALESCE(apply_channel, job_board), COUNT(*) FROM jobs "
      "WHERE status='submitted' AND substr(applied_at,1,10)=? GROUP BY 1", today)))
print("attempt outcomes today:", dict(q("SELECT status, COUNT(*) FROM jobs WHERE substr(last_attempt_at,1,10)=? "
      "GROUP BY 1", today)))
print("employer responses:", dict(q("SELECT response_status, COUNT(*) FROM jobs WHERE response_status IS NOT NULL GROUP BY 1")))
PY
if [[ -f output/metrics.jsonl ]]; then
    echo; echo "last run metrics:"; tail -1 output/metrics.jsonl | python3 -c "import json,sys; r=json.load(sys.stdin); print(' ', r['at'], 'total', r['total_s'], 's'); [print('  ', s) for s in r['stages']]"
fi
echo; echo "recent log:"; tail -12 output/hermes_cron.log 2>/dev/null | sed 's/^/  /'
