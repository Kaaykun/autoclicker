"""Application and tray icons.

Artwork is loaded from ``autoclicker/resources/`` when it is there, and drawn
in code when it is not, so the app never ships looking broken and dropping in
a real ``icon.png`` needs no code change.

The tray glyph distinguishes running from idle by *shape*, not colour. macOS
renders menu-bar icons as template images -- it throws the colour away and
recolours the alpha channel to match the menu bar -- so a green-vs-grey dot
would look identical in both states up there.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resources"

#: Candidate filenames for user-supplied artwork, best first.
#: Windows leads with the squared variant: it does not mask icons and has no
#: corner convention, so baked-in rounded corners read as transparent notches
#: against a taskbar highlight or an Explorer selection tint. macOS wants the
#: rounded artwork, because it does not mask either and the curve is expected
#: to be in the file.
APP_ICON_NAMES_WINDOWS = ("icon-square.png", "icon.png", "icon.ico")
APP_ICON_NAMES = ("icon.png", "icon.svg", "icon.icns")
TRAY_ICON_NAMES = ("tray.png", "tray.svg")

_ACCENT = QColor(46, 120, 220)
_GLYPH = QColor(20, 20, 24)


def _first_existing(names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = RESOURCE_DIR / name
        if candidate.is_file():
            return candidate
    return None


def app_icon() -> QIcon:
    """The window, dock and taskbar icon."""
    names = APP_ICON_NAMES_WINDOWS if sys.platform.startswith("win") else APP_ICON_NAMES
    supplied = _first_existing(names)
    if supplied is not None:
        return QIcon(str(supplied))
    return QIcon(_draw_app_placeholder(256))


def tray_icon(running: bool) -> QIcon:
    """The menu-bar / system-tray icon for the given state."""
    supplied = _first_existing(TRAY_ICON_NAMES)
    if supplied is not None:
        icon = QIcon(str(supplied))
    else:
        icon = QIcon(_draw_tray_glyph(44, filled=running))
    if sys.platform == "darwin":
        # Let macOS recolour it for light and dark menu bars.
        icon.setIsMask(True)
    return icon


def has_custom_artwork() -> bool:
    return _first_existing(APP_ICON_NAMES + APP_ICON_NAMES_WINDOWS) is not None


def _draw_app_placeholder(size: int) -> QPixmap:
    """A rounded tile with a pointer dot and a pulse ring."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_ACCENT)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    centre = size / 2
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(QRectF(centre - size * 0.09, centre - size * 0.09,
                               size * 0.18, size * 0.18))

    pen = QPen(QColor(255, 255, 255, 170))
    pen.setWidthF(size * 0.045)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for factor in (0.30, 0.42):
        painter.drawEllipse(QRectF(centre - size * factor, centre - size * factor,
                                   size * factor * 2, size * factor * 2))
    painter.end()
    return pixmap


def _draw_tray_glyph(size: int, *, filled: bool) -> QPixmap:
    """A ring, solid while running and hollow while idle."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = size / 2
    radius = size * 0.28

    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_GLYPH)
    else:
        pen = QPen(_GLYPH)
        pen.setWidthF(size * 0.10)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(centre - radius, centre - radius, radius * 2, radius * 2))
    painter.end()
    return pixmap
