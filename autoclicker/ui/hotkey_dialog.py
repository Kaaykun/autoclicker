"""Remap the global hotkeys.

Recording runs on pynput's listener thread, so every result comes back through
a QObject's signals rather than touching widgets directly.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.config import HotkeyConfig
from ..core.hotkeys import HotkeyRecorder, format_hotkey
from ..core.platform_checks import is_macos
from .theme import COLOR_ERROR

_PROMPT = "Press a combination…"


class _RecorderSignals(QObject):
    captured = Signal(str)
    cancelled = Signal()
    failed = Signal(str)


class HotkeyDialog(QDialog):
    """Three bindings, each recordable, with conflict checking on OK."""

    FIELDS = (
        ("toggle", "Start / stop"),
        ("panic", "Panic stop"),
        ("capture", "Capture pointer position"),
    )

    def __init__(self, config: HotkeyConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hotkeys")
        self.setModal(True)

        self._specs = {name: getattr(config, name) for name, _ in self.FIELDS}
        self._labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._recording: str | None = None

        self._signals = _RecorderSignals()
        self._signals.captured.connect(self._on_captured)
        self._signals.cancelled.connect(self._on_cancelled)
        self._signals.failed.connect(self._on_failed)
        self._recorder = HotkeyRecorder(
            on_captured=self._signals.captured.emit,
            on_cancelled=self._signals.cancelled.emit,
            on_error=self._signals.failed.emit,
        )

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
        if self._recording is not None:
            return
        self._recording = name
        self._labels[name].setText(_PROMPT)
        for button in self._buttons.values():
            button.setEnabled(False)
        self._recorder.start()

    def _finish_recording(self) -> None:
        name, self._recording = self._recording, None
        for button in self._buttons.values():
            button.setEnabled(True)
        if name is not None:
            self._labels[name].setText(format_hotkey(self._specs[name]))

    def _on_captured(self, spec: str) -> None:
        if self._recording is not None:
            self._specs[self._recording] = spec
        self._finish_recording()
        self._validate()

    def _on_cancelled(self) -> None:
        self._finish_recording()

    def _on_failed(self, message: str) -> None:
        self._finish_recording()
        self._show_error(message)

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

    def reject(self) -> None:
        self._recorder.stop()
        super().reject()

    def accept(self) -> None:
        self._recorder.stop()
        super().accept()

    @staticmethod
    def _platform_note() -> str:
        if is_macos():
            return (
                "Escape cancels a recording. Function keys may need Fn held unless "
                "“Use F1, F2, etc. as standard function keys” is switched on in "
                "System Settings > Keyboard."
            )
        return "Escape cancels a recording."
