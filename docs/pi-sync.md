# One-command Windows → Pi source synchronization

Run `run_pi.cmd` from the local CAN IDS checkout, including VS Code's integrated terminal. It uses Windows OpenSSH, Git and Python's standard library. No GitHub push, WSL, rsync or Windows pip installation is required.

## First connection

On the laptop, install Git for Windows, Python 3.9+ and the Windows OpenSSH client if missing. On the Pi, enable SSH in Imager or the OS settings first. The runner then checks prerequisites with an interactive SSH session and installs missing Python/venv/Git/SSH-client/nano packages using apt/sudo before committing source. If automatic package setup is unavailable, the manual equivalent is:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git openssh-client nano
```

From your Windows checkout:

```powershell
.\run_pi.cmd --host muthu@vehicle-pi.local --target ~/can_ids
```

Replace the login/host. You may use an SSH config alias instead of `user@host`. SSH asks you to verify a new host fingerprint and uses its normal password/key authentication. The runner saves host, target, port and optional key path in the Git-ignored `.pi-sync.json`; it does not store passwords or private-key contents. It verifies/creates your chosen Pi folder before the first laptop source commit. A Git clone and an extracted GitHub repository ZIP are both supported; a ZIP checkout is initialized as a local Git repository after setup succeeds. Future updates need only:

```powershell
.\run_pi.cmd
```

To change the Pi/destination: `run_pi.cmd --setup`. Additional options are `--port 2222` and `--identity C:\Users\YOU\.ssh\id_ed25519`.

## Choose any owned can_ids folder

| Saved target | Meaning |
|---|---|
| `~/can_ids` | SSH user's home, e.g. `/home/muthu/can_ids` |
| `/home/can_ids` | Shared location directly under `/home`, owned by your Pi user |
| `/home/another_user/can_ids` | Works when the SSH user has permission there |
| `/muthu/can_ids` | Custom absolute location, with writable parents |

The receiver requires a project folder named `can_ids` (case-insensitive) and rejects broad targets such as `/home`, `/`, or a user's home directory. Paths must not contain symbolic links. It resolves and checks every managed path before writing/removing source. It never runs recursive deletion of a target directory.

For a new `/home/can_ids` folder that your normal user cannot create, the setup session uses `sudo install -d` for that validated new destination and asks for your normal sudo authentication. It does not change ownership of existing unrelated folders. The equivalent manual Pi-terminal command is:

```bash
sudo install -d -o "$(id -un)" -g "$(id -gn)" /home/can_ids
```

Use the same approach for another explicitly chosen location. The app and sync receiver run as your SSH user, not root. All source, `.venv`, `.env`, sync metadata, lock and backups are inside the selected project directory. The optional app service is registered in the user's standard systemd configuration and points to that directory.

## Add, edit, delete and rename from VS Code

The runner packages the saved working tree, including new non-ignored files and edits that have not been staged or committed. It excludes deleted files even if Git still has their old index entries. Each transfer verifies content hashes before applying changes.

| Local change | Next sync on the Pi |
|---|---|
| Add a source file | Create it under the same relative path |
| Save edits | Replace that file with its exact saved contents |
| Delete a previously synchronized file | Back it up, then remove it |
| Rename/move | Add the new path and remove the old managed path |
| File becomes folder or folder becomes file | Apply when the old subtree contains only managed source; otherwise stop |
| Unchanged source | Leave its contents untouched |
| Change `.env` or generate models/logs locally | Excluded; the Pi's local runtime/configuration survives |

The transferred snapshot is the source of truth for managed source files; later Pi-side edits to those same files will be replaced on the next sync, with the previous version backed up. Each update creates a laptop source commit by default, transfers the snapshot and records a separate Pi Git checkpoint after successful checks (or after transfer with `--code-only`). The Pi message records the laptop SHA. This is file synchronization with history, without a line-level merge or network-delta algorithm. Use `--no-commit` to disable both checkpoints and `--message "Describe update"` to set their message. No-change runs do not create empty commits. Existing Git identity is used; absent identity gets a per-command CAN IDS Sync identity, leaving global Git configuration untouched. Already-staged protected files abort the commit instead of being included.

### Existing Pi project

An existing nonempty source folder without the sync manifest requires first-time adoption:

```powershell
.\run_pi.cmd --adopt
```

This explicitly adopts non-runtime regular source files in the selected folder and removes obsolete ones that are absent locally, after backing them up. Later runs use the manifest to know which old paths to remove. Files created independently on the Pi after adoption are preserved unless a local source path would overwrite them; conflicts with an unmanaged directory stop the operation.

Protected content includes `.env` variants (except the example), `.venv`, `.git`, `.vscode`, logs, `run/`, private keys, `credentials.json`, `secrets.json`, trained joblib/pickle models and captured files under `data/`. Sync metadata and backups are also protected and excluded from uploads. For a new data asset that should be deployed, use a regular non-ignored source asset location rather than `data/`.

## Watch saves automatically

```powershell
.\run_pi.cmd --watch
```

The first snapshot is sent immediately, then the runner watches saved source changes with a short quiet interval. Each later transfer requires noninteractive SSH key/agent authentication; password prompts on every save would interrupt development. Configure an SSH key if needed:

```powershell
ssh-keygen -t ed25519
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh muthu@vehicle-pi.local 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
```

Use the public key belonging to the identity you intend to use. Authenticate encrypted keys through your SSH agent before watching. Test `ssh -o BatchMode=yes muthu@vehicle-pi.local true`. Password-only users can run `run_pi.cmd` manually after saving instead. Ctrl+C stops watching. If a transfer fails, watch mode keeps local changes and retries; it does not report them as successfully synchronized.

## Runtime preparation and restart

Normal runs first check/create the connection and folder, checkpoint changed laptop source, then transfer it. On the Pi they create `.venv` when needed, install requirements initially/when they change, run the project's software tests and restart an **already running** `vehicle-ids.service` only after tests pass. The unit is regenerated with the selected path. The runner performs a bounded health check after restart. A fresh `.env` is copied from the example only if absent; edit the actual Pi Wi-Fi/client settings once.

For first-time service installation, you can now use `.\run.cmd start` from Windows. The equivalent from SSH/PuTTY/Connect is:

```bash
cd ~/can_ids  # replace with your chosen target
nano .env
bash scripts/install_service.sh
sudo loginctl enable-linger "$USER"
```

The one-command source runner does not implicitly change Wi-Fi, set up CAN or flash ESP32 firmware; follow their README setup once.

| Option | Effect |
|---|---|
| `--code-only` | Synchronize source; skip dependency installation, tests and service actions |
| `--no-restart` | Prepare/install/test, leaving the running service untouched |
| `--watch --code-only` | Automatic saved-source mirroring without restarting on every edit |
| `--setup` | Change saved login, target and port |
| `--no-commit` | Disable laptop and Pi source checkpoints |
| `--message "Lab update"` | Set the source-checkpoint commit message |
| `--adopt` | First-time ownership of an existing target's non-runtime source |

If dependencies/tests fail, the source files may already be updated and the existing service has not been restarted. A pending marker makes the next normal run retry dependency preparation/checks. Source and dependency installation are not a single rollback transaction. If a sync is killed and leaves `.can_ids-sync-lock`, verify no runner is active and remove that **empty lock directory only** before retrying.

Previous overwritten/deleted source lives in `<chosen-folder>/.can_ids-backups/<timestamp>/` with its original relative paths. Restore selected files from there if needed, then make the corresponding change locally before the next sync. Backups are kept until you deliberately remove them.

## Run the app or open a terminal with run.cmd

Both runners share the same saved host, folder, port and identity. Run these from the laptop checkout:

```powershell
.\run.cmd
.\run.cmd app
.\run.cmd terminal
.\run.cmd start
.\run.cmd stop
.\run.cmd restart
.\run.cmd status
.\run.cmd logs
.\run.cmd test
.\run.cmd config
.\run.cmd train
```

No action opens a numbered menu. `app` runs the controller in the foreground, or follows existing service logs if the service is already active. `terminal` opens an interactive Pi shell in the selected folder. `start` installs/enables/starts the user service with that folder's actual path; `stop/restart/status/logs` control it. `config` opens the Pi `.env` in nano. `test` runs the software tests and `train` generates the synthetic baseline model. None of these commands pushes GitHub changes.

You can use the same SSH host from VS Code Remote SSH, Windows Terminal or PuTTY. The network may be Wi-Fi, Ethernet, hotspot or VPN as long as Windows can reach the Pi SSH port. A GitHub repository is the source/download location, not a network tunnel. Raspberry Pi Connect remote shell alone does not make the Pi reachable to Windows SSH; use a LAN/VPN route or perform commands inside that browser shell.

## Publish to GitHub separately

After a normal `run_pi.cmd` update, the source commit already exists on the laptop; review `git log -1` and push. For changes made outside the runner, the equivalent manual workflow is:

```powershell
git status --short
git add -A
git diff --cached
git commit -m "Describe the CAN IDS update"
git push origin main
```

If the changes were already committed for you, only `git push origin main` is necessary. To publish the preserved original version as well: `git push origin backup/before-pi-integration-20261122`. No force push is needed.
