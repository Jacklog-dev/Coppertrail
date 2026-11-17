"""Pattern jobs (HANDOVER section 6). Importing this package registers every job."""

# Job modules register themselves on import; add each new one here.
from coppertrail.patterns import (  # noqa: F401, E402
    builds,
    buyouts,
    correlations,
    inflation,
    mispricings,
    progression,
    reversion,
    rhythm,
    spreads,
    supply,
    vendor,
    weekday,
)
from coppertrail.patterns.base import (
    EVENT_COLS,
    EVENT_TYPES,
    REGISTRY,
    Context,
    PatternResult,
    PatternSpec,
    events_frame,
    pattern,
    run,
)

__all__ = [
    "EVENT_COLS",
    "EVENT_TYPES",
    "REGISTRY",
    "Context",
    "PatternResult",
    "PatternSpec",
    "events_frame",
    "pattern",
    "run",
]
