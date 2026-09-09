# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for macOS and Windows.

    uv run pyinstaller autoclicker.spec

Icons come from build/icons/, which `tools/make_icons.py` produces from
autoclicker/resources/icon.png. The build works without them; you just get the
default Python icon.
"""

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
ICONS = ROOT / "build" / "icons"

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")

version = re.search(
    r'__version__ = "([^"]+)"',
    (ROOT / "autoclicker" / "__init__.py").read_text(encoding="utf-8"),
).group(1)

icon_file = None
if IS_MACOS and (ICONS / "icon.icns").is_file():
    icon_file = str(ICONS / "icon.icns")
elif IS_WINDOWS and (ICONS / "icon.ico").is_file():
    icon_file = str(ICONS / "icon.ico")

# pynput picks its backend at runtime with a dynamic import, so PyInstaller's
# static analysis never sees it and the frozen app comes up with no input
# support at all. Naming them explicitly is the fix. Only this platform's, or
# the others drag in Xlib and friends that are not installed.
if IS_MACOS:
    hidden = ["pynput.keyboard._darwin", "pynput.mouse._darwin"]
elif IS_WINDOWS:
    hidden = ["pynput.keyboard._win32", "pynput.mouse._win32"]
else:
    hidden = ["pynput.keyboard._xorg", "pynput.mouse._xorg"]

# The GUI and CLI are imported inside functions so that a missing PySide6
# degrades to headless rather than crashing. That deferral also hides them from
# the analyser, so name them.
hidden += ["autoclicker.ui.app", "autoclicker.cli", "autoclicker.selftest"]

analysis = Analysis(
    # Not autoclicker/__main__.py: see the comment at the top of the launcher.
    ["tools/launcher.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[("autoclicker/resources", "autoclicker/resources")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pytest",
        "numpy",  # only the icon tool needs it
        "PIL",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Autoclicker",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Autoclicker",
)

if IS_MACOS:
    app = BUNDLE(
        collection,
        name="Autoclicker.app",
        icon=icon_file,
        bundle_identifier="io.github.kaaykun.autoclicker",
        version=version,
        info_plist={
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "13.0",
        },
    )
