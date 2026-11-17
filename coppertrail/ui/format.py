"""Display formatting from HANDOVER 8b "Data display conventions".

Pure functions, so the bridge, views and tests share one implementation.
Prices are integers in copper (1g = 100s = 10,000c), as stored by the collector.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from coppertrail.ui.tokens import COIN

MINUS = "−"  # real minus sign, never a hyphen
RISE = "▲"  # black up-pointing triangle
FALL = "▼"  # black down-pointing triangle
LOCAL_TZ = ZoneInfo("Europe/Berlin")  # CET/CEST, the display time zone

# Month names fixed in English: strftime month names follow the process locale.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

Unit = Literal["g", "s", "c"]
Direction = Literal["rise", "fall", "flat"]


def coin_parts(copper: int) -> list[tuple[int, Unit]]:
    """Split a price into (amount, unit) pairs, zero units omitted.

    From 100 gold on, only gold is shown (rounded): the "short form" `3,101●`.
    A price of zero is `0c`.
    """
    if copper < 0:
        raise ValueError("prices are never negative")
    gold, rest = divmod(copper, 10_000)
    if gold >= COIN["short_from_gold"]:
        return [(round(copper / 10_000), "g")]
    silver, cop = divmod(rest, 100)
    parts: list[tuple[int, Unit]] = [
        (n, u) for n, u in ((gold, "g"), (silver, "s"), (cop, "c")) if n
    ]
    return parts or [(0, "c")]


def coins_text(copper: int) -> str:
    """Letter form for axes and plain text: `12g 67s 5c`, `1g 50s`, `3,101g`."""
    return " ".join(f"{n:,}{u}" for n, u in coin_parts(copper))


def thousands(n: int) -> str:
    """`9,063`."""
    return f"{n:,}"


def count(n: float) -> str:
    """Counts: comma separated, from one million as `1.61 M`."""
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.3g} M"
    return f"{round(n):,}"


def direction(value: float) -> Direction:
    if value > 0:
        return "rise"
    if value < 0:
        return "fall"
    return "flat"


def signed_number(value: float, decimals: int = 0) -> str:
    """`+12`, `−3.5`, `0` with a real minus sign."""
    text = f"{abs(value):,.{decimals}f}"
    if float(text.replace(",", "")) == 0:
        return text
    return ("+" if value > 0 else MINUS) + text


def percent_change(pct: float) -> tuple[str, Direction]:
    """Signed change with arrow: `▲ +14.2 %`, `▼ −87 %`, `± 0.0 %`.

    One decimal below 50 %, none from 50 % on. Returns the text and the
    direction, so the caller picks the `rise`/`fall` colour; the arrow and sign
    carry the meaning on their own (never colour alone).
    """
    decimals = 1 if abs(pct) < 50 else 0
    rounded = round(pct, decimals)
    if rounded == 0:
        return f"± {0:.{decimals}f} %", "flat"
    arrow = RISE if rounded > 0 else FALL
    return f"{arrow} {signed_number(rounded, decimals)} %", direction(rounded)


def local_datetime(ts: datetime) -> str:
    """`16 Nov 2026, 08:42` in local time (naive datetimes are taken as UTC)."""
    loc = _local(ts)
    return f"{day(loc)}, {loc:%H:%M}"


def day(d: date) -> str:
    """`16 Nov 2026`."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def date_range(start: date, end: date) -> str:
    """`17 Oct – 16 Nov 2026`; the year is repeated only when it differs."""
    same_year = start.year == end.year
    left = f"{start.day} {MONTHS[start.month - 1]}" if same_year else day(start)
    return f"{left} – {day(end)}"


def _local(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(LOCAL_TZ)


def short_datetime(ts: datetime) -> str:
    """`13 Nov, 07:55` in local time, for "Charts end on …"."""
    loc = _local(ts)
    return f"{loc.day} {MONTHS[loc.month - 1]}, {loc:%H:%M}"


def clock(ts: datetime) -> str:
    """`08:44:10` in local time."""
    return f"{_local(ts):%H:%M:%S}"


def needs_more(days: int) -> str:
    """`Needs 5 more days of data`; from two weeks on in whole weeks, rounded up."""
    if days >= 14:
        return f"Needs {-(-days // 7)} more weeks of data"
    return f"Needs {days} more day{'' if days == 1 else 's'} of data"


def day_month(d: date) -> str:
    """`7 Nov`, for chart subtitles ("100 = 10 Nov")."""
    return f"{d.day} {MONTHS[d.month - 1]}"


def hour_of_day(hour: int) -> str:
    """`07:00`."""
    return f"{int(hour):02d}:00"


def points(value: float) -> str:
    """Index points, always signed: `+19.8 pts`, `−27.0 pts`."""
    text = signed_number(value, 1)
    return f"{text if text[0] in '+' + MINUS else '± ' + text} pts"


def share(fraction: float) -> str:
    """An unsigned percentage with one decimal: `16.3 %`."""
    return f"{fraction * 100:.1f} %"


def _finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def signed_percent(fraction: float) -> str:
    """A signed percentage without arrow, for foot lines: `−4.1 %` (same rounding)."""
    pct = fraction * 100
    decimals = 1 if abs(pct) < 50 else 0
    text = signed_number(round(pct, decimals), decimals)
    return f"{text if text[0] in '+' + MINUS else '± ' + text} %"


def change(fraction: float | None) -> dict | None:
    """A signed fraction (-0.87) as `{text: "▼ −87 %", dir: "fall"}`; None when unknown."""
    if not _finite(fraction):
        return None
    text, d = percent_change(float(fraction) * 100)
    return {"text": text, "dir": d}


def minutes(value: float) -> str:
    """A duration in minutes: `30 min`, `1 h 48 min`, `2 h`."""
    m = int(round(float(value)))
    if m < 60:
        return f"{m} min"
    h, rest = divmod(m, 60)
    return f"{h} h {rest} min" if rest else f"{h} h"


def ratio(value: float) -> str:
    """A price ratio: `1.07 ×` (lowest buyout over vendor price)."""
    return f"{float(value):.2f} ×"


def whole_share(fraction: float) -> str:
    """An unsigned percentage without decimals: `83 %` (shares of nights, events, hours)."""
    return f"{round(float(fraction) * 100)} %"


def signed_coins_text(copper: int) -> str:
    """Letter form with a real minus for losses: `−1g 40s 50c`."""
    text = coins_text(abs(int(copper)))
    return MINUS + text if copper < 0 else text
