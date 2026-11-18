"""Fetch one WoW Forever auction house from the Blizzard API and summarise it.

Research script, not part of the collector. Output goes to `data/blizzard/`
(gitignored) unless `--out` says otherwise; never commit it to the public repo.

Modes:

    # one snapshot: per-item summary as Parquet + a short report
    uv run python scripts/ah_snapshot.py --house 111

    # compare all Alliance houses with the AHledger archive (which house is ours?)
    uv run python scripts/ah_snapshot.py --compare

    # watch: poll every 5 min with If-Modified-Since, save each new snapshot and
    # report what changed (update rhythm, sold/expired estimate)
    uv run python scripts/ah_snapshot.py --house 111 --watch 5 --duration 120

Prices are copper per unit. Item auctions carry `buyout` for the whole stack,
commodities carry `unit_price`; both are turned into a unit price.
Credentials as in `probe_blizzard.py`.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from probe_blizzard import Api, get_token, load_credentials

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ITEMS = [1081, 2318, 2589, 2592, 4245, 5784, 7909, 8146]


def fetch(api: Api, ruleset: int, house: int, since: str | None = None):
    """Return (listings frame, last-modified) or (None, since) on 304."""
    frames = []
    last_modified = since
    for suffix, kind in (("", "item"), ("/commodities", "commodity")):
        path = f"/data/wow/ruleset/{ruleset}/auctions/{house}{suffix}"
        headers = {"If-Modified-Since": since} if since else {}
        r = api.client.get(
            api.base + path,
            params={"namespace": f"dynamic-forever-{api.region}", "locale": "en_GB"},
            headers={**api.headers, **headers},
        )
        if r.status_code == 304:
            return None, since
        r.raise_for_status()
        last_modified = r.headers.get("last-modified", last_modified)
        rows = r.json().get("auctions", []) or []
        df = pd.DataFrame(
            {
                "auction_id": [a["id"] for a in rows],
                "item_id": [a["item"]["id"] for a in rows],
                "quantity": [a.get("quantity", 1) for a in rows],
                "buyout": [a.get("buyout") for a in rows],
                "unit_price": [a.get("unit_price") for a in rows],
                "bid": [a.get("bid") for a in rows],
                "time_left": [a.get("time_left") for a in rows],
            }
        )
        df["kind"] = kind
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    unit = df["unit_price"].astype("Float64")
    from_buyout = df["buyout"].astype("Float64") / df["quantity"]
    df["unit"] = unit.fillna(from_buyout)
    return df, last_modified


def weighted_quantile(prices: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(prices)
    p, w = prices[order], weights[order]
    cum = np.cumsum(w)
    return float(p[np.searchsorted(cum, q * cum[-1])])


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    """One row per item: min, p25, median, p75 (unit price, weighted by quantity),
    quantity, auctions. Bid-only auctions count in quantity but not in prices."""
    out = []
    for item_id, g in df.groupby("item_id", sort=True):
        priced = g[g["unit"].notna()]
        row = {
            "item_id": item_id,
            "kind": g["kind"].iloc[0],
            "quantity": int(g["quantity"].sum()),
            "auctions": len(g),
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
        }
        if len(priced):
            p = priced["unit"].to_numpy(dtype=float)
            w = priced["quantity"].to_numpy(dtype=float)
            row["min"] = int(p.min())
            for key, q in (("p25", 0.25), ("median", 0.5), ("p75", 0.75)):
                row[key] = int(round(weighted_quantile(p, w, q)))
        out.append(row)
    cols = ["item_id", "kind", "quantity", "auctions", "min", "p25", "median", "p75"]
    return pd.DataFrame(out, columns=cols).astype(
        {"min": "Int64", "p25": "Int64", "median": "Int64", "p75": "Int64"}
    )


def report(df: pd.DataFrame, summary: pd.DataFrame, last_modified: str | None) -> None:
    print(f"  data as of (last-modified): {last_modified}")
    by_kind = df.groupby("kind").agg(auctions=("auction_id", "size"), items=("item_id", "nunique"))
    print(by_kind.to_string())
    print(f"  time_left: {df['time_left'].value_counts().to_dict()}")
    gold = (df["unit"].fillna(0) * df["quantity"]).sum() / 10_000
    print(f"  buyout value listed: {gold:,.0f} gold")
    ref = summary[summary["item_id"].isin(REFERENCE_ITEMS)]
    print("  reference items:")
    print(ref.to_string(index=False))


def diff(prev: pd.DataFrame, cur: pd.DataFrame) -> None:
    """What happened between two snapshots, by auction id."""
    p = prev.set_index("auction_id")
    c = cur.set_index("auction_id")
    gone = p.loc[p.index.difference(c.index)]
    new = c.loc[c.index.difference(p.index)]
    both = p.index.intersection(c.index)
    shrunk = (p.loc[both, "quantity"] - c.loc[both, "quantity"]).clip(lower=0)
    print(f"  kept {len(both)}, gone {len(gone)}, new {len(new)}")
    print(f"  gone by time_left before: {gone['time_left'].value_counts().to_dict()}")
    print("    (SHORT ones may have expired; the others were bought or cancelled)")
    print(
        f"  kept auctions with lower quantity (partial buys): {(shrunk > 0).sum()}, "
        f"units {int(shrunk.sum())}"
    )
    gone_units = gone[gone["time_left"] != "SHORT"].groupby("item_id")["quantity"].sum()
    gone_units = gone_units.add(shrunk.groupby(p.loc[both, "item_id"]).sum(), fill_value=0)
    print("  most units gone (not SHORT) per item:")
    print(gone_units.sort_values(ascending=False).head(10).astype(int).to_string())


def compare(api: Api, ruleset: int) -> None:
    r = api.get(f"/data/wow/ruleset/{ruleset}/auctions/", "dynamic-forever")
    houses = [
        h for h in r.json().get("auctions", []) if "alliance" in str(h.get("name", "")).lower()
    ]
    ids: dict[int, set[int]] = {}
    rows = []
    for h in houses:
        try:
            df, lm = fetch(api, ruleset, h["id"])
        except httpx.HTTPStatusError as exc:
            print(f"house {h['id']}: HTTP {exc.response.status_code}")
            continue
        ids[h["id"]] = set(df["auction_id"])
        s = summarise(df[df["item_id"].isin(REFERENCE_ITEMS)]).set_index("item_id")
        rows.append(
            {
                "house": h["id"],
                "auctions": len(df),
                "last_modified": lm,
                **{f"q{i}": s["quantity"].get(i) for i in REFERENCE_ITEMS},
            }
        )
        print(f"house {h['id']}: {len(df)} auctions")
    print()
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nshared auction ids between houses:")
    keys = list(ids)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            print(f"  {a}-{b}: {len(ids[a] & ids[b])}")
    print("\nAHledger archive (forever.normal.alliance.eu), latest quantity per reference item:")
    try:
        import duckdb

        q = duckdb.sql(
            f"select item_id, arg_max(quantity, hour) quantity, max(hour) hour "
            f"from '{(ROOT / 'private' / 'hourly').as_posix()}/*.parquet' "
            f"where item_id in ({','.join(map(str, REFERENCE_ITEMS))}) group by 1 order by 1"
        ).df()
        print(q.to_string(index=False))
    except Exception as exc:  # research output only
        print(f"  not available: {exc}")


def save(out: Path, house: int, df: pd.DataFrame, summary: pd.DataFrame, lm: str | None) -> None:
    stamp = (parsedate_to_datetime(lm) if lm else datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = out / str(house)
    target.mkdir(parents=True, exist_ok=True)
    summary.assign(observed_at=stamp).to_parquet(target / f"summary-{stamp}.parquet", index=False)
    df.drop(columns=["buyout", "unit_price"]).to_parquet(
        target / f"listings-{stamp}.parquet", index=False
    )
    print(f"  saved to {target} ({stamp})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ruleset", type=int, default=2, help="2 = Normal (PvE)")
    ap.add_argument("--house", type=int, default=111, help="111 = Normal Alliance EU")
    ap.add_argument("--compare", action="store_true", help="compare all Alliance houses")
    ap.add_argument("--watch", type=float, help="poll every N minutes")
    ap.add_argument("--duration", type=float, default=120, help="watch for N minutes")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "blizzard")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    cid, secret, _ = load_credentials()
    with httpx.Client(timeout=180) as client:
        api = Api(client, get_token(client, cid, secret), "eu")
        if args.compare:
            compare(api, args.ruleset)
            return

        df, lm = fetch(api, args.ruleset, args.house)
        summary = summarise(df)
        print(f"house {args.house} ({time.strftime('%H:%M:%S')}):")
        report(df, summary, lm)
        if not args.no_save:
            save(args.out, args.house, df, summary, lm)
        if not args.watch:
            return

        end = time.monotonic() + args.duration * 60
        polls = 0
        while time.monotonic() < end:
            time.sleep(args.watch * 60)
            polls += 1
            new, new_lm = fetch(api, args.ruleset, args.house, since=lm)
            now = time.strftime("%H:%M:%S")
            if new is None or new_lm == lm:
                how = "304" if new is None else "200, same last-modified"
                print(f"{now} poll {polls}: not modified ({how}, still {lm})", flush=True)
                continue
            print(f"\n{now} poll {polls}: NEW data, last-modified {new_lm} (was {lm})", flush=True)
            diff(df, new)
            summary = summarise(new)
            if not args.no_save:
                save(args.out, args.house, new, summary, new_lm)
            df, lm = new, new_lm
            sys.stdout.flush()


if __name__ == "__main__":
    main()
