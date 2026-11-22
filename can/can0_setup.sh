#!/usr/bin/env bash
# Device-tree overlay must already match the actual Pi-side MCP2515 crystal/INT.
set -euo pipefail
usage() {
  echo "Usage: bash can/can0_setup.sh [channel (default: can0)] [bitrate (default: 500000)]" >&2
}
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if (( $# > 2 )); then
  usage
  exit 2
fi
channel="${1:-can0}"
bitrate="${2:-500000}"
if [[ ! "$channel" =~ ^[a-zA-Z0-9_-]+$ || ! "$bitrate" =~ ^[0-9]+$ || ! "$bitrate" =~ [1-9] ]]; then
  usage
  exit 2
fi
sudo ip link set "$channel" down
sudo ip link set "$channel" type can bitrate "$bitrate" restart-ms 100
sudo ip link set "$channel" up
ip -details link show "$channel"
