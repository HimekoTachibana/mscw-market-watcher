#!/usr/bin/env bash
# Build the Linux app:  ./build_linux.sh
# Result: dist/"MSCW Market Watcher v<version>"/  and a .tar.gz in release/
#
# The finished program is portable: it carries its own Python, Tk and Chromium and runs on any distribution with
# a glibc at least as new as the one it was BUILT on. For a download that runs everywhere, use the GitHub Actions
# build (it builds on Debian 11, glibc 2.31). A build made here only runs on systems as new as this one.
set -euo pipefail
cd "$(dirname "$0")"
echo "=== MSCW Market Watcher - Linux build ==="

PY=${PYTHON:-python3}
hint="install Python 3.12 or newer with Tk and venv from your distribution's packages"
command -v "$PY" >/dev/null || { echo "python3 not found: $hint"; exit 1; }
"$PY" -c "import tkinter" 2>/dev/null || { echo "Python's Tk module is missing: $hint (the package is usually called python3-tk or python3-tkinter; on Arch it is tk)"; exit 1; }
"$PY" -m venv .buildenv 2>/dev/null || { echo "Python's venv module is missing: $hint"; exit 1; }
# shellcheck disable=SC1091
source .buildenv/bin/activate

python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller

echo "Downloading the Chromium that is shipped inside the program ..."
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --no-shell chromium
python tools/bundle_browser_libs.py

APPNAME=$(python tools/version.py name)
echo "Building \"$APPNAME\" ..."
pyinstaller --noconfirm --clean mesowatcher.spec
[ -x "dist/$APPNAME/$APPNAME" ] || { echo "BUILD FAILED"; exit 1; }
python tools/package.py

echo
echo "SUCCESS"
echo "  Folder:  dist/$APPNAME/   (run ./\"$APPNAME\" inside it - nothing to install)"
echo "  Archive: release/"
echo "  Runs on systems with glibc $(ldd --version | head -1 | grep -oE '[0-9]+\.[0-9]+$') or newer."
