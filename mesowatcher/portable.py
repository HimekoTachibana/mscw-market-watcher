"""Makes the packaged program run without installing anything.

* The Linux and macOS downloads carry their own Chromium (put there at build time with
  PLAYWRIGHT_BROWSERS_PATH=0; Playwright finds it by itself in a frozen program). Windows uses the Edge
  that ships with Windows.
* The Linux download is built on an old glibc (2.31), so it starts on every current distribution. Chromium
  also needs a few shared libraries that a minimal or gaming install might not have (NSS, CUPS, ATK, ...).
  Copies of those are shipped in the folder "browser-libs" but are used ONLY for the ones this computer is
  missing: browser_env() asks `ldd` what Chromium cannot find and links just those into a private folder that
  is given to the browser (never to the rest of the system). Libraries tied to the graphics driver or the
  sound system (libgbm, libdrm, libasound, ...) are never shipped: the system's own are always the right ones.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Libraries that are linked as a group: NSS loads its helper modules from the folder libnss3 came from.
NSS_GROUP = ("libnss3.so", "libnssutil3.so", "libsmime3.so", "libsoftokn3.so", "libfreebl3.so",
             "libfreeblpriv3.so", "libnspr4.so", "libplc4.so", "libplds4.so")
# What the Linux build copies into browser-libs (tools/bundle_browser_libs.py). Nothing driver- or
# sound-specific, nothing every desktop has anyway (glibc, X11/xcb, glib, cairo, pango, dbus).
BUNDLED_LIBS = NSS_GROUP + ("libcups.so.2", "libatk-1.0.so.0", "libatk-bridge-2.0.so.0", "libatspi.so.0",
                            "libxkbcommon.so.0", "libXcomposite.so.1", "libXdamage.so.1", "libXfixes.so.3",
                            "libXrandr.so.2", "libXext.so.6", "libexpat.so.1")

_NOT_FOUND_RE = re.compile(r"^\s*(\S+)\s+=>\s+not found", re.M)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Where the packaged program keeps its files (PyInstaller's _internal folder); the source folder otherwise."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def bundled_libs_dir() -> Optional[Path]:
    d = bundle_dir() / "browser-libs"
    return d if d.is_dir() else None


def local_browsers_dir() -> Optional[Path]:
    """Chromium shipped inside the program (Playwright's package-local browser folder), if any."""
    try:
        import playwright
    except ImportError:
        return None
    d = Path(playwright.__file__).resolve().parent / "driver" / "package" / ".local-browsers"
    return d if d.is_dir() and any(d.glob("chromium-*")) else None


def restore_system_library_path():
    """PyInstaller's launcher points LD_LIBRARY_PATH at the program's own libraries (built on an old Debian) so the
    frozen Python finds them. Child processes inherit that: Chromium, Playwright's driver and the sound player would
    then load those old copies (GLib, fontconfig, ...) instead of the system's and can crash on a newer system.
    The program itself has already loaded what it needs, so the system's own path is put back for everything it
    starts; Chromium then gets only the fallback libraries it is missing (browser_env)."""
    if not (frozen() and sys.platform.startswith("linux")):
        return
    orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)  # what the user had before the launcher changed it
    if orig:
        os.environ["LD_LIBRARY_PATH"] = orig
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)


def setup():
    """Called once at start-up, before Playwright or any other program is started."""
    restore_system_library_path()
    if frozen() and local_browsers_dir() is not None:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")  # Playwright does this too; harmless to be sure


def _elf_of(exe: str) -> str:
    """Chromium's real binary (some setups wrap it in a shell script next to '<name>.real')."""
    try:
        with open(exe, "rb") as f:
            if f.read(2) == b"#!":
                real = exe + ".real"
                return real if os.path.exists(real) else exe
    except OSError:
        pass
    return exe


def missing_libs(exe: str, extra_path: str = "") -> list[str]:
    """Shared libraries `exe` cannot find on this computer (empty when ldd is not available)."""
    ldd = shutil.which("ldd")
    if not ldd or not sys.platform.startswith("linux"):
        return []
    env = dict(os.environ)
    if extra_path:
        env["LD_LIBRARY_PATH"] = extra_path + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    try:
        out = subprocess.run([ldd, _elf_of(exe)], capture_output=True, text=True, timeout=20, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(set(_NOT_FOUND_RE.findall(out)))


def browser_env(exe: str, work_dir: Path) -> tuple[Optional[dict], list[str]]:
    """(environment for the browser or None when nothing is needed, libraries still missing afterwards).

    Links only the bundled copies of libraries this computer lacks into `work_dir` and puts that folder first on
    the browser's LD_LIBRARY_PATH. A bundled library may itself need another bundled one, so this repeats."""
    if not sys.platform.startswith("linux"):
        return None, []
    missing = missing_libs(exe)
    if not missing:
        return None, []
    src = bundled_libs_dir()
    if src is None:
        return None, missing
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    linked: set = set()
    for _ in range(4):
        want = set(missing)
        if want & set(NSS_GROUP):
            want |= set(NSS_GROUP)  # NSS finds its modules next to libnss3: keep the family together
        new = [n for n in want if n not in linked and (src / n).exists()]
        if not new:
            break
        for n in new:
            target = work_dir / n
            try:
                target.symlink_to(src / n)
            except OSError:
                shutil.copy2(src / n, target)
            linked.add(n)
        missing = missing_libs(exe, str(work_dir))
        if not missing:
            break
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(work_dir) + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env, missing


def is_sandbox_error(e: BaseException) -> bool:
    """Chromium refused to start because the OS blocks its sandbox (e.g. Ubuntu 24.04's AppArmor rule against
    unprivileged user namespaces for programs it does not know)."""
    t = str(e).lower()
    return "no usable sandbox" in t or ("sandbox" in t and ("namespace" in t or "setuid" in t))
