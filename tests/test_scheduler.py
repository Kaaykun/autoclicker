"""Jitter bounds and the drift-free scheduler."""

from __future__ import annotations

import random

from autoclicker.core.config import MIN_INTERVAL_MS, IntervalConfig, JitterMode
from autoclicker.core.scheduler import (
    DeadlineScheduler,
    jittered_interval_ms,
    jittered_position,
)


class FakeClock:
    """A clock that only moves when we say so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_scheduler(clock: FakeClock, overshoot: float = 0.0) -> DeadlineScheduler:
    """A scheduler whose blocking wait always oversleeps by ``overshoot``."""

    def waiter(timeout: float) -> bool:
        clock.advance(timeout + overshoot)
        return False

    return DeadlineScheduler(clock=clock, waiter=waiter, spin_threshold=0.0)


# ----------------------------------------------------------------- jitter


def test_jitter_off_returns_the_exact_interval() -> None:
    interval = IntervalConfig(seconds=0, millis=250)
    rng = random.Random(0)
    assert jittered_interval_ms(interval, rng) == 250.0


def test_percentage_jitter_stays_inside_its_band() -> None:
    interval = IntervalConfig(
        seconds=0, millis=100, jitter_mode=JitterMode.PERCENT, jitter_amount=20
    )
    rng = random.Random(1234)
    samples = [jittered_interval_ms(interval, rng) for _ in range(2000)]
    assert all(80.0 <= s <= 120.0 for s in samples)
    # And it actually varies, rather than quietly doing nothing.
    assert len(set(samples)) > 100


def test_millisecond_jitter_stays_inside_its_band() -> None:
    interval = IntervalConfig(
        seconds=0, millis=100, jitter_mode=JitterMode.MILLIS, jitter_amount=30
    )
    rng = random.Random(99)
    samples = [jittered_interval_ms(interval, rng) for _ in range(2000)]
    assert all(70.0 <= s <= 130.0 for s in samples)


def test_jitter_can_never_drive_the_interval_below_the_floor() -> None:
    """A 200% jitter on a 5 ms interval would otherwise go negative."""
    interval = IntervalConfig(
        seconds=0, millis=5, jitter_mode=JitterMode.PERCENT, jitter_amount=100
    )
    rng = random.Random(7)
    samples = [jittered_interval_ms(interval, rng) for _ in range(2000)]
    assert min(samples) >= MIN_INTERVAL_MS


def test_position_jitter_stays_inside_the_radius() -> None:
    rng = random.Random(3)
    points = [jittered_position(500, 400, 10, rng) for _ in range(2000)]
    assert all((x - 500) ** 2 + (y - 400) ** 2 <= 11**2 for x, y in points)
    assert len(set(points)) > 50


def test_zero_position_jitter_is_exact() -> None:
    rng = random.Random(3)
    assert jittered_position(-100, 250, 0, rng) == (-100, 250)


# -------------------------------------------------------------- scheduling


def test_deadlines_do_not_drift_even_with_slow_work_and_oversleeping() -> None:
    """The whole point of the module: error must not accumulate.

    Each iteration burns 1 ms of "click" time and oversleeps by 0.5 ms. A naive
    ``sleep(interval)`` loop would finish 750 ms late over 500 iterations.
    """
    clock = FakeClock()
    scheduler = make_scheduler(clock, overshoot=0.0005)
    scheduler.reset()

    interval = 0.1
    iterations = 500
    for _ in range(iterations):
        clock.advance(0.001)  # the click itself
        assert scheduler.wait_for(interval)

    expected = iterations * interval
    assert abs(clock.now - expected) < 0.005
    assert scheduler.late_resyncs == 0


def test_falling_a_whole_interval_behind_resyncs_instead_of_bursting() -> None:
    """If work outruns the interval we must not queue up catch-up clicks."""
    clock = FakeClock()
    scheduler = make_scheduler(clock)
    scheduler.reset()

    for _ in range(10):
        clock.advance(0.05)  # work takes 50 ms on a 10 ms interval
        scheduler.wait_for(0.01)

    assert scheduler.late_resyncs == 10
    # The deadline tracks the present, rather than sitting half a second behind.
    assert scheduler.deadline >= clock.now - 0.02


def test_an_interrupted_wait_reports_false() -> None:
    clock = FakeClock()
    scheduler = DeadlineScheduler(
        clock=clock,
        waiter=lambda _timeout: True,  # "the stop event fired"
        spin_threshold=0.0,
    )
    scheduler.reset()
    assert scheduler.wait_for(3600.0) is False


def test_reset_clears_the_late_counter() -> None:
    clock = FakeClock()
    scheduler = make_scheduler(clock)
    scheduler.reset()
    clock.advance(1.0)
    scheduler.wait_for(0.01)
    assert scheduler.late_resyncs == 1
    scheduler.reset()
    assert scheduler.late_resyncs == 0
