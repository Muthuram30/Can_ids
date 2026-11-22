# Optional registered USB lab demonstration

The registered device is only a trigger. No file on the drive is mounted or executed by this project. The payload is the version-controlled `usb/usb_attack_demo.py`, which makes a fixed number of logged TCP connection attempts to `ATTACKER_IP:ATTACKER_PORT`. No listener is required for the attempts to be logged.

## Register the actual device

On the Pi, inspect the device and its parent USB node:

```bash
lsusb
udevadm info --attribute-walk --name=/dev/sdX
```

Replace `/dev/sdX` with the actual USB device; do not format or write it. Copy the parent USB `idVendor`, `idProduct` and `serial` into `.env` as `EXPECTED_VENDOR`, `EXPECTED_PRODUCT`, `EXPECTED_SERIAL`. Registration requires a serial containing letters, digits, `.`, `_` or `-`; devices without a usable serial are rejected. Vendor/product should be lower-case hexadecimal. Set `ATTACKER_IP` and optionally the port/attempt limits.

Install **from a checkout owned by your normal Pi user**:

```bash
cd ~/Can_ids
sudo .venv/bin/python scripts/install_usb.py
```

The installer generates a serial-matched udev rule and a systemd template with your actual user and checkout path. Reinsert the registered drive. The template starts the monitor as your user and passes only the kernel device name; the monitor reads and verifies sysfs identity before launching the fixed payload. It refreshes the state file while the drive is present, then stops any remaining payload and marks removal.

## Observe in the dashboard

Use **ML off**. The USB card shows insertion/monitoring. The existing rule uses successful ping reachability to `ATTACKER_IP` as its USB trigger condition; a failed TCP connection by itself does not trigger the countdown. For a dedicated USB demonstration, leave the AP client absent so the Wi-Fi trigger does not take priority, and use a reachable lab destination. If that destination blocks ICMP, the current USB rule will not start; choose another permitted test destination rather than disabling the Windows firewall globally.

After containment the fixed payload is sent SIGTERM. Remove the USB and wait for the rearm cooldown. Monitor logs with:

```bash
journalctl -u 'vehicle-usb-attack@*' -f
```

The generated instance is named from the USB sysfs device, e.g. `vehicle-usb-attack@1-1.3.service`. If migrating an old install, first stop the old `vehicle-usb-attack.service` and `vehicle-usb-attack-remove.service` and archive their old unit files. The new installer replaces only `/etc/udev/rules.d/99-vehicle-usb-demo.rules` and creates `vehicle-usb-attack@.service`; it does not automatically delete old unit files.

## Uninstall the trigger

Stop the active instance shown in `systemctl list-units 'vehicle-usb-attack@*'`, then remove only the installed template and the project's udev rule and reload systemd/udev. Your repository, `.env`, USB contents and other udev rules remain in place. Changing registration requires rerunning the installer so its udev match is updated too.
