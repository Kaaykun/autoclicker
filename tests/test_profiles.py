"""Profile storage: naming, round-tripping, and surviving bad input."""

from __future__ import annotations

import json
from pathlib import Path

from autoclicker.core.config import IntervalConfig, MouseButton, Profile
from autoclicker.core.profiles import ProfileStore, Settings, slugify


def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles")


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    s = store(tmp_path)
    profile = Profile(name="Grinder", interval=IntervalConfig(seconds=2))
    s.save(profile)
    assert s.load("Grinder") == profile


def test_saving_twice_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="Same", interval=IntervalConfig(seconds=0, millis=100)))
    s.save(Profile(name="Same", interval=IntervalConfig(seconds=0, millis=250)))
    assert s.names() == ["Same"]
    loaded = s.load("Same")
    assert loaded is not None and loaded.interval.total_ms == 250


def test_awkward_names_survive_verbatim(tmp_path: Path) -> None:
    """The filename is a slug; the real name lives in the file, unmodified.

    The store deliberately does not tidy names -- trimming is the UI's job, and
    a layer that silently rewrites what you typed is worse than one that does
    not.
    """
    s = store(tmp_path)
    names = ["Bob's grinder / v2", "  spaced  out  ", "\u65e5\u672c\u8a9e", "../escape"]
    for name in names:
        s.save(Profile(name=name))
    assert set(s.names()) == set(names)


def test_names_that_slug_alike_get_separate_files(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="a/b"))
    s.save(Profile(name="a b"))
    assert sorted(s.names()) == ["a b", "a/b"]
    assert len(list((tmp_path / "profiles").glob("*.json"))) == 2


def test_nothing_escapes_the_profile_directory(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="../../etc/passwd"))
    written = list((tmp_path / "profiles").glob("*.json"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "profiles"


def test_delete_and_rename(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="Old"))
    assert s.rename("Old", "New")
    assert s.names() == ["New"]
    assert s.delete("New")
    assert s.names() == []
    assert not s.delete("Missing")


def test_profiles_are_listed_alphabetically(tmp_path: Path) -> None:
    s = store(tmp_path)
    for name in ["zebra", "Apple", "mango"]:
        s.save(Profile(name=name))
    assert s.names() == ["Apple", "mango", "zebra"]


def test_a_corrupt_file_costs_you_that_profile_and_nothing_else(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="Good"))
    (tmp_path / "profiles" / "broken.json").write_text("{not json at all", encoding="utf-8")
    assert s.names() == ["Good"]


def test_a_partial_file_still_loads_with_defaults(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.directory.mkdir(parents=True)
    (s.directory / "sparse.json").write_text(
        json.dumps({"name": "Sparse", "click": {"button": "right"}}), encoding="utf-8"
    )
    loaded = s.load("Sparse")
    assert loaded is not None
    assert loaded.click.button is MouseButton.RIGHT
    assert loaded.interval.total_ms == 1000


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert ProfileStore(tmp_path / "nope").names() == []
    assert ProfileStore(tmp_path / "nope").load("anything") is None


def test_slugify_never_returns_an_empty_or_hidden_name() -> None:
    assert slugify("") == "profile"
    assert slugify("...") == "profile"
    assert slugify("///") == "profile"
    assert not slugify("...hidden").startswith(".")


def test_settings_round_trip_and_tolerate_garbage(tmp_path: Path) -> None:
    settings = Settings(tmp_path)
    assert settings.read() == {}
    settings.update(last_profile="Grinder", always_on_top=True)
    assert settings.read()["last_profile"] == "Grinder"

    settings.path.write_text("[]", encoding="utf-8")
    assert settings.read() == {}


def test_writes_are_atomic_enough_to_leave_no_temp_files(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.save(Profile(name="Clean"))
    assert list((tmp_path / "profiles").glob("*.tmp")) == []
