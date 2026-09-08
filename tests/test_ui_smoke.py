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


# ------------------------------------------------------------------ sequence


def test_sequence_editor_adds_reorders_and_removes(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(10, 20)
    editor.add_point(30, 40)
    assert [(p.x, p.y) for p in editor.points()] == [(10, 20), (30, 40)]

    editor.table.selectRow(0)
    editor._move(1)
    assert [(p.x, p.y) for p in editor.points()] == [(30, 40), (10, 20)]

    editor.table.selectRow(0)
    editor._remove_selected()
    assert [(p.x, p.y) for p in editor.points()] == [(10, 20)]


def test_sequence_cells_parse_what_people_actually_type(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(1, 2)

    editor.table.item(0, 0).setText("-500")
    assert editor.points()[0].x == -500

    editor.table.item(0, 4).setText("250 ms")
    assert editor.points()[0].delay_after_ms == 250.0

    editor.table.item(0, 0).setText("nonsense")
    assert editor.points()[0].x == -500, "a bad edit must keep the previous value"


def test_sequence_points_are_copies_not_live_references(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(1, 2)
    taken = editor.points()
    taken[0].x = 999
    assert editor.points()[0].x == 1


def test_picked_points_go_to_the_sequence_when_it_is_active(qt_app) -> None:
    from autoclicker.ui.target_widget import TargetWidget

    widget = TargetWidget()
    widget.sequence.setChecked(True)
    widget.receive_point(5, 6)
    widget.receive_point(7, 8)

    value = widget.value()
    assert value.mode is TargetMode.SEQUENCE
    assert [(p.x, p.y) for p in value.sequence] == [(5, 6), (7, 8)]
    assert value.validate() == []


def test_a_sequence_round_trips_through_the_target_widget(qt_app) -> None:
    from autoclicker.core.config import SequencePoint
    from autoclicker.ui.target_widget import TargetWidget

    config = TargetConfig(
        mode=TargetMode.SEQUENCE,
        position_jitter_px=3,
        sequence=[
            SequencePoint(x=1, y=2, button=MouseButton.RIGHT,
                          click_type=ClickType.DOUBLE, delay_after_ms=500),
            SequencePoint(x=-9, y=-8),
        ],
    )
    widget = TargetWidget()
    widget.set_value(config)
    assert widget.value() == config


# ------------------------------------------------------------------ profiles


def _window(tmp_path):
    from autoclicker.core.profiles import ProfileStore, Settings
    from autoclicker.ui.main_window import MainWindow

    return MainWindow(
        store=ProfileStore(tmp_path / "profiles"),
        settings=Settings(tmp_path),
    )


def test_a_profile_saved_from_the_window_reloads_into_it(qt_app, tmp_path) -> None:
    window = _window(tmp_path)
    try:
        window.interval.set_value(IntervalConfig(seconds=2, millis=0))
        window._store.save(window._profile("Slow"))
        window._refresh_profiles("Slow")

        window.interval.set_value(IntervalConfig(millis=50))
        assert window.interval.value().total_ms == 50

        window._load_profile("Slow")
        assert window.interval.value().total_ms == 2000
    finally:
        window.close()


def test_editing_marks_the_profile_as_no_longer_matching(qt_app, tmp_path) -> None:
    window = _window(tmp_path)
    try:
        window._store.save(window._profile("Base"))
        window._refresh_profiles("Base")
        assert window.profiles.current_name() == "Base"

        window.options.hold_ms.setValue(25)
        assert window.profiles.current_name() is None
    finally:
        window.close()


def test_loading_a_profile_is_not_mistaken_for_an_edit(qt_app, tmp_path) -> None:
    """Applying a profile fires every widget's changed signal; the guard flag
    is what stops that from immediately marking it unsaved again."""
    window = _window(tmp_path)
    try:
        window._store.save(window._profile("Base"))
        window._refresh_profiles("Base")
        window._load_profile("Base")
        assert window.profiles.current_name() == "Base"
    finally:
        window.close()


def test_a_missing_profile_warns_instead_of_crashing(qt_app, tmp_path) -> None:
    window = _window(tmp_path)
    try:
        window._load_profile("never existed")
        assert "never existed" in window.notice.text()
    finally:
        window.close()


def test_the_last_profile_is_restored_on_the_next_launch(qt_app, tmp_path) -> None:
    from autoclicker.core.profiles import ProfileStore, Settings

    store = ProfileStore(tmp_path / "profiles")
    settings = Settings(tmp_path)

    first = _window(tmp_path)
    first.interval.set_value(IntervalConfig(minutes=5, millis=0))
    store.save(first._profile("Restored"))
    first._refresh_profiles("Restored")
    first.close()

    assert settings.read()["last_profile"] == "Restored"

    second = _window(tmp_path)
    try:
        assert second.profiles.current_name() == "Restored"
        assert second.interval.value().total_ms == 300_000
    finally:
        second.close()
