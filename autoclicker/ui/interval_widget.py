"""The interval controls: hours, minutes, seconds, milliseconds, and jitter."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import (
    FAST_INTERVAL_WARNING_MS,
    IntervalConfig,
    JitterMode,
    coerce_enum,
)
from .theme import COLOR_COUNTDOWN


class IntervalWidget(QGroupBox):
    """Collects an :class:`IntervalConfig` and describes it back in English."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Interval", parent)

        self.hours = self._spin(999, " h")
        self.minutes = self._spin(59, " m")
        self.seconds = self._spin(59, " s")
        self.millis = self._spin(999, " ms")

        fields = QHBoxLayout()
        for spin in (self.hours, self.minutes, self.seconds, self.millis):
            fields.addWidget(spin)
        fields.addStretch(1)

        self.jitter_mode = QComboBox()
        self.jitter_mode.addItem("No jitter", JitterMode.OFF)
        self.jitter_mode.addItem("Jitter by percent", JitterMode.PERCENT)
        self.jitter_mode.addItem("Jitter by milliseconds", JitterMode.MILLIS)
        self.jitter_mode.currentIndexChanged.connect(self._on_change)

        self.jitter_amount = QDoubleSpinBox()
        self.jitter_amount.setRange(0.0, 100_000.0)
        self.jitter_amount.setDecimals(1)
        self.jitter_amount.setEnabled(False)
        self.jitter_amount.valueChanged.connect(self._on_change)

        jitter = QHBoxLayout()
        jitter.addWidget(self.jitter_mode)
        jitter.addWidget(self.jitter_amount)
        jitter.addStretch(1)

        self.summary = QLabel()
        self.summary.setObjectName("hintLabel")

        self.warning = QLabel()
        self.warning.setObjectName("warningLabel")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {COLOR_COUNTDOWN.name()};")
        self.warning.hide()

        layout = QVBoxLayout(self)
        layout.addLayout(fields)
        layout.addLayout(jitter)
        layout.addWidget(self.summary)
        layout.addWidget(self.warning)

        # Defaults go in last, through set_value, which blocks signals while it
        # writes. Setting a spinbox inline above would fire valueChanged before
        # the jitter widgets exist, and _refresh would blow up reaching for them.
        self.set_value(IntervalConfig())

    def _spin(self, maximum: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, maximum)
        spin.setSuffix(suffix)
        spin.valueChanged.connect(self._on_change)
        return spin

    def value(self) -> IntervalConfig:
        return IntervalConfig(
            hours=self.hours.value(),
            minutes=self.minutes.value(),
            seconds=self.seconds.value(),
            millis=self.millis.value(),
            jitter_mode=self._jitter_mode(),
            jitter_amount=self.jitter_amount.value(),
        )

    def set_value(self, config: IntervalConfig) -> None:
        widgets = (self.hours, self.minutes, self.seconds, self.millis,
                   self.jitter_mode, self.jitter_amount)
        for widget in widgets:
            widget.blockSignals(True)
        self.hours.setValue(config.hours)
        self.minutes.setValue(config.minutes)
        self.seconds.setValue(config.seconds)
        self.millis.setValue(config.millis)
        index = self.jitter_mode.findData(config.jitter_mode)
        self.jitter_mode.setCurrentIndex(max(index, 0))
        self.jitter_amount.setValue(config.jitter_amount)
        for widget in widgets:
            widget.blockSignals(False)
        self._refresh()

    def _on_change(self) -> None:
        self._refresh()
        self.changed.emit()

    def _jitter_mode(self) -> JitterMode:
        """Read the combo as a real enum member.

        Qt round-trips a combo's data through QVariant, and a str Enum comes
        back as a plain str. It compares equal to the member but is never
        identical to it, so ``is`` comparisons silently fail -- which is how
        percent jitter ended up labelled in milliseconds.
        """
        return coerce_enum(JitterMode, self.jitter_mode.currentData(), JitterMode.OFF)

    def _refresh(self) -> None:
        mode = self._jitter_mode()
        self.jitter_amount.setEnabled(mode is not JitterMode.OFF)
        if mode is JitterMode.PERCENT:
            self.jitter_amount.setSuffix(" %")
            self.jitter_amount.setMaximum(100.0)
        else:
            self.jitter_amount.setSuffix(" ms")
            self.jitter_amount.setMaximum(100_000.0)

        config = self.value()
        self.summary.setText(describe_rate(config.total_ms))
        too_fast = 0 < config.total_ms < FAST_INTERVAL_WARNING_MS
        self.warning.setVisible(too_fast)
        if too_fast:
            self.warning.setText(
                f"Below {FAST_INTERVAL_WARNING_MS:g} ms the operating system sets the real "
                "rate, not this app. The counter shows what actually happened."
            )


def describe_rate(total_ms: float) -> str:
    """Turn an interval into the sentence a person would say out loud."""
    if total_ms <= 0:
        return "Set an interval of at least 1 ms."
    if total_ms < 1000:
        return f"About {1000 / total_ms:.1f} clicks per second."

    seconds = total_ms / 1000
    if seconds < 60:
        return _every(seconds, "second")
    minutes = seconds / 60
    if minutes < 60:
        return _every(minutes, "minute")
    return _every(minutes / 60, "hour")


def _every(amount: float, unit: str) -> str:
    """"One click per second", not "One click every 1 seconds"."""
    if amount == 1:
        return f"One click per {unit}."
    return f"One click every {amount:g} {unit}s."
