"""Hotkey spec handling and the corner-failsafe geometry."""

from __future__ import annotations

import pytest

from autoclicker.core.failsafe import is_in_corner
from autoclicker.core.hotkeys import canonical_spec, format_hotkey

SCREEN = (0, 0, 1920, 1080)


def test_modifiers_are_ordered_consistently() -> None:
    assert canonical_spec({"shift", "ctrl"}, "k") == "<ctrl>+<shift>+k"
    assert canonical_spec({"ctrl", "shift"}, "k") == "<ctrl>+<shift>+k"


def test_left_and_right_modifiers_collapse_to_one_name() -> None:
    assert canonical_spec({"ctrl_l"}, "k") == canonical_spec({"ctrl_r"}, "k")


def test_a_bare_function_key_needs_no_modifiers() -> None:
    assert canonical_spec(set(), "<f6>") == "<f6>"


def test_display_names_are_platform_appropriate() -> None:
    spec = "<cmd>+<alt>+k"
    assert format_hotkey(spec, platform="darwin") == "Command + Option + K"
    assert format_hotkey(spec, platform="win32") == "Win + Alt + K"


def test_display_of_special_keys() -> None:
    assert format_hotkey("<f6>") == "F6"
    assert format_hotkey("<page_down>") == "Page Down"
    assert format_hotkey("") == "Not set"


# ------------------------------------------------------------------ failsafe


@pytest.mark.parametrize("point", [(0, 0), (1919, 0), (0, 1079), (1919, 1079), (5, 5)])
def test_every_corner_triggers(point: tuple[int, int]) -> None:
    assert is_in_corner(*point, [SCREEN], margin_px=10)


@pytest.mark.parametrize("point", [(960, 540), (0, 540), (960, 0), (100, 100)])
def test_edges_and_the_middle_do_not_trigger(point: tuple[int, int]) -> None:
    """An edge is not a corner -- you brush those by accident all day."""
    assert not is_in_corner(*point, [SCREEN], margin_px=10)


def test_corners_of_a_second_monitor_work() -> None:
    """A left-hand second monitor sits at negative x, and its corners are
    interior to the combined desktop -- per-screen checks are the only way."""
    screens = [(-1920, 0, 0, 1080), SCREEN]
    assert is_in_corner(-1915, 5, screens, margin_px=10)
    assert is_in_corner(-5, 1075, screens, margin_px=10)


def test_a_point_on_no_screen_never_triggers() -> None:
    assert not is_in_corner(5000, 5000, [SCREEN], margin_px=10)


def test_a_zero_margin_disables_the_failsafe() -> None:
    assert not is_in_corner(0, 0, [SCREEN], margin_px=0)
