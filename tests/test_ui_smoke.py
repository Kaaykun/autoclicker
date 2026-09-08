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
    assert widget.value().total_ms == 1000

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
    widget.set_value(IntervalConfig(seconds=0, millis=2))
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
        (1000, "per second"),
        (90_000, "every 1.5 minutes"),
        (7_200_000, "every 2 hours"),
        (60_000, "per minute"),
        (3_600_000, "per hour"),
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


def _window(tmp_path, recorder=None):
    """A window with a throwaway config directory, never the user's real one."""
    from autoclicker.core.profiles import ProfileStore, Settings
    from autoclicker.ui.main_window import MainWindow

    return MainWindow(
        store=ProfileStore(tmp_path / "profiles"),
        settings=Settings(tmp_path),
        recorder=recorder,
    )


def test_a_profile_saved_from_the_window_reloads_into_it(qt_app, tmp_path) -> None:
    window = _window(tmp_path)
    try:
        window.interval.set_value(IntervalConfig(seconds=2, millis=0))
        window._store.save(window._profile("Slow"))
        window._refresh_profiles("Slow")

        window.interval.set_value(IntervalConfig(seconds=0, millis=50))
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
    first.interval.set_value(IntervalConfig(minutes=5, seconds=0, millis=0))
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


# ------------------------------------------------------------- new defaults


def test_the_window_opens_at_one_click_per_second(qt_app) -> None:
    from autoclicker.ui.interval_widget import IntervalWidget

    widget = IntervalWidget()
    value = widget.value()
    assert (value.hours, value.minutes, value.seconds, value.millis) == (0, 0, 1, 0)
    assert not widget.warning.isVisible()


# ----------------------------------------------------------- sequence units


def test_the_wait_column_follows_the_chosen_unit(qt_app) -> None:
    from autoclicker.core.config import SequencePoint
    from autoclicker.core.units import MILLISECONDS, SECONDS
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.set_points([SequencePoint(x=1, y=1, delay_after_ms=1500)])

    assert editor.unit.currentData() == SECONDS, "seconds is the sensible default"
    assert editor.table.item(0, 4).text() == "1.5 s"

    editor.unit.setCurrentIndex(editor.unit.findData(MILLISECONDS))
    assert editor.table.item(0, 4).text() == "1500 ms"
    assert editor.points()[0].delay_after_ms == 1500, "switching units must not edit data"


def test_a_wait_typed_without_a_unit_uses_the_column_unit(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(1, 1)
    editor.table.item(0, 4).setText("2")
    assert editor.points()[0].delay_after_ms == 2000.0


def test_a_wait_typed_with_a_unit_overrides_the_column(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(1, 1)
    editor.table.item(0, 4).setText("250 ms")
    assert editor.points()[0].delay_after_ms == 250.0


def test_an_unparseable_wait_keeps_the_previous_value(qt_app) -> None:
    from autoclicker.ui.sequence_widget import SequenceEditor

    editor = SequenceEditor()
    editor.add_point(1, 1)
    editor.table.item(0, 4).setText("3")
    editor.table.item(0, 4).setText("whenever")
    assert editor.points()[0].delay_after_ms == 3000.0


# ------------------------------------------------------------------ recording


class StubRecorder:
    """Stands in for pynput so these tests do not depend on input permissions."""

    def __init__(self, events=None, can_start=True) -> None:
        self._events = events or []
        self._can_start = can_start
        self.is_recording = False

    def start(self) -> bool:
        self.is_recording = self._can_start
        return self._can_start

    def stop(self):
        self.is_recording = False
        return self._events


def test_recording_puts_you_in_sequence_mode_and_shows_progress(qt_app, tmp_path) -> None:
    window = _window(tmp_path, StubRecorder())
    try:
        window._toggle_recording()
        assert window._recording
        assert window.target.value().mode is TargetMode.SEQUENCE
        assert "Stop recording" in window.target.editor.record_button.text()

        window._bridge.recordCountChanged.emit(3)
        assert "3 clicks" in window.target.editor.record_button.text()
    finally:
        window.close()


def test_a_recording_becomes_sequence_points(qt_app, tmp_path) -> None:
    from autoclicker.core.config import MouseButton as Button
    from autoclicker.core.recorder import ClickEvent

    events = [
        ClickEvent(100, 100, Button.LEFT, 0.0),
        ClickEvent(100, 100, Button.LEFT, 0.12),   # a double-click
        ClickEvent(400, 300, Button.RIGHT, 2.0),
    ]
    window = _window(tmp_path, StubRecorder(events))
    try:
        window._toggle_recording()
        window._toggle_recording()

        points = window.target.value().sequence
        assert [(p.x, p.y) for p in points] == [(100, 100), (400, 300)]
        assert points[0].click_type is ClickType.DOUBLE
        assert points[1].button is Button.RIGHT
        assert not window._recording
        assert "Recorded 2 points" in window.status.text()
    finally:
        window.close()


def test_a_recording_appends_rather_than_wiping_existing_points(qt_app, tmp_path) -> None:
    from autoclicker.core.config import MouseButton as Button
    from autoclicker.core.recorder import ClickEvent

    window = _window(tmp_path, StubRecorder([ClickEvent(9, 9, Button.LEFT, 0.0)]))
    try:
        window.target.sequence.setChecked(True)
        window.target.editor.add_point(1, 1)
        window._toggle_recording()
        window._toggle_recording()
        assert [(p.x, p.y) for p in window.target.value().sequence] == [(1, 1), (9, 9)]
    finally:
        window.close()


def test_dropping_recorded_timing_leaves_the_interval_in_charge(qt_app, tmp_path) -> None:
    from autoclicker.core.config import MouseButton as Button
    from autoclicker.core.recorder import ClickEvent

    events = [ClickEvent(0, 0, Button.LEFT, 0.0), ClickEvent(500, 0, Button.LEFT, 4.0)]
    window = _window(tmp_path, StubRecorder(events))
    try:
        window.target.editor.keep_timing_box.setChecked(False)
        window._toggle_recording()
        window._toggle_recording()
        assert [p.delay_after_ms for p in window.target.value().sequence] == [0.0, 0.0]
    finally:
        window.close()


def test_a_recorder_that_cannot_listen_says_so_instead_of_pretending(qt_app, tmp_path) -> None:
    window = _window(tmp_path, StubRecorder(can_start=False))
    try:
        window._toggle_recording()
        assert not window._recording
        assert "Input Monitoring" in window.notice.text()
    finally:
        window.close()


def test_clicks_on_the_autoclicker_itself_are_ignored_while_recording(qt_app, tmp_path) -> None:
    """Otherwise the click that presses Stop becomes the last recorded point."""
    window = _window(tmp_path, StubRecorder())
    try:
        window.setGeometry(100, 100, 400, 300)
        inside = window.frameGeometry().center()
        assert window._is_over_this_window(inside.x(), inside.y())
        assert not window._is_over_this_window(5000, 5000)
    finally:
        window.close()


def test_starting_the_clicker_is_blocked_while_recording(qt_app, tmp_path) -> None:
    window = _window(tmp_path, StubRecorder())
    try:
        window._toggle_recording()
        window._toggle()
        assert not window._engine.is_running
        assert not window.start_button.isEnabled()
    finally:
        window.close()


# -------------------------------------------------------------- discoverable


def test_the_hotkeys_are_reachable_without_the_menu_bar(qt_app, tmp_path) -> None:
    """On macOS the menu bar is at the top of the screen, not in the window."""
    window = _window(tmp_path)
    try:
        assert window.safety.hotkeys_button.text() == "Hotkeys…"
        summary = window.safety.hotkey_summary.text()
        assert "F6" in summary and "F7" in summary and "F9" in summary

        # Detach the window's own slot first: it opens a modal dialog, which
        # would hang a headless run.
        window.safety.hotkeysRequested.disconnect()
        seen: list[bool] = []
        window.safety.hotkeysRequested.connect(lambda: seen.append(True))
        window.safety.hotkeys_button.click()
        assert seen
    finally:
        window.close()


def test_the_record_hotkey_is_part_of_the_config_and_conflict_checked() -> None:
    from autoclicker.core.config import HotkeyConfig

    assert HotkeyConfig().record == "<f9>"
    assert HotkeyConfig().validate() == []
    assert HotkeyConfig(record="<f6>").validate()


# --------------------------------------------------------------------- icons


def test_the_supplied_artwork_is_picked_up(qt_app) -> None:
    from autoclicker.ui.icons import app_icon, has_custom_artwork

    assert has_custom_artwork(), "autoclicker/resources/icon.png should be committed"
    icon = app_icon()
    assert not icon.isNull()
    assert icon.availableSizes(), "the icon should carry at least one real size"


def test_windows_prefers_the_squared_artwork(qt_app, monkeypatch) -> None:
    """Windows does not mask icons, so baked-in rounded corners read as notches
    against a taskbar highlight."""
    from autoclicker.ui import icons

    monkeypatch.setattr(icons.sys, "platform", "win32")
    chosen = icons._first_existing(icons.APP_ICON_NAMES_WINDOWS)
    assert chosen is not None and chosen.name == "icon-square.png"

    monkeypatch.setattr(icons.sys, "platform", "darwin")
    chosen = icons._first_existing(icons.APP_ICON_NAMES)
    assert chosen is not None and chosen.name == "icon.png"


def test_the_tray_glyph_differs_between_running_and_idle(qt_app) -> None:
    """It has to differ by shape: macOS strips the colour from menu-bar icons."""
    from autoclicker.ui.icons import _draw_tray_glyph

    idle = _draw_tray_glyph(44, filled=False).toImage()
    running = _draw_tray_glyph(44, filled=True).toImage()
    assert idle != running

    centre = idle.rect().center()
    assert idle.pixelColor(centre).alpha() == 0, "idle is a hollow ring"
    assert running.pixelColor(centre).alpha() > 0, "running is filled"


def test_icons_still_work_with_no_artwork_at_all(qt_app, monkeypatch, tmp_path) -> None:
    from autoclicker.ui import icons

    monkeypatch.setattr(icons, "RESOURCE_DIR", tmp_path)
    assert not icons.has_custom_artwork()
    assert not icons.app_icon().isNull()
    assert not icons.tray_icon(running=False).isNull()


# ---------------------------------------------------------------------- tray


def test_the_window_survives_a_desktop_with_no_tray(qt_app, tmp_path) -> None:
    """The offscreen platform has no tray, which is the case worth covering:
    the close-to-tray option must not be offerable, or the window becomes
    closable into nothing."""
    window = _window(tmp_path)
    try:
        if window._tray is None:
            assert not window.keep_in_tray_action.isEnabled()
            window.keep_in_tray_action.setChecked(True)
            assert not window.keep_in_tray_action.isChecked()
    finally:
        window.close()


def test_the_counter_reports_the_achieved_rate_while_running(qt_app, tmp_path) -> None:
    import time

    window = _window(tmp_path)
    try:
        window._engine.clicks_fired = 500
        window._run_started_at = time.monotonic() - 10.0
        window._refresh_counter()
        assert "500 clicks" in window.counter.text()
        assert "/s" in window.counter.text()

        window._run_started_at = None
        window._refresh_counter()
        assert window.counter.text() == "500 clicks"
    finally:
        window.close()
