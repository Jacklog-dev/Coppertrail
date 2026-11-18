# Item icons (design, approved 2026-11-18)

## Intent

Readability: show each item's real icon next to its name, so items are found at a glance.
HANDOVER 8b's IP rule is about not making the app look like an in-game window (character
view, profession overview); item icons are allowed. Frames, borders, tooltips and game fonts
stay out.

## Goals, non-goals

- Goal: icon beside every item name (overview item list, item detail list and header,
  movers, pattern tables, group editor) and a larger one in the item detail header.
- Non-goal: icon fetching in the hourly/nightly collector (that is auction data only).
- Non-goal: bundling image files in the repo or the exe.
- Anti-goal: users needing a Blizzard developer key to see icons.

## Approaches

1. **Item -> icon file id map shipped with the app, images by URL (picked).** A one-off dev
   script asks `/data/wow/media/item/{id}` once per item and writes
   `coppertrail/ui/web/data/icons.json`. The app builds
   `https://render.worldofwarcraft.com/eu/icons/56/<file_data_id>.jpg`; that host serves
   icons without a key (verified 2026-11-18). Rerun the script and release when a patch adds items.
2. Nightly collector fetches icons into `window/` (rejected: nightly is auction data only).
3. Icons committed or bundled in the exe (rejected by Jack).
4. Runtime media lookups (rejected: every user would need a key). Wowhead URLs need the icon
   name too and add a third party.

## Design

- `scripts/fetch_icon_map.py`: credentials as the collector (`load_credentials`), item ids
  from the data folder's newest `window/blizzard/items/<day>.parquet` plus the newest hourly
  ids, 4 parallel requests with the client's backoff. Asset `key == "icon"`, `file_data_id`.
  Merges with the existing map (keeps old entries), writes sorted JSON. Never logs secrets.
- `coppertrail/ui/icons.py`: loads the map once, `icon_url(item_id) -> str | None`.
- Bridge: `icons()` in `EXPOSED`, returns `{id: url}` for the catalog's items. JS loads it once
  (`js/itemicon.js`) and `itemIcon(id, size)` returns an `<img loading=lazy>` or, without an
  entry or on load error, a neutral square with one 1 px border.
- CSP `img-src 'self' data: https://render.worldofwarcraft.com`; `test_web_offline` allows
  that one host for images only. CLAUDE.md and HANDOVER 8b wording updated.
- Sizes: 18 px in lists and tables, 40 px in the item detail header. Sizes come from tokens.

## Left to the builder

Exact token names, placement inside each cell, the fallback square's colours (existing tokens).
