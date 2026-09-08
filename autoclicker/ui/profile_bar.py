"""The saved-profile picker."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

_UNSAVED = "Unsaved settings"


class ProfileBar(QWidget):
    profileChosen = Signal(str)
    saveRequested = Signal()
    saveAsRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        self.combo.currentIndexChanged.connect(self._on_choice)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.saveRequested)
        self.save_as_button = QPushButton("Save as…")
        self.save_as_button.clicked.connect(self.saveAsRequested)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.deleteRequested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Profile"))
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.save_button)
        layout.addWidget(self.save_as_button)
        layout.addWidget(self.delete_button)

    def set_profiles(self, names: list[str], current: str | None = None) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(_UNSAVED, None)
        for name in names:
            self.combo.addItem(name, name)
        index = self.combo.findData(current) if current else 0
        self.combo.setCurrentIndex(max(index, 0))
        self.combo.blockSignals(False)
        self._refresh_buttons()

    def current_name(self) -> str | None:
        return self.combo.currentData()

    def mark_unsaved(self) -> None:
        """Drop back to the placeholder without emitting a load."""
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self._refresh_buttons()

    def _on_choice(self) -> None:
        self._refresh_buttons()
        name = self.current_name()
        if name:
            self.profileChosen.emit(name)

    def _refresh_buttons(self) -> None:
        named = self.current_name() is not None
        self.save_button.setEnabled(named)
        self.delete_button.setEnabled(named)
