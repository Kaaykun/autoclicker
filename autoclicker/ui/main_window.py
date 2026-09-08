"""The main window: assembles the widgets and owns the engine.

Three things here are load-bearing:

* Everything the engine, the hotkey listener and the failsafe report arrives
  through :class:`~autoclicker.ui.bridge.EngineBridge`, never directly. Those
  all run on their own threads; widgets may only be touched from this one.
* The per-click callback is deliberately *not* wired to a signal. At a 1 ms
  interval that would post a thousand queued events a second into the GUI
  thread purely to redraw a number. A 10 Hz timer polls the engine's counter
  instead.
* Hotkey trouble is shown inline, never in a modal dialog. It can fire while
  the window is still being constructed, and a modal there deadlocks the app
  before it appears -- which on macOS without Input Monitoring is every launch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
from ..core.profiles import ProfileStore, Settings
from ..core.recorder import ClickRecorder, points_from_events
from .bridge import EngineBridge
from .hotkey_dialog import HotkeyDialog
from .interval_widget import IntervalWidget
from .options_widget import OptionsWidget
from .picker_overlay import PickerOverlay
from .profile_bar import ProfileBar
from .screens import screen_rects
from .target_widget import TargetWidget
from .theme import COLOR_COUNTDOWN, COLOR_ERROR, COLOR_IDLE, COLOR_RUNNING

#: How often the counter refreshes while running.
POLL_INTERVAL_MS = 100


class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore | None = None,
                 settings: Settings | None = None,
                 recorder: ClickRecorder | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autoclicker")

        self._store = store if store is not None else ProfileStore()
        self._settings = settings if settings is not None else Settings()

        self._backend = PynputBackend()
        self._bridge = EngineBridge()
        self._engine = ClickEngine(self._backend, self._bridge.callbacks())
        self._hotkeys = HotkeyConfig()
        self._hotkey_manager = HotkeyManager(on_error=self._bridge.warningRaised.emit)
        self._failsafe: CornerFailsafe | None = None
        self._overlay: PickerOverlay | None = None
        self._recorder = recorder if recorder is not None else ClickRecorder(
            on_event=self._bridge.recordCountChanged.emit,
            ignore=self._is_over_this_window,
        )
        self._recording = False
        #: Guards against a profile load being mistaken for the user editing.
        self._applying = False

        self._build_ui()
        self._connect()
        self._apply_hotkeys(self._hotkeys)
        self._restore_session()
        QTimer.singleShot(0, self._check_permissions_at_startup)

    # ------------------------------------------------------------------ ui

    def _build_ui(self) -> None:
        self.profiles = ProfileBar()

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
        self.start_button.setMinimumHeight(42)
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self._toggle)

        # Two columns: the settings stack on the left, the target -- which
        # grows a whole table when a sequence is open -- on the right. One tall
        # column made the window taller than most laptop screens.
        left = QVBoxLayout()
        left.addWidget(self.profiles)
        left.addWidget(self.interval)
        left.addWidget(self.options)
        left.addWidget(self.safety)
        left.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(self.target)

        columns = QHBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.notice)
        layout.addLayout(columns, 1)
        layout.addLayout(status_row)
        layout.addWidget(self.start_button)
        self.setCentralWidget(central)
        self.setMinimumWidth(880)
        self.resize(940, 620)

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
        self._bridge.recordRequested.connect(self._toggle_recording)
        self._bridge.recordCountChanged.connect(self._on_record_count)
        self._bridge.failsafeTripped.connect(self._on_failsafe)

        self.target.pickRequested.connect(self._pick_point)
        self.target.recordRequested.connect(self._toggle_recording)
        self.safety.hotkeysRequested.connect(self._edit_hotkeys)

        for widget in (self.interval, self.options, self.target):
            widget.changed.connect(self._on_edited)

        self.profiles.profileChosen.connect(self._load_profile)
        self.profiles.saveRequested.connect(self._save_profile)
        self.profiles.saveAsRequested.connect(self._save_profile_as)
        self.profiles.deleteRequested.connect(self._delete_profile)

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._refresh_counter)

    # -------------------------------------------------------------- profile

    def _profile(self, name: str | None = None) -> Profile:
        return Profile(
            name=name or self.profiles.current_name() or "Current",
            interval=self.interval.value(),
            click=self.options.click_value(),
            repeat=self.options.repeat_value(),
            target=self.target.value(),
            safety=self.safety.value(),
            hotkeys=self._hotkeys,
        )

    def _apply_profile(self, profile: Profile) -> None:
        self._applying = True
        try:
            self.interval.set_value(profile.interval)
            self.options.set_value(profile.click, profile.repeat)
            self.target.set_value(profile.target)
            self.safety.set_value(profile.safety)
            self._apply_hotkeys(profile.hotkeys)
        finally:
            self._applying = False

    def _on_edited(self) -> None:
        """Any manual change means the shown profile no longer matches."""
        if not self._applying:
            self.profiles.mark_unsaved()

    def _refresh_profiles(self, current: str | None = None) -> None:
        self.profiles.set_profiles(self._store.names(), current)

    def _load_profile(self, name: str) -> None:
        profile = self._store.load(name)
        if profile is None:
            self._on_warning(f"Could not read the profile “{name}”.")
            self._refresh_profiles()
            return
        self._apply_profile(profile)
        self.status.setText(f"Loaded “{name}”")

    def _save_profile(self) -> None:
        name = self.profiles.current_name()
        if not name:
            self._save_profile_as()
            return
        self._store.save(self._profile(name))
        self._refresh_profiles(name)
        self.status.setText(f"Saved “{name}”")

    def _save_profile_as(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save profile", "Profile name")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self._store.names():
            answer = QMessageBox.question(
                self, "Replace profile", f"“{name}” already exists. Replace it?"
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        self._store.save(self._profile(name))
        self._refresh_profiles(name)
        self.status.setText(f"Saved “{name}”")

    def _delete_profile(self) -> None:
        name = self.profiles.current_name()
        if not name:
            return
        answer = QMessageBox.question(self, "Delete profile", f"Delete “{name}”?")
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._store.delete(name)
        self._refresh_profiles()
        self.status.setText(f"Deleted “{name}”")

    def _restore_session(self) -> None:
        stored = self._settings.read()
        last = stored.get("last_profile")
        self._refresh_profiles(last if isinstance(last, str) else None)
        if isinstance(last, str) and last in self._store.names():
            self._load_profile(last)
        if stored.get("always_on_top"):
            self.on_top_action.setChecked(True)

    # -------------------------------------------------------------- control

    def _toggle(self) -> None:
        if self._recording:
            self.status.setText("Stop the recording first.")
            return
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
        self.status.setText({
            StopReason.FAILSAFE: "Stopped — screen corner",
            StopReason.PANIC: "Stopped — panic key",
            StopReason.COMPLETED: "Finished",
            StopReason.ERROR: "Error",
        }.get(reason, "Idle"))
        self.status.setToolTip(detail)

    def _on_error(self, message: str) -> None:
        """A run failed. This is worth a dialog."""
        self._set_colour(COLOR_ERROR)
        QMessageBox.critical(self, "Autoclicker", message)

    def _on_warning(self, message: str) -> None:
        """Degraded but usable. Says so in the window; never a modal."""
        self.notice.setText(message)
        self.notice.show()

    def _refresh_counter(self) -> None:
        clicks = self._engine.clicks_fired
        self.counter.setText(f"{clicks:,} click{'' if clicks == 1 else 's'}")

    def _refresh_labels(self) -> None:
        running = self._engine.is_running
        toggle_label = format_hotkey(self._hotkeys.toggle)
        self.start_button.setText(
            f"Stop  ({toggle_label})" if running else f"Start  ({toggle_label})"
        )
        for widget in (self.profiles, self.interval, self.options, self.safety):
            widget.setEnabled(not running and not self._recording)
        self.target.setEnabled(not running)
        self.start_button.setEnabled(not self._recording)
        self.target.set_capture_hint(format_hotkey(self._hotkeys.capture))
        self.target.set_record_hotkey_label(format_hotkey(self._hotkeys.record))

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
        self.target.receive_point(x, y)
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
        self.target.receive_point(x, y)
        self.raise_()
        self.activateWindow()

    def _on_pick_cancelled(self) -> None:
        self._overlay = None
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------ recording

    def _toggle_recording(self) -> None:
        if self._engine.is_running:
            self.status.setText("Stop the clicker before recording.")
            return
        if self._recording:
            self._finish_recording()
        else:
            self._begin_recording()

    def _begin_recording(self) -> None:
        # Recorded points land in the sequence, so put the user in front of it.
        self.target.sequence.setChecked(True)
        if not self._recorder.start():
            self._on_warning(
                "Could not listen for clicks. On macOS this needs Input Monitoring "
                "permission for whichever app is hosting this process."
            )
            return
        self._recording = True
        self.target.editor.set_recording(True, 0)
        self._refresh_labels()
        self.status.setText(
            f"Recording — press {format_hotkey(self._hotkeys.record)} to stop"
        )

    def _finish_recording(self) -> None:
        events = self._recorder.stop()
        self._recording = False
        points = points_from_events(events, keep_timing=self.target.editor.keep_timing())
        self.target.editor.set_recording(False)
        self.target.editor.append_points(points)
        self._refresh_labels()
        self.status.setText(
            f"Recorded {len(points)} point{'' if len(points) == 1 else 's'} "
            f"from {len(events)} click{'' if len(events) == 1 else 's'}"
        )

    def _on_record_count(self, count: int) -> None:
        if self._recording:
            self.target.editor.set_recording(True, count)

    def _is_over_this_window(self, x: int, y: int) -> bool:
        """Ignore clicks aimed at the autoclicker itself while recording.

        Otherwise the click that presses Stop becomes the last recorded point.
        """
        return self.frameGeometry().contains(x, y)

    # -------------------------------------------------------------- hotkeys

    def _edit_hotkeys(self) -> None:
        # Stop listening first, or pressing F6 to record it would start a run.
        self._hotkey_manager.stop()
        dialog = HotkeyDialog(self._hotkeys, self)
        self._apply_hotkeys(dialog.value() if dialog.exec() else self._hotkeys)

    def _apply_hotkeys(self, config: HotkeyConfig) -> None:
        self._hotkeys = config
        self.notice.hide()
        self._hotkey_manager.bind({
            config.toggle: self._bridge.toggleRequested.emit,
            config.panic: self._bridge.panicRequested.emit,
            config.capture: self._bridge.captureRequested.emit,
            config.record: self._bridge.recordRequested.emit,
        })
        self._hotkey_manager.start()
        self._refresh_labels()
        self.safety.set_panic_label(format_hotkey(config.panic))
        self.safety.set_hotkey_summary(config)

    # ---------------------------------------------------------- permissions

    def _check_permissions_at_startup(self) -> None:
        report = check_permissions()
        if not report.all_clear:
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
        self._recorder.stop()
        self._hotkey_manager.stop()
        if self._failsafe is not None:
            self._failsafe.stop()
        if self._overlay is not None:
            self._overlay.finish()
        try:
            self._settings.update(
                last_profile=self.profiles.current_name(),
                always_on_top=self.on_top_action.isChecked(),
            )
        except OSError:
            pass
        super().closeEvent(event)


class _SafetyWidget(QGroupBox):
    """Countdown, corner failsafe, and the way in to the hotkey settings."""

    hotkeysRequested = Signal()

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

        # The menu bar carries this too, but on macOS the menu bar lives at the
        # top of the screen rather than in the window, so it is easy to miss.
        self.hotkeys_button = QPushButton("Hotkeys…")
        self.hotkeys_button.clicked.connect(self.hotkeysRequested)
        self.hotkey_summary = QLabel()
        self.hotkey_summary.setObjectName("hintLabel")
        self.hotkey_summary.setWordWrap(True)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.hotkeys_button)
        hotkey_row.addWidget(self.hotkey_summary, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(countdown_row)
        layout.addWidget(self.corner_failsafe)
        layout.addWidget(self.panic_label)
        layout.addLayout(hotkey_row)

    def set_hotkey_summary(self, config) -> None:
        self.hotkey_summary.setText(
            f"{format_hotkey(config.toggle)} start/stop · "
            f"{format_hotkey(config.capture)} capture · "
            f"{format_hotkey(config.record)} record"
        )

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
