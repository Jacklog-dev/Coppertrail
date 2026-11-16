"""Collector configuration: defaults in code, optional overrides from a TOML file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

# Jack's leather chain plus the scarce goods from HANDOVER section 7. Ids checked
# against /v1/tooltip on 2026-11-16.
DEFAULT_PINNED: tuple[int, ...] = (
    # Leathers
    2934,
    2318,
    2319,
    4234,
    4304,
    8170,
    15417,
    # Hides and cured hides
    783,
    4232,
    4235,
    8169,
    8171,
    4231,
    4233,
    4236,
    8172,
    15407,
    # Armor kits
    2304,
    2313,
    4265,
    8173,
    15564,
    # Scarce goods: Black Lotus, Arcane Crystal, Arcanite Bar, Mooncloth, Righteous Orb
    13468,
    12363,
    12360,
    14342,
    12811,
)


@dataclass
class Config:
    market: str = "forever.normal.alliance.eu"
    base_url: str = "https://api.ahledger.com"
    population_url: str = "https://ahledger.com/wow-forever/population/data.csv"
    user_agent: str = "Coppertrail-collector/0.1 (+https://github.com/Jacklog-dev/Coppertrail)"

    # API archiving. AHledger's terms change on 2026-12-10: keeping answers past
    # their cache time then needs the Data licence. Whether to continue is Jack's call.
    api_archive_enabled: bool = True
    api_archive_until: date = date(2026, 12, 9)
    warn_days_before_cutoff: int = 14

    # Rate limiting (keyless limit from 2026-12-10).
    requests_per_minute: float = 30.0
    max_retries: int = 5
    max_retry_after_s: float = 600.0
    timeout_s: float = 60.0

    # Watchlist rules (HANDOVER section 2), joined by OR.
    bulk_min_sales_per_day: float = 100.0
    bulk_min_quantity: int = 50
    valuable_min_gold_per_day: float = 200.0  # sales per day x median, in gold
    valuable_min_sales_per_day: float = 20.0
    exclude_qualities: tuple[str, ...] = ("POOR",)
    sticky_days: int = 3  # keep an item this many days after it falls below the rules
    pinned: tuple[int, ...] = DEFAULT_PINNED
    max_items: int | None = None  # cap the watchlist (testing only)

    # Per-scan data (secondary): top N watchlist items by turnover.
    scans_top_n: int = 200
    fetch_scans: bool = True

    # Time budget: once exceeded, the remaining per-scan fetches are skipped.
    max_run_minutes: float = 60.0
    # An interrupted run younger than this is resumed; older ones are finalized.
    resume_max_age_hours: float = 12.0

    gap_window_hours: int = 168

    def rate_interval_s(self) -> float:
        return 60.0 / self.requests_per_minute


def load_config(path: Path | None) -> Config:
    """Load overrides from a TOML file with a [collector] table (missing file = defaults)."""
    cfg = Config()
    if path is not None and path.exists():
        _apply_toml(cfg, path)
    # The CI workflow sets this so its own date gate and the collector share one value.
    env_until = os.environ.get("COPPERTRAIL_API_ARCHIVE_UNTIL")
    if env_until:
        cfg.api_archive_until = date.fromisoformat(env_until)
    return cfg


def _apply_toml(cfg: Config, path: Path) -> None:
    with path.open("rb") as fh:
        data = tomllib.load(fh).get("collector", {})
    known = {f.name: f for f in fields(Config)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Unknown collector config key: {key!r} in {path}")
        if key == "api_archive_until" and isinstance(value, str):
            value = date.fromisoformat(value)
        if key in ("pinned", "exclude_qualities"):
            value = tuple(value)
        setattr(cfg, key, value)


@dataclass
class CutoffStatus:
    allowed: bool
    days_left: int
    message: str = field(default="")


def check_cutoff(cfg: Config, today: date) -> CutoffStatus:
    """Decide whether API archiving may run today."""
    days_left = (cfg.api_archive_until - today).days
    if not cfg.api_archive_enabled:
        return CutoffStatus(False, days_left, "API archiving is disabled in config.")
    if days_left < 0:
        return CutoffStatus(
            False,
            days_left,
            f"API archiving stopped: today is past API_ARCHIVE_UNTIL ({cfg.api_archive_until}). "
            "AHledger's terms require the Data licence for archives from 2026-12-10. "
            "Continuing is Jack's decision; change api_archive_until only after he decides.",
        )
    msg = ""
    if days_left <= cfg.warn_days_before_cutoff:
        msg = (
            f"WARNING: API archiving ends in {days_left} day(s) ({cfg.api_archive_until}). "
            "Ask Jack whether to continue past the cutoff."
        )
    return CutoffStatus(True, days_left, msg)
