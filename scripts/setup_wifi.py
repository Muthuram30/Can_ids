#!/usr/bin/env python3
"""Explicit NetworkManager setup; no network changes during application startup."""
import argparse
import ipaddress
import os
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    return subprocess.run(args, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def interface(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", name):
        raise ValueError("Invalid network interface name")
    return name


def settings(mode, env):
    home = interface(env.get("HOME_IFACE", "wlan0"))
    ap = interface(env.get("AP_IFACE", "wlan1"))
    if home == ap:
        raise ValueError("HOME_IFACE and AP_IFACE must be different; preserve management access")
    prefix = "HOME" if mode == "home" else "AP"
    ssid, password = env.get(prefix + "_SSID", ""), env.get(prefix + "_PASSWORD", "")
    if not ssid or len(ssid.encode()) > 32 or ssid == "YOUR_HOME_WIFI":
        raise ValueError("Set a real SSID (1-32 bytes) in .env")
    if not 8 <= len(password) <= 63 or password.startswith("REPLACE"):
        raise ValueError("Set a real WPA2 password (8-63 characters) in .env")
    address = ipaddress.IPv4Address(env.get("AP_IP", "10.50.0.1"))
    network = ipaddress.IPv4Network(str(address) + "/24", strict=False)
    if address in (network.network_address, network.broadcast_address):
        raise ValueError("AP_IP must be a usable host address in a /24 subnet")
    return home if mode == "home" else ap, ssid, password, str(address)


def configure(mode, env):
    iface, ssid, password, address = settings(mode, env)
    # Do not race an existing legacy hostapd/dnsmasq setup.
    if mode == "ap":
        for service in ("hostapd", "dnsmasq"):
            if subprocess.run(["systemctl", "is-active", "--quiet", service]).returncode == 0:
                raise ValueError("Stop the old hostapd/dnsmasq AP before using NetworkManager")
    profile = "vehicle-ids-" + mode
    existing = run("nmcli", "-g", "NAME", "connection", "show", capture=True).stdout.splitlines()
    if profile not in existing:
        run("nmcli", "connection", "add", "type", "wifi", "ifname", iface,
            "con-name", profile, "ssid", ssid)
    run("nmcli", "connection", "modify", profile,
        "connection.interface-name", iface, "connection.autoconnect", "yes",
        "802-11-wireless.ssid", ssid,
        "802-11-wireless.mode", "infrastructure" if mode == "home" else "ap",
        "802-11-wireless-security.key-mgmt", "wpa-psk",
        "802-11-wireless-security.psk", password,
        "ipv4.method", "auto" if mode == "home" else "shared")
    if mode == "ap":
        run("nmcli", "connection", "modify", profile,
            "802-11-wireless.band", "bg", "802-11-wireless.channel", "6",
            "802-11-wireless-security.proto", "rsn",
            "ipv4.addresses", address + "/24", "ipv4.never-default", "yes",
            "ipv6.method", "disabled")
    run("nmcli", "connection", "up", profile)
    print("Configured", profile, "on", iface, "(password not printed)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("home", "ap", "status", "down"))
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    if args.mode == "status":
        run("nmcli", "device", "status")
        run("ip", "-4", "address", "show")
    elif args.mode == "down":
        # Only our dedicated AP profile; home Wi-Fi remains connected.
        run("nmcli", "connection", "down", "vehicle-ids-ap")
    else:
        configure(args.mode, os.environ)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    except subprocess.CalledProcessError:
        # Never include argv here: NetworkManager commands contain the PSK.
        raise SystemExit("NetworkManager command failed; check adapter, privileges and configuration")
