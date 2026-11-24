#!/usr/bin/env bash
# Install or update the raw data database jobs on the Raspberry Pi.
# Usage: sudo bash install.sh            install or update, then enable both timers
#        sudo bash install.sh --status   show the timers, the last runs and the database size
# Install outside :25-:56 (listings run) and :00-:20 (items run).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
APP=/opt/coppertrail
DATA=/var/lib/coppertrail
DB=$DATA/raw.sqlite
USER_=coppertrail
UNITS=(coppertrail-raw.service coppertrail-raw.timer coppertrail-items.service coppertrail-items.timer)

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash $0 $*" >&2
    exit 1
fi

if [[ "${1:-}" == "--status" ]]; then
    systemctl list-timers coppertrail-raw.timer coppertrail-items.timer --no-pager || true
    for svc in coppertrail-raw.service coppertrail-items.service; do
        echo
        journalctl -u "$svc" -n 10 --no-pager || true
    done
    echo
    ls -lh "$DB" "$DB-wal" 2>/dev/null || echo "no database yet at $DB"
    exit 0
fi

id "$USER_" >/dev/null 2>&1 || { echo "user $USER_ is missing" >&2; exit 1; }
command -v sqlite3 >/dev/null || apt-get install -y sqlite3

install -d -m 755 "$APP"
install -m 755 "$HERE/coppertrail_raw.py" "$APP/coppertrail_raw.py"
install -m 755 "$HERE/set-blizzard-secret.sh" "$APP/set-blizzard-secret.sh"
install -d -m 750 -o root -g "$USER_" /etc/coppertrail
install -d -m 755 -o "$USER_" -g "$USER_" "$DATA"
for unit in "${UNITS[@]}"; do
    install -m 644 "$HERE/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now coppertrail-raw.timer coppertrail-items.timer

echo "Installed. Database: $DB"
echo "The old day files in $DATA/raw go after the first new listing hour is stored."
if [[ ! -f /etc/coppertrail/blizzard.env ]]; then
    echo "Next: sudo bash $APP/set-blizzard-secret.sh"
fi
