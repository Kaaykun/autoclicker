"""Recording real mouse clicks into a replayable sequence.

The listener is a thin pynput wrapper; the interesting part is
:func:`points_from_events`, which is pure and therefore testable. It does two
things a raw event log cannot:

* **Merges rapid repeat clicks into one point.** Two clicks in the same spot
  200 ms apart are a double-click, not two singles, and replaying them as two
  singles would not open the folder you just double-clicked.
* **Turns absolute timestamps into per-point delays**, which is what makes a
  recording reproduce your rhythm rather than firing everything at the global
  interval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import ClickType, MouseButton, SequencePoint

logger = logging.getLogger(__name__)

#: Two clicks closer together than this, in the same place, are one gesture.
DEFAULT_DOUBLE_CLICK_MS = 300.0
#: How far the pointer may drift and still count as "the same place".
DEFAULT_MERGE_RADIUS_PX = 4
#: Clicks in the first moments after Record is pressed are the user letting go
#: of the Record button itself.
DEFAULT_GRACE_SECONDS = 0.4

_CLICK_TYPES = (ClickType.SINGLE, ClickType.DOUBLE, ClickType.TRIPLE)


@dataclass(frozen=True)
class ClickEvent:
    x: int
    y: int
    button: MouseButton
    at: float


def points_from_events(
    events: list[ClickEvent],
    *,
    keep_timing: bool = True,
    double_click_ms: float = DEFAULT_DOUBLE_CLICK_MS,
    merge_radius_px: int = DEFAULT_MERGE_RADIUS_PX,
) -> list[SequencePoint]:
    """Fold a click log into sequence points."""
    if not events:
        return []

    groups: list[list[ClickEvent]] = [[events[0]]]
    for event in events[1:]:
        current = groups[-1]
        previous = current[-1]
        same_spot = (event.x - previous.x) ** 2 + (event.y - previous.y) ** 2 <= merge_radius_px**2
        quick = (event.at - previous.at) * 1000.0 <= double_click_ms
        room_left = len(current) < len(_CLICK_TYPES)
        if same_spot and quick and room_left and event.button is previous.button:
            current.append(event)
        else:
            groups.append([event])

    points: list[SequencePoint] = []
    for index, group in enumerate(groups):
        first = group[0]
        delay_ms = 0.0
        if keep_timing and index + 1 < len(groups):
            # Measured from the end of this gesture to the start of the next,
            # so the pause is the pause, not the pause plus the double-click.
            delay_ms = max((groups[index + 1][0].at - group[-1].at) * 1000.0, 0.0)
        points.append(
            SequencePoint(
                x=first.x,
                y=first.y,
                button=first.button,
                click_type=_CLICK_TYPES[len(group) - 1],
                delay_after_ms=delay_ms,
            )
        )
    return points


class ClickRecorder:
    """Listens for real mouse clicks until told to stop."""

    def __init__(
        self,
        on_event: Callable[[int], None] | None = None,
        ignore: Callable[[int, int], bool] | None = None,
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_event = on_event
        self._ignore = ignore
        self._grace_seconds = grace_seconds
        self._clock = clock
        self._listener = None
        self._started_at = 0.0
        self.events: list[ClickEvent] = []

    @property
    def is_recording(self) -> bool:
        return self._listener is not None

    def start(self) -> bool:
        if self.is_recording:
            return True
        self.events = []
        self._started_at = self._clock()
        try:
            from pynput import mouse

            listener = mouse.Listener(on_click=self._on_click)
            listener.daemon = True
            listener.start()
        except Exception:  # pragma: no cover - platform dependent
            logger.warning("Could not start the click recorder", exc_info=True)
            return False
        self._listener = listener
        return True

    def stop(self) -> list[ClickEvent]:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # pragma: no cover - platform dependent
                logger.exception("Could not stop the click recorder")
        return list(self.events)

    def _on_click(self, x: float, y: float, button: object, pressed: bool) -> None:
        if not pressed:
            return
        now = self._clock()
        if now - self._started_at < self._grace_seconds:
            return
        mapped = _map_button(button)
        if mapped is None:
            return
        point = (round(x), round(y))
        if self._ignore is not None and self._ignore(*point):
            return
        self.events.append(ClickEvent(point[0], point[1], mapped, now))
        if self._on_event is not None:
            self._on_event(len(self.events))


def _map_button(button: object) -> MouseButton | None:
    name = getattr(button, "name", None)
    if name in ("left", "right", "middle"):
        return MouseButton(name)
    return None
