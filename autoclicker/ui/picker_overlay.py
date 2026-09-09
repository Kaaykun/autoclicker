"""The full-screen crosshair used to lock an on-screen point.

**One overlay window per display, not one window across all of them.** macOS
enables "Displays have separate Spaces" by default, and under it a single
window cannot span two displays -- it gets confined to one. The symptom is
precise and easy to misread: the picker works perfectly on whichever display
the window landed on, and the crosshair freezes at the boundary when the
pointer crosses to any other. A window per screen is what screenshot tools do
for the same reason.

The coordinates reported do **not** come from Qt. They come from the click
backend, through ``position_provider``. Qt reports logical, device-independent
pixels; the input layer works in whatever the platform actually uses -- the
same on macOS, but not on a Windows display running at 150% scaling, where
Qt's (100, 100) is the system's (150, 150). Picking a point in Qt space and
clicking it in backend space would land the clicks somewhere else entirely.
Asking the backend where the pointer is sidesteps the conversion: the number
stored is by construction the number that works.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QScreen
from PySide6.QtWidgets import QWidget

_SHADE = QColor(0, 0, 0, 90)
_CROSSHAIR = QColor(255, 255, 255, 200)
_LABEL_BG = QColor(20, 20, 24, 230)
_LABEL_FG = QColor(255, 255, 255)
_LABEL_PADDING = 8


class PickerOverlay(QWidget):
    """A translucent cover for exactly one display."""

    picked = Signal(int, int)
    cancelled = Signal()
    #: The pointer moved onto this overlay; the manager clears the others.
    pointerMoved = Signal(QWidget)

    def __init__(self, position_provider: Callable[[], tuple[int, int]], parent=None) -> None:
        super().__init__(parent)
        self._position_provider = position_provider
        self._reported = (0, 0)
        self._local_x = 0
        self._local_y = 0
        self._crosshair = False

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

    def cover(self, screen) -> None:
        """Show this overlay filling ``screen``.

        The window has to be told which screen it belongs to *before* it is
        placed, or the platform puts it wherever it likes and the geometry then
        refers to the wrong display.
        """
        self.createWinId()
        handle = self.windowHandle()
        # Bind only when there is a real QScreen to bind to. windowHandle() can
        # be None before the window is realised, and the tests drive this with
        # stand-in screens so that a two-display layout can be exercised on a
        # machine that has one.
        if handle is not None and isinstance(screen, QScreen):
            handle.setScreen(screen)
        self.setGeometry(screen.geometry())
        self._refresh_position()
        self.show()
        self.raise_()

    def finish(self) -> None:
        self.releaseKeyboard()
        self.hide()

    def take_keyboard(self) -> None:
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()

    def release_keyboard(self) -> None:
        self.releaseKeyboard()

    def set_crosshair(self, visible: bool) -> None:
        if self._crosshair != visible:
            self._crosshair = visible
            self.update()

    # ------------------------------------------------------------- events

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        self._local_x, self._local_y = position.x(), position.y()
        self._crosshair = True
        self._refresh_position()
        self.pointerMoved.emit(self)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            self.cancelled.emit()
            return
        self._refresh_position()
        x, y = self._reported
        self.picked.emit(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), _SHADE)

        if self._crosshair:
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


class PointPicker(QObject):
    """Runs one :class:`PickerOverlay` per display and reports the first result."""

    picked = Signal(int, int)
    cancelled = Signal()

    def __init__(
        self,
        position_provider: Callable[[], tuple[int, int]],
        screens: Sequence | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._position_provider = position_provider
        self._screens = screens
        self._overlays: list[PickerOverlay] = []
        self._keyboard_owner: PickerOverlay | None = None

    @property
    def is_active(self) -> bool:
        return bool(self._overlays)

    @property
    def overlays(self) -> list[PickerOverlay]:
        return list(self._overlays)

    def start(self) -> None:
        if self._overlays:
            return
        screens = self._screens if self._screens is not None else QGuiApplication.screens()
        for screen in screens:
            overlay = PickerOverlay(self._position_provider)
            overlay.picked.connect(self._on_picked)
            overlay.cancelled.connect(self._on_cancelled)
            overlay.pointerMoved.connect(self._on_pointer_moved)
            overlay.cover(screen)
            self._overlays.append(overlay)

        if self._overlays:
            self._give_keyboard(self._overlay_under_pointer() or self._overlays[0])

    def finish(self) -> None:
        overlays, self._overlays = self._overlays, []
        self._keyboard_owner = None
        for overlay in overlays:
            overlay.finish()
            overlay.deleteLater()

    # ------------------------------------------------------------ internals

    def _on_picked(self, x: int, y: int) -> None:
        self.finish()
        self.picked.emit(x, y)

    def _on_cancelled(self) -> None:
        self.finish()
        self.cancelled.emit()

    def _on_pointer_moved(self, overlay: PickerOverlay) -> None:
        # Only the display under the pointer draws a crosshair, and only that
        # window needs the keyboard for Escape to work.
        for other in self._overlays:
            if other is not overlay:
                other.set_crosshair(False)
        self._give_keyboard(overlay)

    def _give_keyboard(self, overlay: PickerOverlay) -> None:
        if self._keyboard_owner is overlay:
            return
        if self._keyboard_owner is not None:
            self._keyboard_owner.release_keyboard()
        self._keyboard_owner = overlay
        overlay.take_keyboard()

    def _overlay_under_pointer(self) -> PickerOverlay | None:
        try:
            x, y = self._position_provider()
        except Exception:
            return None
        for overlay in self._overlays:
            if overlay.geometry().contains(x, y):
                return overlay
        return None
