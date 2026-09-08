"""Where the clicks land: follow the cursor, or lock a point."""

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

#: Wide enough for any plausible multi-monitor desktop, and negative because
#: a display placed left of or above the primary lives at negative coordinates.
COORD_LIMIT = 100_000


class TargetWidget(QGroupBox):
    changed = Signal()
    pickRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Target", parent)

        self.follow_cursor = QRadioButton("Follow the cursor")
        self.follow_cursor.setChecked(True)
        self.fixed_point = QRadioButton("Fixed point")
        group = QButtonGroup(self)
        group.addButton(self.follow_cursor)
        group.addButton(self.fixed_point)
        self.follow_cursor.toggled.connect(self._on_mode_toggle)

        self.x = self._coord(" X")
        self.y = self._coord(" Y")
        self.pick_button = QPushButton("Pick a point…")
        self.pick_button.clicked.connect(self.pickRequested)

        point_row = QHBoxLayout()
        point_row.addWidget(self.x)
        point_row.addWidget(self.y)
        point_row.addWidget(self.pick_button)
        point_row.addStretch(1)

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
        layout.addWidget(self.capture_hint)
        layout.addLayout(jitter_row)

        self._on_mode_toggle()

    def _coord(self, prefix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(-COORD_LIMIT, COORD_LIMIT)
        spin.setPrefix(prefix + "  ")
        spin.valueChanged.connect(self.changed)
        return spin

    def set_capture_hint(self, hotkey_label: str) -> None:
        self.capture_hint.setText(
            f"Or press {hotkey_label} to capture wherever the pointer is right now."
        )

    def set_point(self, x: int, y: int) -> None:
        """Lock a picked point and switch to fixed-point mode."""
        self.x.blockSignals(True)
        self.y.blockSignals(True)
        self.x.setValue(x)
        self.y.setValue(y)
        self.x.blockSignals(False)
        self.y.blockSignals(False)
        self.fixed_point.setChecked(True)
        self.changed.emit()

    def value(self) -> TargetConfig:
        return TargetConfig(
            mode=(
                TargetMode.FIXED_POINT
                if self.fixed_point.isChecked()
                else TargetMode.FOLLOW_CURSOR
            ),
            x=self.x.value(),
            y=self.y.value(),
            position_jitter_px=self.position_jitter.value(),
        )

    def set_value(self, config: TargetConfig) -> None:
        for widget in (self.follow_cursor, self.x, self.y, self.position_jitter):
            widget.blockSignals(True)
        self.fixed_point.setChecked(config.mode is TargetMode.FIXED_POINT)
        self.follow_cursor.setChecked(config.mode is not TargetMode.FIXED_POINT)
        self.x.setValue(config.x)
        self.y.setValue(config.y)
        self.position_jitter.setValue(config.position_jitter_px)
        for widget in (self.follow_cursor, self.x, self.y, self.position_jitter):
            widget.blockSignals(False)
        self._on_mode_toggle()

    def _on_mode_toggle(self) -> None:
        fixed = self.fixed_point.isChecked()
        for widget in (self.x, self.y, self.pick_button):
            widget.setEnabled(fixed)
        self.changed.emit()
