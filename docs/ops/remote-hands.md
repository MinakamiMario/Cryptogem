# Remote Hands — Tailscale + RustDesk

## Doel

Remote GUI-toegang tot de Mac vanuit Android (of elk ander device)
via een beveiligde Tailscale tunnel + RustDesk directe verbinding.

**Gebruik**: systeembeheer, macOS permission prompts, crash recovery,
OS updates — alles wat niet via Telegram of SSH kan.

## Policy

### Auto-login: UIT

Auto-login blijft **uitgeschakeld**. Consequentie:

- Na een reboot moet je **lokaal** inloggen (wachtwoord op scherm)
  voordat RustDesk control werkt.
- Tailscale daemon start wel automatisch (LaunchDaemon = root),
  maar RustDesk draait als user-level service en wacht op login.
- **Focus op uptime + gecontroleerde reboots** — voorkom ongeplande
  reboots. Zie [Controlled Reboot Runbook](#controlled-reboot-runbook).

### Waarom geen auto-login

- FileVault disk-encryptie vereist wachtwoord bij boot
- Onbeveiligde fysieke toegang bij diefstal
- macOS Keychain is pas beschikbaar na login

## Verbindingsmethode

```
Adres:     100.67.19.108:21118
Protocol:  TCP direct (geen relay)
Auth:      Permanent wachtwoord (ingesteld in RustDesk GUI)
```

**Gebruik altijd het Tailscale IP** — nooit het RustDesk ID (275203157).
Het ID gaat via de publieke rendezvous server; het Tailscale IP blijft
binnen je eigen encrypted mesh.

### Verbinden vanaf Android

1. Open Tailscale app — check dat je verbonden bent
2. Open RustDesk app
3. Voer in: `100.67.19.108:21118`
4. Voer permanent wachtwoord in
5. Verbonden

## Firewall (pf)

RustDesk poorten zijn **alleen bereikbaar via Tailscale** (100.64.0.0/10).
Alle andere bronnen (LAN, WiFi, internet) worden geblokkeerd door pf.

```
# /etc/pf.anchors/com.rustdesk.tailscale-only
block in quick proto tcp from ! 100.64.0.0/10 to any port 21115:21119
block in quick proto udp from ! 100.64.0.0/10 to any port 21116
```

Anchor is geladen via `/etc/pf.conf` en actief bij boot.

### Verificatie firewall

```bash
sudo pfctl -s info | head -3          # Status: Enabled
sudo pfctl -a com.rustdesk.tailscale-only -sr   # block rules zichtbaar
```

## Componenten

| Component | Type | Auto-start | Pad |
|-----------|------|------------|-----|
| Tailscale | LaunchDaemon (root) | Ja, bij boot | `/Library/LaunchDaemons/com.tailscale.tailscaled.plist` |
| RustDesk  | LaunchDaemon (root) | Ja, na login | `/Library/LaunchDaemons/com.carriez.RustDesk_service.plist` |
| pf anchor | Boot config | Ja, bij boot | `/etc/pf.anchors/com.rustdesk.tailscale-only` |

## Checklist na reboot

Na een (geplande) reboot, check vanuit je telefoon:

1. **Log lokaal in** op de Mac (wachtwoord op scherm)
2. **Tailscale**: open Tailscale app op Android — Mac moet online staan
3. **RustDesk**: verbind met `100.67.19.108:21118` — scherm zichtbaar
4. **Firewall**: optioneel, via RustDesk terminal:
   ```bash
   sudo pfctl -s info | grep Status
   ```
5. **Lab daemon**: check Telegram — dashboard moet werken (📊 knop)

## Recovery

### RustDesk niet bereikbaar

1. Check Tailscale app op Android — staat de Mac online?
   - **Nee** → Mac is uit of Tailscale daemon crashed. Lokale toegang nodig.
   - **Ja** → RustDesk probleem. Ga naar stap 2.
2. SSH via Tailscale: `ssh oussama@100.67.19.108`
3. Check RustDesk:
   ```bash
   lsof -nP -iTCP:21118 -sTCP:LISTEN
   # Leeg? Herstart:
   open /Applications/RustDesk.app
   ```

### Tailscale niet bereikbaar

1. Mac is waarschijnlijk uit of WiFi is weg
2. Fysieke toegang nodig — of wacht tot Mac weer online komt
3. Na fysieke login, check:
   ```bash
   /opt/homebrew/bin/tailscale status
   # Als "not running":
   sudo launchctl load -w /Library/LaunchDaemons/com.tailscale.tailscaled.plist
   /opt/homebrew/bin/tailscale up
   ```

### Tailscale key expired

1. Ga naar: https://login.tailscale.com/admin/machines
2. Klik op de Mac → **Disable key expiry**
3. Of: lokaal `tailscale up --reset` uitvoeren

## Controlled Reboot Runbook

### HARD RULE

> **Nooit rebooten zonder maintenance window + lokale login beschikbaar.**
>
> - Reboot is een **expliciete taak** met owner (jij, de user)
> - Agents mogen NOOIT een reboot initiëren of suggereren
> - Geen `sudo reboot`, `shutdown`, of `restart` in agent code
> - Shell guard blokkeert `reboot` en `shutdown` binaries

### Wanneer rebooten

- macOS systeemupdates die reboot vereisen
- Kernel panics of onherstelbare freezes
- Gepland onderhoud (maintenance window)
- **Altijd**: fysieke toegang of RustDesk-verbinding bevestigd vóór reboot

### Stappen

1. **Notify via Telegram**:
   ```bash
   python -m lab.tg "🔄 Geplande reboot in 5 minuten — maintenance"
   ```
2. **Stop lab daemon**:
   ```bash
   launchctl bootout gui/$(id -u)/com.cryptogem.lab
   ```
3. **Reboot**:
   ```bash
   sudo reboot
   ```
4. **Log lokaal in** (wachtwoord op scherm)
5. **Verify Remote Hands** — checklist hierboven
6. **Verify lab daemon**:
   ```bash
   launchctl print gui/$(id -u)/com.cryptogem.lab
   python3 -m lab.main status --tg
   ```
7. **Confirm via Telegram**: dashboard moet werken

### Na reboot: waarom RustDesk even niet kan

RustDesk draait als user-level service. Zolang het macOS loginscherm
actief is (voor je wachtwoord invoert), is er geen user session →
geen RustDesk. Tailscale werkt wel (root daemon), dus je kunt SSH
gebruiken als noodpad, maar GUI-control vereist lokale login.

## Setup script

Initiële installatie (eenmalig, met sudo):

```bash
sudo bash lab/deploy/setup-remote-hands.sh
```

Zie `lab/deploy/setup-remote-hands.sh` voor details.
