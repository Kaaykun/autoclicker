"""Entry point: ``python -m autoclicker``.

Opens the window by default. ``--cli`` (and any CLI flag) runs headless, which
is also the automatic fallback if PySide6 is not installed.
"""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]

    if "--cli" in argv:
        from .cli import main as cli_main

        return cli_main([arg for arg in argv if arg != "--cli"])

    try:
        from .ui.app import run
    except ImportError as exc:
        print(f"The GUI needs PySide6, which is not installed ({exc}).", file=sys.stderr)
        print("Install it with: pip install PySide6", file=sys.stderr)
        print("Running headless instead; pass --cli to skip this message.\n", file=sys.stderr)
        from .cli import main as cli_main

        return cli_main(argv)

    if argv:
        print(f"Ignoring arguments {argv}; pass --cli to use the command line.", file=sys.stderr)
    return run()


if __name__ == "__main__":
    sys.exit(main())
