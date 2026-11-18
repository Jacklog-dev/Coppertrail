"""Blizzard Game Data API client for WoW Forever.

One OAuth client-credentials token per client (refreshed once on 401), a request
throttle, and retries on 429/5xx that honour `Retry-After`. Errors never carry the
client id, the secret or the token.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime

import httpx

from .config import Blizzard
from .throttle import Throttle, parse_retry_after

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth.battle.net/token"
DYNAMIC = "dynamic-forever"
STATIC = "static-forever"
STATIC_FALLBACK = "static-classic1x"
_RETRY = {429, 500, 502, 503, 504}
_OK = {200, 304, 404}


class BlizzardError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Fetched:
    items: dict
    commodities: dict
    last_modified: datetime
    namespace: str


def _last_modified(r: httpx.Response) -> datetime | None:
    value = r.headers.get("last-modified")
    if not value:
        return None
    return parsedate_to_datetime(value).astimezone(UTC)


class BlizzardClient:
    def __init__(
        self,
        cfg: Blizzard,
        client_id: str,
        client_secret: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cfg = cfg
        self._auth = (client_id, client_secret)
        self._sleep = sleep
        self._throttle = Throttle(1.0 / cfg.rate_per_s, sleep=sleep)
        self._http = httpx.Client(
            transport=transport,
            timeout=cfg.timeout_s,
            headers={"Accept-Encoding": "gzip"},
        )
        self._token: str | None = None
        self.base = f"https://{cfg.region}.api.blizzard.com"
        self.requests = 0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BlizzardClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # Low level ---------------------------------------------------------------

    def _new_token(self) -> str:
        try:
            r = self._http.post(
                TOKEN_URL, data={"grant_type": "client_credentials"}, auth=self._auth
            )
        except httpx.TransportError as exc:
            raise BlizzardError(f"token request failed: {type(exc).__name__}") from None
        if r.status_code != 200:
            raise BlizzardError(f"token request failed: HTTP {r.status_code}", r.status_code)
        self._token = r.json()["access_token"]
        return self._token

    def get(
        self, path: str, namespace: str, if_modified_since: datetime | None = None
    ) -> httpx.Response:
        """GET with namespace, locale and token. Returns 200, 304 and 404 responses;
        raises BlizzardError for anything else once retries are used up."""
        params = {"namespace": f"{namespace}-{self.cfg.region}", "locale": self.cfg.locale}
        headers = {}
        if if_modified_since is not None:
            headers["If-Modified-Since"] = format_datetime(if_modified_since, usegmt=True)
        refreshed = False
        status = None
        for attempt in range(self.cfg.max_retries + 1):
            token = self._token or self._new_token()
            self._throttle.wait()
            self.requests += 1
            try:
                r = self._http.get(
                    self.base + path,
                    params=params,
                    headers={**headers, "Authorization": f"Bearer {token}"},
                )
            except httpx.TransportError as exc:
                status = None
                log.warning("%s: %s, retrying", path, type(exc).__name__)
                self._sleep(2.0**attempt)
                continue
            status = r.status_code
            if status in _OK:
                return r
            if status == 401 and not refreshed:
                refreshed = True
                self._new_token()
                continue
            if status in _RETRY:
                wait = parse_retry_after(r.headers.get("retry-after"), 2.0**attempt)
                log.warning("%s: HTTP %s, waiting %.0fs", path, status, wait)
                self._sleep(wait)
                continue
            break
        raise BlizzardError(f"{path}: HTTP {status}", status)

    def json(self, path: str, namespace: str) -> dict:
        r = self.get(path, namespace)
        if r.status_code != 200:
            raise BlizzardError(f"{path}: HTTP {r.status_code}", r.status_code)
        return r.json()

    # Endpoints ---------------------------------------------------------------

    def _house_path(self) -> str:
        return f"/data/wow/ruleset/{self.cfg.ruleset}/auctions/{self.cfg.house}"

    def house_name(self) -> str:
        index = self.json(f"/data/wow/ruleset/{self.cfg.ruleset}/auctions/", DYNAMIC)
        for house in index.get("auctions", []):
            if house.get("id") == self.cfg.house:
                return str(house.get("name", ""))
        raise BlizzardError(f"house {self.cfg.house} is not in ruleset {self.cfg.ruleset}")

    def listings(self, since: datetime | None) -> Fetched | None:
        """Both listing endpoints of the house, or None when nothing is newer than `since`."""
        bodies = []
        stamps = []
        namespace = ""
        for path in (self._house_path(), self._house_path() + "/commodities"):
            r = self.get(path, DYNAMIC, if_modified_since=since)
            if r.status_code == 304:
                return None
            if r.status_code != 200:
                raise BlizzardError(f"{path}: HTTP {r.status_code}", r.status_code)
            lm = _last_modified(r)
            if lm is None:
                raise BlizzardError(f"{path}: no Last-Modified header")
            if since is not None and lm <= since:
                return None
            namespace = namespace or r.headers.get("battlenet-namespace", "")
            bodies.append(r.json())
            stamps.append(lm)
        return Fetched(
            items=bodies[0],
            commodities=bodies[1],
            last_modified=stamps[0],
            namespace=namespace or f"{DYNAMIC}-{self.cfg.region}",
        )

    def item(self, item_id: int) -> tuple[dict | None, str]:
        for ns in (STATIC, STATIC_FALLBACK):
            r = self.get(f"/data/wow/item/{item_id}", ns)
            if r.status_code == 200:
                return r.json(), r.headers.get("battlenet-namespace", f"{ns}-{self.cfg.region}")
        return None, ""

    def media_icon(self, item_id: int) -> int | None:
        """The item's icon file id (`file_data_id` of the "icon" asset), or None if unknown."""
        for ns in (STATIC, STATIC_FALLBACK):
            r = self.get(f"/data/wow/media/item/{item_id}", ns)
            if r.status_code != 200:
                continue
            for asset in r.json().get("assets", []):
                if asset.get("key") == "icon" and asset.get("file_data_id"):
                    return int(asset["file_data_id"])
        return None

    def static_namespace(self) -> str:
        r = self.get("/data/wow/item-class/index", STATIC)
        if r.status_code != 200:
            raise BlizzardError(f"item-class index: HTTP {r.status_code}", r.status_code)
        return r.headers.get("battlenet-namespace", "")
