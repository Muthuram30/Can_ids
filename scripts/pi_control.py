#!/usr/bin/env python3
"""Pi-side app lifecycle commands, always relative to this checkout."""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
UNIT = "vehicle-ids.service"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def perform(action):
    if action == "terminal":
        return run("bash")
    if action == "config":
        if not (ROOT / ".env").exists():
            raise ValueError("Run run_pi.cmd to create the environment first")
        return run("nano", str(ROOT / ".env"))
    if action in ("app", "test", "train"):
        if not PYTHON.exists():
            raise ValueError("Run run_pi.cmd first to install the Pi environment")
        if action == "app":
            active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT]).returncode == 0
            if active:
                print("App already runs as a service; showing logs. Use run.cmd stop before a foreground run.", flush=True)
                return run("journalctl", "--user", "-u", UNIT, "-f", "-n", "40")
            return run(str(PYTHON), "app.py")
        if action == "test":
            return run(str(PYTHON), "-m", "unittest", "discover", "-s", "tests", "-v")
        return run(str(PYTHON), "train_can_ids_model.py")
    if action == "start":
        return run("bash", "scripts/install_service.sh")
    if action == "restart":
        return run("systemctl", "--user", "restart", UNIT)
    if action == "stop":
        return run("systemctl", "--user", "stop", UNIT)
    if action == "status":
        # An inactive service exits 3; displaying it is still a successful status query.
        result = subprocess.run(["systemctl", "--user", "status", UNIT, "--no-pager"], cwd=ROOT)
        if result.returncode not in (0, 3):
            raise subprocess.CalledProcessError(result.returncode, result.args)
        return result
    if action == "logs":
        return run("journalctl", "--user", "-u", UNIT, "-f", "-n", "40")
    raise ValueError("Unknown Pi action")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("app", "terminal", "start", "stop", "restart", "status", "logs", "test", "config", "train"))
    perform(parser.parse_args().action)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
