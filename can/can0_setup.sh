#!/bin/bash
# Brings up the MCP2515 as can0 on the Raspberry Pi.
#
# One-time setup, add to /boot/firmware/config.txt (Pi 5) or /boot/config.txt:
#   dtparam=spi=on
#   dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25
#
# oscillator=8000000 matches "MCP_8MHZ" used in the ESP32 firmware's CAN0.begin() calls.
# interrupt=25 matches INT -> physical pin 22 / GPIO25 in the wiring schematic.
# Reboot after editing config.txt, then run this script (or add it to a systemd unit / cron @reboot).

set -e
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 500000 restart-ms 100
sudo ip link set can0 up
ip -details link show can0
