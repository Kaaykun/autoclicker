"""Drift-free interval scheduling, plus the jitter that feeds it.

A naive ``while running: click(); sleep(interval)`` loop drifts: every
iteration silently adds the click duration and the sleep overshoot, so a
"100 ms" clicker quietly runs at 104 ms and the error compounds. This module
works on absolute deadlines from a monotonic clock instead, so the error never
accumulates.

Every moving part -- the clock, the blocking wait, the yield -- is injectable,
which is what lets the tests fast-forward simulated hours without sleeping.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

from .config import MIN_INTERVAL_MS, IntervalConfig, JitterMode

#: How close to the deadline we stop blocking and start spinning. Blocking
#: sleeps routinely overshoot by a millisecond or more; a short spin buys back
#: that precision without burning a core for the whole interval.
DEFAULT_SPIN_THRESHOLD_S = 0.002


def jittered_interval_ms(interval: IntervalConfig, rng: random.Random) -> float:
    """Return this iteration's interval in milliseconds, jitter applied.

    Never returns less than ``MIN_INTERVAL_MS``, whatever the jitter settings
    say -- a negative or zero interval would spin the engine flat out.
    """
    base = interval.total_ms
    if interval.jitter_mode is JitterMode.OFF or interval.jitter_amount <= 0:
        return max(base, MIN_INTERVAL_MS)

    if interval.jitter_mode is JitterMode.PERCENT:
        spread = base * (interval.jitter_amount / 100.0)
    else:
        spread = interval.jitter_amount

    return max(base + rng.uniform(-spread, spread), MIN_INTERVAL_MS)


def jittered_position(x: int, y: int, radius_px: int, rng: random.Random) -> tuple[int, int]:
    """Scatter a point uniformly inside a disc of ``radius_px``.

    A disc rather than a square, and ``sqrt``-scaled so the density is even
    rather than clustered at the centre -- square jitter has visible corners
    and centre-heavy jitter has a visible bullseye.
    """
    if radius_px <= 0:
        return x, y
    angle = rng.uniform(0.0, 2.0 * math.pi)
    distance = radius_px * math.sqrt(rng.random())
    return round(x + distance * math.cos(angle)), round(y + distance * math.sin(angle))


def _blocking_wait(timeout: float) -> bool:
    """Default waiter: sleep, and report that nothing interrupted us."""
    time.sleep(timeout)
    return False


def _never_interrupted() -> bool:
    return False


class DeadlineScheduler:
    """Paces a loop to absolute deadlines instead of cumulative sleeps.

    Args:
        clock: Monotonic time source, in seconds.
        waiter: Blocking wait of up to ``timeout`` seconds, returning ``True``
            if it was interrupted (in the engine this is ``Event.wait``, so a
            stop is noticed immediately even mid-interval).
        is_interrupted: Cheap non-blocking check used during the final spin.
        yielder: Called while spinning, to hand the CPU back briefly.
        spin_threshold: Seconds before the deadline to switch from blocking to
            spinning. Set to 0 to disable spinning entirely.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        waiter: Callable[[float], bool] = _blocking_wait,
        is_interrupted: Callable[[], bool] = _never_interrupted,
        yielder: Callable[[], None] | None = None,
        spin_threshold: float = DEFAULT_SPIN_THRESHOLD_S,
    ) -> None:
        self._clock = clock
        self._waiter = waiter
        self._is_interrupted = is_interrupted
        self._yielder = yielder if yielder is not None else lambda: time.sleep(0)
        self._spin_threshold = spin_threshold
        self._deadline = clock()
        self.late_resyncs = 0

    @property
    def deadline(self) -> float:
        return self._deadline

    def reset(self) -> None:
        """Anchor the schedule to now. Call once before the loop starts."""
        self._deadline = self._clock()
        self.late_resyncs = 0

    def wait_for(self, interval_seconds: float) -> bool:
        """Advance the deadline by one interval and block until it arrives.

        Returns ``False`` if the wait was interrupted, ``True`` if the deadline
        was reached normally.
        """
        self._deadline += interval_seconds
        now = self._clock()

        if self._deadline < now - interval_seconds:
            # We fell more than a whole interval behind -- a slow click, a
            # system hiccup, a laptop waking from sleep. Resync to now instead
            # of firing a burst of catch-up clicks, which is never what someone
            # wants from a clicker.
            self._deadline = now
            self.late_resyncs += 1

        return self._sleep_until(self._deadline)

    def _sleep_until(self, deadline: float) -> bool:
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return not self._is_interrupted()
            if remaining > self._spin_threshold:
                if self._waiter(remaining - self._spin_threshold):
                    return False
            else:
                if self._is_interrupted():
                    return False
                self._yielder()
