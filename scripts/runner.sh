#!/bin/bash
# ============================================================================
# CAN IDS HIL - Complete System Initialization Script
# ============================================================================
# This script performs comprehensive system initialization and can be run
# repeatedly for recovery/reinitialization.
#
# Usage: ./scripts/runner.sh
#
# The script:
# 1. Checks Linux/Raspberry Pi environment
# 2. Verifies Python and creates/activates venv
# 3. Installs Python dependencies
# 4. Loads .env configuration
# 5. Configures can0 (if hardware present)
# 6. Configures wlan1 AP (if hardware present)
# 7. Starts/restarts hostapd and dnsmasq
# 8. Verifies candump availability
# 9. Starts IDS application
#
# IMPORTANT: Does NOT run apt install on every execution - checks first!
# ============================================================================

set -u

# Configuration
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"

# Colors for output
RED=$'\e[31m'
GREEN=$'\e[32m'
YELLOW=$'\e[33m'
BLUE=$'\e[34m'
RST=$'\e[0m'

info() {  echo "${BLUE}[INFO]${RST} $*"; }
ok() {    echo "${GREEN}[ OK ]${RST} $*"; }
warn() {  echo "${YELLOW}[WARN]${RST} $*"; }
error() { echo "${RED}[FAIL]${RST} $*"; }

# ============================================================================
# 1. Environment Check
# ============================================================================

info "CAN IDS HIL System Initialization"
info "Project directory: $PROJECT_DIR"

# Check if on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    error "This script requires Linux (Raspberry Pi OS)"
    exit 1
fi

# Check if Raspberry Pi
if [[ -f /proc/device-tree/model ]]; then
    MODEL=$(cat /proc/device-tree/model)
    info "Detected: $MODEL"
else
    warn "Could not detect Raspberry Pi model"
fi

# ============================================================================
# 2. Python Environment
# ============================================================================

info "Checking Python environment..."

# Find Python 3
PYTHON=""
for cmd in python3.11 python3.10 python3.9 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "Python 3 not found. Install with: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PYTHON_VERSION=$($PYTHON --version)
ok "Found: $PYTHON_VERSION"

# Create/activate virtual environment
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
ok "Virtual environment activated"

# ============================================================================
# 3. Python Dependencies
# ============================================================================

info "Installing/updating Python dependencies..."
pip install --quiet --upgrade pip

if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
    pip install --quiet -r "$PROJECT_DIR/requirements.txt"
    ok "Python dependencies installed"
else
    warn "requirements.txt not found"
fi

# ============================================================================
# 4. Load Configuration
# ============================================================================

info "Loading configuration..."

if [[ -f "$ENV_FILE" ]]; then
    # Source .env file (simple key=value parser)
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    ok "Configuration loaded from .env"
else
    warn ".env file not found - using defaults"
    warn "Copy .env.example to .env and configure"
fi

# Set defaults if not in .env
CAN_INTERFACE="${CAN_INTERFACE:-can0}"
CAN_BITRATE="${CAN_BITRATE:-500000}"
AP_IFACE="${AP_IFACE:-wlan1}"
AP_IP="${AP_IP:-10.50.0.1}"
APP_PORT="${APP_PORT:-5000}"

# ============================================================================
# 5. CAN Interface Configuration
# ============================================================================

info "Checking CAN interface: $CAN_INTERFACE..."

if ip link show "$CAN_INTERFACE" &>/dev/null; then
    # Interface exists
    ok "$CAN_INTERFACE exists"
    
    # Check if up
    STATE=$(ip -br link show "$CAN_INTERFACE" | awk '{print $2}')
    if [[ "$STATE" != "UP" ]]; then
        info "Bringing up $CAN_INTERFACE..."
        sudo ip link set "$CAN_INTERFACE" down 2>/dev/null || true
        sudo ip link set "$CAN_INTERFACE" type can bitrate "$CAN_BITRATE" restart-ms 100
        sudo ip link set "$CAN_INTERFACE" up
        ok "$CAN_INTERFACE up @ ${CAN_BITRATE} bps"
    else
        ok "$CAN_INTERFACE already up"
    fi
else
    warn "$CAN_INTERFACE not found (MCP2515 not detected)"
    warn "Application will retry CAN connection automatically"
    warn "Check: dmesg | grep -i mcp251x"
fi

# ============================================================================
# 6. Wi-Fi AP Configuration
# ============================================================================

info "Checking Wi-Fi AP interface: $AP_IFACE..."

if [[ -d "/sys/class/net/$AP_IFACE" ]]; then
    ok "$AP_IFACE exists"
    
    # Unblock Wi-Fi
    sudo rfkill unblock wifi 2>/dev/null || true
    
    # Disable NetworkManager management
    if command -v nmcli &>/dev/null; then
        sudo nmcli device set "$AP_IFACE" managed no 2>/dev/null || true
    fi
    
    # Configure IP
    sudo ip link set "$AP_IFACE" up
    sudo ip addr flush dev "$AP_IFACE"
    sudo ip addr add "${AP_IP}/24" dev "$AP_IFACE"
    
    CURRENT_IP=$(ip -4 -o addr show dev "$AP_IFACE" | awk '{print $4}')
    if [[ "$CURRENT_IP" == "${AP_IP}/24" ]]; then
        ok "$AP_IFACE configured: $CURRENT_IP"
    else
        warn "$AP_IFACE has IP: ${CURRENT_IP:-none} (expected ${AP_IP}/24)"
    fi
else
    warn "$AP_IFACE not found (USB Wi-Fi dongle not connected?)"
    warn "Application will monitor and recover automatically"
fi

# ============================================================================
# 7. Network Services
# ============================================================================

info "Checking network services..."

# hostapd
if systemctl is-active --quiet hostapd; then
    ok "hostapd already running"
else
    info "Starting hostapd..."
    sudo systemctl restart hostapd 2>/dev/null || warn "hostapd not configured"
    sleep 2
    if systemctl is-active --quiet hostapd; then
        ok "hostapd started"
    else
        warn "hostapd not running - check: sudo journalctl -u hostapd -n 20"
    fi
fi

# dnsmasq
if systemctl is-active --quiet dnsmasq; then
    ok "dnsmasq already running"
else
    info "Starting dnsmasq..."
    sudo systemctl restart dnsmasq 2>/dev/null || warn "dnsmasq not configured"
    sleep 1
    if systemctl is-active --quiet dnsmasq; then
        ok "dnsmasq started"
    else
        warn "dnsmasq not running - check: sudo systemctl status dnsmasq"
    fi
fi

# ============================================================================
# 8. CAN Utilities
# ============================================================================

info "Checking CAN utilities..."

if command -v candump &>/dev/null; then
    ok "candump available: $(command -v candump)"
else
    warn "candump not found"
    info "Installing can-utils..."
    sudo apt install -y can-utils
    
    if command -v candump &>/dev/null; then
        ok "candump installed"
    else
        error "Failed to install candump"
    fi
fi

# ============================================================================
# 9. USB Demo Service
# ============================================================================

info "Checking USB demo service..."

if systemctl list-unit-files vehicle-usb-attack.service &>/dev/null; then
    if systemctl is-enabled --quiet vehicle-usb-attack.service; then
        ok "USB demo service installed and enabled"
    else
        warn "USB demo service installed but not enabled"
        info "Enable with: sudo systemctl enable vehicle-usb-attack.service"
    fi
else
    warn "USB demo service not installed"
    info "Install with: sudo ./scripts/install_usb_demo.sh"
fi

# ============================================================================
# 10. Application Startup
# ============================================================================

info "Preparing to start application..."

# Check if port already in use
if ss -ltn "sport = :$APP_PORT" 2>/dev/null | grep -q LISTEN; then
    warn "Port $APP_PORT already in use"
    info "Stopping old instance..."
    sudo fuser -k "${APP_PORT}/tcp" 2>/dev/null || true
    sleep 2
fi

# Print summary
echo ""
echo "============================================================================"
echo "SYSTEM STATUS"
echo "============================================================================"
echo ""
echo "CAN:        $CAN_INTERFACE ($(ip -br link show "$CAN_INTERFACE" 2>/dev/null | awk '{print $2}' || echo 'DOWN'))"
echo "Wi-Fi AP:   $AP_IFACE ($(ip -4 -o addr show dev "$AP_IFACE" 2>/dev/null | awk '{print $4}' || echo 'DOWN'))"
echo "hostapd:    $(systemctl is-active hostapd)"
echo "dnsmasq:    $(systemctl is-active dnsmasq)"
echo "candump:    $(command -v candump &>/dev/null && echo 'available' || echo 'missing')"
echo "Python:     $PYTHON_VERSION (venv)"
echo "Port:       $APP_PORT"
echo ""
echo "Dashboard:  http://$(hostname -I | awk '{print $1}'):$APP_PORT"
echo "            http://${AP_IP}:$APP_PORT (from Vehicle-IDS AP)"
echo ""
echo "============================================================================"
echo ""

# Start application
info "Starting CAN IDS application..."
info "Press Ctrl+C to stop"
echo ""

cd "$PROJECT_DIR"
exec python3 app.py
