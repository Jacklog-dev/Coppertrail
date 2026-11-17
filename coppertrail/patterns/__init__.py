"""Pattern jobs (HANDOVER section 6). Importing this package registers every job."""

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

# Job modules register themselves on import; add each new one here.
# from coppertrail.patterns import rhythm  # noqa: F401

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
