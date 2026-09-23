#!/usr/bin/env bash
# install_timers.sh — Install/refresh the Hermes systemd --user units (idempotent).
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST"
for unit in hermes.service hermes.timer hermes-watch.service hermes-watch.timer \
            hermes-summary.service hermes-summary.timer; do
    install -m 644 "$SRC/$unit" "$DEST/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now hermes.timer hermes-watch.timer hermes-summary.timer
systemctl --user list-timers 'hermes*' --no-pager
