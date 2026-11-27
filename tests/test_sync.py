"""Our database and the sync from the Pi's export. Hand-made fixtures, no network."""

from __future__ import annotations

import gzip
import io
import json

from coppertrail import db
from coppertrail import sync as s

H1 = "2026-11-25T10:23:05Z"  # hour 10:00 UTC
H2 = "2026-11-25T11:23:01Z"
T1 = s.epoch("2026-11-25T10:00:00Z")
T2 = T1 + 3600


def snapshot(sid, endpoint, lm, auctions, gz=True):
    body = json.dumps({"auctions": auctions}).encode()
    if gz:
        body = gzip.compress(body)
    head = {"table": "snapshot", "id": sid, "endpoint": endpoint, "last_modified": lm,
            "fetched_at": lm, "namespace": "ns", "encoding": "gzip" if gz else "identity",
            "size": len(body)}  # fmt: skip
    return head, body


def item(seq, item_id, name=None, quality="COMMON", class_id=7, fetched="2026-11-25T10:01:00Z"):
    details = {"id": item_id, "name": name, "quality": {"type": quality, "name": quality.title()},
               "item_class": {"id": class_id, "name": "x"}}  # fmt: skip
    body = json.dumps(details).encode() if name else b""
    head = {"table": "item", "seq": seq, "item_id": item_id, "namespace": "ns" if name else None,
            "status": 200 if name else 404, "fetched_at": fetched,
            "encoding": "identity" if name else None, "size": len(body)}  # fmt: skip
    return head, body


class Stream:
    def __init__(self, buf):
        self.stream = buf

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class FakePi:
    """Serves export streams from a list of rows, honouring the bookmarks like the Pi.

    `fail_after=N` cuts a real export (not the maxima probe) after N rows, without end line.
    """

    def __init__(self, rows, fail_after=None):
        self.rows, self.fail_after, self.calls = rows, fail_after, []

    def __call__(self, after_snapshot, after_item):
        self.calls.append((after_snapshot, after_item))
        probe = after_snapshot >= 2**60
        snaps = [
            r for r in self.rows if r[0]["table"] == "snapshot" and r[0]["id"] > after_snapshot
        ]
        items = [r for r in self.rows if r[0]["table"] == "item" and r[0]["seq"] > after_item]
        sent = snaps + items
        cut = self.fail_after is not None and not probe
        if cut:
            sent = sent[: self.fail_after]
        out = io.BytesIO()
        for head, body in sent:
            out.write(json.dumps(head).encode() + b"\n" + body)
        if not cut:
            ids = [h["id"] for h, _ in self.rows if h["table"] == "snapshot"] or [0]
            seqs = [h["seq"] for h, _ in self.rows if h["table"] == "item"] or [0]
            end = {"end": True, "snapshot_max": max(ids), "item_max": max(seqs)}
            out.write(json.dumps(end).encode() + b"\n")
        out.seek(0)
        return Stream(out)


ROWS = [
    snapshot(1, "items", H1, [
        {"id": 1, "item": {"id": 10}, "buyout": 900, "quantity": 3},  # 300 per unit
        {"id": 2, "item": {"id": 10}, "buyout": 500, "quantity": 1},
        {"id": 3, "item": {"id": 11}, "bid": 50, "quantity": 1},  # bid only: no price
    ]),
    snapshot(2, "commodities", H1, [
        {"id": 4, "item": {"id": 20}, "unit_price": 1500, "quantity": 20},
        {"id": 5, "item": {"id": 20}, "unit_price": 1200, "quantity": 1},
    ]),
    snapshot(3, "items", H2, [{"id": 6, "item": {"id": 10}, "buyout": 400, "quantity": 1}],
             gz=False),
    snapshot(4, "commodities", H2, [{"id": 7, "item": {"id": 20}, "unit_price": 1300,
                                     "quantity": 5}]),
    item(1, 10, "Linen Cloth"),
    item(2, 20, "Copper Ore"),
    item(3, 99),  # unknown to Blizzard
]  # fmt: skip


def con(tmp_path):
    return db.connect(tmp_path / "our.sqlite")


def test_lowest_price_per_unit_and_bid_only_ignored():
    head, body = ROWS[0]
    assert s.lowest_prices(s.decode(body, head["encoding"])) == {10: 300}
    assert s.lowest_prices({"auctions": []}) == {}


def test_sync_stores_lowest_price_per_item_and_hour(tmp_path):
    c = con(tmp_path)
    result = s.sync(c, FakePi(ROWS), now=lambda: T2)
    assert result.ok and (result.snapshots, result.items) == (4, 3)
    assert sorted(c.execute("SELECT item_id, at, low FROM price")) == [
        (10, T1, 300), (10, T2, 400), (20, T1, 1200), (20, T2, 1300),
    ]  # fmt: skip
    assert db.hour_span(c) == (2, T1, T2)
    assert sorted(db.listed_now(c)) == [(10, "Linen Cloth", 7, 400), (20, "Copper Ore", 7, 1300)]
    assert db.bookmarks(c) == (4, 3)


def test_second_sync_reads_only_new_rows(tmp_path):
    c = con(tmp_path)
    pi = FakePi(ROWS[:2])
    s.sync(c, pi, now=lambda: T2)
    pi.rows = ROWS
    result = s.sync(c, pi, now=lambda: T2)
    assert (result.snapshots, result.items) == (2, 3)
    assert pi.calls[-1] == (2, 0)
    assert db.history(c, 10) == [(T1, 300), (T2, 400)]


def test_same_hour_twice_keeps_the_lower_price(tmp_path):
    c = con(tmp_path)
    again = snapshot(5, "items", H1, [{"id": 8, "item": {"id": 10}, "buyout": 250, "quantity": 1}])
    s.sync(c, FakePi([ROWS[0], again]), now=lambda: T2)
    assert db.history(c, 10) == [(T1, 250)]


def test_history_has_gaps_where_the_item_was_not_listed(tmp_path):
    c = con(tmp_path)
    s.sync(c, FakePi(ROWS[:3]), now=lambda: T2)
    assert db.history(c, 20) == [(T1, 1200), (T2, None)]
    assert db.history(c, 20, since=T2) == [(T2, None)]


def test_broken_stream_keeps_what_was_read(tmp_path):
    c = con(tmp_path)
    result = s.sync(c, FakePi(ROWS, fail_after=2), now=lambda: T2)
    assert not result.ok and "ended early" in result.message
    assert db.bookmarks(c) == (2, 0)
    assert db.hour_span(c)[0] == 1
    result = s.sync(c, FakePi(ROWS), now=lambda: T2)  # the next sync carries on
    assert result.ok and db.bookmarks(c) == (4, 3)


def test_item_details_older_than_30_days_are_deleted(tmp_path):
    c = con(tmp_path)
    s.sync(c, FakePi(ROWS), now=lambda: T2 + 31 * 86400)
    assert c.execute("SELECT count(*) FROM item").fetchone() == (0,)


def test_older_details_never_replace_newer_ones(tmp_path):
    c = con(tmp_path)
    db.set_item(c, 10, "New", "COMMON", 7, 200)
    db.set_item(c, 10, "Old", "COMMON", 7, 100)
    assert db.item_name(c, 10) == "New"


def test_unwanted_rule():
    assert db.unwanted("POOR", 7)  # gray
    assert db.unwanted("RARE", 9) and db.unwanted("EPIC", 9)  # recipes
    assert db.unwanted("RARE", 2) and db.unwanted("UNCOMMON", 4)  # equipment below epic
    assert not db.unwanted("EPIC", 2) and not db.unwanted("EPIC", 4)
    assert not db.unwanted("COMMON", 7) and not db.unwanted("RARE", 0)
    assert not db.unwanted(None, None)  # unknown to Blizzard: kept


LISTED = [
    snapshot(1, "items", H1, [
        {"id": n, "item": {"id": iid}, "buyout": 100 + n, "quantity": 1}
        for n, iid in enumerate([30, 31, 32, 33, 34, 35, 36])
    ]),
    item(1, 30, "Gray Junk", "POOR", 15),
    item(2, 31, "Pattern: Something", "RARE", 9),
    item(3, 32, "Green Sword", "UNCOMMON", 2),
    item(4, 33, "Blue Helm", "RARE", 4),
    item(5, 34, "Epic Sword", "EPIC", 2),
    item(6, 35, "Mithril Bar", "COMMON", 7),
]  # 36: no details yet, kept  # fmt: skip


def test_unwanted_items_lose_their_prices(tmp_path):
    c = con(tmp_path)
    s.sync(c, FakePi(LISTED), now=lambda: T2)
    assert sorted(i for i, *_ in db.listed_now(c)) == [34, 35, 36]
    assert db.unwanted_ids(c) == {30, 31, 32, 33}


def test_known_unwanted_items_are_not_stored_again(tmp_path):
    c = con(tmp_path)
    pi = FakePi(LISTED)
    s.sync(c, pi, now=lambda: T2)
    pi.rows = [*LISTED, snapshot(2, "items", H2, [{"id": 9, "item": {"id": 30}, "buyout": 5,
                                                   "quantity": 1}])]  # fmt: skip
    s.sync(c, pi, now=lambda: T2)
    assert db.history(c, 30) == [(T1, None), (T2, None)]


def test_old_names_table_is_replaced_and_details_read_again(tmp_path):
    path = tmp_path / "our.sqlite"
    old = db.sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE name (item_id INTEGER PRIMARY KEY, name TEXT, fetched_at INTEGER);"
        "CREATE TABLE bookmark (key TEXT PRIMARY KEY, value INTEGER NOT NULL);"
        "INSERT INTO bookmark VALUES ('snapshot', 48), ('item', 7417);"
    )
    old.commit()
    old.close()
    c = db.connect(path)
    assert db.bookmarks(c) == (48, 0)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'name'").fetchone()


def test_progress_counts_snapshots(tmp_path):
    seen = []
    s.sync(con(tmp_path), FakePi(ROWS), progress=lambda d, t: seen.append((d, t)), now=lambda: T2)
    assert seen[0] == (0, 4) and seen[-1] == (4, 4)


def test_export_command_passes_only_the_bookmarks(monkeypatch):
    calls = []

    class Proc:
        def __init__(self, cmd, **kw):
            calls.append(cmd)
            self.stdout = io.BytesIO()

    monkeypatch.setattr(s.subprocess, "Popen", Proc)
    monkeypatch.delenv("COPPERTRAIL_PI", raising=False)
    s.Export(7, 9)
    (cmd,) = calls
    assert cmd[0] == "ssh" and "BatchMode=yes" in cmd
    assert cmd[-2] == "coppertrail@coppertrail-pi"
    assert cmd[-1].endswith("export --after-snapshot 7 --after-item 9")
