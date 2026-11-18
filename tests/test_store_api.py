from datetime import UTC, datetime, timedelta

import httpx
import pyarrow.parquet as pq
import pytest

from coppertrail.collector.legacy.api import AhledgerClient, ApiError, Throttle
from coppertrail.collector.legacy.config import Config
from coppertrail.collector.legacy.store import HOURLY, Store, to_arrow

T0 = datetime(2026, 11, 15, 22, tzinfo=UTC)


def _row(item, hour, minv, fetched):
    return {
        "item_id": item,
        "hour": hour,
        "min": minv,
        "p25": None,
        "median": None,
        "p75": None,
        "quantity": 1,
        "auctions": 1,
        "source": "api",
        "run_id": "r",
        "fetched_at": fetched,
    }


def test_upsert_is_idempotent_and_newest_wins(tmp_path):
    store = Store(tmp_path)
    f1 = T0 + timedelta(days=1)
    rows = [_row(1, T0 + timedelta(hours=h), 10, f1) for h in range(4)]  # spans two days
    written = store.upsert(HOURLY, to_arrow(HOURLY, rows))
    assert [p.name for p in written] == ["2026-11-15.parquet", "2026-11-16.parquet"]
    store.upsert(HOURLY, to_arrow(HOURLY, rows))
    assert store.read_all(HOURLY).num_rows == 4

    newer = [_row(1, T0, 99, f1 + timedelta(hours=1))]
    store.upsert(HOURLY, to_arrow(HOURLY, newer))
    older = [_row(1, T0, 5, f1 - timedelta(hours=1))]
    store.upsert(HOURLY, to_arrow(HOURLY, older))
    t = pq.read_table(store.day_path(HOURLY, T0.date())).to_pylist()
    assert [r["min"] for r in t] == [99, 10]
    assert pq.read_table(store.day_path(HOURLY, T0.date())).schema == HOURLY.schema


def test_upsert_keeps_unchanged_rows_and_files(tmp_path):
    """A refetch with the same values must not restamp rows or rewrite the day file,
    so git sees no change for days whose prices are final."""
    store = Store(tmp_path)
    f1 = T0 + timedelta(days=1)
    store.upsert(HOURLY, to_arrow(HOURLY, [_row(1, T0, 10, f1), _row(2, T0, 20, f1)]))
    path = store.day_path(HOURLY, T0.date())
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns

    refetch = [
        {**_row(1, T0, 10, f1 + timedelta(hours=5)), "run_id": "r2"},
        {**_row(2, T0, 20, f1 + timedelta(hours=5)), "run_id": "r2"},
    ]
    assert store.upsert(HOURLY, to_arrow(HOURLY, refetch)) == []
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime

    # One changed value and one new key: only those rows carry the new run.
    changed = [
        {**_row(1, T0, 11, f1 + timedelta(hours=6)), "run_id": "r3"},
        {**_row(2, T0, 20, f1 + timedelta(hours=6)), "run_id": "r3"},
        {**_row(3, T0, 30, f1 + timedelta(hours=6)), "run_id": "r3"},
    ]
    assert store.upsert(HOURLY, to_arrow(HOURLY, changed)) == [path]
    got = {
        r["item_id"]: (r["min"], r["run_id"], r["fetched_at"])
        for r in pq.read_table(path).to_pylist()
    }
    assert got == {
        1: (11, "r3", f1 + timedelta(hours=6)),
        2: (20, "r", f1),
        3: (30, "r3", f1 + timedelta(hours=6)),
    }


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_throttle_spacing():
    c = FakeClock()
    th = Throttle(2.0, clock=c.clock, sleep=c.sleep)
    for _ in range(3):
        th.wait()
    assert c.sleeps == [2.0, 2.0]


def test_retry_after_is_honoured():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "17"})
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = FakeClock()
    client = AhledgerClient(
        Config(),
        transport=httpx.MockTransport(handler),
        throttle=Throttle(2.0, clock=c.clock, sleep=c.sleep),
    )
    assert client.get("/x").json() == {"ok": True}
    assert c.sleeps == [17.0, 30.0]  # Retry-After, then the 503 default
    assert client.stats.requests == 3 and client.stats.retries == 2 and client.stats.errors == 0


def test_non_retryable_error():
    client = AhledgerClient(
        Config(), transport=httpx.MockTransport(lambda r: httpx.Response(404)), throttle=Throttle(0)
    )
    with pytest.raises(ApiError) as e:
        client.get("/x")
    assert e.value.status == 404 and client.stats.errors == 1
