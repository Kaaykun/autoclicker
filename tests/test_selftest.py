"""The self-test is what the release workflow runs against the frozen binary,
so a mistake in it would silently stop guarding the builds. These tests check
the harness, not the checks: that a pass reports 0, that one broken check
fails the run, and that the log file the Windows job reads gets written."""

from __future__ import annotations

import pytest

from autoclicker import selftest


def test_a_clean_run_reports_success(capsys) -> None:
    assert selftest.run() == 0
    assert "self-test passed" in capsys.readouterr().out


def test_one_broken_check_fails_the_whole_run(monkeypatch, capsys) -> None:
    def broken() -> None:
        raise RuntimeError("PySide6 is not in this bundle")

    monkeypatch.setattr(selftest, "CHECKS", [("qt", broken)])

    assert selftest.run() == 1
    out = capsys.readouterr().out
    assert "FAIL  qt" in out
    # The traceback matters: a red job that only says "exit 1" is not a report.
    assert "PySide6 is not in this bundle" in out
    assert "self-test failed" in out


def test_a_skipped_check_is_not_a_failure(monkeypatch, capsys) -> None:
    def unavailable() -> None:
        raise selftest.Skipped("no display here")

    monkeypatch.setattr(selftest, "CHECKS", [("input backend", unavailable)])

    assert selftest.run() == 0
    assert "skip  input backend: no display here" in capsys.readouterr().out


def test_the_report_is_also_written_to_the_log_file(monkeypatch, tmp_path) -> None:
    """A windowed Windows build has no console, so the file is the only output."""
    log = tmp_path / "selftest.log"
    monkeypatch.setenv("AUTOCLICKER_SELFTEST_LOG", str(log))
    monkeypatch.setattr(selftest, "CHECKS", [])

    assert selftest.run() == 0
    assert "self-test passed" in log.read_text(encoding="utf-8")


def test_an_unwritable_log_path_does_not_break_the_run(monkeypatch) -> None:
    monkeypatch.setenv("AUTOCLICKER_SELFTEST_LOG", "/no/such/directory/selftest.log")
    monkeypatch.setattr(selftest, "CHECKS", [])

    assert selftest.run() == 0


@pytest.mark.parametrize("name", [name for name, _ in selftest.CHECKS])
def test_every_real_check_passes_here(name) -> None:
    """The checks run against the source tree too, where they should all pass
    (or skip, on a headless Linux box that pynput refuses to import on)."""
    check = dict(selftest.CHECKS)[name]
    try:
        check()
    except selftest.Skipped:
        pytest.skip("not meaningful on this machine")
