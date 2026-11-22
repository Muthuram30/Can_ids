#!/usr/bin/env python3
"""Install the optional, serial-matched USB lab trigger. Run explicitly with sudo."""
import os
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def render(root, user, vendor, product, serial):
    if not re.fullmatch(r"[0-9a-fA-F]{4}", vendor) or not re.fullmatch(r"[0-9a-fA-F]{4}", product):
        raise ValueError("Set EXPECTED_VENDOR and EXPECTED_PRODUCT to four hexadecimal digits")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", serial):
        raise ValueError("A registered EXPECTED_SERIAL (letters/numbers/._-) is required")
    if any(c in str(root) for c in ('%', '"', '\\', '\n')):
        raise ValueError("Use a simple project path")
    unit = f'''[Unit]
Description=Registered CAN IDS USB demo (%I)

[Service]
Type=simple
User={user}
WorkingDirectory="{root}"
ExecStart="{root}/.venv/bin/python" "{root}/usb/usb_attack_trigger.py" --device %I
KillMode=control-group
TimeoutStopSec=5
'''
    rule = (f'ACTION=="add", SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", '
            f'ATTR{{idVendor}}=="{vendor.lower()}", ATTR{{idProduct}}=="{product.lower()}", '
            f'ATTR{{serial}}=="{serial}", TAG+="systemd", '
            'ENV{SYSTEMD_WANTS}+="vehicle-usb-attack@%k.service"\n')
    return unit, rule


def main():
    import pwd
    if os.geteuid() != 0 or not os.environ.get("SUDO_USER"):
        raise SystemExit("Run sudo .venv/bin/python scripts/install_usb.py as the Pi project owner")
    user = os.environ["SUDO_USER"]
    if pwd.getpwnam(user).pw_uid != ROOT.stat().st_uid:
        raise SystemExit("Run from a checkout owned by your Pi user")
    load_dotenv(ROOT / ".env", override=False)
    unit, rule = render(ROOT, user, *(os.environ.get(k, "") for k in
                        ("EXPECTED_VENDOR", "EXPECTED_PRODUCT", "EXPECTED_SERIAL")))
    Path("/etc/systemd/system/vehicle-usb-attack@.service").write_text(unit)
    Path("/etc/udev/rules.d/99-vehicle-usb-demo.rules").write_text(rule)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    print("Installed. Reinsert only the registered demo USB. No files on it will be executed.")


if __name__ == "__main__":
    main()
