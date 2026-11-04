#!/usr/bin/env bash
# Build the Linux app:  ./build_linux.sh
# Result: dist/"MSCW Market Watcher v<version>"/  and a .tar.gz in release/
set -euo pipefail
cd "$(dirname "$0")"
echo "=== MSCW Market Watcher - Linux build ==="

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "python3 not found. Install it: sudo apt install python3 python3-venv"; exit 1; }
"$PY" -c "import tkinter" 2>/dev/null || { echo "Tk is missing. Install it: sudo apt install python3-tk  (Fedora: sudo dnf install python3-tkinter)"; exit 1; }
"$PY" -m venv .buildenv 2>/dev/null || { echo "venv is missing. Install it: sudo apt install python3-venv"; exit 1; }
# shellcheck disable=SC1091
source .buildenv/bin/activate

python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller

APPNAME=$(python tools/version.py name)
echo "Building \"$APPNAME\" ..."
pyinstaller --noconfirm --clean mesowatcher.spec
[ -x "dist/$APPNAME/$APPNAME" ] || { echo "BUILD FAILED"; exit 1; }
python tools/package.py

echo
echo "SUCCESS"
echo "  Folder:  dist/$APPNAME/   (run ./\"$APPNAME\" inside it)"
echo "  Archive: release/"
echo
echo "First run on a machine without Chrome/Edge: install the browser Playwright uses once:"
echo "  .buildenv/bin/python -m playwright install chromium"
echo "and choose 'chromium' under Settings -> Browser. Sound needs 'paplay' or 'aplay' (sudo apt install alsa-utils)."
