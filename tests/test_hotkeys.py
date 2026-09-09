"""Hotkey spec handling and the corner-failsafe geometry."""

from __future__ import annotations

import pytest

from autoclicker.core.failsafe import is_in_corner
from autoclicker.core.hotkeys import canonical_spec, format_hotkey

SCREEN = (0, 0, 1920, 1080)


def test_modifiers_are_ordered_consistently() -> None:
    assert canonical_spec({"shift", "ctrl"}, "k") == "<ctrl>+<shift>+k"
    assert canonical_spec({"ctrl", "shift"}, "k") == "<ctrl>+<shift>+k"


def test_left_and_right_modifiers_collapse_to_one_name() -> None:
    assert canonical_spec({"ctrl_l"}, "k") == canonical_spec({"ctrl_r"}, "k")


def test_a_bare_function_key_needs_no_modifiers() -> None:
    assert canonical_spec(set(), "<f6>") == "<f6>"


def test_display_names_are_platform_appropriate() -> None:
    spec = "<cmd>+<alt>+k"
    assert format_hotkey(spec, platform="darwin") == "Command + Option + K"
    assert format_hotkey(spec, platform="win32") == "Win + Alt + K"


def test_display_of_special_keys() -> None:
    assert format_hotkey("<f6>") == "F6"
    assert format_hotkey("<page_down>") == "Page Down"
    assert format_hotkey("") == "Not set"


# ------------------------------------------------------------------ failsafe


@pytest.mark.parametrize("point", [(0, 0), (1919, 0), (0, 1079), (1919, 1079), (5, 5)])
def test_every_corner_triggers(point: tuple[int, int]) -> None:
    assert is_in_corner(*point, [SCREEN], margin_px=10)


@pytest.mark.parametrize("point", [(960, 540), (0, 540), (960, 0), (100, 100)])
def test_edges_and_the_middle_do_not_trigger(point: tuple[int, int]) -> None:
    """An edge is not a corner -- you brush those by accident all day."""
    assert not is_in_corner(*point, [SCREEN], margin_px=10)


def test_corners_of_a_second_monitor_work() -> None:
    """A left-hand second monitor sits at negative x, and its corners are
    interior to the combined desktop -- per-screen checks are the only way."""
    screens = [(-1920, 0, 0, 1080), SCREEN]
    assert is_in_corner(-1915, 5, screens, margin_px=10)
    assert is_in_corner(-5, 1075, screens, margin_px=10)


def test_a_point_on_no_screen_never_triggers() -> None:
    assert not is_in_corner(5000, 5000, [SCREEN], margin_px=10)


def test_a_zero_margin_disables_the_failsafe() -> None:
    assert not is_in_corner(0, 0, [SCREEN], margin_px=0)


# ------------------------------------------------------- listener lifetime
#
# These inject a fake pynput.keyboard rather than importing the real one. The
# real module cannot even be imported without a display, and the guarantee
# under test -- that the listener is created exactly once -- matters on every
# platform, so it should not be skipped on most of them.


class FakeListener:
    instances = 0

    def __init__(self, on_press=None, on_release=None) -> None:
        FakeListener.instances += 1
        self.on_press = on_press
        self.on_release = on_release
        self.stopped = False
        self.daemon = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True

    def canonical(self, key):
        return key


class FakeHotKey:
    def __init__(self, keys, on_activate) -> None:
        self.keys = keys
        self.on_activate = on_activate
        self.held: set = set()

    @staticmethod
    def parse(spec: str):
        if " " in spec:
            raise ValueError(f"unparseable: {spec}")
        return [token for token in spec.split("+") if token]

    def press(self, key) -> None:
        self.held.add(key)
        if set(self.keys) <= self.held:
            self.on_activate()

    def release(self, key) -> None:
        self.held.discard(key)


class FakeKeyboardModule:
    Listener = FakeListener
    HotKey = FakeHotKey


@pytest.fixture
def fake_keyboard(monkeypatch):
    """Make ``from pynput import keyboard`` yield the fake."""
    import sys
    import types

    FakeListener.instances = 0
    module = FakeKeyboardModule
    package = sys.modules.get("pynput") or types.ModuleType("pynput")
    monkeypatch.setitem(sys.modules, "pynput", package)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", module)
    monkeypatch.setattr(package, "keyboard", module, raising=False)
    return module


def test_rebinding_does_not_create_a_second_listener(fake_keyboard) -> None:
    """The whole reason this class was rewritten.

    Creating a pynput keyboard listener while a Qt event loop is running
    crashes Python on macOS (pynput #511/#512), and ``bind`` used to stop and
    restart one. Changing a hotkey would have taken the app down.
    """
    from autoclicker.core.hotkeys import HotkeyManager

    manager = HotkeyManager()
    manager.bind({"<f6>": lambda: None})
    manager.start()
    assert FakeListener.instances == 1

    for _ in range(5):
        manager.bind({"<f7>": lambda: None, "<f8>": lambda: None})
    assert FakeListener.instances == 1, "rebinding must reuse the listener"
    assert manager.is_active


def test_rebinding_actually_changes_what_fires(fake_keyboard) -> None:
    from autoclicker.core.hotkeys import HotkeyManager

    fired: list[str] = []
    manager = HotkeyManager()
    manager.bind({"<f6>": lambda: fired.append("old")})
    manager.start()

    manager.bind({"<f6>": lambda: fired.append("new")})
    manager._on_press("<f6>")
    assert fired == ["new"]


def test_pausing_suppresses_hotkeys_without_stopping_the_listener(fake_keyboard) -> None:
    from autoclicker.core.hotkeys import HotkeyManager

    fired: list[str] = []
    manager = HotkeyManager()
    manager.bind({"<f6>": lambda: fired.append("f6")})
    manager.start()

    manager.set_paused(True)
    manager._on_press("<f6>")
    assert fired == [], "paused hotkeys must not fire"
    assert manager.is_active, "but the listener stays up -- it cannot be restarted"
    assert FakeListener.instances == 1

    manager._on_release("<f6>")
    manager.set_paused(False)
    manager._on_press("<f6>")
    assert fired == ["f6"]


def test_an_unparseable_binding_is_skipped_rather_than_fatal(fake_keyboard) -> None:
    from autoclicker.core.hotkeys import HotkeyManager

    fired: list[str] = []
    manager = HotkeyManager()
    manager.bind({
        "<f6>": lambda: fired.append("good"),
        "not a hotkey at all": lambda: None,
    })
    manager.start()
    manager._on_press("<f6>")
    assert fired == ["good"], "one bad binding must not lose the others"


def test_starting_twice_is_harmless(fake_keyboard) -> None:
    from autoclicker.core.hotkeys import HotkeyManager

    manager = HotkeyManager()
    manager.bind({"<f6>": lambda: None})
    manager.start()
    manager.start()
    assert FakeListener.instances == 1


def test_stop_really_stops(fake_keyboard) -> None:
    from autoclicker.core.hotkeys import HotkeyManager

    manager = HotkeyManager()
    manager.bind({"<f6>": lambda: None})
    manager.start()
    manager.stop()
    assert not manager.is_active
