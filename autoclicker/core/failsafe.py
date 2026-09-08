"""The corner failsafe.

When a clicker is firing every millisecond it eats the click you are trying to
land on its own Stop button. Slamming the pointer into a screen corner is the
gesture that always works, because it needs no click at all.

The geometry is a pure function so it can be tested; the listener around it is
a thin pynput wrapper.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

#: (left, top, right, bottom) for one screen, in virtual-desktop coordinates.
ScreenRect = tuple[int, int, int, int]


def is_in_corner(x: int, y: int, screens: Sequence[ScreenRect], margin_px: int) -> bool:
    """True if (x, y) sits in the corner box of any screen.

    Checked per screen rather than across the whole virtual desktop, so the
    corners of a second monitor work too -- on a multi-monitor setup most
    corners are interior to the combined bounding box.
    """
    if margin_px < 1:
        return False
    for left, top, right, bottom in screens:
        if not (left <= x <= right and top <= y <= bottom):
            continue
        near_x = x - left < margin_px or right - x < margin_px
        near_y = y - top < margin_px or bottom - y < margin_px
        if near_x and near_y:
            return True
    return False


class CornerFailsafe:
    """Watches pointer movement and fires once when a corner is hit."""

    def __init__(
        self,
        screens: Sequence[ScreenRect],
        margin_px: int,
        on_trigger: Callable[[], None],
    ) -> None:
        self._screens = list(screens)
        self._margin = margin_px
        self._on_trigger = on_trigger
        self._listener = None
        self._fired = False

    @property
    def is_active(self) -> bool:
        return self._listener is not None

    def start(self) -> None:
        if self.is_active or not self._screens:
            return
        self._fired = False
        try:
            from pynput import mouse

            listener = mouse.Listener(on_move=self._moved)
            listener.daemon = True
            listener.start()
        except Exception:  # pragma: no cover - platform dependent
            logger.warning("Corner failsafe unavailable", exc_info=True)
            return
        self._listener = listener

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # pragma: no cover - platform dependent
                logger.exception("Could not stop the corner failsafe")

    def _moved(self, x: float, y: float) -> None:
        if self._fired:
            return
        if is_in_corner(round(x), round(y), self._screens, self._margin):
            self._fired = True
            self._on_trigger()
