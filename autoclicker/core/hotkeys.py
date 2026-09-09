"""Global hotkeys: registration, and recording a new binding.

Hotkey specs use pynput's ``GlobalHotKeys`` notation -- ``<f6>``,
``<ctrl>+<shift>+k`` -- because that is what actually has to be handed to the
listener. :func:`format_hotkey` turns one back into something a human should
read, with the right names per platform (macOS says Command and Option; nobody
outside macOS knows what Option means).

pynput is imported lazily throughout, so this module is importable on a
headless CI runner that has no input system to attach to.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

#: Rendering order, so <shift>+<ctrl>+k and <ctrl>+<shift>+k are the same spec.
MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")

_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}

_MAC_LABELS = {"ctrl": "Control", "alt": "Option", "shift": "Shift", "cmd": "Command"}
_OTHER_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}


class HotkeyError(RuntimeError):
    """The hotkey listener could not be started."""


def canonical_spec(modifiers: Iterable[str], key_token: str) -> str:
    """Assemble a hotkey spec in a stable order.

    ``key_token`` is either a bare character (``k``) or an angled special key
    (``<f6>``), matching what pynput expects.
    """
    present = {_MODIFIER_ALIASES.get(m, m) for m in modifiers}
    parts = [f"<{name}>" for name in MODIFIER_ORDER if name in present]
    parts.append(key_token)
    return "+".join(parts)


def format_hotkey(spec: str, *, platform: str | None = None) -> str:
    """Render a spec for display: ``<ctrl>+<shift>+k`` -> ``Ctrl + Shift + K``."""
    if not spec:
        return "Not set"
    is_mac = (platform or sys.platform) == "darwin"
    labels = _MAC_LABELS if is_mac else _OTHER_LABELS

    rendered: list[str] = []
    for token in spec.split("+"):
        bare = token.strip().strip("<>")
        if not bare:
            continue
        if bare in labels:
            rendered.append(labels[bare])
        elif len(bare) == 1:
            rendered.append(bare.upper())
        else:
            rendered.append(bare.replace("_", " ").title())
    return " + ".join(rendered)


class HotkeyManager:
    """Keeps global hotkeys registered, and rebinds them without restarting.

    The listener is created **once** and never recreated, which is not just
    tidiness. Starting a pynput keyboard Listener while a Qt event loop is
    running crashes Python on macOS -- the Darwin backend queries the keyboard
    layout during setup, and that call is main-queue-only, so the OS traps the
    process (pynput #511, #512, open since 2022). Constructing it before the
    loop starts is safe; anything that would construct another one later is
    not, and ``bind`` used to do exactly that.

    So rebinding swaps the match table in place, and suppressing hotkeys while
    the user is choosing a new one is a pause flag rather than a stop/start.
    """

    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self._on_error = on_error
        self._bindings: dict[str, Callable[[], None]] = {}
        self._hotkeys: list = []
        self._listener = None
        self._paused = False

    @property
    def is_active(self) -> bool:
        return self._listener is not None

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Ignore hotkeys without tearing the listener down."""
        self._paused = bool(paused)

    def bind(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Replace the bindings. Safe to call at any time."""
        self._bindings = {spec: fn for spec, fn in bindings.items() if spec}
        self._rebuild()

    def start(self) -> None:
        """Create the listener. Call once, before the GUI event loop starts."""
        if self.is_active or not self._bindings:
            return
        try:
            from pynput import keyboard

            listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            listener.daemon = True
            listener.start()
        except Exception as exc:  # pragma: no cover - platform dependent
            message = (
                f"Could not register global hotkeys: {exc}. On macOS this "
                "usually means Input Monitoring permission has not been granted."
            )
            logger.warning(message)
            if self._on_error is not None:
                self._on_error(message)
            return
        self._listener = listener
        self._rebuild()

    def stop(self) -> None:
        """Tear the listener down. Only on the way out -- it cannot be restarted."""
        listener, self._listener = self._listener, None
        self._hotkeys = []
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # pragma: no cover - platform dependent
            logger.exception("Could not stop the hotkey listener")

    # ------------------------------------------------------------ internals

    def _rebuild(self) -> None:
        """Rebuild the match table from the current bindings."""
        try:
            from pynput import keyboard
        except Exception:  # pragma: no cover - platform dependent
            return
        hotkeys = []
        for spec, callback in self._bindings.items():
            try:
                hotkeys.append(
                    keyboard.HotKey(keyboard.HotKey.parse(spec), self._fire(callback))
                )
            except Exception:
                logger.warning("Ignoring unparseable hotkey %r", spec, exc_info=True)
        self._hotkeys = hotkeys

    def _fire(self, callback: Callable[[], None]) -> Callable[[], None]:
        def activate() -> None:
            if not self._paused:
                callback()

        return activate

    def _canonical(self, key: object) -> object:
        listener = self._listener
        if listener is None:
            return key
        try:
            return listener.canonical(key)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - platform dependent
            return key

    def _on_press(self, key: object) -> None:
        canonical = self._canonical(key)
        for hotkey in self._hotkeys:
            try:
                hotkey.press(canonical)
            except Exception:  # pragma: no cover - platform dependent
                logger.exception("Hotkey press handling failed")

    def _on_release(self, key: object) -> None:
        canonical = self._canonical(key)
        for hotkey in self._hotkeys:
            try:
                hotkey.release(canonical)
            except Exception:  # pragma: no cover - platform dependent
                logger.exception("Hotkey release handling failed")
