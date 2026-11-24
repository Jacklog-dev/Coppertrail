#!/usr/bin/env bash
# Set the Blizzard API client ID and secret for the raw data database jobs.
# Usage: sudo bash set-blizzard-secret.sh
# Input is hidden and never passed as a command argument. The file is readable by
# root and the coppertrail group only.
set -euo pipefail

ENV_FILE=/etc/coppertrail/blizzard.env
SCRIPT=/opt/coppertrail/coppertrail_raw.py

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash $0" >&2
    exit 1
fi

read -rp  "Blizzard client ID: " client_id
read -rsp "Blizzard client secret (hidden): " client_secret
echo
if [[ -z "$client_id" || -z "$client_secret" ]]; then
    echo "Both values are needed; nothing changed." >&2
    exit 1
fi

install -d -m 750 -o root -g coppertrail /etc/coppertrail
tmp=$(mktemp /etc/coppertrail/.blizzard.env.XXXXXX)
chmod 640 "$tmp"
chown root:coppertrail "$tmp"
printf 'BLIZZARD_CLIENT_ID=%s\nBLIZZARD_CLIENT_SECRET=%s\n' "$client_id" "$client_secret" > "$tmp"
mv -f "$tmp" "$ENV_FILE"
unset client_id client_secret
echo "Saved to $ENV_FILE."

if [[ -f "$SCRIPT" ]]; then
    echo "Checking with Blizzard..."
    # Load the file into the checker's environment only, as the service user.
    sudo -u coppertrail bash -c "set -a; . '$ENV_FILE'; exec python3 '$SCRIPT' check"
fi
