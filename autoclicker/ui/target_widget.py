"""Where the clicks land: follow the cursor, lock a point, or walk a sequence."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import TargetConfig, TargetMode
from .sequence_widget import SequenceEditor

#: Wide enough for any plausible multi-monitor desktop, and negative because a
#: display placed left of or above the primary lives at negative coordinates.
COORD_LIMIT = 100_000


class TargetWidget(QGroupBox):
    changed = Signal()
    pickRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Target", parent)

        self.follow_cursor = QRadioButton("Follow the cursor")
        self.follow_cursor.setChecked(True)
        self.fixed_point = QRadioButton("Fixed point")
        self.sequence = QRadioButton("Sequence of points")

        self._group = QButtonGroup(self)
        for button in (self.follow_cursor, self.fixed_point, self.sequence):
            self._group.addButton(button)
        self._group.buttonToggled.connect(self._on_mode_toggle)

        self.x = self._coord("X")
        self.y = self._coord("Y")
        self.pick_button = QPushButton("Pick a point…")
        self.pick_button.clicked.connect(self.pickRequested)

        point_row = QHBoxLayout()
        point_row.addWidget(self.x)
        point_row.addWidget(self.y)
        point_row.addWidget(self.pick_button)
        point_row.addStretch(1)

        self.editor = SequenceEditor()
        self.editor.addPointRequested.connect(self.pickRequested)
        self.editor.changed.connect(self.changed)
        self.editor.hide()

        self.capture_hint = QLabel()
        self.capture_hint.setObjectName("hintLabel")
        self.capture_hint.setWordWrap(True)

        self.position_jitter = QSpinBox()
        self.position_jitter.setRange(0, 500)
        self.position_jitter.setSuffix(" px")
        self.position_jitter.setToolTip(
            "Scatter each click randomly within this many pixels of the target."
        )
        self.position_jitter.valueChanged.connect(self.changed)

        jitter_row = QHBoxLayout()
        jitter_row.addWidget(QLabel("Position jitter"))
        jitter_row.addWidget(self.position_jitter)
        jitter_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.follow_cursor)
        layout.addWidget(self.fixed_point)
        layout.addLayout(point_row)
        layout.addWidget(self.sequence)
        layout.addWidget(self.editor)
        layout.addWidget(self.capture_hint)
        layout.addLayout(jitter_row)

        self._sync_enabled()

    def _coord(self, axis: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(-COORD_LIMIT, COORD_LIMIT)
        spin.setPrefix(f"{axis}  ")
        spin.valueChanged.connect(self.changed)
        return spin

    # -------------------------------------------------------------- points

    def receive_point(self, x: int, y: int) -> None:
        """Take a picked or captured point and put it wherever it belongs."""
        if self.sequence.isChecked():
            self.editor.add_point(x, y)
        else:
            self.set_point(x, y)

    def set_point(self, x: int, y: int) -> None:
        """Lock a point and switch to fixed-point mode."""
        self.x.blockSignals(True)
        self.y.blockSignals(True)
        self.x.setValue(x)
        self.y.setValue(y)
        self.x.blockSignals(False)
        self.y.blockSignals(False)
        self.fixed_point.setChecked(True)
        self.changed.emit()

    def set_capture_hint(self, hotkey_label: str) -> None:
        self.capture_hint.setText(
            f"Or press {hotkey_label} to capture wherever the pointer is right now."
        )

    # --------------------------------------------------------------- value

    def value(self) -> TargetConfig:
        return TargetConfig(
            mode=self._mode(),
            x=self.x.value(),
            y=self.y.value(),
            position_jitter_px=self.position_jitter.value(),
            sequence=self.editor.points(),
        )

    def set_value(self, config: TargetConfig) -> None:
        widgets = (self.follow_cursor, self.fixed_point, self.sequence,
                   self.x, self.y, self.position_jitter)
        for widget in widgets:
            widget.blockSignals(True)
        self.follow_cursor.setChecked(config.mode is TargetMode.FOLLOW_CURSOR)
        self.fixed_point.setChecked(config.mode is TargetMode.FIXED_POINT)
        self.sequence.setChecked(config.mode is TargetMode.SEQUENCE)
        self.x.setValue(config.x)
        self.y.setValue(config.y)
        self.position_jitter.setValue(config.position_jitter_px)
        for widget in widgets:
            widget.blockSignals(False)
        self.editor.set_points(config.sequence)
        self._sync_enabled()

    def _mode(self) -> TargetMode:
        if self.fixed_point.isChecked():
            return TargetMode.FIXED_POINT
        if self.sequence.isChecked():
            return TargetMode.SEQUENCE
        return TargetMode.FOLLOW_CURSOR

    def _on_mode_toggle(self, _button, checked: bool) -> None:
        # buttonToggled fires twice per change, once for the button being
        # cleared. Only the checked half is a real mode change.
        if not checked:
            return
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self) -> None:
        fixed = self.fixed_point.isChecked()
        for widget in (self.x, self.y, self.pick_button):
            widget.setEnabled(fixed)
        self.editor.setVisible(self.sequence.isChecked())
        self.pick_button.setText("Pick a point…")
