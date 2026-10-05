#!/usr/bin/env python3
"""
usb_attack_trigger.py -- controlled lab USB demonstration trigger.

Started by vehicle-usb-attack.service, which is in turn started ONLY by the udev
rule 99-vehicle-usb-demo.rules when a specific, pre-registered demonstration USB
stick is inserted (matched by vendor/product ID and serial number).

This script does NOT execute arbitrary code found on the USB stick. It:
  1. re-verifies the inserted device's identity against EXPECTED_* below
     (defence in depth -- the udev match already restricts this, but a script
     that's about to launch something should not trust its caller blindly);
  2. writes the shared status file app.py's monitor thread reads
     (USB_DETECTED -> ATTACK_TRIGGERED);
  3. launches exactly one fixed, version-controlled payload from this same
     project directory (usb_attack_demo.py) -- never a script read off the USB;
  4. logs device identity, payload path, PID and timestamps;
  5. on device removal (called again with --removed by the udev "remove" rule),
     stops the payload and marks the state REMOVED.

Environment variables (set in vehicle-usb-attack.service):
  PROJECT_DIR       - project directory (default: this script's directory)
  EXPECTED_VENDOR   - USB vendor ID, e.g. "0781"
  EXPECTED_PRODUCT  - USB product ID, e.g. "5581"
  EXPECTED_SERIAL   - USB serial number of the registered demo stick (recommended;
                      vendor/product alone matches every stick of that model)
  ATTACKER_IP       - passed through to the payload (default 10.214.203.60)
udev also passes the device's own IDs as DEVTYPE/ID_VENDOR_ID/ID_MODEL_ID/ID_SERIAL_SHORT
via the environment when it runs the service; systemd forwards them if the .service
uses `PassEnvironment=` or the udev rule sets them with `ENV{}` before RUN+=.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.environ.get("PROJECT_DIR", HERE)
STATE_FILE = os.path.join(PROJECT_DIR, "run", "usb_state.json")
PID_FILE = os.path.join(PROJECT_DIR, "run", "usb_payload.pid")
PAYLOAD = os.path.join(PROJECT_DIR, "usb_attack_demo.py")
LOG_FILE = os.path.join(PROJECT_DIR, "usb_attack_trigger.log")

EXPECTED_VENDOR = os.environ.get("EXPECTED_VENDOR", "").lower()
EXPECTED_PRODUCT = os.environ.get("EXPECTED_PRODUCT", "").lower()
EXPECTED_SERIAL = os.environ.get("EXPECTED_SERIAL", "")
ATTACKER_IP = os.environ.get("ATTACKER_IP", "10.214.203.60")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("usb-trigger")


def write_state(**fields):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    data = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    data.update(fields)
    data["event_at"] = time.time()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, STATE_FILE)


def device_identity():
    """Identity as reported by udev in the environment. Falls back to 'unknown' fields
    rather than raising, so a misconfigured environment fails closed (verify_identity
    below will then correctly refuse to launch anything)."""
    return {
        "vendor": os.environ.get("ID_VENDOR_ID", "").lower(),
        "product": os.environ.get("ID_MODEL_ID", "").lower(),
        "serial": os.environ.get("ID_SERIAL_SHORT", ""),
        "name": os.environ.get("ID_MODEL", "unknown-device"),
    }


def verify_identity(dev):
    if not EXPECTED_VENDOR or not EXPECTED_PRODUCT:
        log.error("EXPECTED_VENDOR/EXPECTED_PRODUCT not configured -- refusing to launch anything")
        return False
    if dev["vendor"] != EXPECTED_VENDOR or dev["product"] != EXPECTED_PRODUCT:
        log.error("Device %s:%s does not match the registered demo USB (%s:%s) -- ignoring",
                  dev["vendor"], dev["product"], EXPECTED_VENDOR, EXPECTED_PRODUCT)
        return False
    if EXPECTED_SERIAL and dev["serial"] != EXPECTED_SERIAL:
        log.error("Serial %s does not match the registered demo USB (%s) -- ignoring",
                  dev["serial"], EXPECTED_SERIAL)
        return False
    return True


def handle_removed():
    log.info("Registered demo USB removed")
    pid = None
    if os.path.exists(PID_FILE):
        try:
            pid = int(open(PID_FILE).read().strip())
        except (OSError, ValueError):
            pid = None
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Stopped payload pid %d", pid)
        except ProcessLookupError:
            pass
    write_state(present=False, attack_triggered=False, status="REMOVED", payload_pid=None)


def handle_inserted():
    dev = device_identity()
    log.info("USB insertion event: vendor=%s product=%s serial=%s name=%s",
             dev["vendor"], dev["product"], dev["serial"], dev["name"])
    write_state(present=True, attack_triggered=False, status="USB_DETECTED",
                device=dev["name"], payload_pid=None)

    if not verify_identity(dev):
        write_state(status="IDLE", present=False)
        return 1
    if not os.path.exists(PAYLOAD):
        log.error("Configured payload %s not found -- refusing to launch", PAYLOAD)
        write_state(status="USB_DETECTED")
        return 1

    log.info("Identity verified -- launching configured demonstration payload %s", PAYLOAD)
    env = dict(os.environ, ATTACKER_IP=ATTACKER_IP)
    proc = subprocess.Popen([sys.executable, PAYLOAD], cwd=PROJECT_DIR, env=env)
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    log.info("Payload started: pid=%d target=%s", proc.pid, ATTACKER_IP)
    write_state(attack_triggered=True, status="ATTACK_TRIGGERED", payload_pid=proc.pid)
    return 0


if __name__ == "__main__":
    sys.exit(handle_removed() if "--removed" in sys.argv else handle_inserted())
