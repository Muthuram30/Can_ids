"""Exercise both ends with real Git/files/subprocesses and a local SSH transport shim."""
import argparse
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sync_pi as sync
from scripts import pi_sync_receiver as receiver
from scripts import run_pi_control as launcher
from scripts import pi_control


class PiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.local = self.base / "laptop"
        self.pi = self.base / "can_ids"
        (self.local / "scripts").mkdir(parents=True)
        self.receiver_source = (sync.ROOT / "scripts/pi_sync_receiver.py").read_bytes()
        (self.local / "scripts/pi_sync_receiver.py").write_bytes(self.receiver_source)
        (self.local / "app.py").write_text("# original app\n")
        (self.local / "can_features.py").write_text("# features\n")
        (self.local / ".gitignore").write_text(".env\n.pi-sync.json\n")
        self.config = dict(host="lab-pi", port=22, target=str(self.pi))
        self.real_run = subprocess.run

    def invoke_preflight_python(self, config, adopt):
        # Execute the actual target check embedded in the SSH preflight, while
        # leaving its apt/sudo prerequisite branch unexecuted on Windows.
        command = sync.preflight_command(config, adopt)
        shell = shlex.split(command[-1])[2]
        check = shlex.split(shell.splitlines()[-1])
        return self.real_run([sys.executable, *check[1:]], check=True, capture_output=True)

    def transport(self, command, **kwargs):
        if command[0] == "ssh":
            if "-t" in command:
                self.assertFalse((self.local / ".git").exists())
                return self.invoke_preflight_python(self.config, False)
            self.assertTrue((self.local / ".git").exists())
            remote = shlex.split(command[-1])
            return self.real_run([sys.executable, *remote[1:]], **kwargs)
        return self.real_run(command, **kwargs)

    def test_first_setup_then_real_git_checkpoints_and_source_reconciliation(self):
        args = argparse.Namespace(no_commit=False, message="Lab source update", adopt=False,
                                  code_only=True, no_restart=False)
        with patch.object(sync, "ROOT", self.local), patch.object(sync.subprocess, "run", side_effect=self.transport):
            sync.prepare(self.config)
            self.assertTrue(self.pi.is_dir())
            sync.sync_once(self.config, args)
            local_first = subprocess.check_output(["git", "-C", str(self.local), "rev-parse", "HEAD"]).decode().strip()
            (self.pi / ".env").write_text("LAB_SECRET=preserve\n")
            (self.local / "new.py").write_text("# added\n")
            (self.local / "app.py").write_text("# modified app\n")
            (self.local / "old.py").write_text("# old\n")
            sync.sync_once(self.config, args)
            (self.local / "old.py").rename(self.local / "renamed.py")
            sync.sync_once(self.config, args)
        self.assertEqual((self.pi / "app.py").read_text(), "# modified app\n")
        self.assertTrue((self.pi / "new.py").exists())
        self.assertTrue((self.pi / "renamed.py").exists())
        self.assertFalse((self.pi / "old.py").exists())
        self.assertEqual((self.pi / ".env").read_text(), "LAB_SECRET=preserve\n")
        local_head = subprocess.check_output(["git", "-C", str(self.local), "rev-parse", "HEAD"]).decode().strip()
        self.assertNotEqual(local_first, local_head)
        pi_message = subprocess.check_output(["git", "-C", str(self.pi), "log", "-1", "--format=%B"]).decode()
        self.assertIn(local_head, pi_message)
        pi_tracked = subprocess.check_output(["git", "-C", str(self.pi), "ls-files"]).decode()
        self.assertNotIn(".env\n", pi_tracked)
        self.assertNotIn(".can_ids-sync.json", pi_tracked)
        self.assertTrue(list((self.pi / ".can_ids-backups").glob("*/old.py")))

    def test_failed_setup_prevents_any_laptop_commit(self):
        with patch.object(sync, "ROOT", self.local), \
             patch.object(sync, "configuration", return_value=self.config), \
             patch.object(sync, "prepare", side_effect=RuntimeError("unreachable Pi")), \
             patch.object(sync, "checkpoint") as commit, patch.object(sys, "argv", ["sync_pi.py"]):
            with self.assertRaises(RuntimeError):
                sync.main()
            commit.assert_not_called()
        self.assertFalse((self.local / ".git").exists())

    def test_git_commits_adopted_deletions_and_file_directory_changes(self):
        self.pi.mkdir()
        (self.pi / "old.py").write_text("old")
        receiver.commit_source(self.pi, ["old.py"], "first")
        (self.pi / "old.py").unlink()
        (self.pi / "old.py").mkdir()
        (self.pi / "old.py" / "child.py").write_text("child")
        receiver.commit_source(self.pi, ["old.py", "old.py/child.py", "never-tracked-deleted.py"], "second")
        tracked = subprocess.check_output(["git", "-C", str(self.pi), "ls-files"]).decode().splitlines()
        self.assertEqual(tracked, ["old.py/child.py"])

    def test_already_staged_secrets_are_never_committed(self):
        self.pi.mkdir()
        (self.pi / "app.py").write_text("source")
        receiver.commit_source(self.pi, ["app.py"], "source")
        before = subprocess.check_output(["git", "-C", str(self.pi), "rev-parse", "HEAD"])
        (self.pi / ".env").write_text("secret")
        subprocess.run(["git", "-C", str(self.pi), "add", ".env"], check=True)
        with self.assertRaises(ValueError):
            receiver.commit_source(self.pi, ["app.py"], "should fail")
        self.assertEqual(before, subprocess.check_output(["git", "-C", str(self.pi), "rev-parse", "HEAD"]))

    def test_controller_quotes_custom_folder_and_opens_interactive_ssh(self):
        config = dict(host="user@pi", port=2222, target="~/lab space/can_ids")
        command = launcher.command(config, "terminal")
        self.assertIn("-t", command)
        self.assertIn('"$HOME"/', command[-1])
        self.assertIn("'lab space/can_ids'", command[-1])
        self.assertTrue(command[-1].endswith("exec bash"))
        self.assertIn("scripts/pi_control.py", launcher.command(config, "app")[-1])

    def test_app_does_not_start_a_second_controller_over_service(self):
        python = self.local / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(pi_control, "ROOT", self.local), patch.object(pi_control, "PYTHON", python), \
             patch.object(pi_control.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            pi_control.perform("app")
        self.assertEqual(run.call_args.args[0][0], "journalctl")
        self.assertFalse(any(call.args[0][0] == str(python) for call in run.call_args_list))

    def test_foreground_and_tests_use_chosen_pi_venv(self):
        python = self.local / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(pi_control, "ROOT", self.local), patch.object(pi_control, "PYTHON", python), \
             patch.object(pi_control.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)) as run:
            pi_control.perform("app")
            self.assertEqual(run.call_args.args[0], (str(python), "app.py"))
            pi_control.perform("test")
            self.assertIn("unittest", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["cwd"], self.local)


if __name__ == "__main__":
    unittest.main()
