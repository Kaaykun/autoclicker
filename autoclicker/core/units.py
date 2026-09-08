"""Parsing and formatting durations the way people actually type them.

Used by the sequence table's delay column. Kept out of the ``ui`` package
because it is pure text handling and deserves tests that do not need Qt.
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
