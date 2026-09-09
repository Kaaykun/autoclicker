"""Smoke tests: the package imports and the core layer stays Qt-free."""

from __future__ import annotations

import pathlib
import re

import autoclicker


def test_version() -> None:
    assert autoclicker.__version__


def test_the_version_matches_pyproject() -> None:
    """Two files carry the version, and they drift.

    (The third place is uv.lock, which records the project's own version --
    ``uv lock`` has to be re-run after a bump or CI's ``--locked`` sync fails.
    A test cannot check that without shelling out to uv, so it is written down
    in the release checklist in the README instead.)
    """
    root = pathlib.Path(autoclicker.__file__).parent.parent
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert match, "no version found in pyproject.toml"
    assert match.group(1) == autoclicker.__version__


def test_core_has_no_qt_imports() -> None:
    core = pathlib.Path(autoclicker.__file__).parent / "core"
    for path in core.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "PySide6" not in source, f"{path.name} imports Qt; core must stay GUI-free"
