# Network and remote access notes

The management connection (`HOME_IFACE`, normally wlan0, or Ethernet) is for SSH, Git and Raspberry Pi Connect. The separate lab AP (`AP_IFACE`, normally a USB adapter such as wlan1) is for the configured demo client. NetworkManager owns both in the supported setup.

| Task | Windows / browser | Pi command or location |
|---|---|---|
| Open terminal | CMD/PowerShell: `ssh piuser@vehicle-pi.local` | SSH enabled in Imager or `sudo systemctl enable --now ssh` |
| PuTTY | Hostname/IP, SSH, port 22 | Same Pi username and Linux commands |
| Connect browser shell | Sign in at `https://connect.raspberrypi.com` | `rpi-connect on`, `rpi-connect signin` |
| VS Code live editing | Remote-SSH: Connect to Host, then Open Folder | `/home/piuser/Can_ids`; saves land directly on the Pi |
| Dashboard on LAN | `http://PI_LAN_IP:5000` | `bash scripts/runner.sh` or the user service |
| Dashboard tunnel | `ssh -L 5000:127.0.0.1:5000 piuser@vehicle-pi.local` | App listening on port 5000 |
| Demo AP browser | Join the `.env` AP_SSID; `http://10.50.0.1:5000` | `sudo .venv/bin/python scripts/setup_wifi.py ap` |

Replace `piuser`, hostname and port with your settings. The demo client may be the same Windows laptop, but switching its only Wi-Fi radio away from home Wi-Fi changes the SSH path: use the AP address `10.50.0.1`, Ethernet or a second adapter. Only the demo client's application controls are blocked; the code does not block SSH.

## Existing hostapd/dnsmasq setups

The old runner rewrote network configuration on startup. The new runner launches only Python and does not stop any other network services.

If this Pi already has a hostapd/dnsmasq AP, use an Ethernet/local management session before migrating. Check what they serve:

```bash
systemctl status hostapd dnsmasq
nmcli device status
sudo cat /etc/hostapd/hostapd.conf
sudo ls /etc/dnsmasq.d
```

If these services belong **only to this old lab AP**, save their configuration, then stop/disable them before asking NetworkManager to manage the USB adapter:

```bash
sudo cp -a /etc/hostapd /etc/hostapd.before-can-ids-networkmanager
sudo cp -a /etc/dnsmasq.d /etc/dnsmasq.d.before-can-ids-networkmanager
sudo systemctl disable --now hostapd dnsmasq
sudo nmcli device set wlan1 managed yes
cd ~/Can_ids
sudo .venv/bin/python scripts/setup_wifi.py ap
```

Replace `wlan1` with `AP_IFACE`. Inspect existing `/etc/NetworkManager/conf.d` and `/etc/dhcpcd.conf` entries if a legacy setup explicitly marks this adapter unmanaged or assigns its IP. Remove only the obsolete entries for this adapter after saving a copy. The helper intentionally does not rewrite those global files.

Keep `AUTO_FIX_AP=0`. If other services depend on hostapd/dnsmasq, retain your existing AP and configure it separately instead of running the NetworkManager AP helper. The gateway itself can monitor any existing AP whose interface/IP match `.env`; old hostapd recovery is available only by explicitly setting `AUTO_FIX_AP=1` and granting the necessary narrowly scoped privileges. The default does not need passwordless sudo.

## Passwords and client identity

`.env` uses python-dotenv syntax, not shell syntax. `HOME_PASSWORD="a password # with spaces"` preserves spaces and `#`. The helper never prints the password and does not include failed command arguments in its error text. NetworkManager stores connection secrets in its own system profile; use `chmod 600 .env` for the project file. No real credentials belong in Git.

`ATTACKER_IP` must be the designated client's **AP-side** IPv4. Find it using Windows `ipconfig`. Use `ip neigh show dev wlan1` and `iw dev wlan1 station dump` on the Pi to check presence. The gateway's ping probe is bound to `AP_IFACE`, so a reachable home-LAN device does not by itself count as an AP client.

For changing DHCP addresses, either reserve a stable address using your network configuration or use `ATTACKER_MAC`. Windows may randomize the hardware address per SSID; record the address actually used on this lab network. The AP helper does not promise `.100` as the lease it will issue.

`ipv4.method=shared` creates DHCP and shared networking on the AP. NetworkManager manages the networking behavior; the Python app enforces only its own HTTP control refusals. It does not authenticate CAN senders or isolate the client at the radio/firewall layer.

## Remote shell versus dashboard

Raspberry Pi Connect can give a browser remote shell without a direct inbound SSH route. That shell can run Git, tests and service commands and can `curl` the local API. It does not make a Windows browser's `localhost:5000` point at the Pi. Use a LAN/VPN SSH route for the tunnel, or Connect desktop sharing with a Pi browser. See [official Connect requirements](https://www.raspberrypi.com/documentation/services/connect.html).

## Disconnect and rollback

Stop only this lab AP with `sudo .venv/bin/python scripts/setup_wifi.py down`. Restart it with the `ap` command; its profile autoconnects on later boots/device reinsertion. If NetworkManager cannot recover the adapter, inspect `journalctl -u NetworkManager` rather than starting a competing hostapd service.

Before a remote update, the deployment helper creates a `backup/pi-before-update-*` branch. Inspect it with `git branch --list 'backup/*'`. To run a known version without losing current edits, create a separate worktree:

```bash
git worktree add ../Can_ids-previous BACKUP_BRANCH_NAME
```

Do not launch both controller copies at once. Review differences and use `git revert` on main if a published update needs undoing.
