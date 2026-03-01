#!/usr/bin/env python3
"""Remote Hands healthcheck — quick diagnosis of Tailscale + RustDesk.

Usage:
    python3 lab/tools/remote_hands_healthcheck.py

Output: PASS/FAIL summary per component.
No shell tools that are blocked by shell_guard (no git, gh, pytest, etc.).
"""
from __future__ import annotations

import socket
import subprocess
import sys


TAILSCALE_BIN = '/opt/homebrew/bin/tailscale'
RUSTDESK_PORT = 21118
EXPECTED_TS_IP = '100.67.19.108'


def check_tailscale_running() -> tuple[bool, str]:
    """Check if Tailscale is running and has an IP."""
    try:
        result = subprocess.run(
            [TAILSCALE_BIN, 'ip', '-4'],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        if ip:
            match = '(expected)' if ip == EXPECTED_TS_IP else f'(expected {EXPECTED_TS_IP})'
            return True, f'Tailscale IP: {ip} {match}'
        return False, 'Tailscale: no IPv4 address'
    except FileNotFoundError:
        return False, f'Tailscale binary not found: {TAILSCALE_BIN}'
    except subprocess.TimeoutExpired:
        return False, 'Tailscale: command timeout'
    except Exception as e:
        return False, f'Tailscale: {e}'


def check_rustdesk_listening() -> tuple[bool, str]:
    """Check if RustDesk is listening on the expected port."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            result = s.connect_ex(('::1', RUSTDESK_PORT))
            if result == 0:
                return True, f'RustDesk listening on port {RUSTDESK_PORT}'
    except Exception:
        pass
    # Fallback to IPv4
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            result = s.connect_ex(('127.0.0.1', RUSTDESK_PORT))
            if result == 0:
                return True, f'RustDesk listening on port {RUSTDESK_PORT}'
    except Exception:
        pass
    return False, f'RustDesk NOT listening on port {RUSTDESK_PORT}'


def check_pf_enabled() -> tuple[bool, str]:
    """Best-effort check if pf firewall is enabled.

    Requires root for full check — falls back to checking config file.
    """
    # Try pfctl (needs root, may fail)
    try:
        result = subprocess.run(
            ['pfctl', '-s', 'info'],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if 'Status:' in line:
                enabled = 'Enabled' in line
                return enabled, f'pf: {line.strip()}'
    except Exception:
        pass

    # Fallback: check if config file has our anchor
    try:
        with open('/etc/pf.conf') as f:
            content = f.read()
        if 'com.rustdesk.tailscale-only' in content:
            return True, 'pf: anchor configured in /etc/pf.conf (cannot verify active — needs root)'
        return False, 'pf: anchor NOT found in /etc/pf.conf'
    except Exception as e:
        return False, f'pf: cannot read config — {e}'


def main() -> int:
    checks = [
        ('Tailscale', check_tailscale_running),
        ('RustDesk', check_rustdesk_listening),
        ('Firewall', check_pf_enabled),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, fn in checks:
        ok, detail = fn()
        results.append((name, ok, detail))

    # Output
    print('Remote Hands Healthcheck')
    print('=' * 40)
    all_ok = True
    for name, ok, detail in results:
        icon = 'PASS' if ok else 'FAIL'
        print(f'  [{icon}] {name}: {detail}')
        if not ok:
            all_ok = False

    print('=' * 40)
    if all_ok:
        print('RESULT: ALL PASS')
    else:
        print('RESULT: FAIL — see above')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
