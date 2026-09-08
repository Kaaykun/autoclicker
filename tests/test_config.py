"""Config maths, validation and JSON round-tripping."""

from __future__ import annotations

import pytest

from autoclicker.core.config import (
    ClickType,
    HotkeyConfig,
    IntervalConfig,
    JitterMode,
    MouseButton,
    Profile,
    RepeatConfig,
    SequencePoint,
    TargetConfig,
    TargetMode,
)


@pytest.mark.parametrize(
    ("kwargs", "expected_ms"),
    [
        ({"millis": 100}, 100),
        ({"seconds": 1}, 1000),
        ({"minutes": 1}, 60_000),
        ({"hours": 1}, 3_600_000),
        ({"hours": 1, "minutes": 2, "seconds": 3, "millis": 4}, 3_723_004),
        ({"millis": 0}, 0),
    ],
)
def test_interval_total_ms(kwargs: dict[str, int], expected_ms: int) -> None:
    assert IntervalConfig(**{"millis": 0, **kwargs}).total_ms == expected_ms


def test_interval_rejects_zero_and_negative() -> None:
    assert IntervalConfig(millis=0).validate()
    assert IntervalConfig(millis=-5).validate()
    assert IntervalConfig(millis=1).validate() == []


def test_percentage_jitter_is_bounded() -> None:
    assert IntervalConfig(jitter_mode=JitterMode.PERCENT, jitter_amount=150).validate()
    assert IntervalConfig(jitter_mode=JitterMode.PERCENT, jitter_amount=20).validate() == []


def test_click_type_counts() -> None:
    assert ClickType.SINGLE.count == 1
    assert ClickType.DOUBLE.count == 2
    assert ClickType.TRIPLE.count == 3


def test_repeat_count_must_be_positive_when_limited() -> None:
    assert RepeatConfig(until_stopped=False, count=0).validate()
    assert RepeatConfig(until_stopped=True, count=0).validate() == []


def test_sequence_mode_needs_points() -> None:
    assert TargetConfig(mode=TargetMode.SEQUENCE).validate()
    assert TargetConfig(
        mode=TargetMode.SEQUENCE, sequence=[SequencePoint(x=1, y=2)]
    ).validate() == []


def test_duplicate_hotkeys_are_rejected() -> None:
    assert HotkeyConfig(toggle="<f6>", panic="<f6>").validate()
    assert HotkeyConfig().validate() == []


def test_profile_round_trips_through_json() -> None:
    profile = Profile(
        name="Gaming",
        interval=IntervalConfig(seconds=2, millis=50, jitter_mode=JitterMode.PERCENT,
                                jitter_amount=15),
        target=TargetConfig(
            mode=TargetMode.SEQUENCE,
            position_jitter_px=4,
            sequence=[
                SequencePoint(x=10, y=20, button=MouseButton.RIGHT,
                              click_type=ClickType.DOUBLE, delay_after_ms=250),
                SequencePoint(x=-30, y=-40),
            ],
        ),
    )
    assert Profile.from_json(profile.to_json()) == profile


def test_negative_coordinates_survive_a_round_trip() -> None:
    """Second monitors live at negative coordinates; nothing may clamp them."""
    target = TargetConfig(mode=TargetMode.FIXED_POINT, x=-1920, y=-200)
    assert TargetConfig.from_dict(target.to_dict()) == target


def test_unknown_enum_values_fall_back_instead_of_exploding() -> None:
    profile = Profile.from_dict({"click": {"button": "telepathy"}})
    assert profile.click.button is MouseButton.LEFT


def test_future_schema_version_degrades_to_defaults() -> None:
    profile = Profile.from_dict({"schema_version": 999, "name": "From the future"})
    assert profile.name == "From the future"
    assert profile.interval.total_ms == 100


def test_fast_interval_produces_a_warning_not_an_error() -> None:
    profile = Profile(interval=IntervalConfig(millis=2))
    assert profile.validate() == []
    assert profile.warnings()
