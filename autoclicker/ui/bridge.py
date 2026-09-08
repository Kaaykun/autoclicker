"""The thread boundary.

The engine, the hotkey listener and the failsafe all run on their own threads
and call plain Python callables. Qt widgets may only be touched from the GUI
thread. This object sits between: its methods are safe to call from anywhere,
and the signals they emit are delivered on the GUI thread by Qt's queued
connections.

Every cross-thread notification in the app goes through here. Nothing else in
``ui`` should be handed to a background thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.engine import EngineCallbacks, EngineState, StopReason


class EngineBridge(QObject):
    """Adapts engine, hotkey and failsafe callbacks into Qt signals."""

    stateChanged = Signal(str)
    clicked = Signal(int, int, int)
    countdownTick = Signal(float)
    finished = Signal(str, str)
    #: A run could not continue. Worth interrupting the user for.
    errorRaised = Signal(str)
    #: Something is degraded but the app still works -- hotkeys that would
    #: not register, for instance. Must never be shown modally: this can
    #: fire while the window is still being constructed.
    warningRaised = Signal(str)

    toggleRequested = Signal()
    panicRequested = Signal()
    captureRequested = Signal()
    failsafeTripped = Signal()

    def callbacks(self) -> EngineCallbacks:
        return EngineCallbacks(
            on_state=self._on_state,
            on_click=self._on_click,
            on_countdown=self.countdownTick.emit,
            on_finished=self._on_finished,
            on_error=self.errorRaised.emit,
        )

    # These run on the engine thread; emitting is the only thing they do.

    def _on_state(self, state: EngineState) -> None:
        self.stateChanged.emit(state.value)

    def _on_click(self, total: int, x: int, y: int) -> None:
        self.clicked.emit(total, x, y)

    def _on_finished(self, reason: StopReason, detail: str) -> None:
        self.finished.emit(reason.value, detail)
