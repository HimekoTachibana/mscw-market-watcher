import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from mesowatcher import core, updater

NAME = core.FULL_NAME
SCRIPT = b'#!/bin/sh\ntouch "$(dirname "$0")/ran"\n'


def make_targz(top: str, exe_body: bytes = SCRIPT) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(f"{top}/{top}")
        info.size, info.mode = len(exe_body), 0o755
        t.addfile(info, io.BytesIO(exe_body))
    return buf.getvalue()


class Fake:
    """A tiny stand-in for api.github.com plus the download host."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.latest: dict | None = None
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/releases/latest"):
                    if outer.latest is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = json.dumps(outer.latest).encode()
                elif self.path in outer.files:
                    body = outer.files[self.path]
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def publish(self, tag: str, assets: dict[str, bytes], digest=True, notes="Notes here"):
        out = []
        for n, data in assets.items():
            self.files[f"/dl/{n}"] = data
            a = {"name": n, "size": len(data), "browser_download_url": f"{self.base}/dl/{n}"}
            if digest:
                a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
            out.append(a)
        self.latest = {"tag_name": tag, "name": f"{NAME} {tag}", "body": notes,
                       "html_url": f"{self.base}/release/{tag}", "assets": out}

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def fake():
    f = Fake()
    yield f
    f.close()


# ------------------------------------------------------------- pure helpers
def test_version_parsing_and_compare():
    assert updater.parse_version("v0.4.1") == (0, 4, 1)
    assert updater.parse_version("1.2") == (1, 2)
    assert updater.parse_version("latest") is None
    assert updater.is_newer("v0.5.0", "0.4.0")
    assert updater.is_newer("v0.10.0", "0.9.9")  # numeric, not text, comparison
    assert not updater.is_newer("v0.4.0", "0.4.0")
    assert not updater.is_newer("v0.4", "0.4.0")  # trailing zeros do not count
    assert not updater.is_newer("v0.3.9", "0.4.0")
    assert not updater.is_newer("nonsense", "0.4.0")


def test_pick_asset_matches_github_renamed_files():
    assets = [{"name": "MSCW.Market.Watcher.v0.4.0.Linux.tar.gz"},
              {"name": "MSCW.Market.Watcher.v0.4.0.macOS.tar.gz"},
              {"name": "MSCW.Market.Watcher.v0.4.0.Windows.zip"},
              {"name": "Source code.zip"}]
    assert updater.pick_asset(assets, "windows")["name"].endswith("Windows.zip")
    assert updater.pick_asset(assets, "linux")["name"].endswith("Linux.tar.gz")
    assert updater.pick_asset(assets, "macos")["name"].endswith("macOS.tar.gz")
    assert updater.pick_asset(assets[:2], "windows") is None
    assert updater.os_key("win32") == "windows" and updater.os_key("darwin") == "macos"
    assert updater.os_key("linux") == "linux"


def test_problem_reasons(tmp_path):
    good = tmp_path / f"{NAME} v0.4.0"
    good.mkdir()
    assert updater.problem(good, "linux", True) == ""
    assert "source code" in updater.problem(good, "linux", False)
    assert "could not be located" in updater.problem(None, "linux", True)
    renamed = tmp_path / "my app"
    renamed.mkdir()
    assert "renamed" in updater.problem(renamed, "linux", True)
    weird = tmp_path / f"{NAME} 100%"
    weird.mkdir()
    assert "character" in updater.problem(weird, "win32", True)
    assert updater.problem(weird, "linux", True) == ""


def test_install_target():
    assert updater.install_target("/opt/x/MSCW Market Watcher v1/MSCW Market Watcher v1", "linux") == \
        Path("/opt/x/MSCW Market Watcher v1")
    mac = "/Applications/MSCW Market Watcher v1.app/Contents/MacOS/MSCW Market Watcher v1"
    assert updater.install_target(mac, "darwin") == Path("/Applications/MSCW Market Watcher v1.app")
    assert updater.install_target("/usr/bin/python3", "darwin") is None


# ------------------------------------------------------------------ GitHub
def test_check_newer_same_and_missing(fake):
    fake.publish("v0.5.0", {"MSCW.Market.Watcher.v0.5.0.Linux.tar.gz": b"abc"})
    rel = updater.check("o/r", "0.4.0", "linux", fake.base)
    assert rel.tag == "v0.5.0" and rel.version == (0, 5, 0) and rel.notes == "Notes here"
    assert rel.asset_size == 3 and rel.sha256 == hashlib.sha256(b"abc").hexdigest()
    assert updater.check("o/r", "0.5.0", "linux", fake.base) is None  # already current
    with pytest.raises(updater.UpdateError, match="no download for Windows"):
        updater.check("o/r", "0.4.0", "windows", fake.base)
    fake.latest = None
    with pytest.raises(updater.UpdateError, match="No release"):
        updater.check("o/r", "0.4.0", "linux", fake.base)
    with pytest.raises(updater.UpdateError, match="owner/name"):
        updater.check("not a repo", "0.4.0", "linux", fake.base)


def test_check_unreachable():
    with pytest.raises(updater.UpdateError, match="Could not reach GitHub"):
        updater.fetch_latest("o/r", "http://127.0.0.1:1", timeout=2)


def test_download_verifies_checksum_and_progress(fake, tmp_path):
    data = os.urandom(700_000)
    fake.publish("v0.5.0", {"x.Linux.tar.gz": data})
    rel = updater.check("o/r", "0.4.0", "linux", fake.base)
    seen = []
    p = updater.download(rel, tmp_path / "d", progress=lambda d, t: seen.append((d, t)))
    assert p.read_bytes() == data and seen[-1] == (len(data), len(data))

    rel.sha256 = "0" * 64
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(rel, tmp_path / "d2")
    assert not list((tmp_path / "d2").iterdir())  # bad file removed

    rel.sha256, rel.asset_size = "", len(data) + 5
    with pytest.raises(updater.UpdateError, match="incomplete"):
        updater.download(rel, tmp_path / "d3")

    ev = threading.Event()
    ev.set()
    rel.asset_size = len(data)
    with pytest.raises(updater.UpdateError, match="cancelled"):
        updater.download(rel, tmp_path / "d4", cancel=ev)


def test_download_refuses_plain_http_to_other_hosts(tmp_path):
    rel = updater.Release("v1", (1,), "n", "", "", "a.zip", "http://example.com/a.zip", 0, "")
    with pytest.raises(updater.UpdateError, match="non-HTTPS"):
        updater.download(rel, tmp_path)


# ----------------------------------------------------------------- archives
def test_extract_zip_and_tar_and_unsafe(tmp_path):
    top = f"{NAME} v1.0.0"
    zp = tmp_path / "a.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(f"{top}/{top}.exe", "x")
    assert updater.extract(zp, tmp_path / "z").name == top

    tp = tmp_path / "a.tar.gz"
    tp.write_bytes(make_targz(top))
    got = updater.extract(tp, tmp_path / "t")
    assert got.name == top and os.access(got / top, os.X_OK)

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../escape.txt", "x")
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater.extract(evil, tmp_path / "e")
    assert not (tmp_path / "escape.txt").exists()

    two = tmp_path / "two.zip"
    with zipfile.ZipFile(two, "w") as z:
        z.writestr("a/x", "1")
        z.writestr("b/x", "1")
    with pytest.raises(updater.UpdateError, match="layout"):
        updater.extract(two, tmp_path / "two")


# ------------------------------------------------ prepare + helper end to end
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="runs the sh helper")


def wait_for(path: Path, secs: float = 15) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def install_fake_app(parent: Path, version: str) -> tuple[Path, Path]:
    d = parent / f"{NAME} v{version}"
    d.mkdir(parents=True)
    exe = d / d.name
    exe.write_bytes(SCRIPT)
    exe.chmod(0o755)
    return d, exe


@posix_only
def test_full_update_swaps_folder_and_relaunches(fake, tmp_path):
    old, old_exe = install_fake_app(tmp_path, "0.5.0")
    new_top = f"{NAME} v0.6.0"
    fake.publish("v0.6.0", {"MSCW.Market.Watcher.v0.6.0.Linux.tar.gz": make_targz(new_top)})
    rel = updater.check("o/r", "0.5.0", "linux", fake.base)
    stages = []
    plan = updater.prepare(rel, old, running_exe=str(old_exe), platform="linux", status=stages.append)
    assert stages == ["Downloading v0.6.0 ...", "Unpacking ..."]
    assert plan.dest == tmp_path / new_top and plan.new.is_dir() and old.is_dir()  # nothing swapped yet

    waiter = subprocess.Popen(["sleep", "1"])  # stands in for the app that is about to quit
    updater.start_helper(plan, pid=waiter.pid, platform="linux")
    assert wait_for(plan.dest / "ran"), "new version was not started"
    waiter.wait()
    leftovers = [old, Path(str(old) + ".old"), plan.stage]  # the helper clears these a moment after starting the app
    deadline = time.time() + 10
    while any(p.exists() for p in leftovers) and time.time() < deadline:
        time.sleep(0.2)
    assert not any(p.exists() for p in leftovers)
    assert plan.dest.is_dir()


@posix_only
def test_helper_restores_old_app_when_swap_fails(fake, tmp_path):
    old, old_exe = install_fake_app(tmp_path, "0.5.0")
    fake.publish("v0.6.0", {"MSCW.Market.Watcher.v0.6.0.Linux.tar.gz": make_targz(f"{NAME} v0.6.0")})
    rel = updater.check("o/r", "0.5.0", "linux", fake.base)
    plan = updater.prepare(rel, old, running_exe=str(old_exe), platform="linux")
    import shutil
    shutil.rmtree(plan.new)  # sabotage: the unpacked update vanishes before the swap
    waiter = subprocess.Popen(["sleep", "1"])
    updater.start_helper(plan, pid=waiter.pid, platform="linux")
    assert wait_for(old / "ran"), "old version was not restored and restarted"
    assert old.is_dir() and not plan.dest.exists()


def test_prepare_refuses_existing_destination_and_cleans_up(fake, tmp_path):
    old, old_exe = install_fake_app(tmp_path, "0.5.0")
    (tmp_path / f"{NAME} v0.6.0").mkdir()
    fake.publish("v0.6.0", {"MSCW.Market.Watcher.v0.6.0.Linux.tar.gz": make_targz(f"{NAME} v0.6.0")})
    rel = updater.check("o/r", "0.5.0", "linux", fake.base)
    with pytest.raises(updater.UpdateError, match="already exists"):
        updater.prepare(rel, old, running_exe=str(old_exe), platform="linux")
    assert not any(p.name.startswith(".") for p in tmp_path.iterdir())  # stage folder removed


def test_prepare_rejects_archive_without_program(fake, tmp_path):
    old, old_exe = install_fake_app(tmp_path, "0.5.0")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(f"{NAME} v0.6.0/readme.txt")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    fake.publish("v0.6.0", {"MSCW.Market.Watcher.v0.6.0.Linux.tar.gz": buf.getvalue()})
    rel = updater.check("o/r", "0.5.0", "linux", fake.base)
    with pytest.raises(updater.UpdateError, match="does not contain the program"):
        updater.prepare(rel, old, running_exe=str(old_exe), platform="linux")


def test_helper_scripts_use_expected_arguments():
    # The Windows script cannot run here; at least make sure it uses all seven arguments and ends cleanly.
    for n in range(1, 8):
        assert f"%~{n}" in updater._BAT
    assert 'del "%~f0"' in updater._BAT and "move \"%NEW%\" \"%DEST%\"" in updater._BAT
    for n in range(1, 9):
        assert f'"${n}"' in updater._SH


def test_helper_launch_mode_follows_platform_argument(monkeypatch, tmp_path):
    """macOS starts the new .app with 'open'; everything else runs the program directly. Decided by the caller,
    not by sniffing the OS inside the script, so it behaves the same wherever it runs."""
    seen = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: seen.append(args))
    plan = updater.Plan("v1", tmp_path / "s", tmp_path / "o", tmp_path / "n", tmp_path / "d", tmp_path / "ln",
                        tmp_path / "lo")
    updater.start_helper(plan, pid=1, platform="darwin")
    updater.start_helper(plan, pid=1, platform="linux")
    assert seen[0][-1] == "open" and seen[1][-1] == "exec"
    assert len(seen[0]) == 10  # /bin/sh, script, then eight arguments
