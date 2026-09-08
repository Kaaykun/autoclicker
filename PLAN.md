# Autoclicker — Project Plan

A cross-platform (macOS + Windows) desktop auto-clicker written in Python with a
PySide6 GUI.

Status: planning / scaffolding. Nothing in `autoclicker/` is implemented yet
beyond module stubs.

---

## 1. Goals

| # | Requirement | Notes |
|---|---|---|
| G1 | Click interval settable in hours, minutes, seconds, milliseconds | Combined into a single total-ms value internally |
| G2 | Mouse button: left / right / middle | |
| G3 | Click type: single / double (triple as a bonus) | Configurable double-click gap |
| G4 | Repeat N times **or** repeat until stopped | |
| G5 | Fixed target: pick a point on screen, confirm with a click, lock X/Y | Full-screen crosshair overlay |
| G6 | Follow-cursor mode: click wherever the pointer currently is | |
| G7 | Global start/stop hotkey, remappable from a settings dialog | Works while the app is unfocused |
| G8 | Runs on macOS and Windows from the same source tree | Python 3.10+ |
| G9 | Private GitHub repository | |

### Agreed extras

| # | Extra | Why |
|---|---|---|
| E1 | **Randomised jitter** — ±% or ±ms on the interval, ±N px on the position | Machine-perfect timing is both detectable and unrealistic; jitter makes runs look human |
| E2 | **Profiles + click sequences** — named JSON configs; optional ordered list of points (A → wait → B → wait → C, looped) | Reuse setups; automate multi-point workflows |
| E3 | **Safety: panic hotkey + corner failsafe + start countdown** | A runaway clicker that steals every click is genuinely hard to stop; this is the single most important feature in the app |

### Deferred (nice-to-have, tracked as later milestones)

Session limits (stop after N minutes), live stats counter, system-tray icon,
always-on-top mini mode, keyboard-key spam mode, drag support, sound feedback,
scheduled start.

---

## 2. Stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.10+ | Match/`dataclass` features, broad wheel availability |
| GUI | **PySide6** (Qt 6, LGPL) | Native-feeling on both OSes, real dark mode, a proper full-screen transparent overlay for the point picker, and `Signal`/`Slot` gives thread-safe UI updates for free |
| Input | **pynput** | Cross-platform mouse control *and* a global hotkey listener in one dependency. Lower latency than PyAutoGUI (no Pillow / screenshot machinery), and PyAutoGUI has no global hotkey support at all |
| Config | stdlib `json` + `dataclasses` | Human-readable, diffable, no dependency |
| Tests | pytest | Pure-logic only; the click backend is injectable so CI never fires a real click |
| Lint/format | ruff | One tool, fast |
| Packaging (later) | PyInstaller | `.app` on macOS, `.exe` on Windows, built by a GitHub Actions matrix on tag |

Runtime dependencies stay deliberately small: `PySide6`, `pynput`. That's it.

---

## 3. Architecture

```
autoclicker/
├── __main__.py              # entry point: python -m autoclicker
├── core/                    # zero Qt imports — importable and testable headless
│   ├── config.py            # dataclasses + JSON (de)serialisation
│   ├── engine.py            # ClickEngine: the worker loop
│   ├── backends.py          # ClickBackend protocol; PynputBackend, FakeBackend
│   ├── scheduler.py         # drift-free deadline timing + jitter
│   ├── hotkeys.py           # global hotkey registration, chord recording
│   ├── profiles.py          # profile store on disk
│   └── platform_checks.py   # macOS permission detection & guidance
├── ui/                      # all Qt lives here
│   ├── main_window.py
│   ├── interval_widget.py   # h / m / s / ms spinboxes
│   ├── options_widget.py    # button, click type, repeat
│   ├── target_widget.py     # follow-cursor vs fixed point vs sequence
│   ├── picker_overlay.py    # full-screen crosshair picker
│   ├── hotkey_dialog.py     # remap start/stop and panic
│   ├── profile_bar.py
│   └── theme.py
└── resources/
```

**Layering rule:** `core/` must never import Qt, and `ui/` must never do
timing-sensitive work. That split is what makes the engine testable and keeps
the GUI responsive.

### Threading model

Three threads, one direction of control:

- **Main / GUI thread** — Qt event loop. Owns all widgets. Never blocks.
- **Engine thread** (`QThread`) — runs the click loop. Emits Qt signals
  (`clicked`, `finished`, `error`) which Qt queues back onto the GUI thread.
  Never touches a widget directly.
- **Listener thread** — pynput's own listener thread for global hotkeys and the
  corner failsafe. Emits signals too; does no work inline.

Start/stop is a `threading.Event`, checked at the top of every loop iteration
and inside every sleep, so stopping is immediate even on a 3-hour interval.

### Timing

Naïve `time.sleep(interval)` in a loop drifts: every iteration adds the sleep
overshoot plus the click duration. Instead the scheduler works on absolute
deadlines from a monotonic clock:

```
deadline = perf_counter()
while running:
    click()
    deadline += interval_seconds()      # jittered per iteration
    sleep_until(deadline)               # coarse sleep, then a short spin
```

`sleep_until` sleeps to ~2 ms before the deadline and busy-waits the remainder,
which gets us reliably inside ~1 ms without burning a core. Below roughly 5 ms
the OS event pipeline, not Python, becomes the limit — the UI will say so
rather than silently lying about the rate.

---

## 4. Feature detail

### 4.1 Interval

Four spinboxes (h / m / s / ms) collapse to `total_ms`. Minimum 1 ms; a warning
label appears below 10 ms. Jitter (E1) is applied per-iteration:

- mode: `off` | `uniform ±%` | `uniform ±ms`
- the jittered interval is clamped to ≥ 1 ms
- optional fixed RNG seed for reproducible runs

### 4.2 Click options

- Button: left / right / middle
- Type: single / double / triple, with a configurable inter-click gap
  (default 40 ms — the OS decides what counts as a double-click, so this is
  tunable rather than fixed)
- Optional hold duration: press, wait N ms, release
- Repeat: fixed count, or "until stopped"

### 4.3 Targeting

Three modes:

1. **Follow cursor** — click at whatever position the pointer currently holds.
2. **Fixed point** — a locked (X, Y). Set by:
   - the **picker overlay**: a borderless, translucent, always-on-top window
     spanning the whole virtual desktop, showing a crosshair and live
     coordinates; left-click confirms, `Esc` cancels;
   - manual entry in two spinboxes;
   - a **capture hotkey** that grabs the current pointer position without an
     overlay (a fallback for macOS setups where a click-through overlay
     misbehaves).
3. **Sequence** (E2) — an ordered table of points, each with its own
   `x, y, button, click_type, delay_after_ms`; looped for N passes or until
   stopped.

Coordinates are stored in the **virtual-desktop space** (all monitors combined),
matching what both Qt and pynput use. Negative coordinates are legal on
multi-monitor setups where a second display sits left of or above the primary —
so the point spinboxes must not clamp at 0. On macOS Retina, Qt reports logical
points and Quartz takes logical points, so no DPI scaling should be needed;
this gets verified empirically in M4 on Jaris's machine and, if it turns out
otherwise, gets a per-platform scale factor.

### 4.4 Hotkeys

- **Start/Stop toggle** — default `F6` (the de-facto autoclicker convention)
- **Panic / force stop** — default `F8`; always active while the engine runs and
  cannot be disabled
- **Capture cursor position** — default `F7`
- Remapping happens in a dialog with a "Press a key combination…" recording
  mode that captures the next chord via pynput and shows it back.
- Conflicts with existing system shortcuts are checked against a small known
  list and warned about rather than silently swallowed. On macOS, F-keys may
  require `Fn` unless "Use F1, F2 etc. as standard function keys" is enabled —
  the dialog says so.

### 4.5 Safety (E3)

- **Panic hotkey**, above.
- **Corner failsafe** (optional, on by default): a mouse listener aborts the run
  if the pointer is slammed into any screen corner (within a 10 px box). This is
  the escape hatch when the clicker itself is stealing your clicks.
- **Start countdown** (default 3 s, configurable, can be 0) before the first
  click, so there's time to move the pointer into place.
- **Auto-stop on error** — any backend exception stops the run and surfaces in
  the UI rather than spinning silently.

### 4.6 Profiles (E2)

Versioned JSON (`schema_version` field so future changes can migrate) in the
platform config directory:

- macOS: `~/Library/Application Support/Autoclicker/profiles/`
- Windows: `%APPDATA%\Autoclicker\profiles\`

Save / load / rename / duplicate / delete from a profile bar at the top of the
window. The last-used profile is restored on launch.

---

## 5. Platform notes

### macOS

The app needs two permissions, granted to **the process that hosts Python** —
during development that's Terminal/iTerm/your IDE, and once bundled it's
`Autoclicker.app`:

- **Accessibility** — to post synthetic clicks
- **Input Monitoring** — to observe global hotkeys

`platform_checks.py` detects the missing grant (a pynput listener that starts
and immediately dies is the tell) and shows a dialog with a button that opens
the right pane directly:

```
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

Two gotchas worth writing into the README: re-signing or moving the app resets
its grant, and macOS periodically re-prompts for these permissions.

### Windows

No special permissions for normal use. But **UIPI** means a non-elevated process
cannot send input to an elevated (admin) window — if the target is running as
administrator, the autoclicker must be too. Documented rather than worked
around.

---

## 6. Testing

Pure-logic pytest suite, no real clicks:

- interval math (h/m/s/ms → ms, boundary values, minimum clamp)
- jitter stays inside its declared bounds over N samples; never < 1 ms
- scheduler drift: over 500 simulated iterations, accumulated error stays flat
- profile JSON round-trip, and loading an unknown `schema_version`
- hotkey chord parse/format round-trip
- engine behaviour against `FakeBackend`: exact click count for fixed-repeat,
  stop-event responsiveness, sequence ordering

CI (GitHub Actions): ruff + pytest on ubuntu / macos / windows. GUI modules are
import-guarded so headless CI doesn't need a display.

Manual checklist (in `docs/manual-testing.md`) covers the things a machine
can't check: overlay picker accuracy on each monitor, hotkeys while another app
is focused, panic key under a 1 ms click storm.

---

## 7. Milestones

| M | Deliverable | Definition of done |
|---|---|---|
| **M0** ✅ | Plan + scaffold + private repo | This document, module stubs, README, CI skeleton, first push |
| **M1** ✅ | Core engine | `config`, `scheduler`, `backends`, `engine` + tests green. Drivable from a tiny CLI, no GUI |
| **M2** ✅ | Basic GUI | Interval, click options, repeat, Start/Stop button. Actually clicks |
| **M3** ✅ | Hotkeys + safety | Global toggle + panic + countdown + corner failsafe; macOS permission dialog |
| **M4** ✅ | Targeting | Picker overlay, fixed point, capture hotkey; multi-monitor verified |
| **M5** ✅ | Profiles + jitter | Save/load, jitter controls wired |
| **M6** ✅ | Sequences | Point table, ordered playback |
| **M7** | Polish | Dark theme, always-on-top, live stats, tray icon |
| **M8** | Packaging | PyInstaller specs, tagged release workflow producing `.app` + `.exe` |

M0–M6 are done. M7 (polish) and M8 (packaging) remain; M8 in particular needs
a token with `workflow` scope, since a release workflow is a workflow file.

The two risks below marked as needing real hardware (Retina coordinates, the
overlay on macOS Spaces) are still unverified — they cannot be checked from
CI or a headless runner, only by using the app.

---

## 8. Risks and open questions

1. **macOS permission friction** — the single most likely source of "it doesn't
   work". Mitigated by explicit detection and a one-click path to the settings
   pane. Unsigned builds later on will also need a right-click → Open to get
   past Gatekeeper.
2. **Retina / DPI coordinate mismatch** — believed to be a non-issue (both Qt
   and Quartz use logical points) but must be verified on real hardware in M4.
3. **Very fast intervals** — below ~5 ms the bottleneck is the OS, not us. The
   UI reports the *achieved* rate so the number on screen is honest.
4. **Overlay click-through on macOS** — a full-screen translucent window that
   captures one click can behave oddly with Spaces/full-screen apps. The
   capture-hotkey fallback exists precisely for this.
5. **Sub-millisecond scheduling on Windows** — default timer resolution is
   ~15.6 ms; if this bites, `timeBeginPeriod(1)` via ctypes is the fix.

---

## 9. A note on use

Auto-clickers are ordinary automation tools, but plenty of games and online
services forbid them in their terms of service, and some detect them. This is a
personal-productivity tool; where you point it is your call, and the jitter
feature exists for realism in testing, not for evading enforcement.
