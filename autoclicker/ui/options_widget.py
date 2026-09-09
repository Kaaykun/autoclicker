"""What the engine repeats: clicks or keystrokes, and how many times."""

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
    QWidget,
)

from ..core.config import (
    ActionType,
    ClickConfig,
    ClickType,
    MouseButton,
    RepeatConfig,
    coerce_enum,
)


class OptionsWidget(QGroupBox):
    """Collects the action type, a :class:`ClickConfig` and a :class:`RepeatConfig`."""

    changed = Signal()
    #: Emitted when the action type changes, so the window can swap panels.
    actionChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Action", parent)

        self.action = QComboBox()
        self.action.addItem("Click the mouse", ActionType.CLICK)
        self.action.addItem("Press a key", ActionType.KEY)
        self.action.currentIndexChanged.connect(self._on_action_changed)

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

        self.gap_ms = QSpinBox()
        self.gap_ms.setRange(0, 5_000)
        self.gap_ms.setSuffix(" ms")
        self.gap_ms.setSpecialValueText("Native")
        self.gap_ms.setToolTip(
            "Spacing between the presses of a double or triple click.\n"
            "“Native” lets the OS mark them as one gesture, which is what makes a "
            "double-click open a folder. Set a gap only if a target app wants the "
            "presses spaced out."
        )
        self.gap_ms.valueChanged.connect(self.changed)

        # Click-only controls live in their own container so the whole group can
        # be hidden in key mode without unpicking a form layout row by row.
        self.click_options = QWidget()
        form = QFormLayout(self.click_options)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Mouse button", self.button)
        form.addRow("Click type", self.click_type)
        form.addRow("Hold for", self.hold_ms)
        form.addRow("Multi-click gap", self.gap_ms)

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

        action_row = QFormLayout()
        action_row.addRow("What to repeat", self.action)

        layout = QVBoxLayout(self)
        layout.addLayout(action_row)
        layout.addWidget(self.click_options)
        layout.addLayout(repeat_row)

    # -------------------------------------------------------------- value

    def action_value(self) -> ActionType:
        """Qt hands back a plain str for a str Enum, so coerce before comparing.

        ``currentData() is ActionType.KEY`` is False even when it is the key
        entry, which silently left the wrong panel on screen.
        """
        return coerce_enum(ActionType, self.action.currentData(), ActionType.CLICK)

    def click_value(self) -> ClickConfig:
        return ClickConfig(
            button=coerce_enum(MouseButton, self.button.currentData(), MouseButton.LEFT),
            click_type=coerce_enum(
                ClickType, self.click_type.currentData(), ClickType.SINGLE
            ),
            inter_click_gap_ms=float(self.gap_ms.value()),
            hold_ms=float(self.hold_ms.value()),
        )

    def repeat_value(self) -> RepeatConfig:
        return RepeatConfig(
            until_stopped=self.until_stopped.isChecked(),
            count=self.count.value(),
        )

    def set_value(self, action: ActionType, click: ClickConfig, repeat: RepeatConfig) -> None:
        widgets = (self.action, self.button, self.click_type, self.hold_ms,
                   self.gap_ms, self.until_stopped, self.count)
        for widget in widgets:
            widget.blockSignals(True)
        self.action.setCurrentIndex(max(self.action.findData(action), 0))
        self.button.setCurrentIndex(max(self.button.findData(click.button), 0))
        self.click_type.setCurrentIndex(max(self.click_type.findData(click.click_type), 0))
        self.hold_ms.setValue(int(click.hold_ms))
        self.gap_ms.setValue(int(click.inter_click_gap_ms))
        self.until_stopped.setChecked(repeat.until_stopped)
        self.fixed_count.setChecked(not repeat.until_stopped)
        self.count.setValue(repeat.count)
        self.count.setEnabled(not repeat.until_stopped)
        for widget in widgets:
            widget.blockSignals(False)
        self._sync_action()

    # ------------------------------------------------------------ internals

    def _on_action_changed(self) -> None:
        self._sync_action()
        self.actionChanged.emit(self.action_value().value)
        self.changed.emit()

    def _sync_action(self) -> None:
        self.click_options.setVisible(self.action_value() is ActionType.CLICK)

    def _on_repeat_toggle(self) -> None:
        self.count.setEnabled(not self.until_stopped.isChecked())
        self.changed.emit()
