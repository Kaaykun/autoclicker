"""Offscreen GUI smoke tests.

These build the real widgets against Qt's ``offscreen`` platform plugin, so
they need no display and run in CI. They are shallow by design -- they check
that things construct, wire up and report sane values, not that anything looks
right.

The excepthook fixture is the point of the file. PySide6 catches an exception
raised inside a slot, prints it, and carries on, so a widget whose constructor
quietly explodes still "works" and still ships. Recording excepthook turns that
silence back into a failure.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Import QtWidgets rather than just PySide6: the wheel is often installed while
# the Qt runtime libraries it links against are not, which is the usual state of
# a bare Linux box. pytest.importorskip only skips on ModuleNotFoundError, so a
# missing libEGL would fail collection instead of skipping.
try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - depends on the machine
    pytest.skip(f"the Qt runtime is not available: {exc}", allow_module_level=True)

from autoclicker.core.config import (  # noqa: E402
    ClickConfig,
    ClickType,
    IntervalConfig,
    JitterMode,
    MouseButton,
    RepeatConfig,
    TargetConfig,
    TargetMode,
)
from autoclicker.ui.interval_widget import describe_rate  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_swallowed_exceptions():
    """Fail if Qt swallowed an exception from inside a slot."""
    captured: list[tuple] = []
    original = sys.excepthook
    sys.excepthook = lambda *args: captured.append(args)
    try:
        yield
    finally:
        sys.excepthook = original
    assert not captured, f"an exception escaped into a Qt slot: {captured[0][1]!r}"


# ------------------------------------------------------------------ widgets


def test_interval_widget_round_trips(qt_app) -> None:
    from autoclicker.ui.interval_widget import IntervalWidget

    widget = IntervalWidget()
    assert widget.value().total_ms == 100

    config = IntervalConfig(
        hours=1, minutes=2, seconds=3, millis=4,
        jitter_mode=JitterMode.PERCENT, jitter_amount=15.0,
    )
    widget.set_value(config)
    assert widget.value() == config
    assert widget.jitter_amount.isEnabled()


def test_interval_widget_warns_only_when_very_fast(qt_app) -> None:
    from autoclicker.ui.interval_widget import IntervalWidget

    widget = IntervalWidget()
    assert not widget.warning.isVisible()
    widget.set_value(IntervalConfig(millis=2))
    assert widget.warning.text()


def test_options_widget_round_trips(qt_app) -> None:
    from autoclicker.ui.options_widget import OptionsWidget

    widget = OptionsWidget()
    assert widget.repeat_value().until_stopped
    assert not widget.count.isEnabled()

    click = ClickConfig(button=MouseButton.MIDDLE, click_type=ClickType.TRIPLE, hold_ms=25.0)
    repeat = RepeatConfig(until_stopped=False, count=42)
    widget.set_value(click, repeat)
    assert widget.click_value() == click
    assert widget.repeat_value() == repeat
    assert widget.count.isEnabled()


def test_target_widget_round_trips_and_locks_picked_points(qt_app) -> None:
    from autoclicker.ui.target_widget import TargetWidget

    widget = TargetWidget()
    assert widget.value().mode is TargetMode.FOLLOW_CURSOR
    assert not widget.x.isEnabled()

    widget.set_point(-1280, 400)
    value = widget.value()
    assert value.mode is TargetMode.FIXED_POINT
    assert (value.x, value.y) == (-1280, 400)
    assert widget.x.isEnabled()

    config = TargetConfig(mode=TargetMode.FOLLOW_CURSOR, x=5, y=6, position_jitter_px=7)
    widget.set_value(config)
    assert widget.value() == config


def test_target_widget_accepts_negative_coordinates(qt_app) -> None:
    """A second monitor left of the primary is the common case for this."""
    from autoclicker.ui.target_widget import TargetWidget

    widget = TargetWidget()
    widget.set_point(-3000, -1200)
    assert (widget.value().x, widget.value().y) == (-3000, -1200)


# -------------------------------------------------------------- main window


def test_main_window_builds_and_reports_a_runnable_profile(qt_app) -> None:
    from autoclicker.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.windowTitle() == "Autoclicker"
        assert "Start" in window.start_button.text()
        assert window._profile().validate() == []
        assert "F8" in window.safety.panic_label.text()
        assert "F7" in window.target.capture_hint.text()
    finally:
        window.close()


def test_hotkey_failures_are_shown_inline_not_in_a_modal(qt_app) -> None:
    """A modal here would deadlock the app before the window ever appears.

    On macOS without Input Monitoring this is not hypothetical: hotkey
    registration fails on every launch until the permission is granted.
    """
    from autoclicker.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window._bridge.warningRaised.emit("hotkeys are unavailable")
        assert window.notice.text() == "hotkeys are unavailable"
    finally:
        window.close()


def test_the_picker_reports_backend_coordinates_not_qt_ones(qt_app) -> None:
    """The whole reason the overlay takes a position provider."""
    from autoclicker.ui.picker_overlay import PickerOverlay

    overlay = PickerOverlay(lambda: (1234, -567))
    seen: list[tuple[int, int]] = []
    overlay.picked.connect(lambda x, y: seen.append((x, y)))

    overlay._refresh_position()
    assert overlay._reported == (1234, -567)


def test_a_broken_position_provider_does_not_crash_the_overlay(qt_app) -> None:
    from autoclicker.ui.picker_overlay import PickerOverlay

    def explode() -> tuple[int, int]:
        raise RuntimeError("Accessibility permission is not granted")

    overlay = PickerOverlay(explode)
    overlay._refresh_position()
    assert overlay._reported == (0, 0)


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize(
    ("total_ms", "fragment"),
    [
        (100, "10.0 clicks per second"),
        (1000, "every 1 seconds"),
        (90_000, "every 1.5 minutes"),
        (7_200_000, "every 2 hours"),
        (0, "at least 1 ms"),
    ],
)
def test_rate_descriptions(total_ms: float, fragment: str) -> None:
    assert fragment in describe_rate(total_ms)
