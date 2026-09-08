"""Folding a raw click log into a replayable sequence."""

from __future__ import annotations

from autoclicker.core.config import ClickType, MouseButton
from autoclicker.core.recorder import ClickEvent, points_from_events


def click(x: int, y: int, at: float, button: MouseButton = MouseButton.LEFT) -> ClickEvent:
    return ClickEvent(x=x, y=y, button=button, at=at)


def test_no_events_is_no_points() -> None:
    assert points_from_events([]) == []


def test_separated_clicks_become_separate_points() -> None:
    points = points_from_events([click(10, 10, 0.0), click(50, 50, 1.0), click(90, 90, 2.5)])
    assert [(p.x, p.y) for p in points] == [(10, 10), (50, 50), (90, 90)]
    assert all(p.click_type is ClickType.SINGLE for p in points)


def test_the_gap_between_clicks_becomes_the_delay() -> None:
    points = points_from_events([click(0, 0, 0.0), click(1000, 0, 1.5), click(0, 1000, 2.0)])
    assert [p.delay_after_ms for p in points] == [1500.0, 500.0, 0.0]


def test_the_last_point_has_no_delay_so_the_interval_governs_the_loop() -> None:
    points = points_from_events([click(0, 0, 0.0), click(500, 0, 1.0)])
    assert points[-1].delay_after_ms == 0.0


def test_two_fast_clicks_in_one_spot_are_a_double_click() -> None:
    """Replaying these as two singles would not open the folder you just opened."""
    points = points_from_events([click(100, 100, 0.0), click(101, 100, 0.15)])
    assert len(points) == 1
    assert points[0].click_type is ClickType.DOUBLE


def test_three_fast_clicks_are_a_triple() -> None:
    points = points_from_events(
        [click(100, 100, 0.0), click(100, 100, 0.1), click(100, 100, 0.2)]
    )
    assert len(points) == 1
    assert points[0].click_type is ClickType.TRIPLE


def test_a_fourth_fast_click_starts_a_new_point() -> None:
    points = points_from_events(
        [click(5, 5, 0.0), click(5, 5, 0.1), click(5, 5, 0.2), click(5, 5, 0.3)]
    )
    assert [p.click_type for p in points] == [ClickType.TRIPLE, ClickType.SINGLE]


def test_fast_clicks_in_different_places_do_not_merge() -> None:
    points = points_from_events([click(100, 100, 0.0), click(400, 400, 0.05)])
    assert len(points) == 2


def test_fast_clicks_with_different_buttons_do_not_merge() -> None:
    points = points_from_events(
        [click(10, 10, 0.0), click(10, 10, 0.05, MouseButton.RIGHT)]
    )
    assert len(points) == 2
    assert [p.button for p in points] == [MouseButton.LEFT, MouseButton.RIGHT]


def test_slow_clicks_in_one_spot_stay_separate() -> None:
    points = points_from_events([click(10, 10, 0.0), click(10, 10, 1.0)])
    assert len(points) == 2


def test_a_small_hand_wobble_still_counts_as_the_same_spot() -> None:
    points = points_from_events([click(200, 200, 0.0), click(202, 201, 0.1)])
    assert len(points) == 1


def test_dropping_the_timing_leaves_the_global_interval_in_charge() -> None:
    points = points_from_events(
        [click(0, 0, 0.0), click(500, 0, 3.0), click(0, 500, 9.0)], keep_timing=False
    )
    assert [p.delay_after_ms for p in points] == [0.0, 0.0, 0.0]
    assert len(points) == 3


def test_negative_coordinates_are_recorded_as_they_are() -> None:
    """Clicks on a monitor left of the primary."""
    points = points_from_events([click(-1500, -300, 0.0)])
    assert (points[0].x, points[0].y) == (-1500, -300)
