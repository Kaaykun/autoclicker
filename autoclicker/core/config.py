"""Configuration dataclasses and their JSON representation.

Everything the engine needs to run is described here, and nothing here imports
Qt or pynput -- a ``Profile`` is a plain, serialisable value object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1

#: Anything below this is rejected outright; the OS cannot keep up regardless.
MIN_INTERVAL_MS = 1.0
#: Below this the OS event pipeline, not Python, is the limiting factor.
FAST_INTERVAL_WARNING_MS = 10.0
#: A fresh, unconfigured autoclicker clicks once a second.
DEFAULT_INTERVAL_SECONDS = 1


class MouseButton(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class ClickType(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"

    @property
    def count(self) -> int:
        """How many press/release pairs this click type is worth."""
        return {ClickType.SINGLE: 1, ClickType.DOUBLE: 2, ClickType.TRIPLE: 3}[self]


class JitterMode(str, Enum):
    OFF = "off"
    PERCENT = "percent"
    MILLIS = "millis"


class TargetMode(str, Enum):
    FOLLOW_CURSOR = "follow_cursor"
    FIXED_POINT = "fixed_point"
    SEQUENCE = "sequence"


class ActionType(str, Enum):
    """What the engine repeats: mouse clicks, or key presses."""

    CLICK = "click"
    KEY = "key"


class KeyMode(str, Enum):
    SINGLE = "single"
    SEQUENCE = "sequence"


def coerce_enum(cls: type[Enum], value: Any, default: Enum) -> Any:
    """Coerce ``value`` to a member of ``cls``, falling back to ``default``.

    Called from ``__post_init__`` as well as from the JSON loaders, because
    these fields arrive from three directions and only one of them is typed:
    JSON on disk, CLI strings, and Qt. That last one is the surprising case --
    a combo box round-trips its data through QVariant, and a ``str`` Enum comes
    back out as a plain ``str``. It compares equal to the member, so nothing
    looks wrong until something reaches for ``.value``.
    """
    try:
        return cls(value)
    except ValueError:
        return default


@dataclass
class IntervalConfig:
    """The delay between clicks, split the way the UI presents it."""

    hours: int = 0
    minutes: int = 0
    seconds: int = DEFAULT_INTERVAL_SECONDS
    millis: int = 0
    jitter_mode: JitterMode = JitterMode.OFF
    #: Percent (0-100) when mode is PERCENT, milliseconds when mode is MILLIS.
    jitter_amount: float = 0.0

    def __post_init__(self) -> None:
        self.jitter_mode = coerce_enum(JitterMode, self.jitter_mode, JitterMode.OFF)

    @property
    def total_ms(self) -> float:
        return ((self.hours * 60 + self.minutes) * 60 + self.seconds) * 1000.0 + self.millis

    @property
    def total_seconds(self) -> float:
        return self.total_ms / 1000.0

    def validate(self) -> list[str]:
        problems: list[str] = []
        if min(self.hours, self.minutes, self.seconds, self.millis) < 0:
            problems.append("Interval components cannot be negative.")
        if self.total_ms < MIN_INTERVAL_MS:
            problems.append(f"Interval must be at least {MIN_INTERVAL_MS:g} ms.")
        if self.jitter_mode is JitterMode.PERCENT and not 0 <= self.jitter_amount <= 100:
            problems.append("Percentage jitter must be between 0 and 100.")
        if self.jitter_mode is JitterMode.MILLIS and self.jitter_amount < 0:
            problems.append("Millisecond jitter cannot be negative.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "hours": self.hours,
            "minutes": self.minutes,
            "seconds": self.seconds,
            "millis": self.millis,
            "jitter_mode": self.jitter_mode.value,
            "jitter_amount": self.jitter_amount,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntervalConfig:
        """Rebuild from JSON.

        The components are all-or-nothing: if the data names *any* of them, the
        rest are zero. Falling back to the 1-second default per-field would mean
        ``{"millis": 250}`` quietly loading as 1.25 seconds.
        """
        fields = ("hours", "minutes", "seconds", "millis")
        present = {name: int(data[name]) for name in fields if name in data}
        if not present:
            present = {"seconds": DEFAULT_INTERVAL_SECONDS}
        return cls(
            hours=present.get("hours", 0),
            minutes=present.get("minutes", 0),
            seconds=present.get("seconds", 0),
            millis=present.get("millis", 0),
            jitter_mode=coerce_enum(JitterMode, data.get("jitter_mode"), JitterMode.OFF),
            jitter_amount=float(data.get("jitter_amount", 0.0)),
        )


@dataclass
class ClickConfig:
    """What a single "click" actually sends."""

    button: MouseButton = MouseButton.LEFT
    click_type: ClickType = ClickType.SINGLE
    #: 0 means "let the OS do it natively", which is what makes a double-click
    #: register as a real double-click rather than two lone clicks. Set a
    #: positive gap only if a target app wants the presses spaced out.
    inter_click_gap_ms: float = 0.0
    #: How long the button stays held on each press.
    hold_ms: float = 0.0

    def __post_init__(self) -> None:
        self.button = coerce_enum(MouseButton, self.button, MouseButton.LEFT)
        self.click_type = coerce_enum(ClickType, self.click_type, ClickType.SINGLE)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.inter_click_gap_ms < 0:
            problems.append("Inter-click gap cannot be negative.")
        if self.hold_ms < 0:
            problems.append("Hold duration cannot be negative.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "button": self.button.value,
            "click_type": self.click_type.value,
            "inter_click_gap_ms": self.inter_click_gap_ms,
            "hold_ms": self.hold_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClickConfig:
        return cls(
            button=coerce_enum(MouseButton, data.get("button"), MouseButton.LEFT),
            click_type=coerce_enum(ClickType, data.get("click_type"), ClickType.SINGLE),
            inter_click_gap_ms=float(data.get("inter_click_gap_ms", 0.0)),
            hold_ms=float(data.get("hold_ms", 0.0)),
        )


@dataclass
class RepeatConfig:
    """How long to keep going."""

    until_stopped: bool = True
    #: Clicks in point modes; complete passes through the list in sequence mode.
    count: int = 100

    def validate(self) -> list[str]:
        if not self.until_stopped and self.count < 1:
            return ["Repeat count must be at least 1."]
        return []

    def to_dict(self) -> dict[str, Any]:
        return {"until_stopped": self.until_stopped, "count": self.count}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepeatConfig:
        return cls(
            until_stopped=bool(data.get("until_stopped", True)),
            count=int(data.get("count", 100)),
        )


@dataclass
class SequencePoint:
    """One stop in a click sequence."""

    x: int = 0
    y: int = 0
    button: MouseButton = MouseButton.LEFT
    click_type: ClickType = ClickType.SINGLE
    #: Overrides the global interval after this point when > 0.
    delay_after_ms: float = 0.0

    def __post_init__(self) -> None:
        self.button = coerce_enum(MouseButton, self.button, MouseButton.LEFT)
        self.click_type = coerce_enum(ClickType, self.click_type, ClickType.SINGLE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "button": self.button.value,
            "click_type": self.click_type.value,
            "delay_after_ms": self.delay_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequencePoint:
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            button=coerce_enum(MouseButton, data.get("button"), MouseButton.LEFT),
            click_type=coerce_enum(ClickType, data.get("click_type"), ClickType.SINGLE),
            delay_after_ms=float(data.get("delay_after_ms", 0.0)),
        )


@dataclass
class KeyStep:
    """One key press in a key sequence.

    ``spec`` is a hotkey string in pynput's notation -- ``a``, ``<f5>``,
    ``<ctrl>+v`` -- the same format the hotkey settings use, so the recorder is
    shared between the two.
    """

    spec: str = ""
    #: How long the key stays held. Long enough and the target app's own key
    #: repeat takes over, which is usually what holding a key is for.
    hold_ms: float = 0.0
    #: Overrides the global interval after this step when > 0.
    delay_after_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "hold_ms": self.hold_ms,
            "delay_after_ms": self.delay_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyStep:
        return cls(
            spec=str(data.get("spec", "")),
            hold_ms=float(data.get("hold_ms", 0.0)),
            delay_after_ms=float(data.get("delay_after_ms", 0.0)),
        )


@dataclass
class KeyConfig:
    """What to press, when the action is keys rather than clicks."""

    mode: KeyMode = KeyMode.SINGLE
    spec: str = ""
    hold_ms: float = 0.0
    sequence: list[KeyStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.mode = coerce_enum(KeyMode, self.mode, KeyMode.SINGLE)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.hold_ms < 0:
            problems.append("Key hold duration cannot be negative.")
        if self.mode is KeyMode.SINGLE:
            if not self.spec:
                problems.append("Choose a key to press.")
        elif not self.sequence:
            problems.append("A key sequence needs at least one key.")
        elif any(not step.spec for step in self.sequence):
            problems.append("Every step in the key sequence needs a key.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "spec": self.spec,
            "hold_ms": self.hold_ms,
            "sequence": [step.to_dict() for step in self.sequence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyConfig:
        return cls(
            mode=coerce_enum(KeyMode, data.get("mode"), KeyMode.SINGLE),
            spec=str(data.get("spec", "")),
            hold_ms=float(data.get("hold_ms", 0.0)),
            sequence=[KeyStep.from_dict(step) for step in data.get("sequence", [])],
        )


@dataclass
class TargetConfig:
    """Where the clicks land.

    Coordinates are in virtual-desktop space, so negative values are legal on
    multi-monitor setups where a display sits left of or above the primary.
    """

    mode: TargetMode = TargetMode.FOLLOW_CURSOR
    x: int = 0
    y: int = 0
    position_jitter_px: int = 0
    sequence: list[SequencePoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.mode = coerce_enum(TargetMode, self.mode, TargetMode.FOLLOW_CURSOR)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.position_jitter_px < 0:
            problems.append("Position jitter cannot be negative.")
        if self.mode is TargetMode.SEQUENCE and not self.sequence:
            problems.append("Sequence mode needs at least one point.")
        return problems

    @property
    def is_sequence(self) -> bool:
        return self.mode is TargetMode.SEQUENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "x": self.x,
            "y": self.y,
            "position_jitter_px": self.position_jitter_px,
            "sequence": [point.to_dict() for point in self.sequence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetConfig:
        return cls(
            mode=coerce_enum(TargetMode, data.get("mode"), TargetMode.FOLLOW_CURSOR),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            position_jitter_px=int(data.get("position_jitter_px", 0)),
            sequence=[SequencePoint.from_dict(p) for p in data.get("sequence", [])],
        )


@dataclass
class SafetyConfig:
    """The controls that make a runaway clicker stoppable."""

    countdown_seconds: float = 0.0
    corner_failsafe: bool = True
    corner_margin_px: int = 10

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.countdown_seconds < 0:
            problems.append("Countdown cannot be negative.")
        if self.corner_margin_px < 1:
            problems.append("Corner failsafe margin must be at least 1 px.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "countdown_seconds": self.countdown_seconds,
            "corner_failsafe": self.corner_failsafe,
            "corner_margin_px": self.corner_margin_px,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyConfig:
        return cls(
            countdown_seconds=float(data.get("countdown_seconds", 0.0)),
            corner_failsafe=bool(data.get("corner_failsafe", True)),
            corner_margin_px=int(data.get("corner_margin_px", 10)),
        )


@dataclass
class HotkeyConfig:
    """Global hotkeys, in pynput's ``GlobalHotKeys`` notation."""

    toggle: str = "<f6>"
    panic: str = "<f8>"
    capture: str = "<f7>"
    record: str = "<f9>"

    def validate(self) -> list[str]:
        bindings = {
            "start/stop": self.toggle,
            "panic": self.panic,
            "capture": self.capture,
            "record": self.record,
        }
        problems = [f"The {name} hotkey is empty." for name, key in bindings.items() if not key]
        assigned = [key for key in bindings.values() if key]
        if len(set(assigned)) != len(assigned):
            problems.append("Two hotkeys are bound to the same combination.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "toggle": self.toggle,
            "panic": self.panic,
            "capture": self.capture,
            "record": self.record,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HotkeyConfig:
        return cls(
            toggle=str(data.get("toggle", "<f6>")),
            panic=str(data.get("panic", "<f8>")),
            capture=str(data.get("capture", "<f7>")),
            record=str(data.get("record", "<f9>")),
        )


@dataclass
class Profile:
    """A complete, named autoclicker setup."""

    name: str = "Default"
    action: ActionType = ActionType.CLICK
    interval: IntervalConfig = field(default_factory=IntervalConfig)
    click: ClickConfig = field(default_factory=ClickConfig)
    key: KeyConfig = field(default_factory=KeyConfig)
    repeat: RepeatConfig = field(default_factory=RepeatConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)

    def __post_init__(self) -> None:
        self.action = coerce_enum(ActionType, self.action, ActionType.CLICK)

    @property
    def sends_keys(self) -> bool:
        return self.action is ActionType.KEY

    def validate(self) -> list[str]:
        """Return every reason this profile cannot be run; empty means good.

        Only the half that is actually in use is checked. Key mode ignores the
        target entirely -- keystrokes go to whatever window has focus -- so an
        empty click sequence left over from earlier must not block a key run.
        """
        problems = [
            *self.interval.validate(),
            *self.repeat.validate(),
            *self.safety.validate(),
            *self.hotkeys.validate(),
        ]
        if self.sends_keys:
            problems += self.key.validate()
        else:
            problems += [*self.click.validate(), *self.target.validate()]
        return problems

    def warnings(self) -> list[str]:
        """Return things worth telling the user that are not errors."""
        notes: list[str] = []
        if MIN_INTERVAL_MS <= self.interval.total_ms < FAST_INTERVAL_WARNING_MS:
            notes.append(
                f"Below {FAST_INTERVAL_WARNING_MS:g} ms the operating system, not this app, "
                "sets the real click rate -- the achieved rate may be lower than requested."
            )
        if (
            self.repeat.until_stopped
            and self.safety.countdown_seconds == 0
            and not self.safety.corner_failsafe
        ):
            notes.append(
                "No countdown, no click limit and no corner failsafe: the panic key is "
                "the only way to stop this."
            )
        return notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "action": self.action.value,
            "interval": self.interval.to_dict(),
            "click": self.click.to_dict(),
            "key": self.key.to_dict(),
            "repeat": self.repeat.to_dict(),
            "target": self.target.to_dict(),
            "safety": self.safety.to_dict(),
            "hotkeys": self.hotkeys.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        """Build a profile from JSON-ish data, tolerating missing keys.

        Unknown ``schema_version`` values are accepted rather than rejected:
        every field falls back to its default, so a newer profile degrades
        instead of failing to load.
        """
        return cls(
            name=str(data.get("name", "Default")),
            action=coerce_enum(ActionType, data.get("action"), ActionType.CLICK),
            interval=IntervalConfig.from_dict(data.get("interval", {})),
            click=ClickConfig.from_dict(data.get("click", {})),
            key=KeyConfig.from_dict(data.get("key", {})),
            repeat=RepeatConfig.from_dict(data.get("repeat", {})),
            target=TargetConfig.from_dict(data.get("target", {})),
            safety=SafetyConfig.from_dict(data.get("safety", {})),
            hotkeys=HotkeyConfig.from_dict(data.get("hotkeys", {})),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, raw: str) -> Profile:
        return cls.from_dict(json.loads(raw))
