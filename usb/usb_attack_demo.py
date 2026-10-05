#!/usr/bin/env python3
"""
usb_attack_demo.py -- controlled lab demonstration payload.

This is the ONLY payload usb_attack_trigger.py will ever launch, and it is a fixed,
version-controlled file in this project (never something read off the USB stick
itself). It exists purely to generate a detectable, IDS-visible network event so
the intrusion-detection demonstration has something real to catch:

  - it makes a small, fixed number of outbound TCP connection attempts to
    ATTACKER_IP:ATTACKER_PORT, spaced a few seconds apart;
  - every attempt is logged loudly, to the terminal/journal and to a log file,
    so the "attack" is an observable, announced event, not a disguised one;
  - it holds each connection open briefly (or fails and moves on) and then
    stops after MAX_ATTEMPTS -- no retry loop that runs forever;
  - it never touches the filesystem outside its own log/state files, never
    scans, never attempts credential access, and executes no remote commands.

It exits on SIGTERM (sent by usb_attack_trigger.py on USB removal, or by app.py's
containment step once the IDS blocks it).
"""
import logging
import os
import signal
import socket
import sys
import time

ATTACKER_IP = os.environ.get("ATTACKER_IP", "10.214.203.60")
ATTACKER_PORT = int(os.environ.get("ATTACKER_PORT", "4444"))  # arbitrary fixed demo port; both ends must agree
MAX_ATTEMPTS = int(os.environ.get("USB_DEMO_MAX_ATTEMPTS", "6"))
ATTEMPT_INTERVAL = float(os.environ.get("USB_DEMO_INTERVAL", "3"))
CONNECT_TIMEOUT = 2.0

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "usb_attack_demo.log")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("usb-demo-payload")

_stop = False


def _handle_term(signum, frame):
    global _stop
    log.warning("Received signal %d — stopping demo payload", signum)
    _stop = True


signal.signal(signal.SIGTERM, _handle_term)
signal.signal(signal.SIGINT, _handle_term)


def main():
    log.warning("=== DEMO ATTACK PAYLOAD STARTED (lab use only) ===")
    log.warning("Target (configured, not discovered): %s:%d", ATTACKER_IP, ATTACKER_PORT)
    for i in range(1, MAX_ATTEMPTS + 1):
        if _stop:
            break
        log.warning("Attempt %d/%d: connecting to %s:%d ...", i, MAX_ATTEMPTS, ATTACKER_IP, ATTACKER_PORT)
        try:
            with socket.create_connection((ATTACKER_IP, ATTACKER_PORT), timeout=CONNECT_TIMEOUT) as s:
                log.warning("Attempt %d: CONNECTED to %s:%d", i, ATTACKER_IP, ATTACKER_PORT)
                try:
                    s.sendall(b"VEHICLE-IDS-DEMO-PROBE\n")
                except OSError:
                    pass
                time.sleep(1)
        except OSError as e:
            log.warning("Attempt %d: connection failed (%s) — this is expected if nothing is listening", i, e)
        if not _stop:
            time.sleep(ATTEMPT_INTERVAL)
    log.warning("=== DEMO ATTACK PAYLOAD FINISHED (%s) ===", "stopped" if _stop else "attempts exhausted")


if __name__ == "__main__":
    main()
