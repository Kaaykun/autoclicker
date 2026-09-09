"""Icon framing.

Pure geometry, no Qt. These guard a mistake that is invisible in code review
and only shows up as "the icon looks slightly too big" once the app is on a
Dock next to other apps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image", reason="Pillow is a dev dependency")
np = pytest.importorskip("numpy")

RESOURCES = Path(__file__).resolve().parent.parent / "autoclicker" / "resources"

#: Apple's macOS icon grid: an 824 px body inside a 1024 px canvas.
MACOS_BODY_RATIO = 824 / 1024


def artwork_ratio(path: Path) -> float:
    """How much of the canvas the non-transparent artwork spans."""
    image = Image.open(path).convert("RGBA")
    alpha = np.array(image)[..., 3]
    columns = np.where(alpha.max(axis=0) > 8)[0]
    return (columns[-1] - columns[0] + 1) / image.size[0]


def test_the_master_artwork_is_full_bleed() -> None:
    assert artwork_ratio(RESOURCES / "icon.png") == pytest.approx(1.0, abs=0.01)


def test_the_macos_icon_leaves_apples_margin() -> None:
    """Without the margin the Dock tile is a quarter larger than its neighbours,
    and the Command-Tab selection outline no longer fits around it."""
    assert artwork_ratio(RESOURCES / "icon-macos.png") == pytest.approx(
        MACOS_BODY_RATIO, abs=0.01
    )


def test_the_windows_icon_has_no_transparent_corners() -> None:
    """Windows masks nothing, so a transparent corner is a visible notch."""
    image = Image.open(RESOURCES / "icon-square.png").convert("RGBA")
    alpha = np.array(image)[..., 3]
    corners = [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]]
    assert all(value == 255 for value in corners), corners
    assert alpha.min() == 255, "the whole canvas should be opaque"


def test_the_corner_fill_continues_the_gradient() -> None:
    """Filled flat rather than extended, the corners would band visibly."""
    image = Image.open(RESOURCES / "icon-square.png").convert("RGB")
    corner = np.array(image.crop((0, 0, 8, 8)), dtype=float).mean(axis=(0, 1))
    inside = np.array(image.crop((80, 80, 88, 88)), dtype=float).mean(axis=(0, 1))
    assert np.abs(corner - inside).max() < 12, (corner, inside)


def test_every_generated_variant_is_committed() -> None:
    """A fresh clone must have the right icon without running the build tool."""
    for name in ("icon.png", "icon-macos.png", "icon-square.png"):
        assert (RESOURCES / name).is_file(), name
