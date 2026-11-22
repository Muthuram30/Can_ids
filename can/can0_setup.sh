#!/usr/bin/env bash
# Device-tree overlay must already match the actual Pi-side MCP2515 crystal/INT.
set -euo pipefail
channel="${1:-can0}"
bitrate="${2:-500000}"
[[ "$channel" =~ ^[a-zA-Z0-9_-]+$ && "$bitrate" =~ ^[0-9]+$ ]] || exit 2
sudo ip link set "$channel" down
sudo ip link set "$channel" type can bitrate "$bitrate" restart-ms 100
sudo ip link set "$channel" up
ip -details link show "$channel"
