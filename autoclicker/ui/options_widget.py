"""Click options: which button, what kind of click, and how many."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import ClickConfig, ClickType, MouseButton, RepeatConfig


class OptionsWidget(QGroupBox):
    """Collects a :class:`ClickConfig` and a :class:`RepeatConfig`."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Click", parent)

        self.button = QComboBox()
        for label, value in (
            ("Left", MouseButton.LEFT),
            ("Right", MouseButton.RIGHT),
            ("Middle", MouseButton.MIDDLE),
        ):
            self.button.addItem(label, value)
        self.button.currentIndexChanged.connect(self.changed)

        self.click_type = QComboBox()
        for label, value in (
            ("Single", ClickType.SINGLE),
            ("Double", ClickType.DOUBLE),
            ("Triple", ClickType.TRIPLE),
        ):
            self.click_type.addItem(label, value)
        self.click_type.currentIndexChanged.connect(self.changed)

        self.hold_ms = QSpinBox()
        self.hold_ms.setRange(0, 60_000)
        self.hold_ms.setSuffix(" ms")
        self.hold_ms.setToolTip("How long the button stays held down. 0 is an instant click.")
        self.hold_ms.valueChanged.connect(self.changed)

        self.until_stopped = QRadioButton("Until stopped")
        self.until_stopped.setChecked(True)
        self.fixed_count = QRadioButton("Repeat")
        group = QButtonGroup(self)
        group.addButton(self.until_stopped)
        group.addButton(self.fixed_count)
        self.until_stopped.toggled.connect(self._on_repeat_toggle)

        self.count = QSpinBox()
        self.count.setRange(1, 10_000_000)
        self.count.setValue(100)
        self.count.setSuffix(" times")
        self.count.setEnabled(False)
        self.count.valueChanged.connect(self.changed)

        repeat_row = QHBoxLayout()
        repeat_row.addWidget(self.until_stopped)
        repeat_row.addWidget(self.fixed_count)
        repeat_row.addWidget(self.count)
        repeat_row.addStretch(1)

        form = QFormLayout()
        form.addRow("Mouse button", self.button)
        form.addRow("Click type", self.click_type)
        form.addRow("Hold for", self.hold_ms)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(repeat_row)

    def click_value(self) -> ClickConfig:
        return ClickConfig(
            button=self.button.currentData(),
            click_type=self.click_type.currentData(),
            hold_ms=float(self.hold_ms.value()),
        )

    def repeat_value(self) -> RepeatConfig:
        return RepeatConfig(
            until_stopped=self.until_stopped.isChecked(),
            count=self.count.value(),
        )

    def set_value(self, click: ClickConfig, repeat: RepeatConfig) -> None:
        for widget in (self.button, self.click_type, self.hold_ms,
                       self.until_stopped, self.count):
            widget.blockSignals(True)
        self.button.setCurrentIndex(max(self.button.findData(click.button), 0))
        self.click_type.setCurrentIndex(max(self.click_type.findData(click.click_type), 0))
        self.hold_ms.setValue(int(click.hold_ms))
        self.until_stopped.setChecked(repeat.until_stopped)
        self.fixed_count.setChecked(not repeat.until_stopped)
        self.count.setValue(repeat.count)
        self.count.setEnabled(not repeat.until_stopped)
        for widget in (self.button, self.click_type, self.hold_ms,
                       self.until_stopped, self.count):
            widget.blockSignals(False)

    def _on_repeat_toggle(self) -> None:
        self.count.setEnabled(not self.until_stopped.isChecked())
        self.changed.emit()
