"""Hand-made Blizzard API payloads and a routing mock transport (no real auction data)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from email.utils import format_datetime

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


def item_auction(
    id: int,
    item_id: int,
    qty: int,
    buyout: int | None = None,
    bid: int | None = None,
    time_left: str = "LONG",
) -> dict:
    a = {"id": id, "item": {"id": item_id}, "quantity": qty, "time_left": time_left}
    if buyout is not None:
        a["buyout"] = buyout
    if bid is not None:
        a["bid"] = bid
    return a


def commodity(id: int, item_id: int, qty: int, unit_price: int, time_left: str = "LONG") -> dict:
    return {
        "id": id,
        "item": {"id": item_id},
        "quantity": qty,
        "unit_price": unit_price,
        "time_left": time_left,
    }


def item_detail(
    item_id: int,
    quality: str = "COMMON",
    cls: str = "Trade Goods",
    cls_id: int = 7,
    sub: str = "Cloth",
    sub_id: int = 5,
    sell: int = 10,
    name: str | None = None,
) -> dict:
    return {
        "id": item_id,
        "name": name or f"Item {item_id}",
        "quality": {"type": quality, "name": quality.title()},
        "level": 5,
        "required_level": 0,
        "item_class": {"name": cls, "id": cls_id},
        "item_subclass": {"name": sub, "id": sub_id},
        "sell_price": sell,
        "purchase_price": sell * 4,
    }


def http_date(t: datetime) -> str:
    return format_datetime(t, usegmt=True)


def token_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 86399})


def mock_transport(routes: dict[str, Handler], calls: list | None = None) -> httpx.MockTransport:
    """Route by URL path; the token endpoint answers by default. Unrouted paths give 404."""
    routes = {"/token": token_ok, **routes}

    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        handler = routes.get(request.url.path)
        return handler(request) if handler else httpx.Response(404)

    return httpx.MockTransport(handle)
