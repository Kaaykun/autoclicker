# Autoclicker

A cross-platform (macOS + Windows) auto-clicker with a PySide6 GUI: precise
intervals down to the millisecond, fixed or follow-cursor targeting, global
hotkeys, randomised jitter, saved profiles, and proper safety controls.

> **Status:** feature-complete for daily use (milestones M0–M6). Packaged
> `.app` / `.exe` builds are still to come — see [PLAN.md](PLAN.md) for the
> roadmap.

## Features

- **Interval** in hours / minutes / seconds / milliseconds
- **Mouse button**: left, right, middle
- **Click type**: single, double or triple, with a tunable inter-click gap
- **Repeat** a fixed number of times, or until stopped
- **Targeting**: follow the cursor, or lock an (X, Y) point picked directly off
  the screen with a crosshair overlay
- **Click sequences**: an ordered list of points, each with its own delay
- **Randomised jitter** on both interval and position, so runs aren't
  machine-perfect
- **Global hotkeys** for start/stop, panic-stop and position capture, all
  remappable
- **Safety**: panic hotkey, corner failsafe, start countdown
- **Profiles** saved as JSON, listed in the window, and restored on launch

## Requirements

- Python 3.10 or newer
- macOS 12+ or Windows 10+

## Install (development)

```bash
git clone git@github.com:<your-account>/autoclicker.git
cd autoclicker
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Run

```bash
python -m autoclicker          # the window
python -m autoclicker --cli    # headless, for scripting
```

Headless mode takes the same settings as flags, and `--dry-run` reports what it
would click without touching the pointer:

```bash
python -m autoclicker --cli --ms 250 -n 20 --button right --dry-run
python -m autoclicker --cli --seconds 1 --at 840 500 --jitter-percent 15
```

### Default hotkeys

| Key | Does |
|---|---|
| `F6` | Start / stop |
| `F7` | Capture the pointer's current position as the target |
| `F8` | Panic stop — always active while running |

All three are remappable under **Settings → Hotkeys**. The pointer hitting any
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

## Where settings live

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/Autoclicker/` |
| Windows | `%APPDATA%\Autoclicker\` |

Profiles are plain JSON in a `profiles/` subfolder — editable by hand, and a
corrupt one costs you that profile rather than the app.

## Development

```bash
ruff check .
pytest
```

The `core/` package holds no Qt imports and is fully testable headless; the
click backend is injectable, so the test suite never fires a real click.

## A note on use

Auto-clickers are ordinary automation tools, but many games and online services
forbid them in their terms of service. Where you point this is your call.

## License

MIT — see [LICENSE](LICENSE).
