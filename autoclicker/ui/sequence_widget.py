"""The click-sequence table, and the controls for recording one.

A list of :class:`SequencePoint` is the model; the table is only a rendering of
it. Structural edits rebuild the table wholesale, which is cheap at these sizes
and avoids the usual QTableWidget trap where moving a row leaves its embedded
combo boxes behind.

Delays are stored in milliseconds and *displayed* in whichever unit is chosen.
A unit typed into a cell always wins over the column's unit, so "250 ms" in a
seconds column means 250 ms.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.config import ClickType, MouseButton, SequencePoint
from ..core.units import MILLISECONDS, SECONDS, format_duration, parse_duration

_COLUMNS = ("X", "Y", "Button", "Click", "Then wait")
_DELAY_COLUMN = 4
_BUTTONS = (("Left", MouseButton.LEFT), ("Right", MouseButton.RIGHT),
            ("Middle", MouseButton.MIDDLE))
_TYPES = (("Single", ClickType.SINGLE), ("Double", ClickType.DOUBLE),
          ("Triple", ClickType.TRIPLE))


class SequenceEditor(QWidget):
    changed = Signal()
    addPointRequested = Signal()
    recordToggleRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list[SequencePoint] = []
        self._rendering = False
        self._recording = False
        self._record_hotkey = ""

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(140)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        header = self.table.horizontalHeader()
        for column in range(len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)

        self.record_button = QPushButton()
        self.record_button.clicked.connect(self.recordToggleRequested)
        self.add_button = QPushButton("Add point…")
        self.add_button.clicked.connect(self.addPointRequested)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button = QPushButton("↑")
        self.up_button.setFixedWidth(34)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QPushButton("↓")
        self.down_button.setFixedWidth(34)
        self.down_button.clicked.connect(lambda: self._move(1))

        buttons = QHBoxLayout()
        buttons.addWidget(self.record_button)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.up_button)
        buttons.addWidget(self.down_button)
        buttons.addStretch(1)

        self.unit = QComboBox()
        self.unit.addItem("seconds", SECONDS)
        self.unit.addItem("milliseconds", MILLISECONDS)
        self.unit.currentIndexChanged.connect(self._on_unit_changed)

        self.keep_timing_box = QCheckBox("Keep recorded timing")
        self.keep_timing_box.setChecked(True)
        self.keep_timing_box.setToolTip(
            "Replay a recording at the speed you performed it. Uncheck to use the "
            "interval above for every step instead."
        )

        options = QHBoxLayout()
        options.addWidget(QLabel("Show waits in"))
        options.addWidget(self.unit)
        options.addSpacing(12)
        options.addWidget(self.keep_timing_box)
        options.addStretch(1)

        self.hint = QLabel()
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addLayout(options)
        layout.addWidget(self.hint)

        self._refresh_chrome()

    # -------------------------------------------------------------- model

    def points(self) -> list[SequencePoint]:
        return [
            SequencePoint(
                x=point.x, y=point.y, button=point.button,
                click_type=point.click_type, delay_after_ms=point.delay_after_ms,
            )
            for point in self._points
        ]

    def set_points(self, points: list[SequencePoint]) -> None:
        self._points = list(points)
        self._render()

    def add_point(self, x: int, y: int) -> None:
        self._points.append(SequencePoint(x=x, y=y))
        self._render()
        self.table.selectRow(len(self._points) - 1)
        self.changed.emit()

    def append_points(self, points: list[SequencePoint]) -> None:
        """Add recorded points to whatever is already here.

        Appending rather than replacing: a recording that silently wiped a
        hand-built sequence would be a bad surprise, and Remove is one click.
        """
        if not points:
            return
        self._points.extend(points)
        self._render()
        self.table.selectRow(len(self._points) - 1)
        self.changed.emit()

    def keep_timing(self) -> bool:
        return self.keep_timing_box.isChecked()

    # ---------------------------------------------------------- recording

    def set_recording(self, active: bool, count: int = 0) -> None:
        self._recording = active
        self._count = count
        self._refresh_chrome(count)

    def set_record_hotkey_label(self, label: str) -> None:
        self._record_hotkey = label
        self._refresh_chrome()

    def _refresh_chrome(self, count: int = 0) -> None:
        suffix = f"  ({self._record_hotkey})" if self._record_hotkey else ""
        if self._recording:
            plural = "" if count == 1 else "s"
            self.record_button.setText(f"Stop recording — {count} click{plural}{suffix}")
            self.hint.setText(
                "Recording. Every click you make is captured, including which button "
                "and how long you paused. Clicks on this window are ignored."
            )
        else:
            self.record_button.setText(f"Record…{suffix}")
            self.hint.setText(
                "Points are clicked in order, then the list repeats. A wait of 0 uses "
                "the interval above. To loop forever, set Repeat to “Until stopped”."
            )
        for widget in (self.add_button, self.remove_button, self.up_button,
                       self.down_button, self.table):
            widget.setEnabled(not self._recording)

    # ------------------------------------------------------------ editing

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._points):
            del self._points[row]
            self._render()
            self.changed.emit()

    def _move(self, offset: int) -> None:
        row = self.table.currentRow()
        target = row + offset
        if not (0 <= row < len(self._points) and 0 <= target < len(self._points)):
            return
        self._points[row], self._points[target] = self._points[target], self._points[row]
        self._render()
        self.table.selectRow(target)
        self.changed.emit()

    def _on_unit_changed(self) -> None:
        self._render()

    def _current_unit(self) -> str:
        return self.unit.currentData() or SECONDS

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering:
            return
        row, column = item.row(), item.column()
        if not 0 <= row < len(self._points):
            return
        point = self._points[row]
        text = item.text().strip()
        if column == 0:
            point.x = _to_int(text, point.x)
        elif column == 1:
            point.y = _to_int(text, point.y)
        elif column == _DELAY_COLUMN:
            parsed = parse_duration(text, self._current_unit())
            if parsed is not None:
                point.delay_after_ms = max(parsed, 0.0)
        self._render()
        self.changed.emit()

    def _on_combo_changed(self, row: int, column: int, value: object) -> None:
        if self._rendering or not 0 <= row < len(self._points):
            return
        if column == 2:
            self._points[row].button = value
        else:
            self._points[row].click_type = value
        self.changed.emit()

    # ---------------------------------------------------------- rendering

    def _render(self) -> None:
        self._rendering = True
        try:
            unit = self._current_unit()
            self.table.setRowCount(len(self._points))
            for row, point in enumerate(self._points):
                self._set_cell(row, 0, str(point.x))
                self._set_cell(row, 1, str(point.y))
                self.table.setCellWidget(row, 2, self._combo(_BUTTONS, point.button, row, 2))
                self.table.setCellWidget(row, 3, self._combo(_TYPES, point.click_type, row, 3))
                self._set_cell(row, _DELAY_COLUMN, format_duration(point.delay_after_ms, unit))
        finally:
            self._rendering = False

    def _set_cell(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, column, item)

    def _combo(self, options, current, row: int, column: int) -> QComboBox:
        combo = QComboBox()
        for label, value in options:
            combo.addItem(label, value)
        index = combo.findData(current)
        combo.setCurrentIndex(max(index, 0))
        combo.currentIndexChanged.connect(
            lambda _index, r=row, c=column, w=combo: self._on_combo_changed(
                r, c, w.currentData()
            )
        )
        return combo


def _to_int(text: str, fallback: int) -> int:
    try:
        return int(float(text.replace(",", ".").split()[0]))
    except (ValueError, IndexError):
        return fallback
