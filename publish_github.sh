#!/usr/bin/env bash
# Upload this folder (with its version history and tags) to a new GitHub repo in YOUR account.
#   ./publish_github.sh                 -> private repo (not searchable, only you can open it)
#   ./publish_github.sh public          -> public repo (anyone with the URL can open it, but GitHub search can find it)
# Needs git and the GitHub CLI (https://cli.github.com), then:  gh auth login
set -euo pipefail
cd "$(dirname "$0")"
VIS=${1:-private}
NAME=${2:-mscw-market-watcher}
command -v gh >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login
[ -d .git ] || { git init -b main && git add . && git commit -m "MSCW Market Watcher $(python3 tools/version.py)"; }
gh repo create "$NAME" "--$VIS" --source . --remote origin --push
git push origin --tags
echo "Done: $(gh repo view "$NAME" --json url -q .url)"
