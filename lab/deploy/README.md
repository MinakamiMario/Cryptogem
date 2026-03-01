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

## Remote Access (noodpad)

Als de Mac onbereikbaar is (WiFi weg, lid dicht, etc.):

1. **Tailscale** — zero-config mesh VPN
   - Install: `brew install tailscale` op Mac + Android/Linux remote
   - `tailscale up` op beide devices → direct SSH/screen-sharing
   - Werkt door NAT heen, geen port forwarding nodig

2. **RustDesk / AnyDesk** — remote desktop als backup
   - RustDesk (open source): `brew install --cask rustdesk`
   - AnyDesk (commercial): `brew install --cask anydesk`
   - Beide werken zonder router config

### Aanbevolen setup
```
Tailscale (altijd aan) → SSH voor CLI access
RustDesk (standby)     → GUI voor noodgevallen
```

**Let op**: dit is puur een noodpad. De lab draait autonoom via launchd
en is volledig bestuurbaar via Telegram (✅ ❌ 📊). Remote access is
alleen nodig voor systeembeheer (OS updates, crash recovery, etc.).
