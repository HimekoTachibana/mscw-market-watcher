"""macOS build only: copy the Chromium that Playwright downloaded (PLAYWRIGHT_BROWSERS_PATH=0) into the finished
.app, next to Playwright's driver, where the program looks for it.

PyInstaller cannot take Chromium itself: it re-signs every binary it collects, and macOS refuses that for the
Chromium app nested inside (it is already signed by Google). So the spec leaves it out and this copies it in
afterwards with `ditto` (keeps symlinks and signatures), then seals the outer app again with an ad-hoc signature.

Run after PyInstaller:  python tools/add_browser_macos.py
"""
import subprocess
import sys
from pathlib import Path

import playwright

if sys.platform != "darwin":
    sys.exit(0)
root = Path(__file__).resolve().parent.parent
name = subprocess.check_output([sys.executable, str(root / "tools" / "version.py"), "name"], text=True).strip()
app = root / "dist" / f"{name}.app"
src = Path(playwright.__file__).resolve().parent / "driver" / "package" / ".local-browsers"
if not src.is_dir():
    sys.exit(f"No Chromium to ship: run  PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --no-shell chromium")
# Frameworks/playwright/... may be a symlink into Resources: copy to wherever it really is
pkg = (app / "Contents" / "Frameworks" / "playwright" / "driver" / "package").resolve()
if not pkg.is_dir():
    sys.exit(f"Playwright's driver was not found in {app}")
dest = pkg / ".local-browsers"
subprocess.run(["rm", "-rf", str(dest)], check=True)
subprocess.run(["ditto", str(src), str(dest)], check=True)
subprocess.run(["codesign", "--force", "-s", "-", str(app)], check=True)
print(f"Chromium copied into {dest}")
