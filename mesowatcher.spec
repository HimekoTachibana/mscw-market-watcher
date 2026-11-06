# PyInstaller spec: works the same on Windows, Linux and macOS.
# Build with:  pyinstaller mesowatcher.spec
# Produces  dist/MSCW Market Watcher v<version>/  containing  MSCW Market Watcher v<version>[.exe]
# (macOS: dist/MSCW Market Watcher v<version>.app). The version comes from mesowatcher/core.py.
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

_src = (Path(SPECPATH) / "mesowatcher" / "core.py").read_text(encoding="utf-8")
VERSION = re.search(r'^VERSION = "([^"]+)"', _src, re.M).group(1)
FULL = re.search(r'^FULL_NAME = "([^"]+)"', _src, re.M).group(1)
NAME = f"{FULL} v{VERSION}"

# Playwright's driver, plus the Chromium installed into it with PLAYWRIGHT_BROWSERS_PATH=0 (Linux, macOS builds)
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

# Linux: fallback copies of libraries Chromium needs, used only where the user's system lacks them (portable.py)
_libs = Path(SPECPATH) / "build" / "browser-libs"
extra_datas = [(str(_libs), "browser-libs")] if sys.platform.startswith("linux") and _libs.is_dir() else []

a = Analysis(
    ["run.py"],
    binaries=pw_binaries,
    datas=[("CHANGELOG.md", "."), ("mesowatcher/icon_ids.txt", "mesowatcher")] + pw_datas + extra_datas,
    hiddenimports=["PIL._tkinter_finder", "greenlet", "pyee", "pyee.asyncio"] + pw_hidden,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{NAME}.app", bundle_identifier="com.mscw.marketwatcher", version=VERSION)
