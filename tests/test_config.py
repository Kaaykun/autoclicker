"""Config maths, validation and JSON round-tripping."""

from __future__ import annotations

import pytest

from autoclicker.core.config import (
    ClickConfig,
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
    blank = {"hours": 0, "minutes": 0, "seconds": 0, "millis": 0}
    assert IntervalConfig(**{**blank, **kwargs}).total_ms == expected_ms


def test_interval_rejects_zero_and_negative() -> None:
    assert IntervalConfig(seconds=0, millis=0).validate()
    assert IntervalConfig(seconds=0, millis=-5).validate()
    assert IntervalConfig(seconds=0, millis=1).validate() == []


def test_percentage_jitter_is_bounded() -> None:
    assert IntervalConfig(jitter_mode=JitterMode.PERCENT, jitter_amount=150).validate()
    assert IntervalConfig(jitter_mode=JitterMode.PERCENT, jitter_amount=20).validate() == []


def test_the_default_interval_is_one_second() -> None:
    assert IntervalConfig().total_ms == 1000
    assert Profile().interval.total_ms == 1000


def test_interval_components_load_all_or_nothing() -> None:
    """A partial interval must not pick up the 1-second default per field.

    Otherwise {"millis": 250} would quietly load as 1.25 seconds.
    """
    assert IntervalConfig.from_dict({"millis": 250}).total_ms == 250
    assert IntervalConfig.from_dict({"seconds": 3}).total_ms == 3000
    assert IntervalConfig.from_dict({}).total_ms == 1000


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
    assert profile.interval.total_ms == 1000


def test_fast_interval_produces_a_warning_not_an_error() -> None:
    profile = Profile(interval=IntervalConfig(seconds=0, millis=2))
    assert profile.validate() == []
    assert profile.warnings()


def test_plain_strings_are_coerced_to_enums_on_construction() -> None:
    """Qt hands back plain strings for str Enums, and so does hand-written JSON.

    They compare equal to the member, so the mistake is invisible right up
    until something reaches for ``.value``.
    """
    click = ClickConfig(button="right", click_type="double")
    assert click.button is MouseButton.RIGHT
    assert click.click_type is ClickType.DOUBLE
    assert click.to_dict()["button"] == "right"

    interval = IntervalConfig(jitter_mode="percent", jitter_amount=10)
    assert interval.jitter_mode is JitterMode.PERCENT

    target = TargetConfig(mode="sequence", sequence=[SequencePoint(button="middle")])
    assert target.mode is TargetMode.SEQUENCE
    assert target.sequence[0].button is MouseButton.MIDDLE

    assert Profile(interval=interval, click=click, target=target).to_json()


def test_a_nonsense_string_falls_back_rather_than_raising() -> None:
    assert ClickConfig(button="telepathy").button is MouseButton.LEFT
