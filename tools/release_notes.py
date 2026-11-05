"""Build the notes of a release from CHANGELOG.md so that no change is ever left out.

The notes hold the section of the version being released AND the section of every earlier version that no
published release has described yet (e.g. a version that was never released on its own). A version counts as
described when a release exists with its tag, or when a release's notes already contain its "## vX.Y.Z" heading.

    python tools/release_notes.py CHANGELOG.md v0.5.6 releases.jsonl > notes.md

releases.jsonl: one JSON object per line, {"tag": "v0.5.5", "body": "..."}, one for each published release
(CI makes it with `gh api`). Without it only the current version's section is used.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^## v(\d+(?:\.\d+)*)\b.*$", re.M)


def ver(text: str) -> tuple:
    m = re.search(r"(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def sections(changelog: str) -> list[tuple[tuple, str, str]]:
    """[(version tuple, heading line, body)] in the order of the file (newest first)."""
    found = list(HEADING.finditer(changelog))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(changelog)
        out.append((ver(m.group(1)), m.group(0).strip(), changelog[m.end():end].strip("\n")))
    return out


def documented(releases: list[dict]) -> set[tuple]:
    seen: set[tuple] = set()
    for r in releases:
        if r.get("tag"):
            seen.add(ver(r["tag"]))
        for m in HEADING.finditer(r.get("body") or ""):
            seen.add(ver(m.group(1)))
    return seen


def build_notes(changelog: str, current: str, releases: list[dict] | None = None) -> str:
    cur = ver(current)
    seen = documented(releases or [])
    seen.discard(cur)  # the release being made is not published yet (a re-run must still describe it)
    picked = [(v, h, b) for v, h, b in sections(changelog)
              if v == cur or (releases is not None and v < cur and v not in seen)]
    if not any(v == cur for v, _, _ in picked):
        return f"Release {current}\n"
    if len(picked) == 1:
        return picked[0][2].strip() + "\n"
    parts = []
    for v, h, b in picked:
        parts.append(f"{h}\n\n{b.strip()}")
    note = ("This release also lists the changes of earlier versions that were never published as their own "
            "release.\n\n")
    return note + "\n\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    changelog = Path(argv[0]).read_text(encoding="utf-8")
    releases = None  # no history available: only the current version
    if len(argv) > 2 and Path(argv[2]).exists():
        releases = []
        for line in Path(argv[2]).read_text(encoding="utf-8").splitlines():
            if line.strip():
                releases.append(json.loads(line))
    sys.stdout.write(build_notes(changelog, argv[1], releases))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
