"""The post-move settle.

Setting the pointer position posts an event rather than applying it, and
pynput builds a click from the position it reads at press time. Clicking
straight after a move can therefore land at the previous location -- in a
sequence, every click one point behind, so the last point looks skipped.
"""

from __future__ import annotations

import pytest

from autoclicker.core.backends import settle_pointer


class LaggingPointer:
    """Reports the old position for the first ``lag`` reads after a move."""

    def __init__(self, start=(0, 0), lag: int = 0, never_arrives: bool = False) -> None:
        self.current = start
        self.pending = start
        self.lag = lag
        self.never_arrives = never_arrives
        self.reads = 0

    def move_to(self, x: int, y: int) -> None:
        self.pending = (x, y)
        self.reads = 0

    def position(self) -> tuple[int, int]:
        self.reads += 1
        if not self.never_arrives and self.reads > self.lag:
            self.current = self.pending
        return self.current


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def run(pointer: LaggingPointer, target=(500, 400), timeout_s=0.03) -> tuple[bool, FakeClock]:
    clock = FakeClock()
    pointer.move_to(*target)
    settled = settle_pointer(
        target,
        pointer.position,
        timeout_s=timeout_s,
        poll_s=0.001,
        clock=clock,
        sleep=clock.sleep,
    )
    return settled, clock


def test_an_instant_move_costs_nothing() -> None:
    settled, clock = run(LaggingPointer(lag=0))
    assert settled
    assert clock.now == 0.0, "no waiting when the move already landed"


def test_a_lagging_move_is_waited_out() -> None:
    pointer = LaggingPointer(lag=5)
    settled, clock = run(pointer)
    assert settled
    assert 0 < clock.now < 0.03


def test_a_move_that_never_lands_gives_up_within_the_timeout() -> None:
    settled, clock = run(LaggingPointer(never_arrives=True))
    assert not settled
    assert clock.now <= 0.031


def test_a_pixel_of_slop_is_close_enough() -> None:
    """Readback can round differently from what was written."""
    pointer = LaggingPointer(start=(500, 401), never_arrives=True)
    clock = FakeClock()
    assert settle_pointer(
        (500, 400), pointer.position, clock=clock, sleep=clock.sleep, tolerance_px=1
    )


def test_a_pointer_that_cannot_be_read_does_not_hang() -> None:
    def explode() -> tuple[int, int]:
        raise RuntimeError("Accessibility permission is not granted")

    assert settle_pointer((1, 1), explode) is False


@pytest.mark.parametrize("target", [(-1920, -200), (0, 0), (3840, 2160)])
def test_it_works_anywhere_on_the_virtual_desktop(target: tuple[int, int]) -> None:
    pointer = LaggingPointer(lag=2)
    settled, _ = run(pointer, target=target)
    assert settled
    assert pointer.current == target
