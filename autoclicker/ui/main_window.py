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

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.backends import PynputBackend
from ..core.config import ActionType, HotkeyConfig, Profile, SafetyConfig
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
from ..core.units import format_counter
from .bridge import EngineBridge
from .hotkey_dialog import HotkeyDialog
from .icons import app_icon, tray_icon
from .interval_widget import IntervalWidget
from .keys_widget import KeysWidget
from .options_widget import OptionsWidget
from .picker_overlay import PointPicker
from .profile_bar import ProfileBar
from .screens import screen_rects
from .target_widget import TargetWidget
from .theme import COLOR_COUNTDOWN, COLOR_ERROR, COLOR_IDLE, COLOR_RUNNING

#: How often the counter refreshes while running.
POLL_INTERVAL_MS = 100


class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore | None = None,
                 settings: Settings | None = None,
                 recorder: ClickRecorder | None = None,
                 hotkey_manager: HotkeyManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autoclicker")
        self.setWindowIcon(app_icon())

        self._store = store if store is not None else ProfileStore()
        self._settings = settings if settings is not None else Settings()

        self._backend = PynputBackend()
        self._bridge = EngineBridge()
        self._engine = ClickEngine(self._backend, self._bridge.callbacks())
        self._hotkeys = HotkeyConfig()
        # Injectable so tests never register real global hotkeys. On macOS
        # that means a Quartz event tap, which needs Input Monitoring the
        # runner has not granted -- and a test suite should not depend on
        # the machine's input permissions either way.
        self._hotkey_manager = hotkey_manager or HotkeyManager(
            on_error=self._bridge.warningRaised.emit
        )
        self._failsafe: CornerFailsafe | None = None
        self._picker: PointPicker | None = None
        self._recorder = recorder if recorder is not None else ClickRecorder(
            on_event=self._bridge.recordCountChanged.emit,
            ignore=self._is_over_this_window,
        )
        self._recording = False
        self._expanded_size = None
        self._tray: QSystemTrayIcon | None = None
        self._quitting = False
        self._run_started_at: float | None = None
        #: Guards against a profile load being mistaken for the user editing.
        self._applying = False

        self._build_ui()
        self._connect()
        self._build_tray()
        self._apply_hotkeys(self._hotkeys)
        self._restore_session()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)
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
        self.keys = KeysWidget()
        # The right column carries whichever panel the action needs. Keystrokes
        # have nothing to aim at, so Target is meaningless in key mode and Keys
        # is meaningless in click mode; only one is ever relevant.
        self.action_panels = QStackedWidget()
        self.action_panels.addWidget(self.target)
        self.action_panels.addWidget(self.keys)
        self.safety = _SafetyWidget()

        self.status = QLabel("Idle")
        self.status.setObjectName("statusLabel")
        self.counter = QLabel("0 clicks")
        self.counter.setObjectName("counterLabel")

        self.mini_button = QToolButton()
        self.mini_button.setCheckable(True)
        self.mini_button.setText("⤢")
        self.mini_button.setToolTip(
            "Mini mode — shrink to just the controls you need while running"
        )
        self.mini_button.toggled.connect(self._set_mini)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status)
        status_row.addStretch(1)
        status_row.addWidget(self.counter)
        status_row.addWidget(self.mini_button)

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
        right.addWidget(self.action_panels)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        # Everything above the status row lives in one container, so mini mode
        # is a single setVisible rather than a list of widgets to keep in sync.
        self._settings_area = QWidget()
        self._settings_area.setLayout(columns)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.notice)
        layout.addWidget(self._settings_area, 1)
        # Kept so mini mode can drop the stretch. Hiding a widget frees its
        # size but not its share of the spare space, so without this the
        # collapsed window keeps a tall void where the settings used to be.
        self._settings_stretch_index = layout.indexOf(self._settings_area)
        self._central_layout = layout
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

        self.mini_action = QAction("Mini mode", self)
        self.mini_action.setCheckable(True)
        self.mini_action.toggled.connect(self.mini_button.setChecked)
        settings.addAction(self.mini_action)

        self.keep_in_tray_action = QAction("Keep running when the window closes", self)
        self.keep_in_tray_action.setCheckable(True)
        self.keep_in_tray_action.toggled.connect(self._apply_tray_preference)
        settings.addAction(self.keep_in_tray_action)

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
        self.options.actionChanged.connect(self._on_action_changed)
        self.keys.changed.connect(self._on_edited)
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
            action=self.options.action_value(),
            interval=self.interval.value(),
            click=self.options.click_value(),
            key=self.keys.value(),
            repeat=self.options.repeat_value(),
            target=self.target.value(),
            safety=self.safety.value(),
            hotkeys=self._hotkeys,
        )

    def _apply_profile(self, profile: Profile) -> None:
        self._applying = True
        try:
            self.interval.set_value(profile.interval)
            self.options.set_value(profile.action, profile.click, profile.repeat)
            self.keys.set_value(profile.key)
            self.target.set_value(profile.target)
            self._sync_action_panel()
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
        if stored.get("mini"):
            self.mini_button.setChecked(True)
        self.keep_in_tray_action.setEnabled(self._tray is not None)
        if stored.get("keep_in_tray") and self._tray is not None:
            self.keep_in_tray_action.setChecked(True)

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
        state = EngineState(state_value)
        if state is EngineState.RUNNING:
            # Time the achieved rate from the first click, not from the button
            # press, or a countdown would drag the average down.
            self._run_started_at = time.monotonic()
        self._set_status(state)
        self._refresh_labels()
        self._update_tray()

    def _on_countdown(self, remaining: float) -> None:
        self.status.setText(f"Starting in {remaining:.1f}s…")

    def _on_finished(self, reason_value: str, detail: str) -> None:
        self._poll.stop()
        if self._failsafe is not None:
            self._failsafe.stop()
            self._failsafe = None
        self._refresh_counter()
        self._run_started_at = None
        self._refresh_labels()
        self._update_tray()

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

    def _action_noun(self) -> str:
        return "press" if self.options.action_value() is ActionType.KEY else "click"

    def _refresh_counter(self) -> None:
        elapsed = None
        if self._run_started_at is not None:
            elapsed = time.monotonic() - self._run_started_at
        self.counter.setText(
            format_counter(self._engine.clicks_fired, elapsed, self._action_noun())
        )
        self._update_tray()

    def _refresh_labels(self) -> None:
        running = self._engine.is_running
        toggle_label = format_hotkey(self._hotkeys.toggle)
        self.start_button.setText(
            f"Stop  ({toggle_label})" if running else f"Start  ({toggle_label})"
        )
        for widget in (self.profiles, self.interval, self.options, self.safety):
            widget.setEnabled(not running and not self._recording)
        self.target.setEnabled(not running)
        self.keys.setEnabled(not running)
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
        if self._picker is not None and self._picker.is_active:
            return
        picker = PointPicker(self._backend.position, parent=self)
        picker.picked.connect(self._on_point_picked)
        picker.cancelled.connect(self._on_pick_cancelled)
        self._picker = picker
        picker.start()

    def _on_point_picked(self, x: int, y: int) -> None:
        self._picker = None
        self.target.receive_point(x, y)
        self.raise_()
        self.activateWindow()

    def _on_pick_cancelled(self) -> None:
        self._picker = None
        self.raise_()
        self.activateWindow()

    # --------------------------------------------------------------- action

    def _on_action_changed(self, _value: str) -> None:
        self._sync_action_panel()

    def _sync_action_panel(self) -> None:
        sends_keys = self.options.action_value() is ActionType.KEY
        self.action_panels.setCurrentWidget(self.keys if sends_keys else self.target)
        self._refresh_counter()

    # ----------------------------------------------------------- mini mode

    def _set_mini(self, on: bool) -> None:
        """Collapse to the status line, counter and Start button.

        Everything you want while it is running, nothing you want while setting
        it up. The pin-on-top setting stays independent, deliberately.
        """
        if on and self._expanded_size is None:
            self._expanded_size = self.size()

        self._settings_area.setVisible(not on)
        self._central_layout.setStretch(self._settings_stretch_index, 0 if on else 1)
        self.setMinimumWidth(300 if on else 880)
        self.setMinimumHeight(0)

        for widget in (self.mini_action, self.mini_button):
            widget.blockSignals(True)
            widget.setChecked(on)
            widget.blockSignals(False)
        self.mini_button.setText("⤢" if not on else "⤡")

        if on:
            # adjustSize alone is unreliable here, so ask the layout what it
            # actually needs and resize to exactly that.
            self.adjustSize()
            hint = self.centralWidget().sizeHint().height()
            self.resize(max(self.minimumWidth(), 320), max(hint, 1))
        elif self._expanded_size is not None:
            self.resize(self._expanded_size)
            self._expanded_size = None

    # ----------------------------------------------------------------- tray

    def _build_tray(self) -> None:
        """A menu-bar / system-tray control, when the desktop offers one."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray = QSystemTrayIcon(tray_icon(running=False), self)
        menu = QMenu()

        self._tray_toggle = QAction("Start", self)
        self._tray_toggle.triggered.connect(self._toggle)
        menu.addAction(self._tray_toggle)
        menu.addSeparator()

        show_action = QAction("Show window", self)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        quit_action = QAction("Quit Autoclicker", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        self._update_tray()

    def _on_tray_activated(self, reason) -> None:
        # macOS opens the menu on any click; elsewhere a plain click should
        # bring the window back.
        if reason is QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _update_tray(self) -> None:
        if self._tray is None:
            return
        running = self._engine.is_running
        self._tray.setIcon(tray_icon(running=running))
        self._tray_toggle.setText("Stop" if running else "Start")
        self._tray.setToolTip(
            f"Autoclicker — {'running' if running else 'idle'}"
            f"\n{format_counter(self._engine.clicks_fired, noun=self._action_noun())}"
        )

    def _apply_tray_preference(self, enabled: bool) -> None:
        """Decide whether closing the window quits the app."""
        keep = bool(enabled) and self._tray is not None
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(not keep)
        self.keep_in_tray_action.setEnabled(self._tray is not None)
        if self._tray is None and enabled:
            self.keep_in_tray_action.setChecked(False)
            self._on_warning("This desktop has no system tray, so the window has to stay open.")

    def _quit(self) -> None:
        self._quitting = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

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
        self._expanded_size = None
        self._tray: QSystemTrayIcon | None = None
        self._quitting = False
        self._run_started_at: float | None = None
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

    def _shutdown(self) -> None:
        """Tear everything down. Runs on a real quit, whichever path got there."""
        self._engine.stop()
        self._recorder.stop()
        self._hotkey_manager.stop()
        if self._failsafe is not None:
            self._failsafe.stop()
        if self._picker is not None:
            self._picker.finish()
        if self._tray is not None:
            self._tray.hide()
        try:
            self._settings.update(
                last_profile=self.profiles.current_name(),
                always_on_top=self.on_top_action.isChecked(),
                keep_in_tray=self.keep_in_tray_action.isChecked(),
                mini=self.mini_button.isChecked(),
            )
        except OSError:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        keeping = (
            self.keep_in_tray_action.isChecked()
            and self._tray is not None
            and not self._quitting
        )
        if keeping:
            # Hide rather than quit, so the hotkeys keep working. Quit is in
            # the tray menu -- and it has to be, or the app becomes unkillable
            # from the UI.
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Autoclicker",
                "Still running. Use the tray icon to start, stop or quit.",
                tray_icon(running=self._engine.is_running),
                4000,
            )
            return
        self._shutdown()
        super().closeEvent(event)


class _SafetyWidget(QGroupBox):
    """Countdown, corner failsafe, and the way in to the hotkey settings."""

    hotkeysRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Safety", parent)

        self.countdown = QSpinBox()
        self.countdown.setRange(0, 60)
        self.countdown.setSuffix(" s")
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
