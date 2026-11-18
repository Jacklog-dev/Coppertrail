from datetime import UTC, datetime

import httpx
import pytest
from blizzard_fixtures import commodity, http_date, item_auction, item_detail, mock_transport

from coppertrail.collector.blizzard import BlizzardClient, BlizzardError
from coppertrail.collector.config import Blizzard

CFG = Blizzard(rate_per_s=1e9)
T0 = datetime(2026, 11, 18, 11, 22, 52, tzinfo=UTC)
ITEMS = "/data/wow/ruleset/2/auctions/111"
COMMS = "/data/wow/ruleset/2/auctions/111/commodities"


def client(routes, calls=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return BlizzardClient(
        CFG, "the-id", "the-secret", transport=mock_transport(routes, calls), sleep=sleeps.append
    )


def listing_routes(last_modified=T0, status=200):
    def items(req):
        if status == 304:
            return httpx.Response(304)
        body = {"auctions": [item_auction(1, 10, 2, buyout=200)]}
        headers = {
            "last-modified": http_date(last_modified),
            "battlenet-namespace": "dynamic-forever-eu",
        }
        return httpx.Response(status, json=body, headers=headers)

    def comms(req):
        if status == 304:
            return httpx.Response(304)
        body = {"auctions": [commodity(2, 20, 5, 30)]}
        return httpx.Response(
            status, json=body, headers={"last-modified": http_date(last_modified)}
        )

    return {ITEMS: items, COMMS: comms}


def test_token_and_headers_and_namespace():
    calls = []
    with client(listing_routes(), calls) as c:
        got = c.listings(None)
        c.listings(None)
    tokens = [r for r in calls if r.url.path == "/token"]
    assert len(tokens) == 1 and tokens[0].method == "POST"
    get = next(r for r in calls if r.url.path == ITEMS)
    assert get.headers["authorization"] == "Bearer tok"
    assert get.url.params["namespace"] == "dynamic-forever-eu"
    assert get.url.params["locale"] == "en_GB"
    assert get.url.host == "eu.api.blizzard.com"
    assert got.last_modified == T0 and got.namespace == "dynamic-forever-eu"
    assert got.items["auctions"][0]["id"] == 1 and got.commodities["auctions"][0]["id"] == 2


def test_if_modified_since_is_sent():
    calls = []
    with client(listing_routes(status=304), calls) as c:
        assert c.listings(T0) is None
    get = next(r for r in calls if r.url.path == ITEMS)
    assert get.headers["if-modified-since"] == http_date(T0)


def test_304_returns_none():
    with client(listing_routes(status=304)) as c:
        assert c.listings(T0) is None


def test_same_last_modified_returns_none():
    with client(listing_routes(last_modified=T0)) as c:
        assert c.listings(T0) is None


def test_429_honours_retry_after():
    seen = []

    def items(req):
        seen.append(req)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return listing_routes()[ITEMS](req)

    sleeps = []
    with client({**listing_routes(), ITEMS: items}, sleeps=sleeps) as c:
        assert c.listings(None) is not None
    assert 3.0 in sleeps


def test_401_refreshes_token_once_then_succeeds():
    seen, tokens = [], []

    def items(req):
        seen.append(req)
        if len(seen) == 1:
            return httpx.Response(401)
        return listing_routes()[ITEMS](req)

    def token(req):
        tokens.append(req)
        return httpx.Response(200, json={"access_token": f"tok{len(tokens)}"})

    with client({**listing_routes(), ITEMS: items, "/token": token}) as c:
        assert c.listings(None) is not None
    assert len(tokens) == 2 and seen[-1].headers["authorization"] == "Bearer tok2"


def test_two_401_raise_without_secrets():
    with client({ITEMS: lambda r: httpx.Response(401)}) as c, pytest.raises(BlizzardError) as e:
        c.listings(None)
    assert e.value.status == 401
    assert "the-secret" not in str(e.value) and "the-id" not in str(e.value)


def test_failed_token_raises_without_secrets():
    with client({"/token": lambda r: httpx.Response(401)}) as c, pytest.raises(BlizzardError) as e:
        c.listings(None)
    assert "the-secret" not in str(e.value) and "the-id" not in str(e.value)


def test_item_falls_back_to_classic1x():
    def item(req):
        if req.url.params["namespace"] == "static-forever-eu":
            return httpx.Response(404)
        headers = {"battlenet-namespace": "static-1.15.8_123-classic1x-eu"}
        return httpx.Response(200, json=item_detail(647), headers=headers)

    with client({"/data/wow/item/647": item}) as c:
        detail, ns = c.item(647)
    assert detail["id"] == 647 and ns == "static-1.15.8_123-classic1x-eu"


def test_item_unknown_everywhere():
    with client({}) as c:
        assert c.item(999999) == (None, "")


def test_house_index_uses_trailing_slash():
    calls = []
    body = {"auctions": [{"id": 110, "name": "Alliance Auction House"}, {"id": 111, "name": "X"}]}
    route = {"/data/wow/ruleset/2/auctions/": lambda r: httpx.Response(200, json=body)}
    with client(route, calls) as c:
        assert c.house_name() == "X"
    assert any(r.url.path == "/data/wow/ruleset/2/auctions/" for r in calls)


def test_static_namespace_from_header():
    headers = {"battlenet-namespace": "static-1.60.1_70399-forever-eu"}
    route = {"/data/wow/item-class/index": lambda r: httpx.Response(200, json={}, headers=headers)}
    with client(route) as c:
        assert c.static_namespace() == "static-1.60.1_70399-forever-eu"
