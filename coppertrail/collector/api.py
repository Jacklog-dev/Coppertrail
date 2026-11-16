"""Throttled, read-only HTTP client for the AHledger API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from .config import Config

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Stats:
    requests: int = 0
    errors: int = 0
    retries: int = 0


def parse_retry_after(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        return default


class Throttle:
    """Keeps a minimum interval between request starts."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval_s = interval_s
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = now + self.interval_s

    def push_back(self, seconds: float) -> None:
        """Delay the next request by at least `seconds` from now (Retry-After)."""
        self._next = max(self._next, self._clock() + seconds)


class AhledgerClient:
    def __init__(
        self,
        cfg: Config,
        transport: httpx.BaseTransport | None = None,
        throttle: Throttle | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cfg = cfg
        self.stats = Stats()
        self.throttle = throttle or Throttle(cfg.rate_interval_s())
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=cfg.base_url,
            headers={"User-Agent": cfg.user_agent, "Accept-Encoding": "gzip"},
            timeout=cfg.timeout_s,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AhledgerClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(
        self, url: str, params: dict | None = None, retries: int | None = None
    ) -> httpx.Response:
        """GET with throttling. Retries on 429/5xx (honouring Retry-After) and network errors."""
        max_retries = self.cfg.max_retries if retries is None else retries
        attempt = 0
        while True:
            self.throttle.wait()
            self.stats.requests += 1
            try:
                resp = self._http.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt >= max_retries:
                    self.stats.errors += 1
                    raise ApiError(f"GET {url} failed: {exc!r}") from exc
                delay = min(5.0 * 3**attempt, self.cfg.max_retry_after_s)
                log.warning("GET %s: %r, retry in %.0fs", url, exc, delay)
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in RETRY_STATUS or attempt >= max_retries:
                    self.stats.errors += 1
                    raise ApiError(f"GET {url} -> HTTP {resp.status_code}", resp.status_code)
                default = 30.0 if resp.status_code in (429, 503) else 5.0 * 3**attempt
                delay = min(
                    parse_retry_after(resp.headers.get("Retry-After"), default),
                    self.cfg.max_retry_after_s,
                )
                log.warning("GET %s -> HTTP %s, retry in %.0fs", url, resp.status_code, delay)
            attempt += 1
            self.stats.retries += 1
            self.throttle.push_back(delay)

    # Endpoints -----------------------------------------------------------------

    def pricetable(self) -> str:
        return self.get(f"/v1/pricetable/{self.cfg.market}").text

    def prices(self, item_id: int, range_: str) -> dict:
        return self.get(f"/v1/prices/{self.cfg.market}/{item_id}", params={"range": range_}).json()

    def tooltip(self, item_ids: list[int]) -> dict:
        if len(item_ids) > 100:
            raise ValueError("tooltip takes at most 100 items")
        items = ",".join(str(i) for i in item_ids)
        return self.get(f"/v1/tooltip/{self.cfg.market}", params={"items": items}).json()

    def economy(self) -> dict:
        return self.get(f"/v1/economy/{self.cfg.market}").json()

    def population_csv(self) -> str:
        """The population CSV lives on the website, not the API. No retries: the site
        sits behind a bot check that scripts do not pass, and we do not try to."""
        resp = self.get(self.cfg.population_url, retries=0)
        ctype = resp.headers.get("Content-Type", "")
        if "html" in ctype:
            raise ApiError(f"population CSV returned {ctype}, not CSV")
        return resp.text
