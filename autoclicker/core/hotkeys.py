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
    """Keeps a set of global hotkeys registered, and rebinds them on demand."""

    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self._on_error = on_error
        self._bindings: dict[str, Callable[[], None]] = {}
        self._listener = None

    @property
    def is_active(self) -> bool:
        return self._listener is not None

    def bind(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Replace the whole binding set, restarting the listener if needed."""
        self._bindings = {spec: fn for spec, fn in bindings.items() if spec}
        if self.is_active:
            self.stop()
            self.start()

    def start(self) -> None:
        if self.is_active or not self._bindings:
            return
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys(dict(self._bindings))
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

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # pragma: no cover - platform dependent
            logger.exception("Could not stop the hotkey listener")


class HotkeyRecorder:
    """Captures the next key combination the user presses.

    Modifiers alone never complete a recording -- you have to land on a real
    key -- and a bare Escape cancels, which is what everyone expects.
    """

    def __init__(
        self,
        on_captured: Callable[[str], None],
        on_cancelled: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_captured = on_captured
        self._on_cancelled = on_cancelled
        self._on_error = on_error
        self._listener = None
        self._modifiers: set[str] = set()

    @property
    def is_recording(self) -> bool:
        return self._listener is not None

    def start(self) -> None:
        if self.is_recording:
            return
        self._modifiers = set()
        try:
            from pynput import keyboard

            listener = keyboard.Listener(on_press=self._press, on_release=self._release)
            listener.daemon = True
            listener.start()
        except Exception as exc:  # pragma: no cover - platform dependent
            if self._on_error is not None:
                self._on_error(f"Could not listen for key presses: {exc}")
            return
        self._listener = listener

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # pragma: no cover - platform dependent
                logger.exception("Could not stop the hotkey recorder")

    # -- listener callbacks (these run on pynput's thread) -----------------

    def _press(self, key: object) -> None:
        name = _modifier_name(key)
        if name is not None:
            self._modifiers.add(name)
            return

        token = _key_token(key, self._listener)
        if token is None:
            return

        if token == "<esc>" and not self._modifiers:
            self.stop()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return

        spec = canonical_spec(self._modifiers, token)
        self.stop()
        self._on_captured(spec)

    def _release(self, key: object) -> None:
        name = _modifier_name(key)
        if name is not None:
            self._modifiers.discard(name)


def _modifier_name(key: object) -> str | None:
    name = getattr(key, "name", None)
    if name is None:
        return None
    return _MODIFIER_ALIASES.get(name)


def _key_token(key: object, listener: object) -> str | None:
    """Turn a pynput key into the token half of a hotkey spec."""
    name = getattr(key, "name", None)
    if name is not None:
        return f"<{name}>"

    # Ask pynput to normalise first: with a modifier held, ``char`` is often a
    # control code rather than the letter that is physically pressed.
    canonical = key
    if listener is not None:
        try:
            canonical = listener.canonical(key)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - platform dependent
            canonical = key

    char = getattr(canonical, "char", None) or getattr(key, "char", None)
    if char and char.isprintable():
        return char.lower()
    return None
