"""Formatting numbers for people: durations, and the click counter.

Kept out of the ``ui`` package because it is pure text handling and deserves
tests that do not need Qt.
"""

from __future__ import annotations

import re

#: Multipliers to milliseconds. Longest names first is irrelevant here because
#: the regex captures the whole suffix, so "ms" never matches as "m".
_UNITS = {
    "ms": 1.0,
    "msec": 1.0,
    "msecs": 1.0,
    "s": 1000.0,
    "sec": 1000.0,
    "secs": 1000.0,
    "second": 1000.0,
    "seconds": 1000.0,
    "m": 60_000.0,
    "min": 60_000.0,
    "mins": 60_000.0,
    "minute": 60_000.0,
    "minutes": 60_000.0,
}

_PATTERN = re.compile(r"^([+-]?\d*\.?\d+)\s*([a-z]*)$")

SECONDS = "s"
MILLISECONDS = "ms"


def parse_duration(text: str, default_unit: str = SECONDS) -> float | None:
    """Return milliseconds, or ``None`` if the text is not a duration.

    A unit written in the text always wins, so "250 ms" means 250 ms even when
    the column is showing seconds. Without one, ``default_unit`` applies.
    """
    cleaned = text.strip().lower().replace(",", ".")
    match = _PATTERN.match(cleaned)
    if match is None:
        return None
    amount, suffix = match.groups()
    unit = suffix or default_unit
    if unit not in _UNITS:
        return None
    try:
        return float(amount) * _UNITS[unit]
    except ValueError:
        return None


def format_duration(millis: float, unit: str = SECONDS) -> str:
    """Render milliseconds in ``unit``, without trailing-zero noise."""
    if unit not in _UNITS:
        unit = SECONDS
    value = millis / _UNITS[unit]
    return f"{value:g} {unit}"


def format_counter(clicks: int, elapsed_s: float | None = None) -> str:
    """The click counter, with the rate actually achieved when known.

    The achieved rate is the honest one to show. Below roughly 5 ms the
    operating system, not this app, decides how fast clicks really go out, so a
    counter that echoed the requested rate back would be quietly lying.
    """
    label = f"{clicks:,} click{'' if clicks == 1 else 's'}"
    if elapsed_s is None or elapsed_s < 0.5 or clicks < 2:
        return label
    rate = clicks / elapsed_s
    if rate >= 10:
        return f"{label}  ·  {rate:.0f}/s"
    if rate >= 1:
        return f"{label}  ·  {rate:.1f}/s"
    return f"{label}  ·  {rate:.2f}/s"
