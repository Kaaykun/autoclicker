# Artwork

Drop artwork here and the app picks it up on the next launch. Nothing in this
folder is required — the app draws a placeholder when a file is missing.

| File | Used for | Wanted |
|---|---|---|
| `icon.png` | Window, dock and taskbar icon; source for the packaged `.icns` / `.ico` | Square PNG, 1024×1024, transparent background |
| `tray.png` | Menu-bar / system-tray icon | Square PNG, 44×44, **black on transparent** |

`tray.png` is deliberately monochrome: macOS treats menu-bar icons as template
images, throwing away the colour and recolouring the alpha channel to suit a
light or dark menu bar. A colourful tray icon will come out as a silhouette.

Once `icon.png` is here, build the packaged icon sets with:

```bash
uv run python tools/make_icons.py
```
