#!/usr/bin/env python3
"""
Central Raspberry Pi controller for the CAN-bus vehicle testbed.

Bridges the web dashboard (joystick + solenoid buttons) to the CAN bus,
and continuously listens for sensor / status / heartbeat frames from the
ESP32 ECUs so the dashboard shows live, always-on telemetry.

Vehicle-IDS: a background monitor thread polls the dedicated Vehicle-IDS AP
interface (wlan1) and the configured attacker client once per second and drives
the SAFE -> UNSAFE (countdown) -> BLOCKED state machine. Nothing depends on the
browser or on app.py being restarted when the Wi-Fi dongle comes and goes.

Requires: pip install flask python-can scikit-learn numpy joblib
can0 is opened lazily and retried, so the app also starts (and the IDS demo
works) while can0 is down -- see can0_setup.sh to bring it up.
The CAN ML anomaly toggle needs can_ids_model.joblib next to this file --
generate it once with: python3 train_can_ids_model.py
"""
import can
import collections
import json
import logging
import math
import os
import re
import signal
import subprocess
import threading
import time
from flask import Flask, jsonify, request, render_template

from can_features import WINDOW_SECONDS as ML_WINDOW_SECONDS, extract_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("vehicle-ids")
logging.getLogger("werkzeug").setLevel(logging.WARNING)  # dashboard polls every 300 ms; keep terminal readable

# ================================================================================
# INTRUSION DETECTION CONFIG
# ---------------------------------------------------------------------------
# AP_IFACE / AP_IP : the dedicated Vehicle-IDS Wi-Fi AP interface and its address
#                    (wlan1 = 10.50.0.1/24). wlan0 (normal network) is never touched.
# ATTACKER_IP      : attacker laptop's DHCP reservation on the Vehicle-IDS subnet.
# ATTACKER_MAC     : OPTIONAL. If set, the attacker is tracked by MAC, so it is still
#                    found if DHCP hands it a different address.
# BLOCK_DELAY      : seconds of visible countdown between detection and block.
# REARM_COOLDOWN   : seconds the attacker must be gone before the system re-arms.
# All values can be overridden with environment variables of the same name.
# ================================================================================
AP_IFACE = os.environ.get("AP_IFACE", "wlan1")
AP_IP = os.environ.get("AP_IP", "10.50.0.1")
ATTACKER_IP = os.environ.get("ATTACKER_IP", "10.214.203.60")
ATTACKER_MAC = os.environ.get("ATTACKER_MAC", "").strip().lower()
BLOCK_DELAY = int(os.environ.get("BLOCK_DELAY", "18"))
REARM_COOLDOWN = int(os.environ.get("REARM_COOLDOWN", "5"))

USB_STATE_FILE = os.environ.get("USB_STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run", "usb_state.json"))
USB_PRESENCE_TIMEOUT = 6.0     # if usb_attack_trigger.py hasn't updated the state file in this long, treat the USB as gone

POLL_INTERVAL = 1.0            # monitor period, seconds
ABSENT_TICKS_BEFORE_CANCEL = 3  # tolerate brief probe misses (Wi-Fi power save) during countdown
HTTP_PRESENCE_WINDOW = 4.0     # an HTTP request from the attacker counts as "present" for this long
SERVICE_CHECK_INTERVAL = 5.0   # hostapd/dnsmasq status refresh
STATUS_LOG_INTERVAL = 10.0     # periodic one-line status in the terminal
AUTO_FIX_AP = os.environ.get("AUTO_FIX_AP", "1") == "1"  # re-apply wlan1 IP + restart hostapd/dnsmasq if wlan1 returns without its address
FIX_COOLDOWN = 20.0

# ---------------- CAN IDs (must match ECU firmware / project ID map) ----------------
ID_PI_HEARTBEAT       = 0x010
ID_MOTOR_HEARTBEAT    = 0x011
ID_SENSOR_HEARTBEAT   = 0x013
ID_SECURITY_HEARTBEAT = 0x014
ID_MOTOR_CMD           = 0x100   # Pi -> Motor ECU
ID_MOTOR_STATUS        = 0x101   # Motor ECU -> Pi
ID_TOF_DIST            = 0x120   # Sensor ECU -> Pi
ID_ULTRASONIC_DIST     = 0x121   # Sensor ECU -> Pi
ID_OBSTACLE_STATUS     = 0x122   # Sensor ECU -> Pi
ID_LOCK_CMD             = 0x140  # Pi -> Security ECU
ID_LOCK_STATUS          = 0x141  # Security ECU -> Pi

CAN_CHANNEL = "can0"
CONTROL_PATHS = {"/api/joystick", "/api/solenoid"}  # endpoints refused for a blocked attacker

# ---------------- CAN ML anomaly detection (Isolation Forest, see train_can_ids_model.py) ----------------
ML_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "can_ids_model.joblib")
ml_bundle = None          # {"scaler", "model", "feature_names", "window_seconds"} once loaded
ml_load_error = None
try:
    import joblib
    import numpy as np
except ImportError as e:
    joblib = None
    ml_load_error = f"scikit-learn/numpy/joblib not installed ({e})"


def load_ml_model():
    global ml_bundle, ml_load_error
    if ml_bundle is not None or joblib is None:
        return
    try:
        ml_bundle = joblib.load(ML_MODEL_PATH)
        log.info("ML: loaded %s (trained on %d features)", ML_MODEL_PATH, len(ml_bundle["feature_names"]))
    except (OSError, ValueError, KeyError) as e:
        ml_load_error = f"could not load {ML_MODEL_PATH} ({e}) -- run train_can_ids_model.py"
        log.warning("ML: %s", ml_load_error)


can_window_lock = threading.Lock()
can_window = collections.deque()  # (timestamp, arbitration_id, data) kept for the last ML_WINDOW_SECONDS


def record_can_frame(ts, arbitration_id, data):
    with can_window_lock:
        can_window.append((ts, arbitration_id, bytes(data)))
        cutoff = ts - ML_WINDOW_SECONDS
        while can_window and can_window[0][0] < cutoff:
            can_window.popleft()


def ml_score_now():
    """Returns (score, is_anomaly) for the current sliding window, or (None, False) if
    the model isn't loaded. score follows sklearn's convention: positive = normal,
    negative = anomalous (so the dashboard can show it directly as a signed number)."""
    if ml_bundle is None:
        load_ml_model()
    if ml_bundle is None:
        return None, False
    with can_window_lock:
        frames = list(can_window)
    feats = extract_features(frames, ml_bundle["window_seconds"])
    x = ml_bundle["scaler"].transform([feats])
    score = float(ml_bundle["model"].decision_function(x)[0])
    anomaly = bool(ml_bundle["model"].predict(x)[0] == -1)
    return score, anomaly

app = Flask(__name__)

# ---------------- CAN bus (opened lazily, re-opened if can0 goes away) ----------------
bus = None
_can_err_logged = False


def get_bus():
    """Return the open CAN bus, or try to open it. Returns None while can0 is unavailable."""
    global bus, _can_err_logged
    if bus is None:
        try:
            bus = can.interface.Bus(channel=CAN_CHANNEL, bustype="socketcan")
            _can_err_logged = False
            log.info("CAN: %s opened", CAN_CHANNEL)
        except Exception as e:  # can0 missing / down
            if not _can_err_logged:
                log.warning("CAN: %s unavailable (%s) -- retrying every 3 s", CAN_CHANNEL, e)
                _can_err_logged = True
            bus = None
    return bus


def can_send(msg):
    b = bus
    if b is None:
        return False
    try:
        b.send(msg)
        return True
    except (can.CanError, OSError):
        return False


state_lock = threading.Lock()
state = {
    "motor_cmd": "S",
    "motor_status": "S",
    "lock_state": "OFF",
    "tof_mm": None,
    "us_left_cm": None,
    "us_right_cm": None,
    "obstacle_flags": 0,
    "can_up": False,
    "nodes": {
        "motor":    {"online": False, "last_seen": 0},
        "sensor":   {"online": False, "last_seen": 0},
        "security": {"online": False, "last_seen": 0},
    },
}

NODE_TIMEOUT = 2.0  # seconds without a heartbeat/frame -> mark node offline

# ---------------- Intrusion Detection state ----------------
# phase: NORMAL    -> SAFE, watching
#        COUNTDOWN -> UNSAFE, visible countdown to the block
#        BLOCKED   -> SAFE + blocked, held while the attacker is still around
# The monitor thread is the ONLY writer of `phase`, so there is exactly one countdown
# (a deadline timestamp, not a thread) and it cannot be duplicated.
security_lock = threading.Lock()
security = {
    "mode": "DEMONSTRATION",     # always shown on dashboard
    "attacker_ip": ATTACKER_IP,
    "status": "SAFE",            # "SAFE" or "UNSAFE"
    "phase": "NORMAL",           # NORMAL / COUNTDOWN / BLOCKED
    "detected": False,           # attacker currently flagged
    "detected_ip": None,
    "detected_at": None,
    "blocking": False,           # countdown to block in progress
    "block_delay": BLOCK_DELAY,
    "seconds_remaining": 0,
    "blocked": False,            # attacker is blocked (held until the attacker leaves)
    "rearm_ready": True,
    "last_event": "System nominal — no intrusions detected",
    "wlan1": {"iface": AP_IFACE, "state": "UNKNOWN", "ip": None},   # MISSING / DOWN / NO-IP / ACTIVE
    "attacker_present": False,
    "hostapd": None,
    "dnsmasq": None,
    "detection_reason": None,     # NETWORK_ATTACKER_PRESENT / USB_ATTACK / CAN_ANOMALY
    # USB attack vector: written by usb_attack_trigger.py to USB_STATE_FILE, merged in here each tick.
    # status: IDLE / USB_DETECTED / ATTACK_TRIGGERED / MONITORING / BLOCKED / REMOVED
    "usb": {"present": False, "attack_triggered": False, "status": "IDLE",
            "device": None, "payload_pid": None, "event_at": None},
    # ML (CAN anomaly) detection. enabled is the dashboard toggle: while True, ML fully
    # replaces the rule-based (wlan1/USB) detection as the trigger for COUNTDOWN/BLOCKED.
    "ml": {"enabled": False, "available": None, "score": None, "anomaly": False, "error": None},
}
_deadline = 0.0
blocked_ips = set()
attacker_http_last = 0.0
last_motor_source = None


def run(cmd, timeout=3):
    """Run a command, never raise. Returns (returncode or None, stdout)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None, ""


# ---------------- wlan1 / attacker probes (all tolerate wlan1 being absent) ----------------
def read_ap_interface():
    path = f"/sys/class/net/{AP_IFACE}"
    if not os.path.isdir(path):
        return {"exists": False, "up": False, "has_ip": False, "active": False}
    try:
        with open(path + "/flags") as f:
            up = bool(int(f.read().strip(), 16) & 1)   # IFF_UP
    except (OSError, ValueError):
        up = False
    rc, out = run(["ip", "-4", "-o", "addr", "show", "dev", AP_IFACE])
    has_ip = rc == 0 and f"{AP_IP}/" in out
    return {"exists": True, "up": up, "has_ip": has_ip, "active": up and has_ip}


def find_ip_by_mac(mac):
    rc, out = run(["ip", "-4", "neigh", "show", "dev", AP_IFACE])
    for line in out.splitlines():
        p = line.split()
        if "lladdr" in p and p[p.index("lladdr") + 1].lower() == mac and p[-1] not in ("FAILED", "INCOMPLETE"):
            return p[0]
    return None


def neigh_mac(ip):
    rc, out = run(["ip", "-4", "neigh", "show", "to", ip, "dev", AP_IFACE])
    m = re.search(r"lladdr\s+([0-9a-fA-F:]{17})", out)
    return m.group(1).lower() if m else None


def associated_macs():
    """MACs of Wi-Fi clients currently associated to the AP, or None if `iw` is unavailable."""
    rc, out = run(["iw", "dev", AP_IFACE, "station", "dump"])
    if rc != 0:
        return None
    return {m.lower() for m in re.findall(r"^Station\s+([0-9a-fA-F:]{17})", out, re.M)}


def probe_attacker():
    """Is the attacker on the Vehicle-IDS network right now? Returns (present, ip).
    Present if it answers a ping, OR (ICMP blocked, e.g. Windows firewall) its MAC is
    still associated to the AP -- so a client that left is noticed immediately."""
    ip = (find_ip_by_mac(ATTACKER_MAC) if ATTACKER_MAC else None) or ATTACKER_IP
    rc, _ = run(["ping", "-c", "1", "-W", "1", ip], timeout=3)
    if rc == 0:
        return True, ip
    mac = ATTACKER_MAC or neigh_mac(ip)
    stations = associated_macs()
    if mac and stations is not None and mac in stations:
        return True, ip
    return False, ip


def service_active(name):
    rc, out = run(["systemctl", "is-active", name])
    return out.strip() == "active"


def read_usb_state(now):
    """Read the status file usb_attack_trigger.py maintains. Missing/stale/corrupt file is
    just IDLE -- this must never crash the monitor thread."""
    try:
        with open(USB_STATE_FILE) as f:
            data = json.load(f)
        age = now - float(data.get("event_at") or 0)
        if age > USB_PRESENCE_TIMEOUT and data.get("status") not in ("IDLE", "REMOVED"):
            data["status"] = "REMOVED"
            data["present"] = False
        return {
            "present": bool(data.get("present")),
            "attack_triggered": bool(data.get("attack_triggered")),
            "status": data.get("status", "IDLE"),
            "device": data.get("device"),
            "payload_pid": data.get("payload_pid"),
            "event_at": data.get("event_at"),
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return {"present": False, "attack_triggered": False, "status": "IDLE",
                "device": None, "payload_pid": None, "event_at": None}


# ---------------- Intrusion cycle (reuses the original detect -> UNSAFE -> countdown -> block -> SAFE flow) ----------------
def start_intrusion_cycle(ip, reason, now=None):
    """Enter UNSAFE + countdown. Only called from the monitor thread and only from NORMAL."""
    global _deadline
    now = time.time() if now is None else now
    event = (f"Intrusion detected: attacker {ip} present on {AP_IFACE}" if reason == "NETWORK_ATTACKER_PRESENT"
             else f"USB attack vector: connection to {ip} detected" if reason == "USB_ATTACK"
             else "CAN anomaly detected by ML model")
    with security_lock:
        if security["phase"] != "NORMAL":
            return False
        _deadline = now + BLOCK_DELAY
        security.update(
            phase="COUNTDOWN", rearm_ready=False, status="UNSAFE", detected=True, detected_ip=ip,
            detected_at=now, blocking=True, blocked=False, seconds_remaining=BLOCK_DELAY,
            detection_reason=reason, last_event=event,
        )
    log.warning("STATE NORMAL -> UNSAFE (%s): attacker %s, blocking in %ds", reason, ip, BLOCK_DELAY)
    return True


def update_countdown(now):
    with security_lock:
        remaining = max(0, math.ceil(_deadline - now))
        security["seconds_remaining"] = remaining
    return remaining


def cancel_intrusion_cycle(reason):
    """Attacker vanished (or wlan1 lost) before the block, or detection mode was switched
    mid-cycle: back to NORMAL, and do NOT claim it was blocked. Also clears any blocked
    address, so a mode switch while BLOCKED doesn't leave a client stuck blocked forever."""
    with security_lock:
        blocked_ips.clear()
        security.update(
            phase="NORMAL", rearm_ready=True, status="SAFE", detected=False, detected_ip=None,
            blocking=False, blocked=False, seconds_remaining=0, detection_reason=None, last_event=reason,
        )
    log.info("STATE -> NORMAL: %s", reason)


def execute_block(ip):
    """The project's block action. Enforced at the application layer: every control endpoint
    now refuses this attacker (HTTP 403) while the dashboard/state endpoints stay reachable so
    the attacker's own page can show BLOCKED. No iptables/nftables rules are added, so the
    Vehicle-IDS AP itself keeps working. The motors are put in a safe state if the attacker
    was the last one driving -- or unconditionally for a CAN-level anomaly, since there is no
    single attacker address to attribute it to."""
    with security_lock:
        reason = security["detection_reason"]
        if ip:
            blocked_ips.add(ip)
        pid = security["usb"].get("payload_pid")
        event = (f"Attacker {ip} blocked — controls disabled, system SAFE" if reason != "CAN_ANOMALY"
                 else "CAN anomaly contained — motor stopped, system SAFE")
        security.update(
            phase="BLOCKED", status="SAFE", detected=False, blocking=False, blocked=True,
            seconds_remaining=0, last_event=event,
        )
        if reason == "USB_ATTACK":
            security["usb"]["status"] = "BLOCKED"
    log.warning("STATE UNSAFE -> SAFE/BLOCKED (%s): %s", reason, event)
    if reason == "USB_ATTACK" and pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
            log.warning("USB demo payload (pid %s) sent SIGTERM as part of containment", pid)
        except (ProcessLookupError, ValueError, PermissionError) as e:
            log.info("USB demo payload not stopped (%s) — likely already exited", e)
    if reason == "CAN_ANOMALY":
        if last_motor_cmd not in (None, "S"):
            send_motor_command("S")
            log.warning("Motor set to STOP: CAN anomaly containment")
    elif last_motor_source == ip and last_motor_cmd not in (None, "S"):
        send_motor_command("S")
        log.warning("Motor set to STOP: last drive command came from the blocked attacker")


def rearm(reason):
    with security_lock:
        blocked_ips.clear()
        security.update(phase="NORMAL", rearm_ready=True, blocked=False, status="SAFE",
                         detection_reason=None, last_event=reason)
    log.info("STATE BLOCKED -> NORMAL: %s", reason)


# ---------------- Background monitor ----------------
_mon = {"iface_state": None, "present": None, "absent_ticks": 0, "absent_since": None,
        "last_svc": 0.0, "last_fix": 0.0, "last_status": 0.0}


def try_fix_ap(now):
    """wlan1 exists but has lost its address (e.g. dongle re-inserted): re-apply it and restart the AP services."""
    if now - _mon["last_fix"] < FIX_COOLDOWN:
        return
    _mon["last_fix"] = now
    log.warning("%s present without %s -- re-applying address and restarting hostapd/dnsmasq", AP_IFACE, AP_IP)
    rc1, _ = run(["sudo", "-n", "ip", "addr", "replace", f"{AP_IP}/24", "dev", AP_IFACE], timeout=5)
    run(["sudo", "-n", "ip", "link", "set", AP_IFACE, "up"], timeout=5)
    rc2, _ = run(["sudo", "-n", "systemctl", "restart", "hostapd"], timeout=15)
    rc3, _ = run(["sudo", "-n", "systemctl", "restart", "dnsmasq"], timeout=15)
    if rc1 != 0:
        log.error("Could not re-apply %s (need passwordless sudo, or run ./start_vehicle_ids.sh)", AP_IP)
    log.info("AP recovery: ip=%s hostapd=%s dnsmasq=%s", rc1, rc2, rc3)


def _iface_key(iface):
    if not iface["exists"]:
        return "MISSING"
    if not iface["has_ip"]:
        return "NO-IP"
    if not iface["up"]:
        return "DOWN"
    return "ACTIVE"


def monitor_tick(now=None):
    now = time.time() if now is None else now

    iface = read_ap_interface()
    if iface["exists"] and not iface["has_ip"] and AUTO_FIX_AP:
        try_fix_ap(now)
        iface = read_ap_interface()

    if now - _mon["last_svc"] >= SERVICE_CHECK_INTERVAL:
        _mon["last_svc"] = now
        hostapd, dnsmasq = service_active("hostapd"), service_active("dnsmasq")
        with security_lock:
            security["hostapd"], security["dnsmasq"] = hostapd, dnsmasq

    with security_lock:
        ip = security["attacker_ip"]
    present = False
    if iface["active"]:
        present, ip = probe_attacker()
        if now - attacker_http_last < HTTP_PRESENCE_WINDOW:
            present = True

    usb = read_usb_state(now)
    usb_reachable = False
    if usb["attack_triggered"] and usb["status"] in ("ATTACK_TRIGGERED", "MONITORING"):
        rc, _ = run(["ping", "-c", "1", "-W", "1", ATTACKER_IP], timeout=3)
        usb_reachable = rc == 0
        if usb_reachable and usb["status"] == "ATTACK_TRIGGERED":
            usb["status"] = "MONITORING"

    with security_lock:
        ml_enabled = security["ml"]["enabled"]
    if ml_bundle is None:
        load_ml_model()   # cheap after the first successful/failed attempt; keeps "available" accurate even when disabled
    ml_score, ml_anomaly = (None, False)
    if ml_enabled:
        ml_score, ml_anomaly = ml_score_now()
    with security_lock:
        security["ml"]["available"] = ml_bundle is not None
        security["ml"]["error"] = ml_load_error if ml_bundle is None else None
        security["ml"]["score"] = ml_score
        security["ml"]["anomaly"] = ml_anomaly

    key = _iface_key(iface)
    if key != _mon["iface_state"]:
        log.info("%s: %s -> %s", AP_IFACE, _mon["iface_state"] or "UNKNOWN", key)
        _mon["iface_state"] = key
    if present != _mon["present"]:
        log.info("Attacker %s on %s: %s", ip, AP_IFACE, "PRESENT" if present else "not present")
        _mon["present"] = present
    if usb["status"] != _mon.get("usb_status"):
        log.info("USB attack vector: %s (device=%s)", usb["status"], usb["device"])
        _mon["usb_status"] = usb["status"]

    with security_lock:
        security["attacker_ip"] = ip
        security["attacker_present"] = present
        security["wlan1"] = {"iface": AP_IFACE, "state": key, "ip": AP_IP if iface["active"] else None}
        # The USB state file is the source of truth for present/attack_triggered/device/pid, but
        # once the IDS has blocked a USB-triggered attack, that containment (BLOCKED) must stick
        # on the dashboard even though the file itself still says MONITORING/ATTACK_TRIGGERED --
        # only a fresh insertion (a new payload_pid) or a rearm should move it off BLOCKED.
        was_blocked = (security["phase"] == "BLOCKED" and security["detection_reason"] == "USB_ATTACK"
                       and security["usb"]["status"] == "BLOCKED")
        same_payload = was_blocked and usb.get("payload_pid") == security["usb"].get("payload_pid")
        if same_payload:
            usb["status"] = "BLOCKED"
        security["usb"] = usb
        phase = security["phase"]

    condition_net = iface["active"] and present
    condition_usb = usb_reachable
    if ml_enabled:
        # ML fully replaces rule-based detection while the toggle is ON: the network/USB
        # conditions are still computed above (so their dashboard rows stay live for
        # comparison) but cannot start/sustain/cancel a cycle while ML governs it.
        condition = ml_anomaly
        reason = "CAN_ANOMALY"
        detect_ip = None
    else:
        condition = condition_net or condition_usb
        reason = "NETWORK_ATTACKER_PRESENT" if condition_net else ("USB_ATTACK" if condition_usb else None)
        detect_ip = ip if condition_net else ATTACKER_IP

    if phase == "NORMAL":
        if condition:
            start_intrusion_cycle(detect_ip, reason, now)
        else:
            with security_lock:   # keep the event line informative without falsely raising UNSAFE
                if not iface["active"]:
                    security["last_event"] = f"{AP_IFACE} not active ({key}) — monitoring, will recover automatically"
                elif security["last_event"].startswith(AP_IFACE):
                    security["last_event"] = "System nominal — no intrusions detected"
            _mon["absent_ticks"] = 0

    elif phase == "COUNTDOWN":
        with security_lock:
            active_ip, active_reason = security["detected_ip"], security["detection_reason"]
        if active_reason == "USB_ATTACK":
            still_active = condition_usb
        elif active_reason == "CAN_ANOMALY":
            still_active = ml_anomaly
        else:
            still_active = condition_net
        if still_active:
            _mon["absent_ticks"] = 0
            if update_countdown(now) <= 0:
                execute_block(active_ip)
                _mon["absent_since"] = None
        else:
            _mon["absent_ticks"] += 1
            if _mon["absent_ticks"] >= ABSENT_TICKS_BEFORE_CANCEL:
                cancel_intrusion_cycle(
                    f"{AP_IFACE} lost before block — countdown cancelled" if active_reason == "NETWORK_ATTACKER_PRESENT" and not iface["active"]
                    else f"USB attack traffic to {active_ip} stopped before block — countdown cancelled (NOT blocked)" if active_reason == "USB_ATTACK"
                    else "CAN anomaly cleared before block — countdown cancelled (NOT blocked)" if active_reason == "CAN_ANOMALY"
                    else f"Attacker {active_ip} disconnected before block — countdown cancelled (NOT blocked)")
                _mon["absent_ticks"] = 0

    elif phase == "BLOCKED":
        if condition:
            _mon["absent_since"] = None
        else:
            _mon["absent_since"] = _mon["absent_since"] or now
            if now - _mon["absent_since"] >= REARM_COOLDOWN:
                rearm("Attacker left the Vehicle-IDS network — system re-armed")
                _mon["absent_since"] = None

    if now - _mon["last_status"] >= STATUS_LOG_INTERVAL:
        _mon["last_status"] = now
        with security_lock:
            log.info("[status] %s=%s attacker=%s usb=%s phase=%s%s hostapd=%s dnsmasq=%s can=%s",
                     AP_IFACE, key, "PRESENT" if present else "absent", security["usb"]["status"], security["phase"],
                     f"({security['seconds_remaining']}s, {security['detection_reason']})" if security["phase"] == "COUNTDOWN" else "",
                     security["hostapd"], security["dnsmasq"], "up" if state["can_up"] else "DOWN")


def monitor_loop():
    while True:
        t0 = time.time()
        try:
            monitor_tick()
        except Exception:
            log.exception("monitor tick failed (continuing)")
        time.sleep(max(0.05, POLL_INTERVAL - (time.time() - t0)))


# ---------------- CAN receive ----------------
def mark_seen(node):
    with state_lock:
        state["nodes"][node]["online"] = True
        state["nodes"][node]["last_seen"] = time.time()


def handle_can_message(msg):
    mid = msg.arbitration_id
    data = msg.data
    record_can_frame(time.time(), mid, data)

    if mid == ID_MOTOR_HEARTBEAT:
        mark_seen("motor")

    elif mid == ID_SENSOR_HEARTBEAT:
        mark_seen("sensor")

    elif mid == ID_SECURITY_HEARTBEAT:
        mark_seen("security")

    elif mid == ID_MOTOR_STATUS and len(data) >= 1:
        with state_lock:
            state["motor_status"] = chr(data[0])
        mark_seen("motor")

    elif mid == ID_TOF_DIST and len(data) >= 2:
        mm = data[0] | (data[1] << 8)
        with state_lock:
            state["tof_mm"] = None if mm == 0xFFFF else mm
        mark_seen("sensor")

    elif mid == ID_ULTRASONIC_DIST and len(data) >= 4:
        left10 = data[0] | (data[1] << 8)
        right10 = data[2] | (data[3] << 8)
        with state_lock:
            state["us_left_cm"] = None if left10 == 0xFFFF else left10 / 10.0
            state["us_right_cm"] = None if right10 == 0xFFFF else right10 / 10.0
        mark_seen("sensor")

    elif mid == ID_OBSTACLE_STATUS and len(data) >= 1:
        with state_lock:
            state["obstacle_flags"] = data[0]
        mark_seen("sensor")

    elif mid == ID_LOCK_STATUS and len(data) >= 1:
        with state_lock:
            state["lock_state"] = "ON" if data[0] else "OFF"
        mark_seen("security")


def can_rx_loop():
    """Runs forever in a background thread, updating shared state from CAN traffic.
    Re-opens can0 if it was not available at start or disappears later."""
    global bus
    while True:
        b = get_bus()
        with state_lock:
            state["can_up"] = b is not None
        if b is None:
            time.sleep(3)
            continue
        try:
            msg = b.recv(timeout=1.0)
        except (can.CanError, OSError) as e:
            log.warning("CAN receive error (%s) -- will re-open %s", e, CAN_CHANNEL)
            try:
                b.shutdown()
            except Exception:
                pass
            bus = None
            continue
        if msg is not None:
            handle_can_message(msg)


def node_timeout_watcher():
    while True:
        now = time.time()
        with state_lock:
            for n in state["nodes"].values():
                if n["online"] and now - n["last_seen"] > NODE_TIMEOUT:
                    n["online"] = False
        time.sleep(0.5)


def pi_heartbeat_loop():
    while True:
        can_send(can.Message(arbitration_id=ID_PI_HEARTBEAT, data=[1], is_extended_id=False))
        time.sleep(0.5)


# ---------------- Motor joystick -> discrete command ----------------
DEADZONE = 20
last_motor_cmd = None
last_motor_send_time = 0.0
MOTOR_RESEND_INTERVAL = 0.2  # keep-alive resend so the ECU failsafe timer doesn't trip while held


def joystick_to_command(x, y):
    """x, y each in [-100, 100]; y positive = forward (pushed up)."""
    if abs(x) < DEADZONE and abs(y) < DEADZONE:
        return "S"
    if abs(y) >= abs(x):
        return "F" if y > 0 else "B"
    return "R" if x > 0 else "L"


def send_motor_command(cmd):
    global last_motor_cmd, last_motor_send_time
    can_send(can.Message(arbitration_id=ID_MOTOR_CMD, data=[ord(cmd)], is_extended_id=False))
    with state_lock:
        state["motor_cmd"] = cmd
    last_motor_cmd = cmd
    last_motor_send_time = time.time()


def motor_keepalive_loop():
    while True:
        if last_motor_cmd is not None and time.time() - last_motor_send_time > MOTOR_RESEND_INTERVAL:
            send_motor_command(last_motor_cmd)
        time.sleep(0.05)


# ---------------- Routes ----------------
@app.before_request
def _client_hook():
    """Per-request check. An HTTP request from the attacker address is only used as an extra
    'attacker is here' signal for the monitor thread (it no longer starts the cycle by itself),
    and once the attacker is BLOCKED its control requests are refused."""
    global attacker_http_last
    addr = request.remote_addr
    with security_lock:
        attacker_ip = security["attacker_ip"]
        is_blocked = addr in blocked_ips
    if addr == attacker_ip:
        attacker_http_last = time.time()
    if is_blocked and request.path in CONTROL_PATHS:
        return jsonify({"error": "blocked"}), 403


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/joystick", methods=["POST"])
def api_joystick():
    global last_motor_source
    body = request.get_json(force=True)
    x = float(body.get("x", 0))
    y = float(body.get("y", 0))
    cmd = joystick_to_command(x, y)
    last_motor_source = request.remote_addr
    send_motor_command(cmd)
    return jsonify({"cmd": cmd})


@app.route("/api/solenoid", methods=["POST"])
def api_solenoid():
    body = request.get_json(force=True)
    on = bool(body.get("on"))
    can_send(can.Message(arbitration_id=ID_LOCK_CMD, data=[1 if on else 0], is_extended_id=False))
    return jsonify({"requested": "ON" if on else "OFF"})


@app.route("/api/ml/toggle", methods=["POST"])
def api_ml_toggle():
    body = request.get_json(force=True, silent=True) or {}
    enabled = bool(body.get("enabled"))
    with security_lock:
        if security["ml"]["enabled"] == enabled:
            return jsonify(dict(security["ml"]))
        security["ml"]["enabled"] = enabled
        mid_cycle = security["phase"] != "NORMAL"
    log.warning("ML toggle -> %s", "ON" if enabled else "OFF")
    if mid_cycle:
        # Switching detection modes mid-cycle would leave a countdown/block running under a
        # reason that's no longer being evaluated; clear it so the newly-active mode starts clean.
        cancel_intrusion_cycle(f"Detection mode switched to {'ML' if enabled else 'rule-based'} — state reset")
    if enabled and ml_bundle is None:
        load_ml_model()
    with security_lock:
        return jsonify(dict(security["ml"]))


@app.route("/api/state")
def api_state():
    addr = request.remote_addr
    with state_lock:
        snapshot = dict(state)
    with security_lock:
        snapshot["security"] = dict(security)
        is_attacker = addr == security["attacker_ip"]
        blocked = addr in blocked_ips and security["phase"] == "BLOCKED"
    snapshot["you"] = {"is_attacker": is_attacker, "blocked": blocked}
    return jsonify(snapshot)


if __name__ == "__main__":
    log.info("Vehicle-IDS starting: AP=%s (%s) attacker=%s%s block_delay=%ds",
             AP_IFACE, AP_IP, ATTACKER_IP, f" mac={ATTACKER_MAC}" if ATTACKER_MAC else "", BLOCK_DELAY)
    threading.Thread(target=can_rx_loop, daemon=True).start()
    threading.Thread(target=node_timeout_watcher, daemon=True).start()
    threading.Thread(target=pi_heartbeat_loop, daemon=True).start()
    threading.Thread(target=motor_keepalive_loop, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
