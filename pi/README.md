# Raw data database on the Raspberry Pi

The Pi keeps Blizzard's data exactly as sent, for 30 days, in one SQLite file. Coppertrail on the PC fetches from it and turns it into its own data. Standard library only (the Pi 1 is armv6l). Design: `docs/superpowers/specs/2026-11-24-pi-raw-store-design.md`.

## Jobs

| Timer | Runs | Does |
|---|---|---|
| `coppertrail-raw.timer` | :27 UTC, retries every 5 min until :55 | `collect`: deletes rows that would turn 30 days old before the next run, then stores each new listing response (items, commodities) as received, gzip and all |
| `coppertrail-items.timer` | :00 UTC, stops at :20 | `items`: reads the item ids of the newest listing responses and looks up item details that are missing, older than 25 days, or a 404 older than 7 days (`static-forever-eu`, then `static-classic1x-eu`) |

Both take the same lock (`/var/lib/coppertrail/.lock`); `collect` waits for it until :35 if an `items` run overran, `items` gives up at once. Exit codes: 0 ok or nothing new, 1 failed, 2 locked. Logs (`journalctl -u coppertrail-raw.service`, `-u coppertrail-items.service`) carry sizes and counts, never bodies or credentials.

## Install or update

From the PC, outside :25–:56 and :00–:20:

```powershell
scp -r pi coppertrail@coppertrail-pi:~/coppertrail-pi
ssh coppertrail@coppertrail-pi "sudo bash ~/coppertrail-pi/install.sh"
```

Set or change the Blizzard credentials (on the Pi; input is hidden):

```bash
sudo bash /opt/coppertrail/set-blizzard-secret.sh
```

It writes `/etc/coppertrail/blizzard.env` (root:coppertrail, mode 640) and checks that Blizzard issues a token. Status: `sudo bash ~/coppertrail-pi/install.sh --status`.

The first version's day files (`/var/lib/coppertrail/raw/*.sqlite`) are deleted by the first `collect` run that stores a response.

## Data

`/var/lib/coppertrail/raw.sqlite` (WAL mode):

- `snapshot`: `id, endpoint ('items'|'commodities'), last_modified, fetched_at, namespace, encoding ('gzip'|'identity'), size, body`. One row per response; `body` is the response body exactly as received.
- `item`: `seq, item_id, namespace (NULL if found nowhere), status (200|404), fetched_at, encoding, body`.

`id` and `seq` only grow (never reused), so they work as bookmarks. About 2.8 MB per hour, about 2 GB for 30 days.

## Export for the PC

```bash
ssh coppertrail@coppertrail-pi "python3 /opt/coppertrail/coppertrail_raw.py export --after-snapshot ID --after-item SEQ"
```

Read-only, needs no credentials. Stdout carries, per row, one JSON header line followed by exactly `size` bytes of body: first every snapshot with `id > ID` (keys `table, id, endpoint, last_modified, fetched_at, namespace, encoding, size`), then every item row with `seq > SEQ` (keys `table, seq, item_id, namespace, status, fetched_at, encoding, size`; `size` 0 for a 404). The last line is `{"end":true,"snapshot_max":N,"item_max":M}`. A count goes to stderr. The PC keeps the highest `id` and `seq` it stored and passes them next time.
