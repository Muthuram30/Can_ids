#!/usr/bin/env bash
# Run on the Pi: bash scripts/update.sh [expected-origin-main-sha]
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
expected="${1:-}"
[[ -z "$expected" || "$expected" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$(git branch --show-current)" == main ]] || { echo "Switch to main first." >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "Pi checkout has edits; commit/stash them first." >&2; exit 1; }
git fetch origin main
target="$(git rev-parse origin/main)"
[[ -z "$expected" || "$expected" == "$target" ]] || { echo "Remote main changed; deployment cancelled." >&2; exit 1; }
git merge-base --is-ancestor HEAD "$target" || { echo "Pi history diverged; resolve it first." >&2; exit 1; }
previous="$(git rev-parse HEAD)"
git branch "backup/pi-before-update-$(date +%Y%m%d-%H%M%S)-$$" "$previous"
git merge --ff-only "$target"
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
if systemctl --user is-active --quiet vehicle-ids.service; then
  systemctl --user restart vehicle-ids.service
  sleep 2
  systemctl --user is-active --quiet vehicle-ids.service
  .venv/bin/python scripts/healthcheck.py
else
  echo "Service not running. Start: bash scripts/runner.sh"
fi
echo "Updated from $previous to $target. Per-device .env was preserved."
