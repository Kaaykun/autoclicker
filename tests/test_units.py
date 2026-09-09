"""Duration text the sequence table has to survive."""

from __future__ import annotations

import pytest

from autoclicker.core.units import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "default_unit", "expected_ms"),
    [
        ("1", "s", 1000.0),
        ("1", "ms", 1.0),
        ("0.5", "s", 500.0),
        ("1.5s", "ms", 1500.0),
        ("250 ms", "s", 250.0),
        ("250ms", "s", 250.0),
        ("2 sec", "ms", 2000.0),
        ("2 seconds", "ms", 2000.0),
        ("1 min", "s", 60_000.0),
        ("  3  ", "s", 3000.0),
        ("1,5", "s", 1500.0),
        ("0", "s", 0.0),
    ],
)
def test_parsing(text: str, default_unit: str, expected_ms: float) -> None:
    assert parse_duration(text, default_unit) == expected_ms


def test_a_written_unit_beats_the_column_unit() -> None:
    """Typing "250 ms" into a seconds column means 250 ms, not 250 seconds."""
    assert parse_duration("250 ms", "s") == 250.0
    assert parse_duration("2 s", "ms") == 2000.0


@pytest.mark.parametrize("text", ["", "soon", "1 fortnight", "abc", "1.2.3", "--5"])
def test_nonsense_is_rejected_rather_than_guessed(text: str) -> None:
    assert parse_duration(text) is None


def test_ms_is_never_read_as_minutes() -> None:
    assert parse_duration("5 ms", "s") == 5.0
    assert parse_duration("5 m", "s") == 300_000.0


@pytest.mark.parametrize(
    ("millis", "unit", "expected"),
    [
        (1000.0, "s", "1 s"),
        (1500.0, "s", "1.5 s"),
        (250.0, "ms", "250 ms"),
        (0.0, "s", "0 s"),
        (250.0, "s", "0.25 s"),
    ],
)
def test_formatting_has_no_trailing_zero_noise(millis: float, unit: str, expected: str) -> None:
    assert format_duration(millis, unit) == expected


def test_formatting_and_parsing_round_trip() -> None:
    for millis in (0.0, 1.0, 250.0, 1000.0, 1500.0, 60_000.0):
        for unit in ("s", "ms"):
            assert parse_duration(format_duration(millis, unit), unit) == millis


# --------------------------------------------------------------- counter


def test_the_counter_is_plain_until_there_is_a_rate_worth_showing() -> None:
    from autoclicker.core.units import format_counter

    assert format_counter(0) == "0 clicks"
    assert format_counter(1) == "1 click"
    assert format_counter(5) == "5 clicks"
    # Too early to divide by: a 0.1 s sample would report wild numbers.
    assert format_counter(5, 0.2) == "5 clicks"
    assert format_counter(1, 10.0) == "1 click"


def test_the_counter_reports_the_rate_actually_achieved() -> None:
    from autoclicker.core.units import format_counter

    assert format_counter(1000, 10.0) == "1,000 clicks  ·  100/s"
    assert format_counter(25, 10.0) == "25 clicks  ·  2.5/s"
    assert format_counter(3, 10.0) == "3 clicks  ·  0.30/s"


def test_large_counts_stay_readable() -> None:
    from autoclicker.core.units import format_counter

    assert format_counter(1234567).startswith("1,234,567 clicks")


def test_the_counter_noun_follows_the_action() -> None:
    from autoclicker.core.units import format_counter

    assert format_counter(3, noun="press") == "3 presses"
    assert format_counter(1, noun="press") == "1 press"
    assert format_counter(1000, 10.0, "press") == "1,000 presses  ·  100/s"


def test_plural_handles_the_nouns_this_app_uses() -> None:
    from autoclicker.core.units import plural

    assert plural("click", 1) == "click"
    assert plural("click", 2) == "clicks"
    assert plural("press", 1) == "press"
    assert plural("press", 3) == "presses", "not 'presss'"
    assert plural("pass", 2) == "passes"
