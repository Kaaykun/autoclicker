"""Engine behaviour, exercised end to end against a fake backend.

No real click is ever sent from this file.
"""

from __future__ import annotations

import threading

import pytest

from autoclicker.core.backends import BackendError, FakeBackend
from autoclicker.core.config import (
    ActionType,
    ClickConfig,
    ClickType,
    IntervalConfig,
    KeyConfig,
    KeyMode,
    KeyStep,
    MouseButton,
    Profile,
    RepeatConfig,
    SafetyConfig,
    SequencePoint,
    TargetConfig,
    TargetMode,
)
from autoclicker.core.engine import ClickEngine, EngineCallbacks, StopReason

TIMEOUT = 5.0


def fast_profile(**overrides) -> Profile:
    """A profile that runs flat out with no countdown, for quick tests."""
    base = {
        "interval": IntervalConfig(seconds=0, millis=1),
        "safety": SafetyConfig(countdown_seconds=0.0),
        "repeat": RepeatConfig(until_stopped=False, count=5),
    }
    base.update(overrides)
    return Profile(**base)


class Watcher:
    """Collects callbacks and lets a test block until the run ends."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.reason: StopReason | None = None
        self.detail = ""
        self.errors: list[str] = []
        self.states: list[str] = []
        self.countdowns: list[float] = []

    def callbacks(self) -> EngineCallbacks:
        return EngineCallbacks(
            on_state=lambda state: self.states.append(state.value),
            on_countdown=self.countdowns.append,
            on_error=self.errors.append,
            on_finished=self._finished,
        )

    def _finished(self, reason: StopReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        self.done.set()

    def wait(self) -> None:
        assert self.done.wait(TIMEOUT), "the engine never finished"


def run_to_completion(profile: Profile, backend: FakeBackend | None = None):
    backend = backend or FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)
    watcher.wait()
    return engine, backend, watcher


# -------------------------------------------------------------- fixed repeat


def test_fixed_repeat_fires_exactly_that_many_clicks() -> None:
    engine, backend, watcher = run_to_completion(fast_profile())
    assert len(backend.clicks) == 5
    assert engine.clicks_fired == 5
    assert watcher.reason is StopReason.COMPLETED


def test_button_and_click_type_reach_the_backend() -> None:
    profile = fast_profile(
        click=ClickConfig(button=MouseButton.RIGHT, click_type=ClickType.DOUBLE),
        repeat=RepeatConfig(until_stopped=False, count=3),
    )
    _, backend, _ = run_to_completion(profile)
    assert [c.button for c in backend.clicks] == [MouseButton.RIGHT] * 3
    assert [c.count for c in backend.clicks] == [2, 2, 2]


# ------------------------------------------------------------------ stopping


def test_until_stopped_keeps_going_and_stops_promptly() -> None:
    profile = fast_profile(
        interval=IntervalConfig(seconds=0, millis=5),
        repeat=RepeatConfig(until_stopped=True),
    )
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)

    threading.Event().wait(0.1)
    assert engine.is_running
    engine.stop()

    watcher.wait()
    assert not engine.is_running
    assert watcher.reason is StopReason.USER
    assert len(backend.clicks) > 1


def test_a_long_interval_still_stops_immediately() -> None:
    """The stop must not wait for the current sleep to elapse."""
    profile = fast_profile(
        interval=IntervalConfig(hours=1, seconds=0),
        repeat=RepeatConfig(until_stopped=True),
    )
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)

    threading.Event().wait(0.05)
    engine.stop(timeout=1.0)
    watcher.wait()
    assert len(backend.clicks) == 1


def test_the_stop_reason_is_preserved() -> None:
    profile = fast_profile(repeat=RepeatConfig(until_stopped=True))
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)
    threading.Event().wait(0.05)
    engine.stop(reason=StopReason.FAILSAFE)
    watcher.wait()
    assert watcher.reason is StopReason.FAILSAFE


def test_stopping_during_the_countdown_fires_no_clicks() -> None:
    profile = fast_profile(
        safety=SafetyConfig(countdown_seconds=30.0),
        repeat=RepeatConfig(until_stopped=True),
    )
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)
    threading.Event().wait(0.1)
    engine.stop()
    watcher.wait()

    assert backend.clicks == []
    assert watcher.countdowns
    assert "countdown" in watcher.detail.lower()


# ----------------------------------------------------------------- targeting


def test_follow_cursor_never_moves_the_pointer() -> None:
    profile = fast_profile(target=TargetConfig(mode=TargetMode.FOLLOW_CURSOR))
    _, backend, _ = run_to_completion(profile, FakeBackend(start_position=(640, 480)))
    assert backend.moves == []
    assert all((c.x, c.y) == (640, 480) for c in backend.clicks)


def test_fixed_point_moves_to_the_locked_coordinates() -> None:
    profile = fast_profile(target=TargetConfig(mode=TargetMode.FIXED_POINT, x=300, y=200))
    _, backend, _ = run_to_completion(profile)
    assert backend.moves == [(300, 200)] * 5


def test_fixed_point_supports_negative_coordinates() -> None:
    """A monitor to the left of the primary lives at negative x."""
    profile = fast_profile(target=TargetConfig(mode=TargetMode.FIXED_POINT, x=-800, y=-100))
    _, backend, _ = run_to_completion(profile)
    assert backend.moves == [(-800, -100)] * 5


def test_position_jitter_scatters_around_the_target() -> None:
    profile = fast_profile(
        target=TargetConfig(mode=TargetMode.FIXED_POINT, x=500, y=500, position_jitter_px=8),
        repeat=RepeatConfig(until_stopped=False, count=40),
    )
    _, backend, _ = run_to_completion(profile)
    assert len(set(backend.moves)) > 1
    assert all((x - 500) ** 2 + (y - 500) ** 2 <= 9**2 for x, y in backend.moves)


# ----------------------------------------------------------------- sequences


def test_a_sequence_visits_its_points_in_order() -> None:
    points = [
        SequencePoint(x=10, y=10, button=MouseButton.LEFT),
        SequencePoint(x=20, y=20, button=MouseButton.RIGHT),
        SequencePoint(x=30, y=30, button=MouseButton.MIDDLE),
    ]
    profile = fast_profile(
        target=TargetConfig(mode=TargetMode.SEQUENCE, sequence=points),
        repeat=RepeatConfig(until_stopped=False, count=2),
    )
    engine, backend, watcher = run_to_completion(profile)

    assert backend.moves == [(10, 10), (20, 20), (30, 30)] * 2
    assert [c.button for c in backend.clicks] == [
        MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE
    ] * 2
    assert engine.passes_completed == 2
    assert watcher.reason is StopReason.COMPLETED


def test_sequence_repeat_counts_passes_not_clicks() -> None:
    points = [SequencePoint(x=1, y=1), SequencePoint(x=2, y=2)]
    profile = fast_profile(
        target=TargetConfig(mode=TargetMode.SEQUENCE, sequence=points),
        repeat=RepeatConfig(until_stopped=False, count=3),
    )
    engine, backend, _ = run_to_completion(profile)
    assert engine.passes_completed == 3
    assert len(backend.clicks) == 6


# -------------------------------------------------------------------- errors


class ExplodingBackend(FakeBackend):
    def click(self, button, count=1, gap_ms=0.0, hold_ms=0.0) -> None:  # noqa: D102
        raise BackendError("Accessibility permission is not granted")


def test_a_backend_failure_stops_the_run_and_surfaces_the_message() -> None:
    _, _, watcher = run_to_completion(fast_profile(), ExplodingBackend())
    assert watcher.reason is StopReason.ERROR
    assert "Accessibility" in watcher.detail
    assert watcher.errors


def test_a_broken_callback_does_not_kill_the_run() -> None:
    def sabotage(*_args: object) -> None:
        raise RuntimeError("the UI blew up")

    backend = FakeBackend()
    watcher = Watcher()
    callbacks = watcher.callbacks()
    callbacks.on_click = sabotage
    engine = ClickEngine(backend, callbacks)
    engine.start(fast_profile())
    watcher.wait()

    assert len(backend.clicks) == 5
    assert watcher.reason is StopReason.COMPLETED


def test_an_invalid_profile_is_refused_before_anything_starts() -> None:
    engine = ClickEngine(FakeBackend())
    with pytest.raises(ValueError, match="at least"):
        engine.start(fast_profile(interval=IntervalConfig(seconds=0, millis=0)))
    assert not engine.is_running


def test_starting_twice_does_not_spawn_a_second_thread() -> None:
    profile = fast_profile(
        interval=IntervalConfig(seconds=0, millis=20),
        repeat=RepeatConfig(until_stopped=True),
    )
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)
    first = engine._thread
    engine.start(profile)
    assert engine._thread is first
    engine.stop()
    watcher.wait()


# ---------------------------------------------------------------- key mode


def key_profile(**overrides) -> Profile:
    base = {
        "action": ActionType.KEY,
        "interval": IntervalConfig(seconds=0, millis=1),
        "safety": SafetyConfig(countdown_seconds=0.0),
        "repeat": RepeatConfig(until_stopped=False, count=4),
        "key": KeyConfig(spec="e"),
    }
    base.update(overrides)
    return Profile(**base)


def test_a_single_key_is_pressed_the_requested_number_of_times() -> None:
    _, backend, watcher = run_to_completion(key_profile())
    assert [k.spec for k in backend.keys] == ["e"] * 4
    assert backend.clicks == [], "key mode must not click"
    assert watcher.reason is StopReason.COMPLETED


def test_key_mode_never_moves_the_pointer() -> None:
    """Keystrokes go to whatever window has focus; coordinates are meaningless."""
    profile = key_profile(
        target=TargetConfig(mode=TargetMode.FIXED_POINT, x=500, y=500),
    )
    _, backend, _ = run_to_completion(profile)
    assert backend.moves == []


def test_a_key_sequence_presses_in_order_and_counts_passes() -> None:
    steps = [KeyStep(spec="a"), KeyStep(spec="<ctrl>+v"), KeyStep(spec="<f5>")]
    profile = key_profile(
        key=KeyConfig(mode=KeyMode.SEQUENCE, sequence=steps),
        repeat=RepeatConfig(until_stopped=False, count=2),
    )
    engine, backend, watcher = run_to_completion(profile)

    assert [k.spec for k in backend.keys] == ["a", "<ctrl>+v", "<f5>"] * 2
    assert engine.passes_completed == 2
    assert watcher.reason is StopReason.COMPLETED


def test_a_key_step_can_override_the_interval() -> None:
    steps = [KeyStep(spec="a", delay_after_ms=5), KeyStep(spec="b")]
    profile = key_profile(
        key=KeyConfig(mode=KeyMode.SEQUENCE, sequence=steps),
        repeat=RepeatConfig(until_stopped=False, count=1),
    )
    _, backend, _ = run_to_completion(profile)
    assert [k.spec for k in backend.keys] == ["a", "b"]


def test_the_hold_duration_reaches_the_backend() -> None:
    profile = key_profile(key=KeyConfig(spec="w", hold_ms=40.0),
                          repeat=RepeatConfig(until_stopped=False, count=2))
    _, backend, _ = run_to_completion(profile)
    assert [k.hold_ms for k in backend.keys] == [40.0, 40.0]


def test_key_mode_reports_through_the_key_callback() -> None:
    backend = FakeBackend()
    watcher = Watcher()
    callbacks = watcher.callbacks()
    seen: list[tuple[int, str]] = []
    callbacks.on_key = lambda total, spec: seen.append((total, spec))
    engine = ClickEngine(backend, callbacks)
    engine.start(key_profile(repeat=RepeatConfig(until_stopped=False, count=3)))
    watcher.wait()
    assert seen == [(1, "e"), (2, "e"), (3, "e")]


def test_key_mode_ignores_a_leftover_empty_click_sequence() -> None:
    """Switching to keys must not be blocked by click settings you are not using."""
    profile = key_profile(target=TargetConfig(mode=TargetMode.SEQUENCE, sequence=[]))
    assert profile.validate() == []
    _, backend, _ = run_to_completion(profile)
    assert len(backend.keys) == 4


def test_a_key_run_with_no_key_chosen_is_refused() -> None:
    engine = ClickEngine(FakeBackend())
    with pytest.raises(ValueError, match="Choose a key"):
        engine.start(key_profile(key=KeyConfig(spec="")))


def test_key_mode_stops_promptly_when_asked() -> None:
    profile = key_profile(
        interval=IntervalConfig(seconds=0, millis=5),
        repeat=RepeatConfig(until_stopped=True),
    )
    backend = FakeBackend()
    watcher = Watcher()
    engine = ClickEngine(backend, watcher.callbacks())
    engine.start(profile)
    threading.Event().wait(0.1)
    engine.stop()
    watcher.wait()
    assert len(backend.keys) > 1
    assert not engine.is_running
