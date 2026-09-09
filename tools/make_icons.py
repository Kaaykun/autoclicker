"""Build the platform icon sets from one master PNG.

Run after changing ``autoclicker/resources/icon.png``:

    uv run python tools/make_icons.py

macOS and Windows want genuinely different things from an app icon, which is
why this does more than resize:

**macOS** does not mask app icons -- unlike iOS, the rounded corners have to be
in the artwork, and they are. It also expects the artwork to sit inside a
margin: on a 1024 canvas Apple's grid puts the icon body at 824 px with 100 px
of clear space each side. Skip that and the icon sits noticeably larger than
every neighbour in the Dock.

**Windows** does not mask either, and it has no corner convention, so baked-in
rounded corners show up as transparent notches against whatever is behind them
-- a taskbar highlight, a File Explorer selection tint. The fix is a square,
full-bleed variant: the background gradient is extended outward into the
corners so the artwork keeps its exact colours right out to the edge.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RESOURCES = ROOT / "autoclicker" / "resources"
BUILD = ROOT / "build" / "icons"

#: Apple's 1024 px grid: an 824 px body inside 100 px of clear space.
MACOS_BODY_RATIO = 824 / 1024

ICNS_SIZES = (16, 32, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def extend_edges_into_corners(image: Image.Image) -> Image.Image:
    """Grow the opaque artwork outward until nothing is transparent.

    Each unknown pixel takes the average of its known neighbours, repeatedly,
    so a gradient continues into the corners instead of meeting a flat patch.
    Partly transparent edge pixels are then composited over the result, which
    keeps the antialiased curve from leaving a seam.
    """
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32)
    rgb, alpha = rgba[..., :3].copy(), rgba[..., 3] / 255.0

    known = alpha > 0.99
    if known.all():
        return image.convert("RGBA")

    filled = rgb.copy()
    filled[~known] = 0.0

    while not known.all():
        padded_rgb = np.pad(filled, ((1, 1), (1, 1), (0, 0)), mode="edge")
        padded_known = np.pad(known.astype(np.float32), ((1, 1), (1, 1)), mode="edge")

        total = np.zeros_like(filled)
        count = np.zeros(known.shape, dtype=np.float32)
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
            neighbour_known = padded_known[dy:dy + known.shape[0], dx:dx + known.shape[1]]
            neighbour_rgb = padded_rgb[dy:dy + known.shape[0], dx:dx + known.shape[1]]
            total += neighbour_rgb * neighbour_known[..., None]
            count += neighbour_known

        newly = (count > 0) & ~known
        if not newly.any():
            break
        filled[newly] = total[newly] / count[newly][..., None]
        known |= newly

    # Composite the original over the extended background so the antialiased
    # curve blends instead of stepping.
    blended = rgb * alpha[..., None] + filled * (1.0 - alpha[..., None])
    out = np.dstack([blended, np.full(alpha.shape, 255.0)]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def with_macos_margin(image: Image.Image, canvas: int = 1024) -> Image.Image:
    """Inset the artwork onto Apple's icon grid."""
    body = round(canvas * MACOS_BODY_RATIO)
    inset = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    resized = image.convert("RGBA").resize((body, body), Image.Resampling.LANCZOS)
    offset = (canvas - body) // 2
    inset.paste(resized, (offset, offset))
    return inset


def build_iconset(image: Image.Image, iconset: Path) -> None:
    if iconset.exists():
        try:
            shutil.rmtree(iconset)
        except OSError:
            # Some sandboxes forbid deletes. The filenames are deterministic,
            # so overwriting in place is just as complete.
            pass
    iconset.mkdir(parents=True, exist_ok=True)
    for size in ICNS_SIZES:
        for scale in (1, 2):
            pixels = size * scale
            suffix = "" if scale == 1 else "@2x"
            resized = image.resize((pixels, pixels), Image.Resampling.LANCZOS)
            resized.save(iconset / f"icon_{size}x{size}{suffix}.png")


def build_icns(iconset: Path, destination: Path) -> bool:
    """Convert an iconset with iconutil. macOS only; returns success."""
    if sys.platform != "darwin" or shutil.which("iconutil") is None:
        return False
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(destination)],
        check=True,
    )
    return True


def build_ico(image: Image.Image, destination: Path) -> None:
    image.save(destination, format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def build_preview(rounded: Image.Image, square: Image.Image, destination: Path) -> None:
    """A side-by-side so the square variant can be eyeballed before shipping."""
    tile = 320
    gap = 24
    canvas = Image.new("RGBA", (tile * 2 + gap * 3, tile + gap * 2), (128, 128, 128, 255))
    canvas.paste(rounded.resize((tile, tile), Image.Resampling.LANCZOS), (gap, gap), 
                 rounded.resize((tile, tile), Image.Resampling.LANCZOS))
    canvas.paste(square.resize((tile, tile), Image.Resampling.LANCZOS), (gap * 2 + tile, gap))
    canvas.convert("RGB").save(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=RESOURCES / "icon.png")
    parser.add_argument("--out", type=Path, default=BUILD)
    parser.add_argument(
        "--no-macos-margin",
        action="store_true",
        help="do not inset the artwork onto Apple's 824/1024 grid",
    )
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"error: no artwork at {args.source}", file=sys.stderr)
        return 2

    master = Image.open(args.source).convert("RGBA")
    if master.size != (1024, 1024):
        print(f"note: resizing {master.size} artwork to 1024x1024", file=sys.stderr)
        master = master.resize((1024, 1024), Image.Resampling.LANCZOS)

    args.out.mkdir(parents=True, exist_ok=True)

    square = extend_edges_into_corners(master)
    square.save(RESOURCES / "icon-square.png")
    print(f"wrote {RESOURCES / 'icon-square.png'}  (square, for Windows)")

    macos_art = master if args.no_macos_margin else with_macos_margin(master)
    # Written into resources as well as the iconset, because Qt overrides the
    # Dock tile at runtime -- see icons.py. The running app has to use the same
    # framing as the bundle icon or it visibly grows the moment it launches.
    macos_art.save(RESOURCES / "icon-macos.png")
    print(f"wrote {RESOURCES / 'icon-macos.png'}  (inset, for macOS)")

    iconset = args.out / "icon.iconset"
    build_iconset(macos_art, iconset)
    icns = args.out / "icon.icns"
    if build_icns(iconset, icns):
        print(f"wrote {icns}")
    else:
        print(f"wrote {iconset}  (run iconutil on macOS to produce icon.icns)")

    ico = args.out / "icon.ico"
    build_ico(square, ico)
    print(f"wrote {ico}  (square corners)")

    preview = args.out / "preview.png"
    build_preview(master, square, preview)
    print(f"wrote {preview}  (rounded vs square, on grey)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
