"""Application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import apply_theme


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName("Autoclicker")
    app.setApplicationDisplayName("Autoclicker")
    apply_theme(app)

    window = MainWindow()
    window.show()
    return app.exec()
