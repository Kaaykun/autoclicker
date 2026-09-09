"""A check that a packaged build is actually complete.

The failure this exists to catch is specific and has happened: PyInstaller's
static analysis misses an import, the build goes green, the zip uploads, and
the app dies on the user's machine at launch. Every one of those bugs was
invisible to the unit tests, which run against the source tree where the
imports obviously resolve.

So this runs *inside the frozen binary* and touches each thing the bundle has
to carry: the GUI toolkit and a Qt platform plugin, the input library and its
platform backend, the bundled resource files, and one real pass of the engine.
It deliberately does not build the main window -- that would register global
hotkeys, which on macOS means an event tap the CI runner has no permission for
and which aborts the process rather than raising.

Run it with ``Autoclicker --self-test`` (or ``python -m autoclicker
--self-test``). Exit status 0 means the build is sound.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import Callable


def _qt() -> None:
    """Start Qt far enough to prove the platform plugin shipped."""
    _needs_qt()

    # Offscreen unless the caller has already chosen: CI runners have no
    # usable display, and this must never pop a window at the user.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    label = QLabel("self test")
    label.show()
    app.processEvents()
    label.close()


def _resources() -> None:
    """The artwork lives in datas=, a separate bundling path from the code.

    ``app_icon()`` alone would not catch a missing file: it quietly falls back
    to a drawn placeholder, which is right for the app and useless as a check.
    So ask whether the real artwork is on disk, then load it.
    """
    _needs_qt()

    from .ui.icons import app_icon, has_custom_artwork, tray_icon

    if not has_custom_artwork():
        raise RuntimeError("the app artwork is missing from the bundle")
    for name, icon in (("app", app_icon()), ("tray", tray_icon(False))):
        if icon.isNull():
            raise RuntimeError(f"the {name} icon did not load from the bundle")


class Skipped(Exception):
    """This check cannot say anything useful on this machine."""


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _needs_qt() -> None:
    """A missing PySide6 is a build failure only in a build.

    Run from a source checkout it usually means the GUI extra was not
    installed, which is a supported way to use the CLI. Inside the frozen app
    it is exactly the bug this module exists to catch.
    """
    try:
        # QtWidgets, not PySide6: the package can import while its shared
        # libraries are missing, and that only shows up on a real submodule.
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as exc:
        if _frozen():
            raise
        raise Skipped(f"PySide6 is not usable here ({exc})") from exc


def _input_backend() -> None:
    """pynput imports its OS backend dynamically, so PyInstaller cannot see it.

    Importing the module is the whole check. Constructing a controller would
    need Accessibility permission, which no CI runner grants.
    """
    try:
        import pynput.keyboard  # noqa: F401
        import pynput.mouse  # noqa: F401
    except ImportError as exc:
        # On Linux pynput needs a live X display and refuses to import without
        # one. That says nothing about whether the module was bundled, so it is
        # not a build failure -- and the shipped builds are macOS and Windows,
        # where this stays strict.
        if sys.platform.startswith("linux"):
            raise Skipped(f"no display on this Linux host ({exc})") from exc
        raise


def _engine() -> None:
    """One real run, against the fake backend, start to finish."""
    import threading

    from .core.backends import FakeBackend
    from .core.config import IntervalConfig, Profile, RepeatConfig
    from .core.engine import ClickEngine, EngineCallbacks

    done = threading.Event()
    backend = FakeBackend()
    engine = ClickEngine(
        backend,
        EngineCallbacks(on_finished=lambda reason, detail: done.set()),
    )
    profile = Profile(
        interval=IntervalConfig(seconds=0, millis=10),
        repeat=RepeatConfig(until_stopped=False, count=3),
    )
    problems = profile.validate()
    if problems:
        raise RuntimeError(f"the built-in profile is invalid: {problems}")

    backend.prepare()
    engine.start(profile)
    if not done.wait(10):
        engine.stop()
        raise RuntimeError("the engine never finished")
    if len(backend.clicks) != 3:
        raise RuntimeError(f"expected 3 clicks, got {len(backend.clicks)}")


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("input backend", _input_backend),
    ("engine", _engine),
    ("qt", _qt),
    ("resources", _resources),
]


def run() -> int:
    """Run every check, report, and return a shell exit status.

    A windowed build on Windows has no console attached, so ``print`` goes
    nowhere and a red CI job would say only "exit 1". Set
    ``AUTOCLICKER_SELFTEST_LOG`` to a path and the same report is written
    there as well.
    """
    from . import __version__

    lines = [
        f"Autoclicker {__version__}",
        f"frozen: {getattr(sys, 'frozen', False)}  python: {sys.version.split()[0]}",
    ]

    failed = 0
    for name, check in CHECKS:
        try:
            check()
        except Skipped as reason:
            lines.append(f"skip  {name}: {reason}")
        except Exception:
            failed += 1
            lines.append(f"FAIL  {name}")
            lines.append(traceback.format_exc().rstrip())
        else:
            lines.append(f"ok    {name}")

    lines.append("self-test failed" if failed else "self-test passed")
    report = "\n".join(lines)

    try:
        print(report, flush=True)
    except Exception:  # no console on a windowed Windows build
        pass

    log = os.environ.get("AUTOCLICKER_SELFTEST_LOG")
    if log:
        try:
            with open(log, "w", encoding="utf-8") as handle:
                handle.write(report + "\n")
        except OSError:
            pass

    return 1 if failed else 0
