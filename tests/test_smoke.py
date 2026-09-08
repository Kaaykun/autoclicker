"""Smoke tests: the package imports and the core layer stays Qt-free."""

from __future__ import annotations

import pathlib

import autoclicker


def test_version() -> None:
    assert autoclicker.__version__


def test_core_has_no_qt_imports() -> None:
    core = pathlib.Path(autoclicker.__file__).parent / "core"
    for path in core.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "PySide6" not in source, f"{path.name} imports Qt; core must stay GUI-free"
