#!/usr/bin/env bash
# Build the macOS app:  ./build_macos.sh   (needs Python 3.12 with Tk, e.g. from python.org)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -m venv .buildenv
source .buildenv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller
APPNAME=$(python tools/version.py name)
pyinstaller --noconfirm --clean mesowatcher.spec
python tools/package.py
echo "SUCCESS: dist/$APPNAME.app  (right-click > Open the first time; it is unsigned)"
