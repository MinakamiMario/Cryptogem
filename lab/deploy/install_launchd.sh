#!/usr/bin/env bash
# Install Cryptogem Lab as macOS launchd daemon.
# Resolves __HOME__ and __REPO__ placeholders in the plist template.
set -euo pipefail

PLIST_NAME="com.cryptogem.lab"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLIST_SRC="$SCRIPT_DIR/${PLIST_NAME}.plist"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
DOMAIN="gui/$(id -u)"

echo "Installing ${PLIST_NAME}..."
echo "  Repo:  $REPO_ROOT"
echo "  Home:  $HOME"
echo "  Plist: $PLIST_DST"

# Ensure LaunchAgents directory exists
mkdir -p "$HOME/Library/LaunchAgents"

# Unload if already loaded
launchctl bootout "${DOMAIN}/${PLIST_NAME}" 2>/dev/null || true

# Template → concrete plist with user paths
sed -e "s|__HOME__|$HOME|g" -e "s|__REPO__|$REPO_ROOT|g" "$PLIST_SRC" > "$PLIST_DST"

# Load + immediate start
launchctl bootstrap "$DOMAIN" "$PLIST_DST"
launchctl kickstart -k "${DOMAIN}/${PLIST_NAME}"

# Verify
sleep 2
if launchctl print "${DOMAIN}/${PLIST_NAME}" > /dev/null 2>&1; then
    echo "✅ ${PLIST_NAME} installed and running"
    echo ""
    echo "Useful commands:"
    echo "  Status:  launchctl print ${DOMAIN}/${PLIST_NAME}"
    echo "  Stop:    launchctl bootout ${DOMAIN}/${PLIST_NAME}"
    echo "  Restart: launchctl kickstart -k ${DOMAIN}/${PLIST_NAME}"
    echo "  Logs:    tail -f ~/Library/Logs/cryptogem-lab.{out,err}.log"
else
    echo "❌ Failed to start ${PLIST_NAME}"
    exit 1
fi
