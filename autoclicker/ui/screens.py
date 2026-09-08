"""Screen geometry helpers, in Qt's coordinate space.

Used for laying the picker overlay across every display and for working out
where the failsafe corners are. Note the deliberate split: these are *Qt*
coordinates, good for drawing. Anything that will later be handed to the click
backend is read from the backend instead -- see :mod:`picker_overlay` for why.
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


def virtual_geometry() -> QRect:
    """The bounding box of every display, combined."""
    geometry = QRect()
    for screen in QGuiApplication.screens():
        geometry = geometry.united(screen.geometry())
    return geometry


def screen_rects() -> list[tuple[int, int, int, int]]:
    """Each display as ``(left, top, right, bottom)``."""
    rects = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        rects.append((geometry.left(), geometry.top(), geometry.right(), geometry.bottom()))
    return rects
