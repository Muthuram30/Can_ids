#!/usr/bin/env python3
"""Sync saved VS Code source to a chosen Pi folder over SSH, without a GitHub push."""
import argparse
import base64
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

# Running as a script places scripts/ on sys.path; unittest imports as a package.
try:
    from .pi_sync_receiver import PACKAGE, source_path, commit_source
except ImportError:
    from pi_sync_receiver import PACKAGE, source_path, commit_source

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".pi-sync.json"


def validate_config(config):
    host = config.get("host", "")
    if not re.fullmatch(r"[A-Za-z0-9_@.:[\]-]+", host) or host.startswith("-"):
        raise ValueError("Use an SSH host alias, user@hostname or user@IP")
    target = config.get("target", "")
    if (not target.startswith(("/", "~/")) or target.rstrip("/").split("/")[-1].lower() != "can_ids"
            or any(c in target for c in ("\n", "\r", "\0", "\\"))):
        raise ValueError("Choose a Pi folder ending in can_ids, e.g. ~/can_ids or /home/muthu/can_ids")
    port = int(config.get("port", 22))
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535")
    config = dict(config, port=port, target=target.rstrip("/"))
    if config.get("identity"):
        config["identity"] = str(Path(config["identity"]).expanduser().resolve())
    return config


def configuration(args):
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    for key in ("host", "target", "port", "identity"):
        if getattr(args, key) is not None:
            config[key] = getattr(args, key)
    if args.setup or not config.get("host"):
        print("One-time Pi connection setup. SSH handles your password/key; no password is saved.")
        config["host"] = input("Pi SSH login [" + config.get("host", "muthu@vehicle-pi.local") + "]: ").strip() or config.get("host", "muthu@vehicle-pi.local")
        config["target"] = input("Pi project folder [" + config.get("target", "~/can_ids") + "]: ").strip() or config.get("target", "~/can_ids")
        config["port"] = input("SSH port [" + str(config.get("port", 22)) + "]: ").strip() or config.get("port", 22)
    config.setdefault("target", "~/can_ids")
    config = validate_config(config)
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def source_files(root):
    result = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                             "--exclude-standard", "-z"], capture_output=True, check=True)
    files = {}
    for raw in set(result.stdout.split(b"\0")) - {b""}:
        name = raw.decode("utf-8")
        path = root / name
        if not source_path(name):
            continue
        # Omit deleted files even while their old entries remain in the Git index.
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            raise ValueError("Source symlinks are unsupported: " + name)
        if path.is_file():
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Source file exceeds 64 MiB: " + name)
            files[name] = path.read_bytes()
    if not {"app.py", "can_features.py"} <= files.keys():
        raise ValueError("Run from a complete CAN IDS checkout")
    return files


def fingerprint(files):
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def snapshot(files):
    archive = tempfile.TemporaryFile()
    hashes = fingerprint(files)
    with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
        entries = dict(files)
        entries[PACKAGE] = json.dumps(dict(version=1, files=hashes)).encode()
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            bundle.addfile(info, io.BytesIO(data))
    archive.seek(0)
    return archive


def ssh_base(config, batch=False, terminal=False):
    command = ["ssh", "-p", str(config["port"]), "-o", "ConnectTimeout=10",
               "-o", "ServerAliveInterval=15"]
    if terminal:
        command.append("-t")
    if batch:
        command += ["-o", "BatchMode=yes"]
    if config.get("identity"):
        command += ["-i", config["identity"]]
    return command + [config["host"]]


def preflight_command(config, adopt=False):
    # The first SSH session has a terminal, so sudo can ask for the Pi password.
    # The archive is transferred in a separate session only after setup succeeds.
    source = (ROOT / "scripts/pi_sync_receiver.py").read_bytes()
    encoded = base64.b64encode(source).decode()
    check = ("import base64,os,subprocess,sys; n={'__name__':'preflight'}; "
             "exec(compile(base64.b64decode('" + encoded + "'),'<preflight>','exec'),n); "
             "n['prepare_target'](sys.argv[1],sys.argv[2]=='1')")
    script = '''set -eu
if ! command -v python3 >/dev/null || ! command -v git >/dev/null || ! command -v ssh >/dev/null || ! command -v nano >/dev/null || ! python3 -c 'import ensurepip,venv,sys; assert sys.version_info >= (3,9)' >/dev/null 2>&1; then
  command -v apt-get >/dev/null || { echo 'Install Python 3, python3-venv and Git on this Pi first.' >&2; exit 1; }
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip git openssh-client nano
fi
'''
    script += shlex.join(["python3", "-c", check, config["target"], "1" if adopt else "0"])
    return ssh_base(config, terminal=True) + [shlex.join(["sh", "-c", script])]


def prepare(config, adopt=False):
    for name in ("ssh", "git"):
        if not shutil.which(name):
            raise ValueError("Install " + name + " on the laptop and add it to PATH")
    print("Checking SSH, Pi prerequisites and destination before making source commits...", flush=True)
    subprocess.run(preflight_command(config, adopt), check=True)
    print("Laptop and Pi connection ready.", flush=True)


def checkpoint(root, message):
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others",
                                     "--exclude-standard", "-z"])
    return commit_source(root, [p.decode() for p in paths.split(b"\0") if p], message)


def ssh_command(config, args, batch=False):
    receiver = (ROOT / "scripts/pi_sync_receiver.py").read_bytes()
    encoded = base64.b64encode(receiver).decode("ascii")
    bootstrap = "import base64;exec(compile(base64.b64decode('" + encoded + "'),'<can_ids_receiver>','exec'))"
    remote = ["python3", "-c", bootstrap, config["target"]]
    if args.adopt:
        remote.append("--adopt")
    if args.code_only:
        remote.append("--code-only")
    if args.no_restart:
        remote.append("--no-restart")
    if getattr(args, "no_commit", False):
        remote.append("--no-commit")
    if getattr(args, "source_commit", ""):
        remote += ["--source-commit", args.source_commit]
    if getattr(args, "message", ""):
        remote += ["--message", args.message]
    return ssh_base(config, batch=batch) + [shlex.join(remote)]


def send(config, args, files, batch=False):
    print("Synchronizing saved source to " + config["host"] + ":" + config["target"], flush=True)
    with snapshot(files) as archive:
        subprocess.run(ssh_command(config, args, batch), stdin=archive, check=True)


def sync_once(config, args, batch=False):
    if not args.no_commit:
        args.source_commit = checkpoint(ROOT, args.message)
        print("Laptop source checkpoint: " + args.source_commit[:12], flush=True)
    elif not (ROOT / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(ROOT)], check=True)
    files = source_files(ROOT)
    send(config, args, files, batch)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true", help="change saved Pi connection settings")
    parser.add_argument("--host", help="SSH login/alias, e.g. muthu@vehicle-pi.local")
    parser.add_argument("--target", help="remote folder, default ~/can_ids")
    parser.add_argument("--port", type=int)
    parser.add_argument("--identity", help="optional local private-key path")
    parser.add_argument("--watch", action="store_true", help="sync saved additions/edits/deletions until Ctrl+C")
    parser.add_argument("--adopt", action="store_true", help="first sync: back up/remove obsolete non-runtime files already in the chosen folder")
    parser.add_argument("--code-only", action="store_true", help="sync source without pip, tests or service actions")
    parser.add_argument("--no-restart", action="store_true", help="update/test without restarting a running user service")
    parser.add_argument("--no-commit", action="store_true", help="mirror source without laptop/Pi Git checkpoints")
    parser.add_argument("--message", default="Update CAN IDS source from laptop", help="Git checkpoint message")
    args = parser.parse_args()
    config = configuration(args)
    prepare(config, args.adopt)
    files = sync_once(config, args)
    if not args.watch:
        return
    print("Watching saved files. Ctrl+C stops watching; later transfers require SSH key/agent login.", flush=True)
    previous = fingerprint(files)
    while True:
        time.sleep(1)
        files = source_files(ROOT)
        current = fingerprint(files)
        if current == previous:
            continue
        # Wait for a quiet interval so editor multi-file saves travel in one snapshot.
        time.sleep(.5)
        files = source_files(ROOT)
        try:
            files = sync_once(config, args, batch=True)
        except subprocess.CalledProcessError:
            print("Sync failed. Source remains local; retrying in five seconds. Check SSH key/agent and Pi logs.", file=sys.stderr)
            time.sleep(5)
            continue
        previous = fingerprint(files)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPi sync stopped.")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Pi sync failed: " + str(error))
