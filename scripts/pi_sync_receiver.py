#!/usr/bin/env python3
"""SSH-side snapshot receiver. Source is sent by sync_pi.py; no extra Pi package needed."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

MANIFEST = ".can_ids-sync.json"
PACKAGE = ".can_ids-package.json"
RESERVED = {MANIFEST, MANIFEST + ".tmp", PACKAGE, ".can_ids-backups", ".pi-sync.json",
            ".can_ids-runtime-pending", ".can_ids-sync-lock", "credentials.json", "secrets.json"}
RUNTIME_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "logs", "run",
                "node_modules", ".vscode", ".idea", "training_results", "checkpoints"}


def source_path(name):
    """Accept only project source paths; reject secrets, state and traversal."""
    parts = PurePosixPath(name).parts
    if (not name or "\\" in name or ":" in name or name.startswith("/")
            or any(p in ("", ".", "..") for p in name.split("/"))
            or any(p in RUNTIME_DIRS or p in RESERVED for p in parts)):
        return False
    filename = parts[-1]
    return (not (filename.startswith(".env") and filename != ".env.example")
            and not filename.endswith((".pyc", ".log", ".joblib", ".pkl", ".pickle", ".pem", ".key"))
            and not (parts[0] == "data" and filename != "README.md"))


def target_folder(value):
    given = Path(value).expanduser()
    if not given.is_absolute() or given.name.lower() != "can_ids":
        raise ValueError("Pi target must be an absolute path or ~/can_ids, ending in can_ids")
    # Check every existing component before resolving or changing anything.
    for candidate in (given, *given.parents):
        if candidate.is_symlink():
            raise ValueError("Target path must not contain symbolic links")
    root = given.resolve()
    if root in (Path.home().resolve(), Path(root.anchor), Path("/home")):
        raise ValueError("Refusing a home directory or filesystem root")
    return root


def prepare_target(value, adopt=False):
    root = target_folder(value)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if root.exists():
            raise ValueError("Choose a project folder owned by your SSH user")
        # Only the validated new project folder is created/owned with sudo.
        subprocess.run(["sudo", "install", "-d", "-o", str(os.getuid()),
                        "-g", str(os.getgid()), str(root)], check=True)
    if not os.access(root, os.W_OK | os.X_OK):
        raise ValueError("Project folder is not writable by the SSH user")
    managed_before(root, adopt)
    print("Pi folder ready: " + str(root), flush=True)
    return root


def inside(root, relative):
    if not source_path(relative):
        raise ValueError("Protected or invalid source path: " + relative)
    path = root / relative
    for component in (path, *path.parents):
        if component == root:
            break
        if component.is_symlink():
            raise ValueError("Refusing a symbolic link: " + relative)
    if not path.resolve().is_relative_to(root):
        raise ValueError("Path escaped target folder")
    return path


def read_package(archive):
    """Read regular files only; tarfile.extract/extractall are deliberately unused."""
    files = {}
    metadata = None
    with tarfile.open(fileobj=archive, mode="r|gz") as bundle:
        for member in bundle:
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise ValueError("Snapshot must contain regular source files below 64 MiB")
            if member.name != PACKAGE and not source_path(member.name):
                raise ValueError("Protected snapshot path: " + member.name)
            data = bundle.extractfile(member).read()
            if member.name == PACKAGE:
                if metadata is not None:
                    raise ValueError("Duplicate package metadata")
                metadata = json.loads(data)
            else:
                if member.name in files:
                    raise ValueError("Duplicate source path")
                files[member.name] = data
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Missing/unsupported snapshot metadata")
    actual = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if actual != metadata.get("files") or not {"app.py", "can_features.py"} <= files.keys():
        raise ValueError("Incomplete or damaged CAN IDS snapshot")
    return files, actual


def managed_before(root, adopt):
    marker = root / MANIFEST
    if marker.is_symlink():
        raise ValueError("Sync manifest must not be a symlink")
    if marker.exists():
        state = json.loads(marker.read_text(encoding="utf-8"))
        if state.get("root") != str(root) or state.get("version") != 1:
            raise ValueError("Sync manifest does not belong to this target")
        previous = set(state["files"])
        if not all(source_path(name) for name in previous):
            raise ValueError("Unsafe path in previous manifest")
        return previous
    if adopt:
        # Explicit first-time adoption: own all non-runtime regular files in THIS folder.
        result = set()
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in RUNTIME_DIRS | RESERVED
                       and not (Path(current) / d).is_symlink()]
            for name in names:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if source_path(relative) and not path.is_symlink():
                    result.add(relative)
        return result
    if root.exists() and any(source_path(item.name) for item in root.iterdir()):
        raise ValueError("Existing folder has no sync manifest. Use --adopt once to mirror its source files; .env/runtime stay protected")
    return set()


def apply_snapshot(root, files, hashes, adopt=False):
    previous = managed_before(root, adopt)
    changed = [name for name, data in files.items()
               if not inside(root, name).is_file() or inside(root, name).read_bytes() != data]
    deleted = sorted(previous - files.keys())
    # Validate the entire operation before any source deletion or modification.
    for name in changed + deleted:
        path = inside(root, name)
        if path.is_dir():
            for current, dirs, names in os.walk(path, followlinks=False):
                for entry in dirs + names:
                    candidate = Path(current) / entry
                    relative = candidate.relative_to(root).as_posix()
                    if (candidate.is_symlink() or not source_path(relative)
                            or candidate.is_file() and relative not in deleted):
                        raise ValueError("Directory contains unmanaged/protected files: " + name)
    root.mkdir(parents=True, exist_ok=True)
    backups = root / ".can_ids-backups"
    if backups.is_symlink():
        raise ValueError("Backup folder must not be a symlink")
    backup = backups / (time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
    for name in changed + deleted:
        path = inside(root, name)
        if path.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    # Deletes affect only formerly managed source files, never whole directory trees.
    for name in deleted:
        path = inside(root, name)
        if path.is_file():
            path.unlink()
    # Prune only empty directories inside the validated destination, including
    # a formerly managed subtree being replaced by a source file.
    prune = set()
    for name in deleted + changed:
        path = inside(root, name)
        if path.is_dir():
            prune.update(p for p in path.rglob("*") if p.is_dir())
            prune.add(path)
        prune.update(p for p in path.parents if p != root and root in p.parents)
    for directory in sorted(prune, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except (FileNotFoundError, OSError):
            pass
    for name in changed:
        path = inside(root, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(files[name])
            staged = Path(temporary.name)
        staged.chmod(0o755 if name.endswith(".sh") else 0o644)
        staged.replace(path)
    state = dict(version=1, root=str(root), files=hashes)
    marker_tmp = root / (MANIFEST + ".tmp")
    if marker_tmp.is_symlink():
        raise ValueError("Temporary manifest must not be a symlink")
    marker_tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    marker_tmp.replace(root / MANIFEST)
    print(f"Pi sync: {len(changed)} added/modified, {len(deleted)} removed; target={root}", flush=True)
    if backup.exists():
        print("Previous source saved in " + str(backup), flush=True)
    return changed, deleted


def commit_source(root, paths, message):
    """Checkpoint only explicitly selected source paths, never credentials/runtime."""
    if (root / ".git").is_symlink() or (root / ".git").is_file():
        raise ValueError("Use an independent project checkout, not a symlink/worktree Git directory")
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    prefix = ["git", "-C", str(root)]
    staged = subprocess.check_output(prefix + ["diff", "--cached", "--name-only", "-z"])
    if any(not source_path(p.decode()) for p in staged.split(b"\0") if p):
        raise ValueError("Protected/runtime files are already staged; unstage them before committing")
    selected = sorted(set(p for p in paths if source_path(p)))
    tracked = {p.decode() for p in subprocess.check_output(prefix + ["ls-files", "-z"]).split(b"\0") if p}
    removed = [p for p in selected if p in tracked and not (root / p).is_file()]
    if removed:
        subprocess.run(prefix + ["update-index", "--force-remove", "-z", "--stdin"],
                       input=b"\0".join(p.encode() for p in removed) + b"\0", check=True)
    selected = [p for p in selected if (root / p).is_file()]
    if selected:
        subprocess.run(prefix + ["add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
                       input=b"\0".join(p.encode() for p in selected) + b"\0", check=True)
    difference = subprocess.run(prefix + ["diff", "--cached", "--quiet"])
    if difference.returncode not in (0, 1):
        raise RuntimeError("Could not inspect Git source changes")
    if difference.returncode:
        identity = []
        for field, fallback in (("user.name", "CAN IDS Sync"), ("user.email", "can-ids-sync@localhost")):
            if subprocess.run(prefix + ["config", "--get", field], stdout=subprocess.DEVNULL).returncode:
                identity += ["-c", field + "=" + fallback]
        subprocess.run(prefix + identity + ["commit", "-q", "-m", message], check=True)
    return subprocess.check_output(prefix + ["rev-parse", "HEAD"]).decode().strip()


def runtime_update(root, changed, initial, restart):
    python = root / ".venv/bin/python"
    if not python.exists():
        subprocess.run(["python3", "-m", "venv", str(root / ".venv")], check=True)
        initial = True
    if initial or "requirements.txt" in changed:
        subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=root, check=True)
    if not (root / ".env").exists():
        shutil.copyfile(root / ".env.example", root / ".env")
        (root / ".env").chmod(0o600)
        print("Created Pi .env from example. Edit Wi-Fi/client settings on the Pi once.", flush=True)
    subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, check=True)
    if restart and subprocess.run(["systemctl", "--user", "is-active", "--quiet", "vehicle-ids.service"]).returncode == 0:
        # Regenerate the unit with this adaptable path before restarting it.
        subprocess.run(["bash", "scripts/install_service.sh"], cwd=root, check=True)
        subprocess.run(["systemctl", "--user", "restart", "vehicle-ids.service"], check=True)
        for attempt in range(10):
            result = subprocess.run([str(python), "scripts/healthcheck.py"], cwd=root)
            if result.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Source synchronized but restarted service failed its health check")
    else:
        print("Source ready. Start/install the app service in this folder when needed.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--adopt", action="store_true")
    parser.add_argument("--code-only", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--message", default="Update CAN IDS source from laptop")
    parser.add_argument("--source-commit", default="")
    args = parser.parse_args()
    root = target_folder(args.target)
    initial = not (root / MANIFEST).exists()
    files, hashes = read_package(sys.stdin.buffer)
    root.mkdir(parents=True, exist_ok=True)
    # Keep lock, manifest and backups inside the chosen project folder.
    lock = root / ".can_ids-sync-lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise SystemExit("Another sync is running (or left a stale lock): " + str(lock))
    try:
        changed, deleted = apply_snapshot(root, files, hashes, args.adopt)
        pending = root / ".can_ids-runtime-pending"
        if pending.is_symlink():
            raise ValueError("Runtime marker must not be a symlink")
        retry = pending.exists()
        if initial or "requirements.txt" in changed or not args.code_only:
            pending.write_text("Runtime setup/checks pending\n", encoding="utf-8")
        if not args.code_only:
            runtime_update(root, changed, initial or retry, not args.no_restart)
            pending.unlink()
        if not args.no_commit:
            tracked = []
            if (root / ".git").exists():
                tracked = [p.decode() for p in subprocess.check_output(
                    ["git", "-C", str(root), "ls-files", "-z"]).split(b"\0") if p]
            message = args.message
            if args.source_commit:
                message += "\n\nLaptop source commit: " + args.source_commit
            # Include formerly tracked source so a failed previous run's deletions
            # are checkpointed too; protected paths remain excluded.
            commit = commit_source(root, [*files, *deleted, *tracked], message)
            print("Pi source checkpoint: " + commit[:12], flush=True)
    finally:
        lock.rmdir()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, RuntimeError) as error:
        raise SystemExit("Pi sync failed: " + str(error))
