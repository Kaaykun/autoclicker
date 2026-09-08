"""Small visual touches, applied on top of whatever palette the OS gives us.

Deliberately not a dark theme. Qt already follows the system appearance on
both platforms, and overriding that would force dark mode on someone who chose
light. These are palette-neutral: sizes, weights, and three status colours that
stay legible either way.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

#: Status colours, picked to hold contrast against light and dark backgrounds.
COLOR_IDLE = QColor(120, 120, 128)
COLOR_RUNNING = QColor(46, 160, 67)
COLOR_COUNTDOWN = QColor(210, 153, 34)
COLOR_ERROR = QColor(218, 54, 51)

STYLESHEET = """
QGroupBox {
    font-weight: 600;
    margin-top: 12px;
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 12px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}
/* Font properties only. The moment a stylesheet sets padding, a border or a
   background on a QPushButton, Qt stops drawing it natively and falls back to
   the stylesheet box model -- which on macOS means the button loses its
   chrome entirely and reads as plain text. Size comes from setMinimumHeight
   in the widget instead. */
QPushButton#primaryButton {
    font-size: 15px;
    font-weight: 600;
}
QLabel#statusLabel {
    font-size: 13px;
    font-weight: 600;
}
QLabel#hintLabel, QLabel#warningLabel {
    font-size: 11px;
}
QLabel#counterLabel {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(STYLESHEET)
