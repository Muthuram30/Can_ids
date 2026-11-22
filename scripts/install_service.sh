#!/usr/bin/env bash
# Per-user service: no hard-coded username, no root Flask process.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -x "$project_dir/.venv/bin/python" && -f "$project_dir/.env" ]] || { echo "Run setup.sh first." >&2; exit 1; }
# systemd's ExecStart handles quoted paths but % is a specifier.
[[ "$project_dir" != *'%'* && "$project_dir" != *'"'* && "$project_dir" != *'\'* ]] || { echo "Use a simple project path." >&2; exit 1; }
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/vehicle-ids.service" <<EOF
[Unit]
Description=CAN IDS lab dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory="$project_dir"
ExecStart="$project_dir/.venv/bin/python" "$project_dir/app.py"
Restart=on-failure
RestartSec=3
KillSignal=SIGINT

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now vehicle-ids.service
echo "For boot without SSH login: sudo loginctl enable-linger $USER"
echo "Logs: journalctl --user -u vehicle-ids.service -f"
