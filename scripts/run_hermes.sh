#!/usr/bin/env bash
# run_hermes.sh — Unattended entry point used by the systemd timers (and by hand).
#
#   scripts/run_hermes.sh [pipeline args…]     e.g. --apply-only, --dry-run, --limit 5
#
# Guarantees: one run at a time (flock), waits for network, starts Ollama if it is
# down, never runs longer than HERMES_MAX_HOURS, notifies the desktop on failure.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
LOG="$ROOT/output/hermes_cron.log"
LOCK="$ROOT/output/hermes.lock"
MAX_HOURS="${HERMES_MAX_HOURS:-4}"
mkdir -p "$ROOT/output" && chmod 700 "$ROOT/output"
cd "$ROOT" || exit 1
export PYTHONUNBUFFERED=1
# systemd --user services have no session bus variable; notify-send needs it.
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

log() { echo "[hermes $(date '+%F %T')] $*" | tee -a "$LOG"; }
alert() { python3 "$ROOT/src/notify.py" "$1" "$2" >/dev/null 2>&1 || notify-send -u critical "$1" "$2" 2>/dev/null || true; }

exec 9>"$LOCK"
if ! flock -n 9; then
    log "another Hermes run holds $LOCK — exiting (no overlap)"
    exit 0
fi

export HERMES_LOCK_HELD=1   # pipeline.py: the lock is already ours
log "run start: $*"
for attempt in $(seq 1 30); do            # up to ~30 min for network after resume/boot
    python3 scripts/preflight.py >>"$LOG" 2>&1
    rc=$?
    [[ $rc -ne 2 ]] && break
    log "network down (attempt $attempt) — waiting 60 s"
    sleep 60
done
case $rc in
    0) ;;
    3) log "Ollama/models unavailable — scoring falls back to keywords, tailoring uses fact templates" ;;
    2) log "network still down after 30 min — giving up"; alert "Hermes: run skipped" "No network"; exit 1 ;;
    *) log "preflight hard failure (rc=$rc)"; alert "Hermes: preflight failed" "See $LOG"; exit 1 ;;
esac

timeout --signal=INT --kill-after=120 "${MAX_HOURS}h" python3 src/pipeline.py "$@" >>"$LOG" 2>&1
rc=$?
if [[ $rc -eq 0 ]]; then
    log "run finished OK"
else
    log "run FAILED (exit $rc)"
    alert "Hermes: run failed (exit $rc)" "tail -50 $LOG"
fi
exit $rc
