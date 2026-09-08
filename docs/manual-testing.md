# Manual test checklist

Things CI can't verify. Run before tagging a release.

## Clicking
- [ ] Left / right / middle each register in a target app
- [ ] Double-click opens a folder / selects a word (the OS accepts the gap)
- [ ] Fixed repeat count fires exactly N clicks
- [ ] With the countdown at 0, starting from the button in follow-cursor mode:
      the first click lands on the Stop button, as expected. Start with the
      hotkey, or set a countdown, to click somewhere else
- [ ] "Until stopped" runs for 60 s without drift (compare counter vs wall clock)
- [ ] 1 ms interval: UI reports the achieved rate honestly, app stays responsive

## Targeting
- [ ] Picker overlay appears across all monitors
- [ ] Coordinates read back match where the click lands, on the primary display
- [ ] Same, on a secondary display positioned left of / above the primary
- [ ] Retina scaling: clicks land where the crosshair was, not at half/double offset
- [ ] Capture-position hotkey grabs the pointer without the overlay
- [ ] Follow-cursor mode tracks the pointer while running

## Sequences and recording
- [ ] Record captures clicks in order, with the right buttons
- [ ] A real double-click comes back as one Double point, not two Singles
- [ ] Clicking the autoclicker's own window during a recording is ignored
- [ ] Recorded pauses replay at roughly the speed they were performed
- [ ] "Keep recorded timing" off makes every step use the interval
- [ ] A recorded sequence loops cleanly on "Until stopped"
- [ ] Every point of a sequence lands where it should, the last one included
      (clicks landing one point behind means the post-move settle is not working;
      `--cli --check-pointer` reports the move latency directly)
- [ ] The wait column switches between seconds and milliseconds without
      changing the underlying values
- [ ] Typing "250 ms" into a seconds column is read as 250 ms

## Hotkeys
- [ ] Start/stop toggle works while another app is focused
- [ ] Panic hotkey stops a 1 ms click storm immediately
- [ ] Corner failsafe aborts the run
- [ ] Remapped hotkey persists across a restart
- [ ] The record hotkey starts and stops a recording
- [ ] The Hotkeys… button in the Safety panel opens the same dialog as the menu

## Platform
- [ ] macOS: permission dialog appears when Accessibility is not granted
- [ ] macOS: the "Open settings" button lands on the right pane
- [ ] Windows: clicks into a normal window; documented failure into an elevated one

## Menu bar / tray
- [ ] The tray icon appears, and its glyph is filled while running and hollow while idle
- [ ] Start and Stop from the tray menu work while the window is hidden
- [ ] With "Keep running when the window closes" on, closing hides the window
      and the hotkeys still work
- [ ] Quit from the tray menu actually exits
- [ ] The click counter shows a rate while running, and drops it when stopped

## Packaged build
- [ ] `uv run pyinstaller autoclicker.spec` produces a launchable app
- [ ] The app icon is the artwork, not the default Python icon — Dock, taskbar,
      window and Cmd-Tab
- [ ] On Windows the icon has no transparent corner notches against a taskbar
      highlight
- [ ] The packaged app can click and can register hotkeys (this is the one that
      catches a missing pynput backend in the bundle)
- [ ] Gatekeeper: right-click → Open works on the first launch
