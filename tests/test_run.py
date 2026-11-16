from datetime import UTC, datetime, timedelta

import httpx

from coppertrail.collector.api import AhledgerClient, Throttle
from coppertrail.collector.config import Config
from coppertrail.collector.run import EXIT_CUTOFF, EXIT_LOCKED, EXIT_OK, Collector
from coppertrail.collector.store import ECONOMY, GAPS, HOURLY, RUNS, SCANS, SNAPSHOT, WATCHLIST

NOW = datetime(2026, 11, 16, 20, 30, tzinfo=UTC)
MARKET = "forever.normal.alliance.eu"


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeApi:
    """Three bulk items (1, 2, 3; 3 is POOR) plus one pinned item (50)."""

    def __init__(self, fail_items=()):
        self.fail_items = set(fail_items)
        self.calls = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        self.calls.append((path, req.url.params.get("range")))
        if path == f"/v1/pricetable/{MARKET}":
            body = (
                "AHL1|forever/normal/alliance/eu|1794859989|3\n"
                "1:100:90:500:100:100:80:120:5000\n"
                "2:100:95:500:100:100:80:120:9000\n"
                "3:100:99:500:100:100:80:120:9000\n"
            )
            return httpx.Response(200, text=body)
        if path == f"/v1/tooltip/{MARKET}":
            ids = [int(i) for i in req.url.params["items"].split(",")]
            q = {3: "POOR"}
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": i,
                            "name": f"Item {i}",
                            "quality": q.get(i, "COMMON"),
                            "itemClass": "Trade Goods",
                            "level": 1,
                        }
                        for i in ids
                    ]
                },
            )
        if path.startswith(f"/v1/prices/{MARKET}/"):
            iid = int(path.rsplit("/", 1)[1])
            if iid in self.fail_items:
                return httpx.Response(404)
            rng = req.url.params["range"]
            base = NOW.replace(minute=0) - timedelta(hours=3)
            step = timedelta(hours=1) if rng == "7d" else timedelta(minutes=20)
            series = [
                {
                    "t": iso(base + k * step),
                    "min": iid,
                    "median": 3,
                    "p25": 2,
                    "p75": 4,
                    "quantity": 10,
                    "auctions": 2,
                }
                for k in range(3)
            ]
            return httpx.Response(200, json={"series": series})
        if path == f"/v1/economy/{MARKET}":
            return httpx.Response(
                200,
                json={
                    "market": MARKET,
                    "current": {
                        "observedAt": iso(NOW),
                        "newestScanAt": iso(NOW),
                        "value": 5,
                        "auctions": 1,
                        "units": 2,
                        "items": 3,
                        "scansInWindow": 4,
                        "contributors": 5,
                    },
                    "daily": [
                        {"day": "2026-11-15", "value": 4, "auctions": 1, "units": 2, "scans": 9}
                    ],
                },
            )
        if req.url.host == "ahledger.com":
            return httpx.Response(429, headers={"Content-Type": "text/html"}, text="<html>")
        return httpx.Response(404)


def make(tmp_path, api, now=NOW, **cfg_kw):
    cfg = Config(pinned=(50,), scans_top_n=1, **cfg_kw)
    client = AhledgerClient(cfg, transport=httpx.MockTransport(api), throttle=Throttle(0))
    return Collector(cfg, tmp_path, client=client, now=lambda: now)


def test_full_run(tmp_path):
    api = FakeApi()
    assert make(tmp_path, api).run() == EXIT_OK
    c = make(tmp_path, api)
    st = c.store
    wl = st.read_all(WATCHLIST).sort_by("rank").to_pylist()
    assert [(r["item_id"], r["reason"], r["scans"]) for r in wl] == [
        (2, "bulk", True),
        (1, "bulk", False),
        (50, "pinned", False),
    ]
    assert st.read_all(HOURLY).num_rows == 9
    assert set(st.read_all(HOURLY).column("source").to_pylist()) == {"api"}
    assert st.read_all(SCANS).num_rows == 3
    assert st.read_all(SNAPSHOT).num_rows == 3
    assert st.read_all(ECONOMY).num_rows == 2
    run = st.read_all(RUNS).to_pylist()[0]
    assert run["status"] == "ok" and run["hourly_done"] == 3
    assert "population CSV skipped" in run["notes"]
    assert st.read_all(GAPS).num_rows == 3
    assert st.staged_runs() == []
    assert not (tmp_path / ".collector.lock").exists()


def test_rerun_is_idempotent(tmp_path):
    api = FakeApi()
    make(tmp_path, api).run()
    later = NOW + timedelta(minutes=5)
    make(tmp_path, api, now=later).run()
    c = make(tmp_path, api)
    assert c.store.read_all(HOURLY).num_rows == 9
    assert c.store.read_all(SCANS).num_rows == 3
    assert c.store.read_all(RUNS).num_rows == 2


def test_interrupted_run_resumes_without_refetching(tmp_path):
    api = FakeApi()
    c = make(tmp_path, api)
    # Simulate a crash after the first hourly item: stage watchlist and one item by hand.
    c.lock.acquire()
    from coppertrail.collector.run import RunState

    c.state = RunState(
        run_id="20261116T200000Z", started_at=(NOW - timedelta(minutes=30)).isoformat()
    )
    c.store.run_dir(c.state.run_id).mkdir(parents=True)
    c._sync_stats()
    watch = c._watchlist(c.state, NOW - timedelta(minutes=30))
    c._series(c.state, watch[:1], HOURLY, "7d", "hour", NOW)
    c.lock.release()  # the process "died"; lock release mimics a stale lock being cleared

    api.calls.clear()
    assert make(tmp_path, api).run() == EXIT_OK
    price_calls = [p for p, r in api.calls if "/prices/" in p and r == "7d"]
    assert len(price_calls) == 2  # item 2 was already staged
    assert not any("pricetable" in p for p, _ in api.calls)
    c2 = make(tmp_path, api)
    runs = c2.store.read_all(RUNS).to_pylist()
    assert [r["run_id"] for r in runs] == ["20261116T200000Z"]
    assert c2.store.read_all(HOURLY).num_rows == 9


def test_partial_failures(tmp_path):
    api = FakeApi(fail_items={1})
    assert make(tmp_path, api).run() == 1  # 1 of 3 failed is above the 5 % threshold
    run = make(tmp_path, api).store.read_all(RUNS).to_pylist()[0]
    assert run["status"] == "failed" and run["errors"] >= 1


def test_lock_blocks_second_instance(tmp_path):
    c = make(tmp_path, FakeApi())
    c.lock.acquire()
    assert make(tmp_path, FakeApi()).run() == EXIT_LOCKED


def test_cutoff_blocks_run(tmp_path):
    api = FakeApi()
    assert make(tmp_path, api, now=datetime(2026, 12, 10, tzinfo=UTC)).run() == EXIT_CUTOFF
    assert api.calls == []


def test_sticky_items(tmp_path):
    api = FakeApi()
    make(tmp_path, api).run()

    class Shrunk(FakeApi):
        def __call__(self, req):
            if "pricetable" in req.url.path:
                return httpx.Response(
                    200,
                    text="AHL1|forever/normal/alliance/eu|1794869989|1\n"
                    "2:100:95:500:100:100:80:120:9000\n",
                )
            return super().__call__(req)

    make(tmp_path, Shrunk(), now=NOW + timedelta(days=1)).run()
    c = make(tmp_path, api)
    wl = c.store.query(
        "SELECT item_id, reason FROM {w} WHERE run_id = "
        "(SELECT max(run_id) FROM {w}) ORDER BY rank",
        w=WATCHLIST.name,
    ).to_pylist()
    assert {r["item_id"]: r["reason"] for r in wl} == {2: "bulk", 1: "sticky", 50: "pinned"}
