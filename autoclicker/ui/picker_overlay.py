"""The full-screen crosshair used to lock an on-screen point.

One design note worth keeping: the coordinates this reports do **not** come
from Qt. They come from the click backend, through ``position_provider``.

Qt reports logical, device-independent pixels; the input layer works in
whatever the platform actually uses -- the same on macOS, but not on a Windows
display running at 150% scaling, where Qt's (100, 100) is the system's
(150, 150). Picking a point in Qt space and clicking it in backend space would
land the clicks somewhere else entirely on a scaled display. Asking the backend
where the pointer is sidesteps the whole conversion: the number we store is by
construction the number that works.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .screens import virtual_geometry

_SHADE = QColor(0, 0, 0, 90)
_CROSSHAIR = QColor(255, 255, 255, 200)
_LABEL_BG = QColor(20, 20, 24, 230)
_LABEL_FG = QColor(255, 255, 255)
_LABEL_PADDING = 8


class PickerOverlay(QWidget):
    """A translucent window over every display. Click to pick, Esc to cancel."""

    picked = Signal(int, int)
    cancelled = Signal()

    def __init__(self, position_provider: Callable[[], tuple[int, int]], parent=None) -> None:
        super().__init__(parent)
        self._position_provider = position_provider
        self._reported = (0, 0)
        self._local_x = 0
        self._local_y = 0

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def start(self) -> None:
        """Cover the desktop and take the keyboard."""
        self.setGeometry(virtual_geometry())
        self._refresh_position()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def finish(self) -> None:
        self.releaseKeyboard()
        self.hide()

    # ------------------------------------------------------------- events

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        self._local_x, self._local_y = position.x(), position.y()
        self._refresh_position()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            self.finish()
            self.cancelled.emit()
            return
        self._refresh_position()
        x, y = self._reported
        self.finish()
        self.picked.emit(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.finish()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), _SHADE)

        pen = QPen(_CROSSHAIR)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(0, self._local_y, self.width(), self._local_y)
        painter.drawLine(self._local_x, 0, self._local_x, self.height())

        self._draw_readout(painter)
        painter.end()

    def _draw_readout(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSize(max(font.pointSize(), 12))
        font.setBold(True)
        painter.setFont(font)

        text = f"X {self._reported[0]}   Y {self._reported[1]}     click to lock  ·  Esc to cancel"
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + _LABEL_PADDING * 2
        height = metrics.height() + _LABEL_PADDING

        # Keep the readout beside the crosshair, but never off the edge.
        x = min(self._local_x + 18, self.width() - width - 4)
        y = min(self._local_y + 18, self.height() - height - 4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_LABEL_BG)
        painter.drawRoundedRect(x, y, width, height, 5, 5)
        painter.setPen(QPen(_LABEL_FG))
        painter.drawText(
            x + _LABEL_PADDING,
            y + height - _LABEL_PADDING // 2 - metrics.descent(),
            text,
        )

    def _refresh_position(self) -> None:
        try:
            self._reported = self._position_provider()
        except Exception:
            # A backend that cannot read the pointer is reported elsewhere;
            # the overlay should not crash on top of it.
            pass
