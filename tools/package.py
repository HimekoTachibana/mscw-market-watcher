"""Zip/tar the finished build into release/ with the version and OS in the file name.
Run after PyInstaller:  python tools/package.py"""
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
name = subprocess.check_output([sys.executable, str(root / "tools" / "version.py"), "name"], text=True).strip()
os_label = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
out = root / "release"
out.mkdir(exist_ok=True)
dist = root / "dist"
src = dist / f"{name}.app" if sys.platform == "darwin" else dist / name
if not src.exists():
    sys.exit(f"Build output not found: {src}")
base = out / f"{name} ({os_label})"
if sys.platform == "win32":
    path = shutil.make_archive(str(base), "zip", root_dir=dist, base_dir=src.name)
else:  # tar keeps the executable permission bits
    path = shutil.make_archive(str(base), "gztar", root_dir=dist, base_dir=src.name)
print(path)
