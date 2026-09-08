"""A headless driver for the engine.

Useful for scripting, for smoke-testing the core on a machine with no GUI, and
for checking permissions before the window layer exists. ``--dry-run`` swaps in
the fake backend so you can watch the timing without the pointer moving.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from .core.backends import FakeBackend, PynputBackend, settle_pointer
from .core.config import (
    DEFAULT_INTERVAL_SECONDS,
    ClickConfig,
    ClickType,
    IntervalConfig,
    JitterMode,
    MouseButton,
    Profile,
    RepeatConfig,
    SafetyConfig,
    TargetConfig,
    TargetMode,
)
from .core.engine import ClickEngine, EngineCallbacks, StopReason


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoclicker",
        description="Click on a timer, from the command line.",
    )

    timing = parser.add_argument_group("interval")
    # All four default to unset rather than 0, so that passing one of them does
    # not silently add the 1-second default on top: --ms 250 means 250 ms.
    timing.add_argument("--hours", type=int)
    timing.add_argument("--minutes", type=int)
    timing.add_argument("--seconds", type=int)
    timing.add_argument("--ms", type=int,
                        help="milliseconds (the interval defaults to 1 second)")
    jitter = timing.add_mutually_exclusive_group()
    jitter.add_argument("--jitter-percent", type=float, metavar="PCT")
    jitter.add_argument("--jitter-ms", type=float, metavar="MS")

    click = parser.add_argument_group("click")
    click.add_argument("--button", choices=[b.value for b in MouseButton], default="left")
    click.add_argument("--type", dest="click_type",
                       choices=[c.value for c in ClickType], default="single")
    click.add_argument("--hold-ms", type=float, default=0.0)

    repeat = parser.add_argument_group("repeat")
    repeat.add_argument("-n", "--repeat", type=int, metavar="N",
                        help="stop after N clicks (N passes in sequence mode)")

    target = parser.add_argument_group("target")
    target.add_argument("--at", nargs=2, type=int, metavar=("X", "Y"),
                        help="click a fixed point instead of following the cursor")
    target.add_argument("--pos-jitter", type=int, default=0, metavar="PX")

    parser.add_argument("--countdown", type=float, default=0.0,
                        help="seconds before the first click (default: 0)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be clicked without touching the pointer")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument(
        "--check-pointer",
        action="store_true",
        help="measure how long pointer moves take to actually land, then exit",
    )
    return parser


def profile_from_args(args: argparse.Namespace) -> Profile:
    if args.jitter_percent is not None:
        jitter_mode, jitter_amount = JitterMode.PERCENT, args.jitter_percent
    elif args.jitter_ms is not None:
        jitter_mode, jitter_amount = JitterMode.MILLIS, args.jitter_ms
    else:
        jitter_mode, jitter_amount = JitterMode.OFF, 0.0

    if args.at:
        target = TargetConfig(
            mode=TargetMode.FIXED_POINT,
            x=args.at[0],
            y=args.at[1],
            position_jitter_px=args.pos_jitter,
        )
    else:
        target = TargetConfig(
            mode=TargetMode.FOLLOW_CURSOR,
            position_jitter_px=args.pos_jitter,
        )

    components = {
        name: value
        for name, value in (
            ("hours", args.hours),
            ("minutes", args.minutes),
            ("seconds", args.seconds),
            ("millis", args.ms),
        )
        if value is not None
    }
    if not components:
        components = {"seconds": DEFAULT_INTERVAL_SECONDS}

    return Profile(
        name="cli",
        interval=IntervalConfig(
            hours=components.get("hours", 0),
            minutes=components.get("minutes", 0),
            seconds=components.get("seconds", 0),
            millis=components.get("millis", 0),
            jitter_mode=jitter_mode,
            jitter_amount=jitter_amount,
        ),
        click=ClickConfig(
            button=MouseButton(args.button),
            click_type=ClickType(args.click_type),
            hold_ms=args.hold_ms,
        ),
        repeat=RepeatConfig(until_stopped=args.repeat is None, count=args.repeat or 1),
        target=target,
        safety=SafetyConfig(countdown_seconds=args.countdown, corner_failsafe=False),
    )


def check_pointer() -> int:
    """Report how long the system takes to apply a pointer move.

    Moving the pointer posts an event rather than applying it, so a click sent
    immediately afterwards can land at the previous position. Everything the
    app does about that depends on the readback agreeing with what was written,
    which this checks directly.

    The pointer is put back where it started.
    """
    backend = PynputBackend(settle=False)
    try:
        origin = backend.position()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        print(f"error: could not read the pointer position: {exc}", file=sys.stderr)
        return 1

    print(f"Pointer is at X {origin[0]}, Y {origin[1]}. Moving it a few times…\n")
    targets = [
        (origin[0] + 60, origin[1]),
        (origin[0] + 60, origin[1] + 60),
        (origin[0], origin[1] + 60),
        origin,
    ]

    worst = 0.0
    failures = 0
    for x, y in targets:
        backend.move_to(x, y)
        started = time.perf_counter()
        landed = settle_pointer((x, y), backend.position, timeout_s=0.25)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        worst = max(worst, elapsed_ms)
        if landed:
            print(f"  ({x}, {y})  landed after {elapsed_ms:5.1f} ms")
        else:
            failures += 1
            reported = backend.position()
            print(f"  ({x}, {y})  NEVER landed — readback says {reported}")

    print()
    if failures:
        print(
            "The readback never agreed with what was written. That is a "
            "coordinate-space mismatch rather than lag, and clicks at a fixed "
            "point will land in the wrong place. Worth reporting."
        )
        return 1
    if worst < 1.0:
        print("Moves apply immediately here. Clicks land where they are aimed.")
    else:
        print(
            f"Moves take up to {worst:.1f} ms to apply. Without waiting for that, a "
            "click sent straight after a move would land at the previous position — "
            "which is exactly the bug the post-move settle exists to prevent."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_pointer:
        return check_pointer()
    profile = profile_from_args(args)

    problems = profile.validate()
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 2
    for warning in profile.warnings():
        print(f"note: {warning}", file=sys.stderr)

    finished = threading.Event()
    outcome: dict[str, object] = {}

    def on_finished(reason: StopReason, detail: str) -> None:
        outcome["reason"] = reason
        outcome["detail"] = detail
        finished.set()

    def on_countdown(remaining: float) -> None:
        if not args.quiet:
            print(f"\rStarting in {remaining:4.1f}s ...", end="", flush=True)

    def on_click(total: int, x: int, y: int) -> None:
        if not args.quiet:
            print(f"\rclicks: {total}  at ({x}, {y})   ", end="", flush=True)

    backend = FakeBackend() if args.dry_run else PynputBackend()
    engine = ClickEngine(
        backend,
        EngineCallbacks(
            on_click=on_click,
            on_countdown=on_countdown,
            on_finished=on_finished,
            on_error=lambda message: print(f"\nerror: {message}", file=sys.stderr),
        ),
    )

    print("Ctrl-C to stop." if args.repeat is None else f"Clicking {args.repeat} times.")
    engine.start(profile)
    try:
        while not finished.wait(0.2):
            pass
    except KeyboardInterrupt:
        engine.stop()
        finished.wait(2.0)

    print()
    reason = outcome.get("reason")
    print(f"{reason.value if isinstance(reason, StopReason) else 'stopped'}: "
          f"{outcome.get('detail', '')}")
    return 1 if reason is StopReason.ERROR else 0
