"""Self-update: look for a newer GitHub release, download the build for this OS, swap it in, relaunch.

How an update works (packaged app only):
  1. check()    asks the GitHub API for the latest release and compares it with core.VERSION.
  2. prepare()  downloads the Windows/Linux/macOS archive, checks its size and SHA-256, unpacks it into a
                hidden staging folder next to the installed app and checks the new program is in there.
                Nothing is changed yet, so a failure here leaves the installed app untouched.
  3. start_helper() starts a tiny script that waits for this program to exit, renames the old app to
                "<name>.old", moves the new one next to it, starts it, then deletes the old one. If the swap
                fails the old app is put back and started again.
Your settings, watchlist and listings live in the user data folder, so an update never touches them.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from . import core

API_BASE = "https://api.github.com"
CHUNK = 256 * 1024


class UpdateError(Exception):
    """A problem worth showing to the user as-is."""


@dataclass
class Release:
    tag: str
    version: tuple
    name: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str  # "" when GitHub gave no digest


@dataclass
class Plan:
    version: str
    stage: Path  # hidden folder holding the unpacked update (deleted by the helper)
    old: Path  # installed app: folder (Windows/Linux) or .app bundle (macOS)
    new: Path  # unpacked new app inside the stage folder
    dest: Path  # where the new app ends up (next to the old one)
    launch_new: Path
    launch_old: Path


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> Optional[tuple]:
    """'v0.4.1' -> (0, 4, 1). None when there is no number in front."""
    m = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _norm(v: tuple) -> tuple:
    v = list(v)
    while len(v) > 1 and v[-1] == 0:
        v.pop()
    return tuple(v)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and _norm(a) > _norm(b)


def os_key(platform: Optional[str] = None) -> str:
    p = platform or sys.platform
    return "windows" if p.startswith("win") else "macos" if p == "darwin" else "linux"


def pick_asset(assets: list, key: str) -> Optional[dict]:
    """The release file for this OS. GitHub turns spaces in names into dots, so match on the OS word."""
    want = ".zip" if key == "windows" else ".tar.gz"
    for a in assets:
        n = str(a.get("name", "")).lower()
        if n.endswith(want) and re.search(rf"(^|[^a-z]){key}([^a-z]|$)", n):
            return a
    return None


# ------------------------------------------------------------------- GitHub
def _headers(accept: str = "application/vnd.github+json") -> dict:
    return {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{core.APP_NAME}/{core.VERSION}"}


def _check_url(url: str):
    u = urlparse(url)
    if u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
        return
    raise UpdateError("Refusing to download from a non-HTTPS address.")


def fetch_latest(repo: str, api_base: str = API_BASE, timeout: float = 15) -> dict:
    repo = (repo or "").strip().strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateError(f"'{repo}' is not a GitHub repository name like owner/name.")
    try:
        r = requests.get(f"{api_base}/repos/{repo}/releases/latest", headers=_headers(), timeout=timeout)
    except requests.RequestException as e:
        raise UpdateError(f"Could not reach GitHub: {e}") from e
    if r.status_code == 404:
        raise UpdateError(f"No release was found for {repo} (none published yet, or the repository is private).")
    if r.status_code in (403, 429):
        raise UpdateError("GitHub is limiting requests from this connection right now. Try again later.")
    if not r.ok:
        raise UpdateError(f"GitHub answered with an error ({r.status_code}).")
    try:
        data = r.json()
    except ValueError as e:
        raise UpdateError("GitHub sent a reply that could not be read.") from e
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent an unexpected reply.")
    return data


def check(repo: str, current: str = core.VERSION, key: Optional[str] = None,
          api_base: str = API_BASE) -> Optional[Release]:
    """The latest release if it is newer than `current`, otherwise None."""
    key = key or os_key()
    data = fetch_latest(repo, api_base)
    tag = str(data.get("tag_name") or "")
    ver = parse_version(tag)
    if ver is None:
        raise UpdateError(f"The latest release has a version this app cannot read: '{tag}'.")
    if not is_newer(tag, current):
        return None
    asset = pick_asset(data.get("assets") or [], key)
    if asset is None:
        raise UpdateError(f"Release {tag} has no download for {key.capitalize()}. "
                          f"Open the release page to see what it contains.")
    digest = str(asset.get("digest") or "")
    return Release(
        tag=tag, version=ver, name=str(data.get("name") or tag), notes=str(data.get("body") or "").strip(),
        page_url=str(data.get("html_url") or ""), asset_name=str(asset["name"]),
        asset_url=str(asset.get("browser_download_url") or ""), asset_size=int(asset.get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else "")


# ----------------------------------------------------------------- download
def download(rel: Release, dest_dir: Path, progress: Optional[Callable[[int, int], None]] = None,
             cancel=None) -> Path:
    """Download the release file into dest_dir; verifies size and SHA-256 when GitHub provided them."""
    _check_url(rel.asset_url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / re.sub(r"[^\w.\-]", "_", rel.asset_name)
    done, h, last = 0, hashlib.sha256(), 0.0
    try:
        with requests.get(rel.asset_url, headers=_headers("application/octet-stream"), stream=True,
                          timeout=30) as r:
            if not r.ok:
                raise UpdateError(f"The download failed (HTTP {r.status_code}).")
            total = int(r.headers.get("Content-Length") or rel.asset_size or 0)
            with open(path, "wb") as f:
                for chunk in r.iter_content(CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise UpdateError("Update cancelled.")
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if progress and (now - last > 0.1 or done == total):
                        progress(done, total)
                        last = now
        if rel.asset_size and done != rel.asset_size:
            raise UpdateError(f"The download is incomplete ({done:,} of {rel.asset_size:,} bytes).")
        if rel.sha256 and h.hexdigest() != rel.sha256:
            raise UpdateError("The downloaded file does not match its checksum, so it was discarded.")
    except requests.RequestException as e:
        path.unlink(missing_ok=True)
        raise UpdateError(f"The download was interrupted: {e}") from e
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _inside(root: Path, name: str) -> bool:
    try:
        (root / name).resolve().relative_to(root.resolve())
        return not Path(name).is_absolute()
    except ValueError:
        return False


def extract(archive: Path, dest: Path) -> Path:
    """Unpack a release archive; returns the single top-level folder (or .app) inside it."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if archive.name.lower().endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                if not all(_inside(dest, n) for n in z.namelist()):
                    raise UpdateError("The update archive contains unsafe paths and was rejected.")
                z.extractall(dest)
        else:
            with tarfile.open(archive) as t:
                if not all(_inside(dest, m.name) for m in t.getmembers()):
                    raise UpdateError("The update archive contains unsafe paths and was rejected.")
                if hasattr(tarfile, "data_filter"):
                    t.extractall(dest, filter="data")
                else:  # Python before 3.12 has no filter; the path check above is the guard
                    t.extractall(dest)
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
        raise UpdateError(f"The update archive could not be unpacked: {e}") from e
    top = [p for p in dest.iterdir() if not p.name.startswith(("._", "__MACOSX"))]
    if len(top) != 1:
        raise UpdateError("The update archive has an unexpected layout.")
    return top[0]


# ------------------------------------------------------------------ install
def install_target(executable: Optional[str] = None, platform: Optional[str] = None) -> Optional[Path]:
    """The installed app: its folder on Windows/Linux, the .app bundle on macOS."""
    exe = Path(executable or sys.executable)
    if (platform or sys.platform) == "darwin":
        for p in exe.parents:
            if p.suffix == ".app":
                return p
        return None
    return exe.parent


def problem(target: Optional[Path], platform: Optional[str] = None, frozen: Optional[bool] = None) -> str:
    """Why this copy cannot update itself ('' when it can)."""
    p = platform or sys.platform
    if not (getattr(sys, "frozen", False) if frozen is None else frozen):
        return "This copy is running from the source code, not from a downloaded build."
    if target is None or not target.is_dir():
        return "The installed program could not be located."
    if not target.name.startswith(core.FULL_NAME):
        return (f"The program's folder was renamed ('{target.name}'). Automatic update only replaces a "
                f"folder whose name starts with '{core.FULL_NAME}'.")
    if not os.access(target.parent, os.W_OK):
        return f"No permission to change files in '{target.parent}'."
    if p.startswith("win") and re.search(r"[%!^&]", str(target)):
        return "The program's path contains a character (% ! ^ &) that the update script cannot handle."
    return ""


def _launch_path(entry: Path, platform: str) -> Path:
    if platform == "darwin":
        if entry.suffix != ".app" or not (entry / "Contents" / "MacOS").is_dir():
            raise UpdateError("The downloaded update does not contain a macOS app.")
        return entry
    exe = entry / (entry.name + (".exe" if platform.startswith("win") else ""))
    if not exe.is_file():
        raise UpdateError("The downloaded update does not contain the program.")
    return exe


def prepare(rel: Release, target: Path, running_exe: Optional[str] = None, platform: Optional[str] = None,
            progress: Optional[Callable[[int, int], None]] = None,
            status: Optional[Callable[[str], None]] = None, cancel=None) -> Plan:
    """Download and unpack the update next to the installed app. Changes nothing that is installed."""
    p = platform or sys.platform
    say = status or (lambda s: None)
    stage = target.parent / f".{core.FULL_NAME.replace(' ', '-')}-update"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        say(f"Downloading {rel.tag} ...")
        archive = download(rel, stage, progress, cancel)
        say("Unpacking ...")
        entry = extract(archive, stage / "new")
        archive.unlink(missing_ok=True)
        if not entry.name.startswith(core.FULL_NAME):
            raise UpdateError("The downloaded update has an unexpected name.")
        launch_new_rel = _launch_path(entry, p).relative_to(entry)
        dest = target.parent / entry.name
        if dest.exists():
            raise UpdateError(f"'{dest}' already exists. Delete or move it, then try again.")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    old_exe = Path(running_exe or sys.executable)
    return Plan(version=rel.tag, stage=stage, old=target, new=entry, dest=dest,
                launch_new=dest / launch_new_rel, launch_old=target if p == "darwin" else old_exe)


_SH = """#!/bin/sh
# args: PID OLD NEW DEST LAUNCH_NEW LAUNCH_OLD STAGE MODE   (MODE: open = macOS .app, exec = plain program)
PID="$1"; OLD="$2"; NEW="$3"; DEST="$4"; LNEW="$5"; LOLD="$6"; STAGE="$7"; MODE="$8"
cd "${TMPDIR:-/tmp}" 2>/dev/null || cd /
alive() {  # running, and not just a zombie waiting for its parent to collect it
  kill -0 "$PID" 2>/dev/null || return 1
  case "$(ps -o stat= -p "$PID" 2>/dev/null)" in Z*) return 1 ;; esac
  return 0
}
i=0
while alive; do
  i=$((i+1)); [ "$i" -ge 240 ] && exit 1
  sleep 0.5
done
launch() {
  if [ "$MODE" = "open" ]; then open -n "$1"; else nohup "$1" >/dev/null 2>&1 & fi
}
rm -rf "$OLD.old"
if mv "$OLD" "$OLD.old" 2>/dev/null; then
  if mv "$NEW" "$DEST" 2>/dev/null; then
    launch "$LNEW"
    sleep 2
    rm -rf "$OLD.old" "$STAGE"
  else
    mv "$OLD.old" "$OLD"
    launch "$LOLD"
  fi
else
  launch "$LOLD"
fi
rm -f "$0"
"""

_BAT = r'''@echo off
cd /d "%TEMP%"
set "PID=%~1"
set "OLD=%~2"
set "NEW=%~3"
set "DEST=%~4"
set "LNEW=%~5"
set "LOLD=%~6"
set "STAGE=%~7"
set /a N=0
:wait
tasklist /FI "PID eq %PID%" /FO CSV /NH 2>nul | find """%PID%""" >nul
if errorlevel 1 goto gone
set /a N+=1
if %N% GEQ 120 goto end
ping -n 2 127.0.0.1 >nul
goto wait
:gone
set /a N=0
rmdir /s /q "%OLD%.old" >nul 2>&1
:swap
move "%OLD%" "%OLD%.old" >nul 2>&1
if not errorlevel 1 goto placed
set /a N+=1
if %N% GEQ 40 goto fail
ping -n 2 127.0.0.1 >nul
goto swap
:placed
move "%NEW%" "%DEST%" >nul 2>&1
if errorlevel 1 goto restore
start "" /D "%DEST%" "%LNEW%"
ping -n 3 127.0.0.1 >nul
rmdir /s /q "%OLD%.old" >nul 2>&1
rmdir /s /q "%STAGE%" >nul 2>&1
goto end
:restore
move "%OLD%.old" "%OLD%" >nul 2>&1
:fail
start "" "%LOLD%"
:end
(goto) 2>nul & del "%~f0"
'''


def start_helper(plan: Plan, pid: Optional[int] = None, platform: Optional[str] = None) -> subprocess.Popen:
    """Start the detached script that finishes the update once this program has exited."""
    p = platform or sys.platform
    pid = pid or os.getpid()
    win = p.startswith("win")
    fd, script = tempfile.mkstemp(prefix="mscw-update-", suffix=".bat" if win else ".sh")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n" if win else "\n") as f:
        f.write(_BAT if win else _SH)
    args = [str(pid), str(plan.old), str(plan.new), str(plan.dest), str(plan.launch_new),
            str(plan.launch_old), str(plan.stage)]
    if not win:
        args.append("open" if p == "darwin" else "exec")
    common = dict(cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
    if win:
        cmd = 'cmd.exe /d /s /c "' + " ".join(f'"{a}"' for a in [script] + args) + '"'
        return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                                **common)
    os.chmod(script, 0o700)
    return subprocess.Popen(["/bin/sh", script] + args, start_new_session=True, **common)
