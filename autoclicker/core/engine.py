"""The click loop.

The engine runs on its own thread and is driven by a ``threading.Event``, which
is what makes a stop immediate rather than "immediate once the current sleep
finishes" -- on a three-hour interval that distinction is the whole ballgame.

Callbacks fire **on the engine thread**. Anything that touches a GUI must
marshal them onto the UI thread itself; the ``ui`` layer adapts them to Qt
signals for exactly that reason.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .backends import BackendError, ClickBackend
from .config import ClickType, KeyMode, MouseButton, Profile, TargetMode
from .scheduler import DeadlineScheduler, jittered_interval_ms, jittered_position
from .units import plural

logger = logging.getLogger(__name__)

#: Granularity of the pre-run countdown, in seconds.
COUNTDOWN_TICK_S = 0.05


@dataclass
class _Step:
    """One repetition's worth of work, whatever the action type.

    Clicks and key presses differ only in what happens at the moment of firing;
    the pacing, repeat counting and stop handling around them are identical, so
    both are flattened into a list of these and driven by one loop.
    """

    is_key: bool = False
    spec: str = ""
    hold_ms: float = 0.0
    x: int = 0
    y: int = 0
    follow_cursor: bool = False
    button: MouseButton = MouseButton.LEFT
    click_type: ClickType = ClickType.SINGLE
    #: Overrides the global interval after this step when set.
    delay_after_ms: float | None = None


class EngineState(str, Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    RUNNING = "running"


class StopReason(str, Enum):
    USER = "user"
    COMPLETED = "completed"
    PANIC = "panic"
    FAILSAFE = "failsafe"
    ERROR = "error"


@dataclass
class EngineCallbacks:
    """Hooks into the run. All optional, all called on the engine thread."""

    on_state: Callable[[EngineState], None] | None = None
    #: (actions_fired, x, y)
    on_click: Callable[[int, int, int], None] | None = None
    #: (actions_fired, key spec) -- the keyboard equivalent of on_click.
    on_key: Callable[[int, str], None] | None = None
    #: Seconds remaining before the first click.
    on_countdown: Callable[[float], None] | None = None
    #: (reason, human-readable detail)
    on_finished: Callable[[StopReason, str], None] | None = None
    on_error: Callable[[str], None] | None = None


class ClickEngine:
    """Runs a :class:`~autoclicker.core.config.Profile` until told to stop."""

    def __init__(
        self,
        backend: ClickBackend,
        callbacks: EngineCallbacks | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.perf_counter,
        spin_threshold: float | None = None,
    ) -> None:
        self._backend = backend
        self._callbacks = callbacks or EngineCallbacks()
        self._rng = rng if rng is not None else random.Random()
        self._clock = clock
        self._spin_threshold = spin_threshold

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = EngineState.IDLE
        self._requested_reason = StopReason.USER

        self.clicks_fired = 0
        self.passes_completed = 0

    # ------------------------------------------------------------------ state

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------------------------------------------------------------- control

    def start(self, profile: Profile) -> None:
        """Begin a run. Raises ``ValueError`` if the profile is not runnable."""
        problems = profile.validate()
        if problems:
            raise ValueError("; ".join(problems))
        if self.is_running:
            return

        self._stop.clear()
        self._requested_reason = StopReason.USER
        self.clicks_fired = 0
        self.passes_completed = 0

        self._thread = threading.Thread(
            target=self._run,
            args=(profile,),
            name="autoclicker-engine",
            daemon=True,
        )
        self._thread.start()

    def stop(self, reason: StopReason = StopReason.USER, timeout: float | None = 2.0) -> None:
        """Ask the run to end and wait briefly for the thread to unwind."""
        if not self.is_running:
            return
        self._requested_reason = reason
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def toggle(self, profile: Profile) -> bool:
        """Start if idle, stop if running. Returns whether it is now running."""
        if self.is_running:
            self.stop()
            return False
        self.start(profile)
        return True

    # ------------------------------------------------------------------- loop

    def _run(self, profile: Profile) -> None:
        reason = StopReason.USER
        detail = ""
        try:
            if self._countdown(profile.safety.countdown_seconds):
                self._set_state(EngineState.RUNNING)
                scheduler = DeadlineScheduler(
                    clock=self._clock,
                    waiter=self._stop.wait,
                    is_interrupted=self._stop.is_set,
                    **({} if self._spin_threshold is None else
                       {"spin_threshold": self._spin_threshold}),
                )
                scheduler.reset()
                reason, detail = self._loop(profile, scheduler)
            else:
                reason, detail = self._requested_reason, "Stopped during the countdown."
        except BackendError as exc:
            reason, detail = StopReason.ERROR, str(exc)
            self._emit(self._callbacks.on_error, detail)
        except Exception as exc:  # noqa: BLE001 - the thread must not die silently
            logger.exception("Autoclicker engine crashed")
            reason, detail = StopReason.ERROR, f"Unexpected error: {exc}"
            self._emit(self._callbacks.on_error, detail)
        finally:
            self._stop.set()
            self._set_state(EngineState.IDLE)
            self._emit(self._callbacks.on_finished, reason, detail)

    def _countdown(self, seconds: float) -> bool:
        """Tick down before the first click. False if stopped part-way."""
        if seconds <= 0:
            return True
        self._set_state(EngineState.COUNTDOWN)
        end = self._clock() + seconds
        while True:
            remaining = end - self._clock()
            if remaining <= 0:
                return True
            self._emit(self._callbacks.on_countdown, remaining)
            if self._stop.wait(min(COUNTDOWN_TICK_S, remaining)):
                return False

    def _build_steps(self, profile: Profile) -> list[_Step]:
        """Flatten whatever the profile describes into a list of repetitions."""
        if profile.sends_keys:
            key = profile.key
            if key.mode is KeyMode.SEQUENCE:
                return [
                    _Step(
                        is_key=True,
                        spec=step.spec,
                        hold_ms=step.hold_ms,
                        delay_after_ms=step.delay_after_ms or None,
                    )
                    for step in key.sequence
                ]
            return [_Step(is_key=True, spec=key.spec, hold_ms=key.hold_ms)]

        target = profile.target
        if target.mode is TargetMode.SEQUENCE:
            return [
                _Step(
                    x=point.x,
                    y=point.y,
                    button=point.button,
                    click_type=point.click_type,
                    delay_after_ms=point.delay_after_ms or None,
                )
                for point in target.sequence
            ]
        return [
            _Step(
                x=target.x,
                y=target.y,
                follow_cursor=target.mode is TargetMode.FOLLOW_CURSOR,
                button=profile.click.button,
                click_type=profile.click.click_type,
            )
        ]

    def _perform(self, step: _Step, profile: Profile) -> None:
        """Fire one step and report it."""
        if step.is_key:
            self._backend.press_key(step.spec, step.hold_ms)
            self.clicks_fired += 1
            self._emit(self._callbacks.on_key, self.clicks_fired, step.spec)
            return

        jitter = profile.target.position_jitter_px
        if step.follow_cursor:
            x, y = self._backend.position()
            if jitter > 0:
                x, y = jittered_position(x, y, jitter, self._rng)
                self._backend.move_to(x, y)
        else:
            x, y = jittered_position(step.x, step.y, jitter, self._rng)
            self._backend.move_to(x, y)

        self._backend.click(
            step.button,
            step.click_type.count,
            profile.click.inter_click_gap_ms,
            profile.click.hold_ms,
        )
        self.clicks_fired += 1
        self._emit(self._callbacks.on_click, self.clicks_fired, x, y)

    def _loop(self, profile: Profile, scheduler: DeadlineScheduler) -> tuple[StopReason, str]:
        repeat = profile.repeat
        steps = self._build_steps(profile)
        if not steps:
            return StopReason.COMPLETED, "Nothing to do."

        # A single step counts repetitions; a real sequence counts complete
        # passes through it, which is what someone setting "repeat 5 times" on
        # a four-point sequence means.
        counts_passes = len(steps) > 1
        noun = "pass" if counts_passes else ("press" if steps[0].is_key else "click")
        index = 0

        while not self._stop.is_set():
            step = steps[index]
            self._perform(step, profile)

            index += 1
            if index >= len(steps):
                index = 0
                self.passes_completed += 1

            if not repeat.until_stopped:
                done = self.passes_completed if counts_passes else self.clicks_fired
                if done >= repeat.count:
                    detail = f"Finished {done} {plural(noun, done)}."
                    if counts_passes:
                        detail += f" ({self.clicks_fired} actions.)"
                    return StopReason.COMPLETED, detail

            interval_ms = (
                step.delay_after_ms
                if step.delay_after_ms is not None
                else jittered_interval_ms(profile.interval, self._rng)
            )
            if not scheduler.wait_for(interval_ms / 1000.0):
                break

        return self._requested_reason, f"Stopped after {self.clicks_fired} actions."

    # ------------------------------------------------------------------ misc

    def _set_state(self, state: EngineState) -> None:
        if state is self._state:
            return
        self._state = state
        self._emit(self._callbacks.on_state, state)

    @staticmethod
    def _emit(callback: Callable[..., None] | None, *args: object) -> None:
        """Call a listener without letting its bugs take the engine down."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - a broken listener is not fatal
            logger.exception("Autoclicker callback raised")
