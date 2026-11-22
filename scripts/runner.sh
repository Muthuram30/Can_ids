#!/usr/bin/env bash
# Launch only. Initial installation and network changes are explicit separate steps.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run: bash scripts/setup.sh" >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Copy .env.example to .env and edit it before starting." >&2
  exit 1
fi
exec .venv/bin/python app.py
