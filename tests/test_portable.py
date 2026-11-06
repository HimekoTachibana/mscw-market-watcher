import os
import sys

import pytest

from mesowatcher import core, portable

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux libraries only")


@pytest.fixture()
def shipped(tmp_path, monkeypatch):
    """A fake browser-libs folder holding every library the build ships."""
    libs = tmp_path / "browser-libs"
    libs.mkdir()
    for n in portable.BUNDLED_LIBS:
        (libs / n).write_bytes(b"\x7fELF fake")
    monkeypatch.setattr(portable, "bundled_libs_dir", lambda: libs)
    return libs


@linux_only
def test_nothing_is_changed_when_the_system_has_every_library(shipped, tmp_path, monkeypatch):
    monkeypatch.setattr(portable, "missing_libs", lambda exe, extra="": [])
    assert portable.browser_env("/x/chrome", tmp_path / "active") == (None, [])
    assert not (tmp_path / "active").exists()


@linux_only
def test_only_missing_libraries_are_linked_and_nss_stays_together(shipped, tmp_path, monkeypatch):
    calls = []

    def fake(exe, extra=""):
        calls.append(extra)
        return ["libcups.so.2", "libnss3.so"] if not extra else []
    monkeypatch.setattr(portable, "missing_libs", fake)
    env, still = portable.browser_env("/x/chrome", tmp_path / "active")
    linked = sorted(p.name for p in (tmp_path / "active").iterdir())
    assert linked == sorted(set(portable.NSS_GROUP) | {"libcups.so.2"})  # not libatk etc.: the system has those
    assert "libXext.so.6" not in linked
    assert env["LD_LIBRARY_PATH"].split(os.pathsep)[0] == str(tmp_path / "active")
    assert still == [] and calls[-1] == str(tmp_path / "active")


@linux_only
def test_a_library_nobody_ships_is_reported(shipped, tmp_path, monkeypatch):
    monkeypatch.setattr(portable, "missing_libs", lambda exe, extra="": ["libgbm.so.1"])
    env, still = portable.browser_env("/x/chrome", tmp_path / "active")
    assert still == ["libgbm.so.1"]  # never shipped: tied to the graphics driver


@linux_only
def test_ldd_on_a_normal_program_finds_nothing_missing():
    assert portable.missing_libs("/bin/sh") == []


def test_sandbox_errors_are_recognised():
    assert portable.is_sandbox_error(RuntimeError("FATAL:zygote_host_impl_linux.cc No usable sandbox! ..."))
    assert portable.is_sandbox_error(RuntimeError("The SUID sandbox helper binary was found, but is not configured"
                                                  " correctly (setuid)"))
    assert not portable.is_sandbox_error(RuntimeError("Executable doesn't exist at /x"))


def test_linux_sound_player_order(monkeypatch):
    have = {"pw-play", "aplay"}
    monkeypatch.setattr(core.shutil, "which", lambda c: f"/usr/bin/{c}" if c in have else None)
    assert core.linux_player("a.wav") == ["pw-play", "a.wav"]  # PipeWire (SteamOS, Bazzite...) before ALSA
    have = {"ffplay"}
    assert core.linux_player("a.wav")[0] == "ffplay"
    have = set()
    assert core.linux_player("a.wav") is None


def test_default_browser_is_the_shipped_chromium_except_on_windows(tmp_path):
    cfg = core.Config(tmp_path / "c.json")
    assert cfg["browser"]["channel"] == ("msedge" if sys.platform == "win32" else "chromium")
