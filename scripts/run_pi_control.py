#!/usr/bin/env python3
"""Windows-side app/terminal launcher sharing run_pi.cmd's saved SSH settings."""
import argparse
import shlex
import subprocess

try:
    from .sync_pi import configuration, ssh_base
except ImportError:
    from sync_pi import configuration, ssh_base

ACTIONS = ("app", "terminal", "start", "stop", "restart", "status", "logs", "test", "config", "train")


def command(config, action):
    target = config["target"]
    # Shell expands only HOME; the user-supplied suffix remains literal.
    folder = '"$HOME"/' + shlex.quote(target[2:]) if target.startswith("~/") else shlex.quote(target)
    remote = "cd -- " + folder + " || { echo 'Run run_pi.cmd to set up this Pi folder first.' >&2; exit 1; }; "
    if action == "terminal":
        remote += "exec bash"
    else:
        remote += shlex.join(["python3", "scripts/pi_control.py", action])
    return ssh_base(config, terminal=True) + [remote]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=ACTIONS)
    parser.add_argument("--host")
    parser.add_argument("--target")
    parser.add_argument("--port", type=int)
    parser.add_argument("--identity")
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    config = configuration(args)
    action = args.action
    if action is None:
        print("Pi: " + config["host"] + ":" + config["target"])
        for index, name in enumerate(ACTIONS, 1):
            print(str(index) + ". " + name)
        choice = input("Action [1 = app]: ").strip() or "1"
        action = ACTIONS[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(ACTIONS) else choice
    if action not in ACTIONS:
        raise ValueError("Choose one of: " + ", ".join(ACTIONS))
    subprocess.run(command(config, action), check=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPi session closed.")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Pi command failed: " + str(error))
