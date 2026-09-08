"""Entry point for the packaged app.

PyInstaller runs its entry script as a top-level module, not as part of a
package, so pointing it at ``autoclicker/__main__.py`` breaks every relative
import in there -- and, worse, silently: the analyser cannot resolve
``from .ui.app import run`` either, so PySide6 and pynput never make it into
the bundle at all. The app then builds cleanly and dies on launch.

This launcher exists purely to give the frozen app an absolute import to start
from. Running from source still goes through ``python -m autoclicker``.
"""

from __future__ import annotations

import sys

from autoclicker.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
