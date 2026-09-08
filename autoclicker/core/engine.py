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
from .config import Profile, TargetMode
from .scheduler import DeadlineScheduler, jittered_interval_ms, jittered_position

logger = logging.getLogger(__name__)

#: Granularity of the pre-run countdown, in seconds.
COUNTDOWN_TICK_S = 0.05


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
    #: (clicks_fired, x, y)
    on_click: Callable[[int, int, int], None] | None = None
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

    def _loop(self, profile: Profile, scheduler: DeadlineScheduler) -> tuple[StopReason, str]:
        target = profile.target
        repeat = profile.repeat
        sequence = list(target.sequence) if target.mode is TargetMode.SEQUENCE else []
        index = 0

        while not self._stop.is_set():
            if sequence:
                point = sequence[index]
                button, click_type = point.button, point.click_type
                x, y = jittered_position(point.x, point.y, target.position_jitter_px, self._rng)
                self._backend.move_to(x, y)
                delay_ms: float | None = point.delay_after_ms or None
            else:
                button, click_type = profile.click.button, profile.click.click_type
                delay_ms = None
                if target.mode is TargetMode.FIXED_POINT:
                    x, y = jittered_position(
                        target.x, target.y, target.position_jitter_px, self._rng
                    )
                    self._backend.move_to(x, y)
                else:
                    x, y = self._backend.position()
                    if target.position_jitter_px > 0:
                        x, y = jittered_position(x, y, target.position_jitter_px, self._rng)
                        self._backend.move_to(x, y)

            self._backend.click(
                button,
                click_type.count,
                profile.click.inter_click_gap_ms,
                profile.click.hold_ms,
            )
            self.clicks_fired += 1
            self._emit(self._callbacks.on_click, self.clicks_fired, x, y)

            if sequence:
                index += 1
                if index >= len(sequence):
                    index = 0
                    self.passes_completed += 1
                    if not repeat.until_stopped and self.passes_completed >= repeat.count:
                        return (
                            StopReason.COMPLETED,
                            f"Finished {self.passes_completed} passes "
                            f"({self.clicks_fired} clicks).",
                        )
            elif not repeat.until_stopped and self.clicks_fired >= repeat.count:
                return StopReason.COMPLETED, f"Finished {self.clicks_fired} clicks."

            interval_ms = (
                delay_ms if delay_ms is not None
                else jittered_interval_ms(profile.interval, self._rng)
            )
            if not scheduler.wait_for(interval_ms / 1000.0):
                break

        return self._requested_reason, f"Stopped after {self.clicks_fired} clicks."

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
