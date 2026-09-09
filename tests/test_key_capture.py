"""Turning a Qt key event into a pynput hotkey spec.

Pure translation, no listener and no OS input -- which is the point. Capturing
through pynput crashes Python on macOS when a Qt event loop is running
(pynput #511/#512), so recording is done in Qt and converted here.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QtWidgets too, not just QtCore: the module under test imports it, and the
# wheel is often present while the Qt runtime libraries it links against are
# not -- the usual state of a bare Linux box.
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog  # noqa: F401
except ImportError as exc:  # pragma: no cover - depends on the machine
    pytest.skip(f"the Qt runtime is not available: {exc}", allow_module_level=True)

from autoclicker.ui.key_capture import (  # noqa: E402
    key_token,
    modifier_names,
    spec_from_key_event,
)

NONE = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
META = Qt.KeyboardModifier.MetaModifier
ALT = Qt.KeyboardModifier.AltModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


# --------------------------------------------------------------- key tokens


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (Qt.Key.Key_A, "a"),
        (Qt.Key.Key_Z, "z"),
        (Qt.Key.Key_5, "5"),
        (Qt.Key.Key_F1, "<f1>"),
        (Qt.Key.Key_F6, "<f6>"),
        (Qt.Key.Key_F12, "<f12>"),
        (Qt.Key.Key_Space, "<space>"),
        (Qt.Key.Key_Escape, None),
        (Qt.Key.Key_Return, "<enter>"),
        (Qt.Key.Key_Backspace, "<backspace>"),
        (Qt.Key.Key_PageDown, "<page_down>"),
        (Qt.Key.Key_Left, "<left>"),
    ],
)
def test_key_tokens(key, expected) -> None:
    if expected is None:
        pytest.skip("escape is handled by the dialog, not the converter")
    assert key_token(key) == expected


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta],
)
def test_a_modifier_alone_is_not_a_binding(key) -> None:
    assert key_token(key) is None
    assert spec_from_key_event(key, CTRL) is None


# --------------------------------------------------------------- modifiers


def test_macos_swaps_control_and_command() -> None:
    """Qt reports Command as ControlModifier on macOS.

    Read literally, pressing Control would bind Command and vice versa -- the
    binding would then never fire, or fire on the wrong key.
    """
    assert modifier_names(CTRL, "darwin") == {"cmd"}
    assert modifier_names(META, "darwin") == {"ctrl"}

    assert modifier_names(CTRL, "win32") == {"ctrl"}
    assert modifier_names(META, "win32") == {"cmd"}


def test_shift_and_alt_are_the_same_everywhere() -> None:
    for platform in ("darwin", "win32", "linux"):
        assert modifier_names(ALT, platform) == {"alt"}
        assert modifier_names(SHIFT, platform) == {"shift"}


def test_combined_modifiers() -> None:
    assert modifier_names(CTRL | SHIFT | ALT, "win32") == {"ctrl", "shift", "alt"}


# -------------------------------------------------------------------- specs


def test_full_specs() -> None:
    assert spec_from_key_event(Qt.Key.Key_F6, NONE) == "<f6>"
    assert spec_from_key_event(Qt.Key.Key_V, CTRL, "win32") == "<ctrl>+v"
    assert spec_from_key_event(Qt.Key.Key_V, CTRL, "darwin") == "<cmd>+v"
    assert spec_from_key_event(Qt.Key.Key_V, META, "darwin") == "<ctrl>+v"


def test_modifier_order_is_stable() -> None:
    """So that the same chord always produces the same spec string."""
    assert spec_from_key_event(
        Qt.Key.Key_K, SHIFT | CTRL, "win32"
    ) == "<ctrl>+<shift>+k"


def test_specs_round_trip_through_the_display_formatter() -> None:
    from autoclicker.core.hotkeys import format_hotkey

    spec = spec_from_key_event(Qt.Key.Key_V, CTRL, "win32")
    assert format_hotkey(spec, platform="win32") == "Ctrl + V"


def test_a_spec_from_capture_is_shaped_like_a_hotkey() -> None:
    """What the converter emits has to be what the listener consumes."""
    import re

    for spec in ("<f6>", "<ctrl>+v", "a", "<ctrl>+<shift>+k", "<space>"):
        for token in spec.split("+"):
            assert re.fullmatch(r"<[a-z_0-9]+>|[a-z0-9]", token), token
