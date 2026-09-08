"""Saved profiles on disk, plus the handful of app-level settings.

Files are named after a slug of the profile name, but the *real* name lives
inside the JSON. That split matters: profile names are free text -- "Bob's
grinder / v2" is a perfectly reasonable thing to type -- and turning one into a
filename is lossy. Reading the name back from the file content means renaming,
unicode and punctuation all behave, and two profiles whose names slug to the
same thing still get separate files.

Anything unreadable is skipped rather than fatal. A corrupt profile should cost
you that profile, not the app.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

from .config import Profile

logger = logging.getLogger(__name__)

APP_DIR_NAME = "Autoclicker"
SETTINGS_FILE = "settings.json"
PROFILE_SUFFIX = ".json"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_SLUG = 64


def config_dir() -> Path:
    """Where this platform expects an app to keep its configuration."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME.lower()


def slugify(name: str) -> str:
    slug = _UNSAFE.sub("-", name.strip()).strip("-._")
    return (slug or "profile")[:_MAX_SLUG]


class ProfileStore:
    """Reads and writes profiles in one directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else config_dir() / "profiles"

    # ------------------------------------------------------------ reading

    def load_all(self) -> list[Profile]:
        """Every readable profile, sorted by name. Unreadable ones are skipped."""
        profiles: list[Profile] = []
        if not self.directory.is_dir():
            return profiles
        for path in sorted(self.directory.glob(f"*{PROFILE_SUFFIX}")):
            profile = self._read(path)
            if profile is not None:
                profiles.append(profile)
        return sorted(profiles, key=lambda p: p.name.lower())

    def names(self) -> list[str]:
        return [profile.name for profile in self.load_all()]

    def load(self, name: str) -> Profile | None:
        for path, profile in self._entries():
            if profile.name == name:
                del path
                return profile
        return None

    # ------------------------------------------------------------ writing

    def save(self, profile: Profile) -> Path:
        """Write a profile, replacing any existing one with the same name."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path_for(profile.name)
        _write_atomic(path, profile.to_json())
        return path

    def delete(self, name: str) -> bool:
        for path, profile in self._entries():
            if profile.name == name:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Could not delete profile %s", path, exc_info=True)
                    return False
                return True
        return False

    def rename(self, old_name: str, new_name: str) -> bool:
        profile = self.load(old_name)
        if profile is None:
            return False
        self.delete(old_name)
        profile.name = new_name
        self.save(profile)
        return True

    # ------------------------------------------------------------ internals

    def _entries(self) -> list[tuple[Path, Profile]]:
        entries: list[tuple[Path, Profile]] = []
        if not self.directory.is_dir():
            return entries
        for path in sorted(self.directory.glob(f"*{PROFILE_SUFFIX}")):
            profile = self._read(path)
            if profile is not None:
                entries.append((path, profile))
        return entries

    def _read(self, path: Path) -> Profile | None:
        try:
            return Profile.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, AttributeError):
            logger.warning("Skipping unreadable profile %s", path, exc_info=True)
            return None

    def _path_for(self, name: str) -> Path:
        """Reuse this name's existing file; otherwise find a free slug."""
        for path, profile in self._entries():
            if profile.name == name:
                return path

        base = slugify(name)
        candidate = self.directory / f"{base}{PROFILE_SUFFIX}"
        counter = 2
        while candidate.exists():
            candidate = self.directory / f"{base}-{counter}{PROFILE_SUFFIX}"
            counter += 1
        return candidate


class Settings:
    """A tiny key/value file for things that outlive a single profile."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else config_dir()
        self.path = self.directory / SETTINGS_FILE

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, values: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path, json.dumps(values, indent=2))

    def update(self, **values: object) -> dict:
        merged = self.read()
        merged.update(values)
        self.write(merged)
        return merged


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file and replace, so a crash cannot truncate the original."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
