"""Remap the global hotkeys.

Capture happens in Qt rather than through pynput -- see :mod:`key_capture` for
why that matters on macOS. It also makes the interaction synchronous, so there
is no listener thread to marshal results back from.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.config import HotkeyConfig
from ..core.hotkeys import format_hotkey
from ..core.platform_checks import is_macos
from .key_capture import KeyCaptureDialog
from .theme import COLOR_ERROR

_PROMPT = "Press a combination…"


class HotkeyDialog(QDialog):
    """Three bindings, each recordable, with conflict checking on OK."""

    FIELDS = (
        ("toggle", "Start / stop"),
        ("panic", "Panic stop"),
        ("capture", "Capture pointer position"),
        ("record", "Record a click sequence"),
    )

    def __init__(self, config: HotkeyConfig, capture=None, parent=None) -> None:
        """``capture`` is injectable so tests need no key press."""
        super().__init__(parent)
        self.setWindowTitle("Hotkeys")
        self.setModal(True)

        self._specs = {name: getattr(config, name) for name, _ in self.FIELDS}
        self._labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._capture = capture or KeyCaptureDialog.capture

        grid = QGridLayout()
        for row, (name, title) in enumerate(self.FIELDS):
            label = QLabel(format_hotkey(self._specs[name]))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            button = QPushButton("Change")
            button.clicked.connect(lambda _checked=False, key=name: self._record(key))
            grid.addWidget(QLabel(title), row, 0)
            grid.addWidget(label, row, 1)
            grid.addWidget(button, row, 2)
            self._labels[name] = label
            self._buttons[name] = button

        self._message = QLabel()
        self._message.setObjectName("hintLabel")
        self._message.setWordWrap(True)
        self._message.setText(self._platform_note())

        self._error = QLabel()
        self._error.setObjectName("warningLabel")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(f"color: {COLOR_ERROR.name()};")
        self._error.hide()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self._message)
        layout.addWidget(self._error)
        layout.addWidget(buttons)

    def value(self) -> HotkeyConfig:
        return HotkeyConfig(**self._specs)

    # ------------------------------------------------------------ recording

    def _record(self, name: str) -> None:
        """Ask for a key. Synchronous, because Qt owns the whole interaction."""
        spec = self._capture(self, f"Press the key for “{dict(self.FIELDS)[name]}”")
        if spec:
            self._specs[name] = spec
            self._labels[name].setText(format_hotkey(spec))
            self._validate()

    # ----------------------------------------------------------- validation

    def _validate(self) -> bool:
        problems = self.value().validate()
        if problems:
            self._show_error(problems[0])
            return False
        self._error.hide()
        return True

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.show()

    def _try_accept(self) -> None:
        if self._validate():
            self.accept()

    @staticmethod
    def _platform_note() -> str:
        if is_macos():
            return (
                "Escape cancels. Function keys may need Fn held unless “Use F1, F2, "
                "etc. as standard function keys” is switched on in System Settings > "
                "Keyboard."
            )
        return "Escape cancels."
