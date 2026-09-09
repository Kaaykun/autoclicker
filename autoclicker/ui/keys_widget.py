"""The Keys panel: what to press when the action is keystrokes.

Deliberately shaped like the Target panel, because it does the same job for
the other action type: a choice between one thing repeated and a sequence
walked in order, with a table for the sequence.

Keys are captured with the same recorder the hotkey settings use, and stored
in the same notation, so anything bindable as a hotkey is also sendable as a
keystroke -- including chords like Ctrl+V.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.config import KeyConfig, KeyMode, KeyStep
from ..core.hotkeys import HotkeyRecorder, format_hotkey
from ..core.units import MILLISECONDS, SECONDS, format_duration, parse_duration

_COLUMNS = ("Key", "Hold", "Then wait")
_HOLD_COLUMN = 1
_DELAY_COLUMN = 2
_PROMPT = "Press a key…"

#: What a recording will do with the key it captures. None means idle --
#: kept distinct from every real target, because the recorder can fail
#: synchronously (no Input Monitoring) and a late capture must not then be
#: applied to whatever happens to be selected.
_TARGET_SINGLE = -2
_TARGET_APPEND = -1


class _RecorderSignals(QObject):
    captured = Signal(str)
    cancelled = Signal()
    failed = Signal(str)


class KeysWidget(QGroupBox):
    changed = Signal()

    def __init__(self, recorder_factory=None, parent=None) -> None:
        """``recorder_factory`` is injectable so tests never start a real
        listener. Registering one means an OS-level key hook, which needs
        permissions a CI runner has not granted -- and a test suite should not
        depend on the machine's input permissions."""
        super().__init__("Keys", parent)

        self._steps: list[KeyStep] = []
        self._single = KeyStep()
        self._rendering = False
        self._recording_target: int | None = None

        self._signals = _RecorderSignals()
        self._signals.captured.connect(self._on_captured)
        self._signals.cancelled.connect(self._on_cancelled)
        self._signals.failed.connect(self._on_failed)
        factory = recorder_factory or HotkeyRecorder
        self._recorder = factory(
            on_captured=self._signals.captured.emit,
            on_cancelled=self._signals.cancelled.emit,
            on_error=self._signals.failed.emit,
        )

        # -- mode ---------------------------------------------------------
        self.single_key = QRadioButton("One key, repeated")
        self.single_key.setChecked(True)
        self.sequence = QRadioButton("Sequence of keys")
        group = QButtonGroup(self)
        group.addButton(self.single_key)
        group.addButton(self.sequence)
        group.buttonToggled.connect(self._on_mode_toggle)

        # -- single key ---------------------------------------------------
        self.key_label = QLabel(format_hotkey(""))
        self.key_label.setObjectName("counterLabel")
        self.record_single = QPushButton("Choose key…")
        self.record_single.clicked.connect(self.record_single_key)

        self.hold = QSpinBox()
        self.hold.setRange(0, 60_000)
        self.hold.setSuffix(" ms")
        self.hold.setToolTip(
            "How long the key stays held. Hold it long enough and the target "
            "app's own key repeat takes over, which is usually the point."
        )
        self.hold.valueChanged.connect(self._on_hold_changed)

        single_row = QHBoxLayout()
        single_row.addWidget(self.key_label, 1)
        single_row.addWidget(self.record_single)
        single_row.addWidget(QLabel("Hold"))
        single_row.addWidget(self.hold)

        # -- sequence -----------------------------------------------------
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
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.hide()

        self.add_button = QPushButton("Add key…")
        self.add_button.clicked.connect(self.record_new_step)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button = QPushButton("↑")
        self.up_button.setFixedWidth(34)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QPushButton("↓")
        self.down_button.setFixedWidth(34)
        self.down_button.clicked.connect(lambda: self._move(1))

        self.buttons_row = QHBoxLayout()
        for widget in (self.add_button, self.remove_button, self.up_button, self.down_button):
            self.buttons_row.addWidget(widget)
            widget.hide()
        self.buttons_row.addStretch(1)

        self.unit = QComboBox()
        self.unit.addItem("seconds", SECONDS)
        self.unit.addItem("milliseconds", MILLISECONDS)
        self.unit.currentIndexChanged.connect(lambda: self._render())
        self.unit_label = QLabel("Show waits in")

        self.unit_row = QHBoxLayout()
        self.unit_row.addWidget(self.unit_label)
        self.unit_row.addWidget(self.unit)
        self.unit_row.addStretch(1)
        for widget in (self.unit_label, self.unit):
            widget.hide()

        self.hint = QLabel()
        self.hint.setObjectName("hintLabel")
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.single_key)
        layout.addLayout(single_row)
        layout.addWidget(self.sequence)
        layout.addWidget(self.table)
        layout.addLayout(self.buttons_row)
        layout.addLayout(self.unit_row)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._sync_visibility()

    # ------------------------------------------------------------- value

    def value(self) -> KeyConfig:
        return KeyConfig(
            mode=KeyMode.SEQUENCE if self.sequence.isChecked() else KeyMode.SINGLE,
            spec=self._single.spec,
            hold_ms=float(self.hold.value()),
            sequence=[
                KeyStep(spec=s.spec, hold_ms=s.hold_ms, delay_after_ms=s.delay_after_ms)
                for s in self._steps
            ],
        )

    def set_value(self, config: KeyConfig) -> None:
        for widget in (self.single_key, self.sequence, self.hold):
            widget.blockSignals(True)
        self.sequence.setChecked(config.mode is KeyMode.SEQUENCE)
        self.single_key.setChecked(config.mode is not KeyMode.SEQUENCE)
        self._single = KeyStep(spec=config.spec, hold_ms=config.hold_ms)
        self.hold.setValue(int(config.hold_ms))
        for widget in (self.single_key, self.sequence, self.hold):
            widget.blockSignals(False)
        self._steps = list(config.sequence)
        self._render()
        self._sync_visibility()

    # --------------------------------------------------------- recording

    def record_single_key(self) -> None:
        """Capture the one key used in single-key mode."""
        self._record(_TARGET_SINGLE)

    def record_new_step(self) -> None:
        """Capture a key and append it to the sequence."""
        self._record(_TARGET_APPEND)

    def record_step(self, row: int) -> None:
        """Re-capture the key for an existing row."""
        self._record(row)

    def _record(self, target: int) -> None:
        if self._recording_target is not None:
            return
        self._recording_target = target
        if target == _TARGET_SINGLE:
            self.key_label.setText(_PROMPT)
            self.record_single.setEnabled(False)
        else:
            self.add_button.setText(_PROMPT)
            self.add_button.setEnabled(False)
        self._recorder.start()

    def _on_captured(self, spec: str) -> None:
        target = self._recording_target
        self._finish_recording()
        if target is None:
            # The recording already ended -- it failed to start, or was
            # cancelled. Applying this key now would edit the wrong thing.
            return

        if target == _TARGET_SINGLE:
            self._single.spec = spec
        elif target == _TARGET_APPEND:
            self._steps.append(KeyStep(spec=spec))
        elif 0 <= target < len(self._steps):
            self._steps[target].spec = spec
        self._render()
        self.changed.emit()

    def _on_cancelled(self) -> None:
        self._finish_recording()

    def _on_failed(self, message: str) -> None:
        self._finish_recording()
        self.hint.setText(message)

    def _finish_recording(self) -> None:
        self._recording_target = None
        self.record_single.setEnabled(True)
        self.add_button.setEnabled(True)
        self.add_button.setText("Add key…")
        self.key_label.setText(format_hotkey(self._single.spec))
        self._refresh_hint()

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column == 0:
            self.record_step(row)

    # ----------------------------------------------------------- editing

    def _on_hold_changed(self) -> None:
        self._single.hold_ms = float(self.hold.value())
        self.changed.emit()

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._render()
            self.changed.emit()

    def _move(self, offset: int) -> None:
        row = self.table.currentRow()
        target = row + offset
        if not (0 <= row < len(self._steps) and 0 <= target < len(self._steps)):
            return
        self._steps[row], self._steps[target] = self._steps[target], self._steps[row]
        self._render()
        self.table.selectRow(target)
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering:
            return
        row, column = item.row(), item.column()
        if not 0 <= row < len(self._steps):
            return
        step = self._steps[row]
        text = item.text().strip()
        if column == _HOLD_COLUMN:
            parsed = parse_duration(text, MILLISECONDS)
            if parsed is not None:
                step.hold_ms = max(parsed, 0.0)
        elif column == _DELAY_COLUMN:
            parsed = parse_duration(text, self._current_unit())
            if parsed is not None:
                step.delay_after_ms = max(parsed, 0.0)
        self._render()
        self.changed.emit()

    def _current_unit(self) -> str:
        return self.unit.currentData() or SECONDS

    # --------------------------------------------------------- rendering

    def _render(self) -> None:
        self._rendering = True
        try:
            unit = self._current_unit()
            self.table.setRowCount(len(self._steps))
            for row, step in enumerate(self._steps):
                key = QTableWidgetItem(format_hotkey(step.spec))
                key.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Recorded, not typed: double-clicking re-records the row.
                key.setFlags(key.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, key)
                self._set_cell(row, _HOLD_COLUMN, format_duration(step.hold_ms, MILLISECONDS))
                self._set_cell(row, _DELAY_COLUMN, format_duration(step.delay_after_ms, unit))
        finally:
            self._rendering = False
        self.key_label.setText(format_hotkey(self._single.spec))

    def _set_cell(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, column, item)

    def _on_mode_toggle(self, _button, checked: bool) -> None:
        if not checked:
            return
        self._sync_visibility()
        self.changed.emit()

    def _sync_visibility(self) -> None:
        sequence = self.sequence.isChecked()
        self.table.setVisible(sequence)
        for widget in (self.add_button, self.remove_button, self.up_button,
                       self.down_button, self.unit_label, self.unit):
            widget.setVisible(sequence)
        for widget in (self.key_label, self.record_single, self.hold):
            widget.setEnabled(not sequence)
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        if self.sequence.isChecked():
            self.hint.setText(
                "Keys are pressed in order, then the list repeats. Double-click a "
                "key to re-record it. A wait of 0 uses the interval above."
            )
        else:
            self.hint.setText(
                "Keystrokes go to whichever window has focus, so there is nothing "
                "to aim at. Chords work too — Ctrl+V, Cmd+S."
            )
