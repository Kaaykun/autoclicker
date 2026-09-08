"""Click backends.

``ClickBackend`` is the seam that keeps the engine testable and headless-safe:
``PynputBackend`` drives the real mouse, ``FakeBackend`` just records what it
was asked to do, so the test suite exercises the whole engine without a single
real click ever reaching the desktop.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .config import MouseButton

logger = logging.getLogger(__name__)

#: How long to wait for the windowing system to actually apply a pointer move
#: before clicking. See :func:`settle_pointer`.
MOVE_SETTLE_TIMEOUT_S = 0.03
MOVE_SETTLE_POLL_S = 0.001
MOVE_SETTLE_TOLERANCE_PX = 1
#: If the readback never agrees with what we set, stop paying for the wait.
MOVE_SETTLE_GIVE_UP_AFTER = 5


def settle_pointer(
    target: tuple[int, int],
    get_position: Callable[[], tuple[int, int]],
    *,
    timeout_s: float = MOVE_SETTLE_TIMEOUT_S,
    poll_s: float = MOVE_SETTLE_POLL_S,
    tolerance_px: int = MOVE_SETTLE_TOLERANCE_PX,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Block until the pointer really is where we asked it to go.

    Setting the pointer position posts an event; it does not take effect
    synchronously. pynput builds a click event from the pointer position it
    reads *at press time*, so clicking straight after a move can put the click
    at the previous location -- which in a sequence means every click lands one
    point behind, and the last point of a pass appears to be skipped.

    Returns whether it converged, so a caller can stop paying for the wait on a
    system where the readback never matches what was written.
    """
    x, y = target
    deadline = clock() + timeout_s
    while True:
        try:
            current_x, current_y = get_position()
        except Exception:
            return False
        if abs(current_x - x) <= tolerance_px and abs(current_y - y) <= tolerance_px:
            return True
        if clock() >= deadline:
            return False
        sleep(poll_s)


class BackendError(RuntimeError):
    """The input backend could not be reached or refused to act."""


@runtime_checkable
class ClickBackend(Protocol):
    """The minimal surface the engine needs from an input backend."""

    def position(self) -> tuple[int, int]:
        """Current pointer position, in virtual-desktop coordinates."""
        ...

    def move_to(self, x: int, y: int) -> None:
        """Move the pointer to an absolute position."""
        ...

    def click(
        self,
        button: MouseButton,
        count: int = 1,
        gap_ms: float = 0.0,
        hold_ms: float = 0.0,
    ) -> None:
        """Press and release ``button`` ``count`` times."""
        ...


@dataclass
class ClickRecord:
    """One click as seen by ``FakeBackend``."""

    at: float
    x: int
    y: int
    button: MouseButton
    count: int


class FakeBackend:
    """An in-memory backend for tests. Records instead of clicking."""

    def __init__(self, start_position: tuple[int, int] = (0, 0), clock=time.perf_counter) -> None:
        self._x, self._y = start_position
        self._clock = clock
        self.clicks: list[ClickRecord] = []
        self.moves: list[tuple[int, int]] = []

    def position(self) -> tuple[int, int]:
        return self._x, self._y

    def move_to(self, x: int, y: int) -> None:
        self._x, self._y = x, y
        self.moves.append((x, y))

    def click(
        self,
        button: MouseButton,
        count: int = 1,
        gap_ms: float = 0.0,
        hold_ms: float = 0.0,
    ) -> None:
        self.clicks.append(ClickRecord(self._clock(), self._x, self._y, button, count))


@dataclass
class _PynputHandles:
    """Lazily imported pynput objects, kept out of module import time."""

    controller: object
    buttons: dict[MouseButton, object] = field(default_factory=dict)


class PynputBackend:
    """The real backend, driving the system pointer through pynput.

    pynput is imported lazily so that importing ``autoclicker.core`` on a
    headless CI runner -- where there is no display to attach to -- does not
    explode.
    """

    def __init__(self, settle: bool = True) -> None:
        self._handles: _PynputHandles | None = None
        self._settle = settle
        self._settle_failures = 0

    def _ensure(self) -> _PynputHandles:
        if self._handles is not None:
            return self._handles
        try:
            from pynput import mouse
        except Exception as exc:  # pragma: no cover - platform dependent
            raise BackendError(f"Could not load the input backend (pynput): {exc}") from exc

        self._handles = _PynputHandles(
            controller=mouse.Controller(),
            buttons={
                MouseButton.LEFT: mouse.Button.left,
                MouseButton.RIGHT: mouse.Button.right,
                MouseButton.MIDDLE: mouse.Button.middle,
            },
        )
        return self._handles

    def position(self) -> tuple[int, int]:
        handles = self._ensure()
        try:
            x, y = handles.controller.position  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - platform dependent
            raise BackendError(f"Could not read the pointer position: {exc}") from exc
        return round(x), round(y)

    def move_to(self, x: int, y: int) -> None:
        handles = self._ensure()
        try:
            handles.controller.position = (x, y)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - platform dependent
            raise BackendError(f"Could not move the pointer: {exc}") from exc

        if not self._settle:
            return
        if settle_pointer((x, y), self.position):
            self._settle_failures = 0
            return

        self._settle_failures += 1
        if self._settle_failures >= MOVE_SETTLE_GIVE_UP_AFTER:
            # The readback disagrees with what we write -- a coordinate-space
            # mismatch rather than lag. Waiting will never help, so stop
            # spending 30 ms on every click for it.
            self._settle = False
            logger.info(
                "Pointer position readback never matches what is written; "
                "skipping the post-move settle from now on."
            )

    def click(
        self,
        button: MouseButton,
        count: int = 1,
        gap_ms: float = 0.0,
        hold_ms: float = 0.0,
    ) -> None:
        handles = self._ensure()
        btn = handles.buttons[button]
        controller = handles.controller

        try:
            if gap_ms <= 0 and hold_ms <= 0:
                # The native path. pynput sets the platform's click-count field
                # here, which is the only reason a double-click registers as a
                # double-click rather than as two unrelated single clicks.
                controller.click(btn, count)  # type: ignore[attr-defined]
                return

            for index in range(count):
                if index:
                    time.sleep(gap_ms / 1000.0)
                controller.press(btn)  # type: ignore[attr-defined]
                if hold_ms > 0:
                    time.sleep(hold_ms / 1000.0)
                controller.release(btn)  # type: ignore[attr-defined]
        except BackendError:
            raise
        except Exception as exc:  # pragma: no cover - platform dependent
            raise BackendError(f"Could not send the click: {exc}") from exc
