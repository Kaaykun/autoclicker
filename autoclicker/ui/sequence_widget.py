"""The click-sequence table.

A list of :class:`SequencePoint` is the model; the table is only a rendering of
it. Structural edits rebuild the table wholesale, which is cheap at these sizes
and avoids the usual QTableWidget trap where moving a row leaves its embedded
combo boxes behind.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.config import ClickType, MouseButton, SequencePoint

_COLUMNS = ("X", "Y", "Button", "Click", "Then wait")
_BUTTONS = (("Left", MouseButton.LEFT), ("Right", MouseButton.RIGHT),
            ("Middle", MouseButton.MIDDLE))
_TYPES = (("Single", ClickType.SINGLE), ("Double", ClickType.DOUBLE),
          ("Triple", ClickType.TRIPLE))


class SequenceEditor(QWidget):
    changed = Signal()
    addPointRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list[SequencePoint] = []
        self._rendering = False

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(120)
        header = self.table.horizontalHeader()
        for column in range(len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)

        self.add_button = QPushButton("Add point…")
        self.add_button.clicked.connect(self.addPointRequested)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button = QPushButton("↑")
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QPushButton("↓")
        self.down_button.clicked.connect(lambda: self._move(1))

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.up_button)
        buttons.addWidget(self.down_button)
        buttons.addStretch(1)

        self.hint = QLabel(
            "Points are clicked in order, then the list repeats. "
            "“Then wait” of 0 uses the interval above."
        )
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(self.hint)

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
        elif column == 4:
            point.delay_after_ms = max(_to_float(text, point.delay_after_ms), 0.0)
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
            self.table.setRowCount(len(self._points))
            for row, point in enumerate(self._points):
                self._set_cell(row, 0, str(point.x))
                self._set_cell(row, 1, str(point.y))
                self.table.setCellWidget(
                    row, 2, self._combo(_BUTTONS, point.button, row, 2)
                )
                self.table.setCellWidget(
                    row, 3, self._combo(_TYPES, point.click_type, row, 3)
                )
                self._set_cell(row, 4, f"{point.delay_after_ms:g} ms")
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


def _to_float(text: str, fallback: float) -> float:
    try:
        return float(text.replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return fallback
