# Lab Deployment

## macOS (launchd) — Primary

### Install (one-time)

```bash
bash lab/deploy/install_launchd.sh
```

The script:
- Resolves `__HOME__` and `__REPO__` placeholders in the plist template
- Copies the resolved plist to `~/Library/LaunchAgents/`
- Loads and starts the daemon immediately

### Daily Operations

```bash
# Status
launchctl print gui/$(id -u)/com.cryptogem.lab

# Stop
launchctl bootout gui/$(id -u)/com.cryptogem.lab

# Restart
launchctl kickstart -k gui/$(id -u)/com.cryptogem.lab

# Logs (live)
tail -f ~/Library/Logs/cryptogem-lab.out.log
tail -f ~/Library/Logs/cryptogem-lab.err.log

# Healthcheck (sends dashboard to Telegram)
python3 -m lab.main status --tg
```

### Self-Test

The lab runs an automatic self-test at every startup:
- **Hard checks** (fail = daemon aborts): BotToken, DB, Agents, Telegram
- **Soft checks** (warn only): Active goals

Results are sent to Telegram automatically.

## Linux (systemd)

```bash
sudo cp lab/deploy/lab.service /etc/systemd/system/
mkdir -p lab/logs
sudo systemctl enable cryptogem-lab
sudo systemctl start cryptogem-lab
sudo systemctl status cryptogem-lab
```

## Remote Hands (Android)

Volledige remote GUI-toegang via Tailscale + RustDesk.
Zie **[docs/ops/remote-hands.md](../../docs/ops/remote-hands.md)** voor het complete runbook.

### Verbinding

```
Adres:  100.67.19.108:21118  (Tailscale IP, direct TCP)
Auth:   Permanent wachtwoord (RustDesk GUI → Settings → Security)
```

### Policy

- **Auto-login: UIT** — reboot vereist lokale login voordat RustDesk werkt
- **Firewall**: RustDesk poorten alleen via Tailscale (pf anchor actief)
- **Geen relay**: `direct-server = 'Y'`, `enable-tunnel = 'N'`

> **Waarschuwing**: zet auto-login NIET aan. FileVault encryptie en
> Keychain security vereisen login bij boot. Focus op uptime en
> gecontroleerde reboots.

### Quick check

```bash
# Healthcheck
python3 lab/tools/remote_hands_healthcheck.py

# Handmatig
tailscale status                          # Tailscale online?
lsof -nP -iTCP:21118 -sTCP:LISTEN        # RustDesk luistert?
sudo pfctl -a com.rustdesk.tailscale-only -sr  # Firewall actief?
```

### Setup (eenmalig)

```bash
sudo bash lab/deploy/setup-remote-hands.sh
```
