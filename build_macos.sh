#!/usr/bin/env bash
# Build the macOS app:  ./build_macos.sh   (needs Python 3.12 with Tk, e.g. from python.org)
# The app carries its own Chromium, so it runs without Chrome or anything else installed.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -m venv .buildenv
source .buildenv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install --no-shell chromium
APPNAME=$(python tools/version.py name)
pyinstaller --noconfirm --clean mesowatcher.spec
python tools/add_browser_macos.py
python tools/package.py
echo "SUCCESS: dist/$APPNAME.app  (right-click > Open the first time; it is unsigned)"
