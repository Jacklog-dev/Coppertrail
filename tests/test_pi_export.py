"""The Pi's export stream for the PC (pi/coppertrail_raw.py `export`). Hand-made fixtures."""

from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "coppertrail_raw", Path(__file__).parents[1] / "pi" / "coppertrail_raw.py"
)
raw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(raw)

LM = datetime(2026, 11, 24, 12, 22, 55, tzinfo=UTC)
FETCHED = datetime(2026, 11, 24, 12, 27, 3, tzinfo=UTC)


def db(tmp_path: Path) -> Path:
    return tmp_path / "raw.sqlite"


def read_stream(data: bytes) -> tuple[list[tuple[dict, bytes]], dict]:
    """Parse an export: (header, body) records and the end line."""
    buf = io.BytesIO(data)
    records = []
    while True:
        header = json.loads(buf.readline())
        if header.get("end"):
            assert buf.read() == b""
            return records, header
        records.append((header, buf.read(header["size"])))


def seed(tmp_path, snapshots=3, items=2) -> sqlite3.Connection:
    con = raw.connect(db(tmp_path))
    for h in range(snapshots):
        body = f"body-{h}".encode()
        raw.store_snapshot(con, "items", LM + timedelta(hours=h), "ns", body, "identity", FETCHED)
    for i in range(items):
        raw.store_item(
            con, 100 + i, "static-forever-eu", 200, f"item-{i}".encode(), "identity", FETCHED
        )
    return con


def export(tmp_path, after_snapshot=0, after_item=0):
    out = io.BytesIO()
    counts = raw.export(db(tmp_path), out, after_snapshot, after_item)
    return counts, read_stream(out.getvalue())


def test_export_streams_new_rows_in_order(tmp_path):
    seed(tmp_path).close()
    counts, (records, end) = export(tmp_path, after_snapshot=1)
    assert counts == (2, 2)
    snaps = [(h, b) for h, b in records if h["table"] == "snapshot"]
    items = [(h, b) for h, b in records if h["table"] == "item"]
    assert [h["id"] for h, _ in snaps] == [2, 3]
    assert [b for _, b in snaps] == [b"body-1", b"body-2"]
    assert snaps[0][0] == {
        "table": "snapshot",
        "id": 2,
        "endpoint": "items",
        "last_modified": "2026-11-24T13:22:55Z",
        "fetched_at": "2026-11-24T12:27:03Z",
        "namespace": "ns",
        "encoding": "identity",
        "size": 6,
    }
    assert [h["seq"] for h, _ in items] == [1, 2]
    assert items[0] == (
        {
            "table": "item",
            "seq": 1,
            "item_id": 100,
            "namespace": "static-forever-eu",
            "status": 200,
            "fetched_at": "2026-11-24T12:27:03Z",
            "encoding": "identity",
            "size": 6,
        },
        b"item-0",
    )
    assert records.index(snaps[-1]) < records.index(items[0])  # snapshots first
    assert end == {"end": True, "snapshot_max": 3, "item_max": 2}


def test_export_404_item_has_no_bytes(tmp_path):
    con = seed(tmp_path, snapshots=0, items=0)
    raw.store_item(con, 5, None, 404, None, None, FETCHED)
    raw.store_item(con, 6, "static-forever-eu", 200, b"x", "identity", FETCHED)
    con.close()
    _, (records, _) = export(tmp_path)
    assert records[0][0]["size"] == 0 and records[0][1] == b""
    assert records[0][0]["encoding"] is None
    assert records[1] == (records[1][0], b"x")


def test_old_bookmark_gets_everything_left(tmp_path):
    con = seed(tmp_path, items=0)
    raw.prune(con, LM + timedelta(days=30) - timedelta(minutes=30))  # deletes id 1 only
    con.close()
    _, (records, end) = export(tmp_path)
    assert [h["id"] for h, _ in records] == [2, 3]
    assert end["snapshot_max"] == 3


def test_export_during_open_write_sees_committed_rows(tmp_path):
    seed(tmp_path, snapshots=1, items=0).close()
    writer = sqlite3.connect(db(tmp_path))
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT INTO snapshot"
        " (endpoint, last_modified, fetched_at, namespace, encoding, size, body)"
        " VALUES ('items', '2026-11-25T00:00:00Z', 'x', 'ns', 'identity', 1, x'00')"
    )
    try:
        _, (records, end) = export(tmp_path)
    finally:
        writer.rollback()
        writer.close()
    assert [h["id"] for h, _ in records] == [1]
    assert end["snapshot_max"] == 1


def test_export_of_missing_db(tmp_path, capsysbinary, monkeypatch):
    counts, (records, end) = export(tmp_path)
    assert counts == (0, 0) and records == []
    assert end == {"end": True, "snapshot_max": 0, "item_max": 0}
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)  # export needs no credentials
    assert raw.main(["--db", str(db(tmp_path)), "export"]) == 0
    assert read_stream(capsysbinary.readouterr().out) == ([], end)
    assert not db(tmp_path).exists()


def test_export_never_writes(tmp_path):
    seed(tmp_path).close()
    before = db(tmp_path).stat().st_mtime_ns
    export(tmp_path)
    assert db(tmp_path).stat().st_mtime_ns == before
    con = sqlite3.connect(db(tmp_path))
    assert con.execute("SELECT count(*) FROM snapshot").fetchone() == (3,)
    con.close()


def test_main_export_writes_only_the_stream_to_stdout(tmp_path, capsysbinary):
    seed(tmp_path).close()
    assert raw.main(["--db", str(db(tmp_path)), "export", "--after-snapshot", "2"]) == 0
    out = capsysbinary.readouterr()
    records, end = read_stream(out.out)
    assert [h.get("id") for h, _ in records if h["table"] == "snapshot"] == [3]
    assert b"exported" in out.err
