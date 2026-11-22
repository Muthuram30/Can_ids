#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
command -v python3 >/dev/null
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
chmod 600 .env
mkdir -p run logs
echo "Edit .env, then: bash scripts/runner.sh"
