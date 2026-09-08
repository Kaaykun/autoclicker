"""Click backends.

``ClickBackend`` is the seam that keeps the engine testable: ``PynputBackend``
drives the real mouse, ``FakeBackend`` records calls so tests never fire a
click. Implemented in M1.
"""

from __future__ import annotations

from typing import Protocol


class ClickBackend(Protocol):
    """Minimal surface the engine needs from an input backend."""

    def position(self) -> tuple[int, int]:
        """Return the current pointer position in virtual-desktop coordinates."""
        ...

    def move_to(self, x: int, y: int) -> None:
        """Move the pointer to an absolute position."""
        ...

    def click(self, button: str, count: int, gap_ms: float, hold_ms: float) -> None:
        """Press and release ``button`` ``count`` times."""
        ...
