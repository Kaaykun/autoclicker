# Autoclicker

A cross-platform (macOS + Windows) auto-clicker with a PySide6 GUI: precise
intervals down to the millisecond, fixed or follow-cursor targeting, global
hotkeys, randomised jitter, saved profiles, and proper safety controls.

> **Status:** complete. All milestones (M0–M8) are done — see
> [docs/PLAN.md](docs/PLAN.md) for the design and history.

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
- **Safety**: panic hotkey, corner failsafe, optional start countdown
- **Profiles** saved as JSON, listed in the window, and restored on launch
- **Menu-bar / tray icon** to start, stop and quit without the window, with an
  option to keep running when the window is closed
- **Live counter** showing the rate actually achieved, not the one requested

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

## Troubleshooting

**Clicks land in the wrong place, or the last point of a sequence looks
skipped.** Moving the pointer posts an event to the windowing system rather
than applying it there and then, so a click sent immediately afterwards can be
built at the *previous* position. In a sequence that shows up as every click
landing one point behind, which makes the final point look like it never
happened. The app waits for each move to actually land before clicking. To see
what your machine does:

```bash
uv run autoclicker --cli --check-pointer
```

It nudges the pointer a few times, reports how long each move took to apply,
and puts it back where it started.

## Building a standalone app

```bash
uv run python tools/make_icons.py        # once, or after changing the artwork
uv run pyinstaller autoclicker.spec
```

The result lands in `dist/` — `Autoclicker.app` on macOS, `Autoclicker/` with
`Autoclicker.exe` on Windows. Tag a commit (`git tag v0.1.0 && git push --tags`)
and GitHub Actions builds both and attaches them to a release.

**These builds are unsigned**, which has consequences worth knowing:

- **macOS** blocks the first launch. Right-click `Autoclicker.app` → **Open** →
  **Open**. Gatekeeper remembers the choice for that copy.
- macOS ties Accessibility and Input Monitoring to the specific binary, and an
  unsigned rebuild is a different binary. **Expect to re-grant both after every
  update.** Signing with a paid Apple Developer ID is what fixes this properly.
- **Windows** SmartScreen warns on first run: **More info** → **Run anyway**.

Running from source with `uv run autoclicker` avoids all of this, because the
permissions attach to your terminal instead and stay put.

### Icons

`autoclicker/resources/icon.png` is the master, 1024×1024. `tools/make_icons.py`
turns it into what each platform actually wants:

- **macOS** gets the rounded artwork inset onto Apple's 824-in-1024 grid, so it
  sits the same size as its neighbours in the Dock. macOS does not mask app
  icons, so the rounded corners have to be in the file.
- **Windows** gets a squared, full-bleed variant. Windows does not mask icons
  either and has no corner convention, so baked-in rounded corners show up as
  transparent notches against a taskbar highlight or an Explorer selection
  tint. The tool extends the background gradient outward into the corners
  rather than filling them flat, so the colours continue seamlessly.

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
click backend is injectable, so the test suite never fires a real click. The
GUI tests build real widgets against Qt's offscreen platform plugin, so they
need no display.

The Qt dependency is `PySide6-Essentials` rather than the full `PySide6`: this
app imports only QtCore, QtGui and QtWidgets, and the Addons half is several
hundred megabytes that would otherwise end up inside every packaged build.

## A note on use

Auto-clickers are ordinary automation tools, but many games and online services
forbid them in their terms of service. Where you point this is your call.

## License

MIT — see [LICENSE](LICENSE).
