# Autoclicker

A cross-platform (macOS + Windows) auto-clicker with a PySide6 GUI: precise
intervals down to the millisecond, fixed or follow-cursor targeting, global
hotkeys, randomised jitter, saved profiles, and proper safety controls.

> **Status:** feature-complete for daily use (milestones M0–M6). Packaged
> `.app` / `.exe` builds are still to come — see [PLAN.md](PLAN.md) for the
> roadmap.

## Features

- **Interval** in hours / minutes / seconds / milliseconds (default: 1 second)
- **Mouse button**: left, right, middle
- **Click type**: single, double or triple, with a tunable inter-click gap
- **Repeat** a fixed number of times, or until stopped
- **Targeting**: follow the cursor, or lock an (X, Y) point picked directly off
  the screen with a crosshair overlay
- **Click sequences**: an ordered list of points, each with its own button,
  click type and delay — shown in seconds or milliseconds, your choice
- **Record a sequence**: press Record (or `F9`), click your way through a task,
  press it again. Your clicks, buttons and pauses come back as a sequence you
  can loop forever
- **Randomised jitter** on both interval and position, so runs aren't
  machine-perfect
- **Global hotkeys** for start/stop, panic-stop and position capture, all
  remappable
- **Safety**: panic hotkey, corner failsafe, start countdown
- **Profiles** saved as JSON, listed in the window, and restored on launch

## Requirements

- Python 3.10 or newer (the repo pins 3.12 in `.python-version`)
- macOS 13+ or Windows 10+ (PySide6 6.11 ships macOS wheels built for 13 and newer)

## Install

This project is managed with [uv](https://docs.astral.sh/uv/). One command
creates the virtualenv, fetches the right Python if you do not have it, and
installs the locked dependency set:

```bash
git clone git@github.com:Kaaykun/autoclicker.git
cd autoclicker
uv sync
```

`uv.lock` is committed, so everyone — and CI — gets byte-identical
dependencies. After changing anything in `pyproject.toml`, run `uv lock` and
commit the result; CI syncs with `--locked` and will fail if the two disagree.

<details>
<summary>Without uv</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e . -r requirements-dev.txt
```

You lose the lockfile guarantee, but nothing else.
</details>

## Run

```bash
uv run autoclicker                    # the window
uv run autoclicker --cli              # headless, for scripting
```

`uv run` syncs first, so it is always working against the locked dependencies —
no activating anything. If you would rather activate the venv, `python -m
autoclicker` does the same thing.

Headless mode takes the same settings as flags, and `--dry-run` reports what it
would click without touching the pointer:

```bash
uv run autoclicker --cli --ms 250 -n 20 --button right --dry-run
uv run autoclicker --cli --seconds 1 --at 840 500 --jitter-percent 15
```

### Default hotkeys

| Key | Does |
|---|---|
| `F6` | Start / stop |
| `F7` | Capture the pointer's current position as the target |
| `F8` | Panic stop — always active while running |
| `F9` | Start / stop recording a click sequence |

All four are remappable — the **Hotkeys…** button in the Safety panel, or
**Settings → Hotkeys** in the menu bar (which on macOS lives at the top of the
screen, not in the window). The pointer hitting any
screen corner also stops a run, which is the escape hatch when the clicker is
eating the click you are trying to land on the Stop button.

## Permissions

### macOS

The app needs two permissions, granted to whichever process hosts Python — your
terminal or IDE during development, or `Autoclicker.app` once bundled:

- **System Settings → Privacy & Security → Accessibility** — to send clicks
- **System Settings → Privacy & Security → Input Monitoring** — for global hotkeys

Without them the app starts but neither clicks nor responds to hotkeys. It will
tell you so and offer to open the right settings pane.

### Windows

Nothing special for normal use. One exception: a non-elevated process cannot
send input to a window running as administrator — to click into an elevated
app, run the autoclicker as administrator too.

## Recording a sequence

1. Choose **Sequence of points** in the Target panel.
2. Press **Record…** or `F9`.
3. Click through whatever you want repeated. Buttons, double-clicks and the
   pauses between them are all captured; clicks on the autoclicker window
   itself are ignored.
4. Press `F9` again to stop. The clicks arrive as points, appended to whatever
   was already in the list.
5. Set Repeat to **Until stopped** and press Start to loop it forever.

Untick **Keep recorded timing** to discard your pauses and drive every step
from the interval instead.

## Where settings live

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/Autoclicker/` |
| Windows | `%APPDATA%\Autoclicker\` |

Profiles are plain JSON in a `profiles/` subfolder — editable by hand, and a
corrupt one costs you that profile rather than the app.

## Development

```bash
uv run ruff check .
uv run pytest
```

Adding a dependency:

```bash
uv add somepackage           # runtime
uv add --dev somepackage     # tooling
```

Both update `pyproject.toml` and `uv.lock` together. Commit both.

The `core/` package holds no Qt imports and is fully testable headless; the
click backend is injectable, so the test suite never fires a real click.

## A note on use

Auto-clickers are ordinary automation tools, but many games and online services
forbid them in their terms of service. Where you point this is your call.

## License

MIT — see [LICENSE](LICENSE).
