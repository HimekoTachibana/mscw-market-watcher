"""Linux build only: copy the shared libraries listed in mesowatcher/portable.py (BUNDLED_LIBS) from the build
machine into build/browser-libs, which the spec ships as "browser-libs". At run time a copy is used only when the
user's computer does not have that library (see portable.browser_env).

Run after `playwright install` and before PyInstaller:  python tools/bundle_browser_libs.py
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from mesowatcher.portable import BUNDLED_LIBS  # noqa: E402

if not sys.platform.startswith("linux"):
    sys.exit(0)

out = root / "build" / "browser-libs"
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)

cache = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
found = {}
for line in cache.splitlines():
    m = re.match(r"\s*(\S+)\s+\(([^)]*)\)\s+=>\s+(\S+)", line)
    if m and ("x86-64" in m.group(2) or "aarch64" in m.group(2)):
        found.setdefault(m.group(1), m.group(3))

# NSS's plugin modules (softokn3, freebl3) are loaded at run time, so Debian keeps them in a "nss" subfolder that
# the ldconfig cache does not list. They are shipped next to libnss3, where NSS looks first.
EXTRA_DIRS = ("/usr/lib/x86_64-linux-gnu/nss", "/usr/lib/aarch64-linux-gnu/nss", "/usr/lib64/nss", "/usr/lib/nss",
              "/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib")

missing = []
for name in BUNDLED_LIBS:
    src = found.get(name) or next((str(Path(d) / name) for d in EXTRA_DIRS if (Path(d) / name).exists()), None)
    if not src:
        missing.append(name)
        continue
    shutil.copy2(Path(src).resolve(), out / name)  # the real file, saved under its soname
    print(f"bundled {name}  <-  {src}")

if missing:
    sys.exit("These libraries were not found on the build machine: " + ", ".join(missing))
print(f"{len(BUNDLED_LIBS)} fallback libraries in {out}")
