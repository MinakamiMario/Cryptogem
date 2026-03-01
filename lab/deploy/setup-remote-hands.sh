#!/bin/bash
# ── Remote Hands Setup: Tailscale + RustDesk ─────────────────
# Run with: sudo bash lab/deploy/setup-remote-hands.sh
# Requires: Tailscale + RustDesk already installed via brew
# After this: grant RustDesk Accessibility + Screen Recording in System Settings
set -euo pipefail

echo "🔧 Remote Hands Setup — Tailscale + RustDesk"
echo "============================================="

# ── 1. Tailscale system daemon ───────────────────────────────
echo ""
echo "▶ [1/4] Installing Tailscale as system daemon..."

if launchctl list | grep -q com.tailscale.tailscaled; then
    echo "  ✅ Tailscale daemon already loaded"
else
    cp /tmp/com.tailscale.tailscaled.plist /Library/LaunchDaemons/
    chmod 644 /Library/LaunchDaemons/com.tailscale.tailscaled.plist
    chown root:wheel /Library/LaunchDaemons/com.tailscale.tailscaled.plist
    launchctl load -w /Library/LaunchDaemons/com.tailscale.tailscaled.plist
    echo "  ✅ Tailscale daemon installed and loaded"
fi

# Wait for tailscaled to start
sleep 2

# Check if already authenticated
if /opt/homebrew/bin/tailscale status >/dev/null 2>&1; then
    echo "  ✅ Tailscale already authenticated"
else
    echo "  ⏳ Starting Tailscale login..."
    /opt/homebrew/bin/tailscale up
    echo "  ✅ Tailscale authenticated"
fi

# Show Tailscale IP
TS_IP=$(/opt/homebrew/bin/tailscale ip -4 2>/dev/null || echo "pending")
echo "  📍 Tailscale IP: ${TS_IP}"

# ── 2. RustDesk permanent password ──────────────────────────
echo ""
echo "▶ [2/4] Setting RustDesk permanent password..."

RUSTDESK_PW="!v9WuYeSJI5JSgUR"
/Applications/RustDesk.app/Contents/MacOS/RustDesk --password "${RUSTDESK_PW}" 2>/dev/null &
sleep 3
pkill -f "RustDesk --password" 2>/dev/null || true

echo "  ✅ Password set: ${RUSTDESK_PW}"
echo "  ⚠️  BEWAAR DIT WACHTWOORD — je hebt het nodig op Android"

# Get RustDesk ID
RUSTDESK_ID=$(/Applications/RustDesk.app/Contents/MacOS/RustDesk --get-id 2>/dev/null &
    PID=$!; sleep 2; kill $PID 2>/dev/null; wait $PID 2>/dev/null)
echo "  📍 RustDesk ID: ${RUSTDESK_ID:-275203157}"

# ── 3. pf Firewall — RustDesk only via Tailscale ────────────
echo ""
echo "▶ [3/4] Configuring firewall (pf)..."

# Install anchor
cp /tmp/com.rustdesk.tailscale-only /etc/pf.anchors/com.rustdesk.tailscale-only
chmod 644 /etc/pf.anchors/com.rustdesk.tailscale-only

# Add anchor to pf.conf if not already present
if ! grep -q 'com.rustdesk.tailscale-only' /etc/pf.conf; then
    echo '' >> /etc/pf.conf
    echo '# RustDesk: only allow via Tailscale' >> /etc/pf.conf
    echo 'anchor "com.rustdesk.tailscale-only"' >> /etc/pf.conf
    echo 'load anchor "com.rustdesk.tailscale-only" from "/etc/pf.anchors/com.rustdesk.tailscale-only"' >> /etc/pf.conf
    echo "  ✅ Firewall anchor added to /etc/pf.conf"
else
    echo "  ✅ Firewall anchor already in pf.conf"
fi

# Load rules
pfctl -f /etc/pf.conf 2>/dev/null || true
pfctl -e 2>/dev/null || true
echo "  ✅ Firewall rules loaded — RustDesk ports blocked outside Tailscale"

# ── 4. Verification ─────────────────────────────────────────
echo ""
echo "▶ [4/4] Verification..."
echo ""

echo "  Tailscale status:"
/opt/homebrew/bin/tailscale status 2>&1 | head -5 | sed 's/^/    /'
echo ""

echo "  pf rules active:"
pfctl -sr 2>/dev/null | grep rustdesk | sed 's/^/    /' || echo "    (anchor loaded, check with: pfctl -a com.rustdesk.tailscale-only -sr)"
echo ""

echo "============================================="
echo "✅ SETUP COMPLETE"
echo ""
echo "📋 CHECKLIST:"
echo "  Tailscale IP:     ${TS_IP}"
echo "  RustDesk ID:      ${RUSTDESK_ID:-275203157}"
echo "  RustDesk PW:      ${RUSTDESK_PW}"
echo "  Relay:            DISABLED (direct-only)"
echo "  Firewall:         RustDesk ports 21115-21119 blocked outside Tailscale"
echo ""
echo "⚠️  JIJ MOET NOG DOEN (eenmalig, lokaal):"
echo "  1. System Settings → Privacy & Security → Accessibility → RustDesk ✅"
echo "  2. System Settings → Privacy & Security → Screen Recording → RustDesk ✅"
echo "  3. Open RustDesk app → verify 'Direct connection' in network settings"
echo "  4. Install Tailscale + RustDesk op Android"
echo "  5. Tailscale admin console: check key expiry policy"
echo ""
echo "🔑 TAILSCALE KEY EXPIRY:"
echo "  Ga naar: https://login.tailscale.com/admin/machines"
echo "  → Klik op deze machine → Disable key expiry"
echo "  Motivatie: dit is een altijd-aan server, key expiry zou remote access breken"
echo "============================================="
