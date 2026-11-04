"""Print the app version / packaged name (used by the build scripts and CI)."""
import re
import sys
from pathlib import Path

src = (Path(__file__).resolve().parent.parent / "mesowatcher" / "core.py").read_text(encoding="utf-8")
version = re.search(r'^VERSION = "([^"]+)"', src, re.M).group(1)
full = re.search(r'^FULL_NAME = "([^"]+)"', src, re.M).group(1)
if len(sys.argv) > 1 and sys.argv[1] == "name":
    print(f"{full} v{version}")
else:
    print(version)
