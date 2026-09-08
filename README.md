# Autoclicker

A cross-platform (macOS + Windows) auto-clicker with a PySide6 GUI: precise
intervals down to the millisecond, fixed or follow-cursor targeting, global
hotkeys, randomised jitter, saved profiles, and proper safety controls.

> **Status:** early development. See [PLAN.md](PLAN.md) for the full design and
> milestones. The package currently contains module stubs — M1 is the first
> working engine.

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
- **Profiles** saved as JSON and restored on launch

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
python -m autoclicker
```

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
