"""Shell guard — hard kill-switch for local CLI calls.

Monkey-patches subprocess.run, subprocess.Popen, and os.system to
block gh, git, pytest, and other binaries that trigger macOS Allow
prompts. InfraGuardian system commands (df, uptime) are unaffected.

Controlled by config.ALLOW_LOCAL_SHELL (default: False).
"""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger('lab.shell_guard')

BLOCKED_BINARIES = frozenset([
    'gh', 'git', 'pytest', 'make', 'which', 'sleep',
])

# Save originals before patching
_original_run = subprocess.run
_original_popen_init = subprocess.Popen.__init__
_original_os_system = os.system


def _extract_binary(args) -> str:
    """Extract binary name from subprocess args."""
    if isinstance(args, (list, tuple)) and args:
        binary = str(args[0])
    elif isinstance(args, str):
        binary = args.split()[0] if args else ''
    else:
        return ''
    # /opt/homebrew/bin/gh → gh
    return binary.rsplit('/', 1)[-1]


def _guarded_run(*args, **kwargs):
    from lab.config import ALLOW_LOCAL_SHELL
    cmd_args = args[0] if args else kwargs.get('args', '')
    binary = _extract_binary(cmd_args)
    if not ALLOW_LOCAL_SHELL and binary in BLOCKED_BINARIES:
        msg = (f"Policy violation: local shell blocked ({binary}). "
               f"Use GitHub Actions or Telegram.")
        logger.error(msg)
        raise PermissionError(msg)
    return _original_run(*args, **kwargs)


def _guarded_popen_init(self, args, *a, **kw):
    from lab.config import ALLOW_LOCAL_SHELL
    binary = _extract_binary(args)
    if not ALLOW_LOCAL_SHELL and binary in BLOCKED_BINARIES:
        msg = (f"Policy violation: local shell blocked ({binary}). "
               f"Use GitHub Actions or Telegram.")
        logger.error(msg)
        raise PermissionError(msg)
    _original_popen_init(self, args, *a, **kw)


def _guarded_os_system(command):
    from lab.config import ALLOW_LOCAL_SHELL
    binary = _extract_binary(command)
    if not ALLOW_LOCAL_SHELL and binary in BLOCKED_BINARIES:
        msg = (f"Policy violation: local shell blocked ({binary}). "
               f"Use GitHub Actions or Telegram.")
        logger.error(msg)
        raise PermissionError(msg)
    return _original_os_system(command)


_installed = False


def install() -> None:
    """Install subprocess guard. Call once at lab startup."""
    global _installed
    if _installed:
        return

    from lab.config import ALLOW_LOCAL_SHELL
    if ALLOW_LOCAL_SHELL:
        logger.info("Shell guard inactive (ALLOW_LOCAL_SHELL=True)")
        _installed = True
        return

    subprocess.run = _guarded_run
    subprocess.Popen.__init__ = _guarded_popen_init
    os.system = _guarded_os_system
    _installed = True
    logger.info(f"Shell guard active: {sorted(BLOCKED_BINARIES)} blocked")


def uninstall() -> None:
    """Restore original subprocess functions (for testing)."""
    global _installed
    subprocess.run = _original_run
    subprocess.Popen.__init__ = _original_popen_init
    os.system = _original_os_system
    _installed = False
