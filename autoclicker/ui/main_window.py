"""The main window: assembles the widgets and owns the engine.

Two threading notes that shape this file:

* Everything the engine, the hotkey listener and the failsafe report arrives
  through :class:`~autoclicker.ui.bridge.EngineBridge`, never directly.
* The per-click callback is deliberately *not* wired to a signal. At a 1 ms
  interval that would post a thousand queued events a second into the GUI
  thread purely to redraw a number. Instead a timer polls the engine's counter
  ten times a second, which also gives us the achieved rate for free -- and the
  achieved rate is the honest one to show, since below about 5 ms the OS, not
  this app, decides how fast the clicks really go out.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.backends import PynputBackend
from ..core.config import HotkeyConfig, Profile, SafetyConfig
from ..core.engine import ClickEngine, EngineState, StopReason
from ..core.failsafe import CornerFailsafe
from ..core.hotkeys import HotkeyManager, format_hotkey
from ..core.platform_checks import (
    Permission,
    PermissionState,
    check_permissions,
    open_privacy_settings,
    permission_guidance,
)
from .bridge import EngineBridge
from .hotkey_dialog import HotkeyDialog
from .interval_widget import IntervalWidget
from .options_widget import OptionsWidget
from .picker_overlay import PickerOverlay
from .screens import screen_rects
from .target_widget import TargetWidget
from .theme import COLOR_COUNTDOWN, COLOR_ERROR, COLOR_IDLE, COLOR_RUNNING

#: How often the counter refreshes while running.
POLL_INTERVAL_MS = 100


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autoclicker")

        self._backend = PynputBackend()
        self._bridge = EngineBridge()
        self._engine = ClickEngine(self._backend, self._bridge.callbacks())
        self._hotkeys = HotkeyConfig()
        self._hotkey_manager = HotkeyManager(on_error=self._bridge.warningRaised.emit)
        self._failsafe: CornerFailsafe | None = None
        self._overlay: PickerOverlay | None = None
        self._run_started_at = 0.0

        self._build_ui()
        self._connect()
        self._apply_hotkeys(self._hotkeys)
        QTimer.singleShot(0, self._check_permissions_at_startup)

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        self.notice = QLabel()
        self.notice.setObjectName("warningLabel")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {COLOR_COUNTDOWN.name()};")
        self.notice.hide()

        self.interval = IntervalWidget()
        self.options = OptionsWidget()
        self.target = TargetWidget()
        self.safety = _SafetyWidget()

        self.status = QLabel("Idle")
        self.status.setObjectName("statusLabel")
        self.counter = QLabel("0 clicks")
        self.counter.setObjectName("counterLabel")

        status_row = QHBoxLayout()
        status_row.addWidget(self.status)
        status_row.addStretch(1)
        status_row.addWidget(self.counter)

        self.start_button = QPushButton()
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._toggle)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.notice)
        layout.addWidget(self.interval)
        layout.addWidget(self.options)
        layout.addWidget(self.target)
        layout.addWidget(self.safety)
        layout.addLayout(status_row)
        layout.addWidget(self.start_button)
        self.setCentralWidget(central)
        self.setMinimumWidth(460)

        self._build_menus()
        self._set_status(EngineState.IDLE)
        self._refresh_labels()

    def _build_menus(self) -> None:
        settings = self.menuBar().addMenu("&Settings")

        hotkeys_action = QAction("Hotkeys…", self)
        hotkeys_action.triggered.connect(self._edit_hotkeys)
        settings.addAction(hotkeys_action)

        self.on_top_action = QAction("Keep window on top", self)
        self.on_top_action.setCheckable(True)
        self.on_top_action.toggled.connect(self._set_always_on_top)
        settings.addAction(self.on_top_action)

        help_menu = self.menuBar().addMenu("&Help")
        permissions_action = QAction("Permissions…", self)
        permissions_action.triggered.connect(self._show_permissions)
        help_menu.addAction(permissions_action)

        about_action = QAction("About Autoclicker", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect(self) -> None:
        self._bridge.stateChanged.connect(self._on_state)
        self._bridge.countdownTick.connect(self._on_countdown)
        self._bridge.finished.connect(self._on_finished)
        self._bridge.errorRaised.connect(self._on_error)
        self._bridge.warningRaised.connect(self._on_warning)
        self._bridge.toggleRequested.connect(self._toggle)
        self._bridge.panicRequested.connect(self._panic)
        self._bridge.captureRequested.connect(self._capture_position)
        self._bridge.failsafeTripped.connect(self._on_failsafe)

        self.target.pickRequested.connect(self._pick_point)

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._refresh_counter)

    # -------------------------------------------------------------- profile

    def _profile(self) -> Profile:
        return Profile(
            name="Current",
            interval=self.interval.value(),
            click=self.options.click_value(),
            repeat=self.options.repeat_value(),
            target=self.target.value(),
            safety=self.safety.value(),
            hotkeys=self._hotkeys,
        )

    # -------------------------------------------------------------- control

    def _toggle(self) -> None:
        if self._engine.is_running:
            self._stop(StopReason.USER)
        else:
            self._start()

    def _start(self) -> None:
        profile = self._profile()
        problems = profile.validate()
        if problems:
            QMessageBox.warning(self, "Cannot start", "\n".join(problems))
            return

        if profile.safety.corner_failsafe:
            self._failsafe = CornerFailsafe(
                screen_rects(),
                profile.safety.corner_margin_px,
                self._bridge.failsafeTripped.emit,
            )
            self._failsafe.start()

        self._engine.start(profile)
        self._poll.start()
        self._refresh_labels()

    def _stop(self, reason: StopReason) -> None:
        self._engine.stop(reason=reason)

    def _panic(self) -> None:
        if self._engine.is_running:
            self._stop(StopReason.PANIC)

    def _on_failsafe(self) -> None:
        if self._engine.is_running:
            self._stop(StopReason.FAILSAFE)

    # --------------------------------------------------------------- events

    def _on_state(self, state_value: str) -> None:
        self._set_status(EngineState(state_value))
        self._refresh_labels()

    def _on_countdown(self, remaining: float) -> None:
        self.status.setText(f"Starting in {remaining:.1f}s…")

    def _on_finished(self, reason_value: str, detail: str) -> None:
        self._poll.stop()
        if self._failsafe is not None:
            self._failsafe.stop()
            self._failsafe = None
        self._refresh_counter()
        self._refresh_labels()

        reason = StopReason(reason_value)
        if reason is StopReason.FAILSAFE:
            self.status.setText("Stopped — screen corner")
        elif reason is StopReason.PANIC:
            self.status.setText("Stopped — panic key")
        elif reason is StopReason.COMPLETED:
            self.status.setText("Finished")
        elif reason is StopReason.ERROR:
            self.status.setText("Error")
        else:
            self.status.setText("Idle")
        self.status.setToolTip(detail)

    def _on_error(self, message: str) -> None:
        """A run failed. This is worth a dialog."""
        self._set_colour(COLOR_ERROR)
        QMessageBox.critical(self, "Autoclicker", message)

    def _on_warning(self, message: str) -> None:
        """Something is degraded but usable -- say so in the window.

        Never a dialog: this fires from ``_apply_hotkeys`` during construction,
        and a modal box there would hang the app before it ever appeared. On
        macOS without Input Monitoring that is exactly what would happen.
        """
        self.notice.setText(message)
        self.notice.show()

    def _refresh_counter(self) -> None:
        clicks = self._engine.clicks_fired
        text = f"{clicks:,} click{'' if clicks == 1 else 's'}"
        self.counter.setText(text)

    def _refresh_labels(self) -> None:
        running = self._engine.is_running
        toggle_label = format_hotkey(self._hotkeys.toggle)
        self.start_button.setText(
            f"Stop  ({toggle_label})" if running else f"Start  ({toggle_label})"
        )
        for widget in (self.interval, self.options, self.target, self.safety):
            widget.setEnabled(not running)
        self.target.set_capture_hint(format_hotkey(self._hotkeys.capture))

    def _set_status(self, state: EngineState) -> None:
        if state is EngineState.RUNNING:
            self.status.setText("Running")
            self._set_colour(COLOR_RUNNING)
        elif state is EngineState.COUNTDOWN:
            self.status.setText("Starting…")
            self._set_colour(COLOR_COUNTDOWN)
        else:
            self.status.setText("Idle")
            self._set_colour(COLOR_IDLE)

    def _set_colour(self, colour) -> None:
        self.status.setStyleSheet(f"color: {colour.name()};")

    # ------------------------------------------------------------ targeting

    def _capture_position(self) -> None:
        try:
            x, y = self._backend.position()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._on_error(str(exc))
            return
        self.target.set_point(x, y)
        self.status.setText(f"Captured X {x}, Y {y}")

    def _pick_point(self) -> None:
        if self._overlay is not None:
            return
        overlay = PickerOverlay(self._backend.position)
        overlay.picked.connect(self._on_point_picked)
        overlay.cancelled.connect(self._on_pick_cancelled)
        self._overlay = overlay
        overlay.start()

    def _on_point_picked(self, x: int, y: int) -> None:
        self._overlay = None
        self.target.set_point(x, y)
        self.raise_()
        self.activateWindow()

    def _on_pick_cancelled(self) -> None:
        self._overlay = None
        self.raise_()
        self.activateWindow()

    # -------------------------------------------------------------- hotkeys

    def _edit_hotkeys(self) -> None:
        # Stop listening first, or pressing F6 to record it would start a run.
        self._hotkey_manager.stop()
        dialog = HotkeyDialog(self._hotkeys, self)
        if dialog.exec():
            self._apply_hotkeys(dialog.value())
        else:
            self._apply_hotkeys(self._hotkeys)

    def _apply_hotkeys(self, config: HotkeyConfig) -> None:
        self._hotkeys = config
        self.notice.hide()
        self._hotkey_manager.bind({
            config.toggle: self._bridge.toggleRequested.emit,
            config.panic: self._bridge.panicRequested.emit,
            config.capture: self._bridge.captureRequested.emit,
        })
        self._hotkey_manager.start()
        self._refresh_labels()
        self.safety.set_panic_label(format_hotkey(config.panic))

    # ---------------------------------------------------------- permissions

    def _check_permissions_at_startup(self) -> None:
        report = check_permissions()
        if report.all_clear:
            return
        self._permission_dialog(report)

    def _show_permissions(self) -> None:
        report = check_permissions()
        if report.all_clear:
            QMessageBox.information(
                self, "Permissions", f"{report.summary()}\n\n{permission_guidance()}"
            )
            return
        self._permission_dialog(report)

    def _permission_dialog(self, report) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Permissions needed")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(report.summary())
        box.setInformativeText(permission_guidance())

        accessibility = None
        input_monitoring = None
        if report.accessibility is not PermissionState.GRANTED:
            accessibility = box.addButton(
                "Open Accessibility", QMessageBox.ButtonRole.ActionRole
            )
        if report.input_monitoring is not PermissionState.GRANTED:
            input_monitoring = box.addButton(
                "Open Input Monitoring", QMessageBox.ButtonRole.ActionRole
            )
        box.addButton("Continue anyway", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is accessibility and accessibility is not None:
            open_privacy_settings(Permission.ACCESSIBILITY)
        elif clicked is input_monitoring and input_monitoring is not None:
            open_privacy_settings(Permission.INPUT_MONITORING)

    def _show_about(self) -> None:
        from .. import __version__

        QMessageBox.about(
            self,
            "Autoclicker",
            f"<b>Autoclicker {__version__}</b><br><br>"
            "A cross-platform auto-clicker.<br><br>"
            f"Panic key: {format_hotkey(self._hotkeys.panic)}<br>"
            "Or slam the pointer into a screen corner.",
        )

    # ----------------------------------------------------------- decoration

    def _set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._engine.stop()
        self._hotkey_manager.stop()
        if self._failsafe is not None:
            self._failsafe.stop()
        if self._overlay is not None:
            self._overlay.finish()
        super().closeEvent(event)


class _SafetyWidget(QGroupBox):
    """Countdown, corner failsafe, and a reminder of the panic key."""

    def __init__(self, parent=None) -> None:
        super().__init__("Safety", parent)

        self.countdown = QSpinBox()
        self.countdown.setRange(0, 60)
        self.countdown.setSuffix(" s")
        self.countdown.setValue(3)
        self.countdown.setToolTip("Time to get the pointer into place before the first click.")

        self.corner_failsafe = QCheckBox("Stop when the pointer hits a screen corner")
        self.corner_failsafe.setChecked(True)

        self.panic_label = QLabel()
        self.panic_label.setObjectName("hintLabel")
        self.panic_label.setWordWrap(True)

        countdown_row = QHBoxLayout()
        countdown_row.addWidget(QLabel("Countdown before starting"))
        countdown_row.addWidget(self.countdown)
        countdown_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(countdown_row)
        layout.addWidget(self.corner_failsafe)
        layout.addWidget(self.panic_label)

    def set_panic_label(self, hotkey_label: str) -> None:
        self.panic_label.setText(
            f"{hotkey_label} always stops the clicker, even while it is running flat out."
        )

    def value(self) -> SafetyConfig:
        return SafetyConfig(
            countdown_seconds=float(self.countdown.value()),
            corner_failsafe=self.corner_failsafe.isChecked(),
        )

    def set_value(self, config: SafetyConfig) -> None:
        self.countdown.setValue(int(config.countdown_seconds))
        self.corner_failsafe.setChecked(config.corner_failsafe)
