"""Entry point: ``python -m autoclicker``.

The GUI arrives in M2; until then this hands straight off to the CLI. Once the
window layer exists, ``--cli`` will pick the headless path explicitly.
"""

from __future__ import annotations

import sys


def main() -> int:
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
