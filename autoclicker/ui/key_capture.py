"""Capturing a key or chord, entirely inside Qt.

This deliberately does not use pynput. Creating a pynput keyboard Listener
after a Qt GUI has started crashes Python on macOS: the Darwin backend asks
the system for the current keyboard layout while setting the listener up, and
that call is only legal on the main dispatch queue. macOS traps the process
instead of returning. It is pynput issues #511 and #512, open since 2022.

Qt has no such problem, and for *recording* a binding it is strictly better
anyway: the user is looking at our dialog, so there is nothing to gain from an
OS-wide hook, and no Input Monitoring permission is needed just to choose a
key.

The result is a spec string in pynput's notation, because that is still what
the global listener consumes.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from ..core.hotkeys import canonical_spec

#: Qt key -> the name pynput uses for it.
_SPECIAL_KEYS = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "page_up",
    Qt.Key.Key_PageDown: "page_down",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_CapsLock: "caps_lock",
    Qt.Key.Key_NumLock: "num_lock",
    Qt.Key.Key_ScrollLock: "scroll_lock",
    Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_Print: "print_screen",
    Qt.Key.Key_Menu: "menu",
}

#: Modifier keys never form a binding on their own.
_MODIFIER_KEYS = frozenset({
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
})


def modifier_names(modifiers, platform: str | None = None) -> set[str]:
    """Translate Qt's modifier flags into pynput's modifier names.

    Qt swaps two of them on macOS: ``ControlModifier`` is the Command key and
    ``MetaModifier`` is the physical Control key. Reading them literally binds
    Command where the user pressed Control.
    """
    is_mac = (platform or sys.platform) == "darwin"
    names: set[str] = set()
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        names.add("shift")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        names.add("alt")
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        names.add("cmd" if is_mac else "ctrl")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        names.add("ctrl" if is_mac else "cmd")
    return names


def key_token(key: int) -> str | None:
    """The key half of a spec: ``a``, ``<f6>``, ``<space>``. None if unusable."""
    if key in _MODIFIER_KEYS:
        return None
    if key in _SPECIAL_KEYS:
        return f"<{_SPECIAL_KEYS[key]}>"
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        return f"<f{key - int(Qt.Key.Key_F1) + 1}>"
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key).lower()
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key)
    if 0x20 < key < 0x7F:
        return chr(key).lower()
    return None


def spec_from_key_event(key: int, modifiers, platform: str | None = None) -> str | None:
    """Build a pynput hotkey spec from a Qt key event. None if not bindable."""
    token = key_token(key)
    if token is None:
        return None
    return canonical_spec(modifier_names(modifiers, platform), token)


class KeyCaptureDialog(QDialog):
    """A modal “press a key” prompt. Returns a spec, or None if cancelled."""

    def __init__(self, parent=None, prompt: str = "Press a key or combination") -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a key")
        self.setModal(True)
        self.spec: str | None = None

        label = QLabel(prompt)
        hint = QLabel("Escape cancels. Modifiers on their own are not enough.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(hint)
        self.setMinimumWidth(320)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape and not modifier_names(event.modifiers()):
            self.reject()
            return
        spec = spec_from_key_event(key, event.modifiers())
        if spec is None:
            # A bare modifier: keep waiting rather than closing on it.
            event.accept()
            return
        self.spec = spec
        self.accept()

    @staticmethod
    def capture(parent=None, prompt: str = "Press a key or combination") -> str | None:
        dialog = KeyCaptureDialog(parent, prompt)
        if dialog.exec():
            return dialog.spec
        return None
