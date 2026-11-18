"""Probe the Blizzard Game Data API for WoW Forever auction data.

Research only: it changes nothing in the collector and writes nothing unless
`--save DIR` is given. It answers:

- which rulesets and auction houses exist (the house for Normal Alliance EU),
- how large one house response is and what an entry looks like,
- whether the data changes between pulls (`Last-Modified`, auction ids kept,
  gone, new), so we learn the update rhythm,
- how many item ids the static Forever namespace knows.

Credentials (never committed, never printed):

1. environment variables `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`, or
2. `blizzard.toml` in the Coppertrail config folder
   (`%APPDATA%\\Coppertrail\\blizzard.toml` on Windows):

       [blizzard]
       client_id = "..."
       client_secret = "..."

Usage:

    uv run python scripts/probe_blizzard.py
    uv run python scripts/probe_blizzard.py --house 110 --repeat 4 --interval 20
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coppertrail.query.settings import config_dir  # noqa: E402

TOKEN_URL = "https://oauth.battle.net/token"
API = "https://{region}.api.blizzard.com"
LOCALE = {"eu": "en_GB", "us": "en_US", "kr": "ko_KR", "tw": "zh_TW"}


def load_credentials() -> tuple[str, str, str]:
    cid = os.environ.get("BLIZZARD_CLIENT_ID")
    secret = os.environ.get("BLIZZARD_CLIENT_SECRET")
    if cid and secret:
        return cid, secret, "environment"
    path = config_dir() / "blizzard.toml"
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8")).get("blizzard", {})
        if raw.get("client_id") and raw.get("client_secret"):
            return raw["client_id"], raw["client_secret"], str(path)
    sys.exit(
        "No credentials. Set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET, "
        f"or create {path} with a [blizzard] table (client_id, client_secret)."
    )


def get_token(client: httpx.Client, cid: str, secret: str) -> str:
    r = client.post(TOKEN_URL, data={"grant_type": "client_credentials"}, auth=(cid, secret))
    if r.status_code != 200:
        sys.exit(f"Token request failed: HTTP {r.status_code} (check id and secret)")
    return r.json()["access_token"]


class Api:
    def __init__(self, client: httpx.Client, token: str, region: str):
        self.client = client
        self.base = API.format(region=region)
        self.region = region
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, namespace: str) -> httpx.Response:
        params = {"namespace": f"{namespace}-{self.region}", "locale": LOCALE[self.region]}
        return self.client.get(self.base + path, params=params, headers=self.headers)


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def show_headers(r: httpx.Response) -> None:
    for key in ("last-modified", "date", "battlenet-namespace", "cache-control"):
        if key in r.headers:
            print(f"    {key}: {r.headers[key]}")


def list_houses(api: Api, ruleset: int) -> list[dict]:
    r = api.get("/data/wow/ruleset/index", "dynamic-forever")
    print(f"ruleset index: HTTP {r.status_code}")
    if r.status_code == 200:
        for rs in r.json().get("rulesets", []):
            print(f"  ruleset {rs.get('id')}: {rs.get('name')}")
    r = api.get(f"/data/wow/ruleset/{ruleset}/auctions/", "dynamic-forever")
    print(f"auction houses of ruleset {ruleset}: HTTP {r.status_code}")
    if r.status_code != 200:
        return []
    houses = r.json().get("auctions", [])
    for h in houses:
        print(f"  house {h.get('id')}: {h.get('name')}")
    return houses


def fetch_house(api: Api, ruleset: int, house: int) -> tuple[dict, dict, httpx.Response]:
    r = api.get(f"/data/wow/ruleset/{ruleset}/auctions/{house}", "dynamic-forever")
    print(f"house {house}: HTTP {r.status_code}, {mb(len(r.content))}")
    show_headers(r)
    items = r.json() if r.status_code == 200 else {}
    rc = api.get(f"/data/wow/ruleset/{ruleset}/auctions/{house}/commodities", "dynamic-forever")
    print(f"house {house} commodities: HTTP {rc.status_code}, {mb(len(rc.content))}")
    show_headers(rc)
    commodities = rc.json() if rc.status_code == 200 else {}
    return items, commodities, r


def describe(label: str, auctions: list[dict]) -> None:
    if not auctions:
        print(f"  {label}: none")
        return
    ids = Counter(a["item"]["id"] for a in auctions)
    keys = sorted({k for a in auctions for k in a})
    no_buyout = sum(1 for a in auctions if "buyout" not in a and "unit_price" not in a)
    print(f"  {label}: {len(auctions)} auctions, {len(ids)} distinct items")
    print(f"    fields: {', '.join(keys)}")
    print(f"    without buyout/unit_price: {no_buyout}")
    print(f"    most listed items: {ids.most_common(5)}")


def probe_items(api: Api, item_ids: list[int]) -> None:
    missing = 0
    for item_id in item_ids:
        r = api.get(f"/data/wow/item/{item_id}", "static-forever")
        if r.status_code == 404:
            missing += 1
        elif r.status_code != 200:
            print(f"  item {item_id}: HTTP {r.status_code}")
    print(f"static item lookups: {missing} of {len(item_ids)} returned 404")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--region", default="eu", choices=sorted(LOCALE))
    ap.add_argument("--ruleset", type=int, default=2, help="2 = Normal")
    ap.add_argument("--house", type=int, help="house id (default: first Alliance house)")
    ap.add_argument("--repeat", type=int, default=1, help="number of pulls")
    ap.add_argument("--interval", type=float, default=20, help="minutes between pulls")
    ap.add_argument("--items", type=int, default=30, help="item ids to look up (0 = skip)")
    ap.add_argument("--save", type=Path, help="write raw JSON here (outside both repos)")
    args = ap.parse_args()

    cid, secret, source = load_credentials()
    print(f"credentials from {source}")
    with httpx.Client(timeout=120) as client:
        api = Api(client, get_token(client, cid, secret), args.region)
        print("token ok\n")

        houses = list_houses(api, args.ruleset)
        house = args.house
        if house is None:
            alliance = [h for h in houses if "alliance" in str(h.get("name", "")).lower()]
            if not alliance:
                sys.exit("No Alliance house found; pass --house ID from the list above.")
            house = alliance[0]["id"]
        print()

        previous: set[int] | None = None
        last_modified = None
        for pull in range(1, args.repeat + 1):
            print(f"--- pull {pull} of {args.repeat} ({time.strftime('%H:%M:%S')}) ---")
            items, commodities, r = fetch_house(api, args.ruleset, house)
            auctions = items.get("auctions", []) or []
            comms = commodities.get("auctions", []) or []
            describe("items", auctions)
            describe("commodities", comms)

            ids = {a["id"] for a in auctions + comms}
            lm = r.headers.get("last-modified")
            if previous is not None:
                print(f"  last-modified changed: {lm != last_modified}")
                print(
                    f"  auction ids kept {len(ids & previous)}, "
                    f"gone {len(previous - ids)}, new {len(ids - previous)}"
                )
            previous, last_modified = ids, lm

            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                (args.save / f"house{house}-{stamp}.json").write_bytes(r.content)

            if pull == 1 and args.items:
                sample = sorted({a["item"]["id"] for a in auctions + comms})[: args.items]
                probe_items(api, sample)
            if pull < args.repeat:
                time.sleep(args.interval * 60)
            print()


if __name__ == "__main__":
    main()
