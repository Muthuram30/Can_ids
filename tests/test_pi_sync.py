"""Real snapshot/receiver tests in disposable directories; no SSH or Pi required."""
import argparse
import io
import json
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts import pi_sync_receiver as receiver
from scripts import sync_pi as sender


def project(**extra):
    return dict({"app.py": b"# app\n", "can_features.py": b"# features\n"}, **extra)


def apply(root, files, adopt=False):
    with sender.snapshot(files) as bundle:
        parsed, hashes = receiver.read_package(bundle)
    return receiver.apply_snapshot(root, parsed, hashes, adopt)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "can_ids"

    def test_add_modify_delete_rename_and_backup(self):
        apply(self.root, project(**{"old/nested.txt": b"old", "rename.txt": b"rename"}))
        (self.root / ".env").write_text("HOME_PASSWORD=keep-me\n")
        (self.root / "can_ids_model.joblib").write_bytes(b"trained-model")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "keep.txt").write_text("local dependency")
        files = project(**{"app.py": b"# modified\n", "new.txt": b"new", "renamed.txt": b"rename"})
        changed, deleted = apply(self.root, files)
        self.assertEqual(set(deleted), {"old/nested.txt", "rename.txt"})
        self.assertFalse((self.root / "old").exists())
        self.assertEqual((self.root / "app.py").read_bytes(), b"# modified\n")
        self.assertEqual((self.root / "renamed.txt").read_bytes(), b"rename")
        self.assertEqual((self.root / ".env").read_text(), "HOME_PASSWORD=keep-me\n")
        self.assertEqual((self.root / "can_ids_model.joblib").read_bytes(), b"trained-model")
        self.assertEqual((self.root / ".venv" / "keep.txt").read_text(), "local dependency")
        backups = list((self.root / ".can_ids-backups").glob("*/old/nested.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old")
        self.assertEqual(apply(self.root, files), ([], []))

    def test_first_adoption_removes_obsolete_source_but_preserves_secrets_and_runtime(self):
        self.root.mkdir()
        (self.root / "obsolete.py").write_text("old")
        for name in (".env", "credentials.json", "secrets.json"):
            (self.root / name).write_text("private")
        (self.root / "run").mkdir()
        (self.root / "run" / "state.json").write_text("runtime")
        with self.assertRaises(ValueError):
            apply(self.root, project())
        apply(self.root, project(), adopt=True)
        self.assertFalse((self.root / "obsolete.py").exists())
        for name in (".env", "credentials.json", "secrets.json", "run/state.json"):
            self.assertTrue((self.root / name).exists(), name)

    def test_managed_file_can_become_directory_and_back(self):
        apply(self.root, project(**{"node": b"file"}))
        apply(self.root, project(**{"node/child.py": b"child"}))
        self.assertEqual((self.root / "node/child.py").read_bytes(), b"child")
        apply(self.root, project(**{"node": b"file again"}))
        self.assertEqual((self.root / "node").read_bytes(), b"file again")

    def test_unmanaged_directory_contents_are_not_erased(self):
        apply(self.root, project(**{"node/managed.py": b"managed"}))
        (self.root / "node/private.txt").write_text("Pi only")
        with self.assertRaises(ValueError):
            apply(self.root, project(**{"node": b"file"}))
        self.assertTrue((self.root / "node/managed.py").exists())
        self.assertEqual((self.root / "node/private.txt").read_text(), "Pi only")

    def test_protected_and_traversal_archive_paths_rejected(self):
        for name in ("../outside", "/home/can_ids/app.py", ".env", ".git/config", "run/usb.json", "credentials.json"):
            with self.subTest(name=name):
                with sender.snapshot(project(**{name: b"bad"})) as bundle:
                    with self.assertRaises(ValueError):
                        receiver.read_package(bundle)

    def test_symlink_archive_entry_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
            member = tarfile.TarInfo("app.py")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            bundle.addfile(member)
        buffer.seek(0)
        with self.assertRaises(ValueError):
            receiver.read_package(buffer)

    def test_damaged_package_rejected(self):
        # Create a well-formed package with an incorrect content digest.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            metadata = json.dumps(dict(version=1, files={})).encode()
            info = tarfile.TarInfo(receiver.PACKAGE)
            info.size = len(metadata)
            archive.addfile(info, io.BytesIO(metadata))
        buffer.seek(0)
        with self.assertRaises(ValueError):
            receiver.read_package(buffer)

    def test_manifest_cannot_delete_outside_target(self):
        apply(self.root, project())
        state = dict(version=1, root=str(self.root), files={"../outside.txt": "bad"})
        (self.root / receiver.MANIFEST).write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            apply(self.root, project())

    def test_receiver_bootstrap_runs_with_real_stdin_archive(self):
        args = argparse.Namespace(adopt=False, code_only=True, no_restart=False)
        config = dict(host="user@pi", port=2222, target=str(self.root))
        command = sender.ssh_command(config, args)
        remote = shlex.split(command[-1])
        with sender.snapshot(project(**{"nested/demo.py": b"demo"})) as archive:
            result = subprocess.run([sys.executable, *remote[1:]], stdin=archive,
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "nested/demo.py").read_bytes(), b"demo")
        self.assertFalse((self.root / ".can_ids-sync-lock").exists())

    def test_git_working_tree_includes_unsaved_to_git_edits_and_deletions(self):
        # Saved editor files participate even before git add/commit.
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "app.py").write_text("original")
        (self.root / "can_features.py").write_text("features")
        (self.root / "removed.py").write_text("remove")
        (self.root / ".gitignore").write_text(".env\n.venv/\n")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        (self.root / "removed.py").unlink()
        (self.root / "new.py").write_text("new")
        (self.root / "app.py").write_text("edited")
        (self.root / ".env").write_text("private")
        files = sender.source_files(self.root)
        self.assertEqual(files["app.py"], b"edited")
        self.assertIn("new.py", files)
        self.assertNotIn("removed.py", files)
        self.assertNotIn(".env", files)

    def test_config_accepts_different_users_and_rejects_broad_targets(self):
        for target in ("~/can_ids", "/home/can_ids", "/home/muthu/can_ids", "/muthu/can_ids"):
            self.assertEqual(sender.validate_config(dict(host="muthu@pi.local", target=target))["target"], target)
        for target in ("/", "/home", "~/", "/home/muthu", "relative/can_ids"):
            with self.assertRaises(ValueError):
                sender.validate_config(dict(host="muthu@pi.local", target=target))
        with self.assertRaises(ValueError):
            sender.validate_config(dict(host="pi -o ProxyCommand=bad", target="~/can_ids"))


if __name__ == "__main__":
    unittest.main()
