#!/usr/bin/env python3
"""Monitor one registered USB; launch only this repository's fixed lab demo."""
import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
STATE_FILE = ROOT / os.getenv("USB_STATE_FILE", "run/usb_state.json")
PAYLOAD = ROOT / "usb" / "usb_attack_demo.py"
log = logging.getLogger("usb-trigger")
stopping = False


def write_state(**fields):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fields["event_at"] = time.time()
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(fields), encoding="utf-8")
    temporary.replace(STATE_FILE)


def device_identity(path):
    return {key: (path / filename).read_text().strip() for key, filename in
            (("vendor", "idVendor"), ("product", "idProduct"), ("serial", "serial"))}


def verify_identity(identity):
    expected = {key: os.getenv("EXPECTED_" + key.upper(), "") for key in ("vendor", "product", "serial")}
    expected["vendor"] = expected["vendor"].lower()
    expected["product"] = expected["product"].lower()
    return all(expected.values()) and all(identity.get(key) == value for key, value in expected.items())


def stop(signum, frame):
    global stopping
    stopping = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="USB sysfs name supplied by udev, e.g. 1-1.3")
    name = parser.parse_args().device
    if not re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", name):
        raise SystemExit("Invalid USB sysfs device name")
    path = Path("/sys/bus/usb/devices") / name
    try:
        identity = device_identity(path)
    except OSError:
        raise SystemExit("USB device disappeared or has no registered serial")
    if not verify_identity(identity):
        raise SystemExit("USB identity mismatch; fixed demo not launched")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.basicConfig(level=logging.INFO)
    proc = subprocess.Popen([sys.executable, str(PAYLOAD)], cwd=ROOT)
    event_id = uuid.uuid4().hex
    log.warning("Registered USB %s: fixed lab demo PID %s", name, proc.pid)
    try:
        while path.exists() and not stopping:
            write_state(present=True, attack_triggered=True, status="MONITORING",
                        device=name, event_id=event_id,
                        payload_pid=proc.pid if proc.poll() is None else None)
            time.sleep(1)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        write_state(present=False, attack_triggered=False, status="REMOVED", device=name, payload_pid=None)


if __name__ == "__main__":
    main()
