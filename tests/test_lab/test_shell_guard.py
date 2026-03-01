"""Tests for lab.shell_guard — hard kill-switch for local CLI calls."""
from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lab.shell_guard import (
    BLOCKED_BINARIES,
    _extract_binary,
    _guarded_os_system,
    _guarded_popen_init,
    _guarded_run,
    install,
    set_violation_callback,
    uninstall,
)


class TestExtractBinary:

    def test_list_args(self):
        assert _extract_binary(['gh', 'pr', 'view']) == 'gh'

    def test_full_path(self):
        assert _extract_binary(['/opt/homebrew/bin/gh']) == 'gh'

    def test_string_args(self):
        assert _extract_binary('git status') == 'git'

    def test_empty(self):
        assert _extract_binary([]) == ''
        assert _extract_binary('') == ''

    def test_allowed_binary(self):
        assert _extract_binary(['df', '-h']) == 'df'
        assert 'df' not in BLOCKED_BINARIES


class TestGuardedRun:

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_gh_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_run(['gh', 'pr', 'view'])

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_git_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_run(['git', 'status'])

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_pytest_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_run(['pytest', 'tests/'])

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_full_path_blocked(self):
        """Full path like /opt/homebrew/bin/gh is also blocked."""
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_run(['/opt/homebrew/bin/gh', 'release', 'view'])

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_sleep_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_run(['sleep', '10'])

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    @patch('lab.shell_guard._original_run', return_value=MagicMock(returncode=0))
    def test_allowed_binary_passes(self, mock_run):
        """System commands like df are NOT blocked."""
        _guarded_run(['df', '-h'])
        mock_run.assert_called_once()

    @patch('lab.config.ALLOW_LOCAL_SHELL', True)
    @patch('lab.shell_guard._original_run', return_value=MagicMock(returncode=0))
    def test_flag_true_allows_all(self, mock_run):
        """ALLOW_LOCAL_SHELL=True disables the guard."""
        _guarded_run(['gh', 'pr', 'view'])
        mock_run.assert_called_once()


class TestGuardedOsSystem:

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_gh_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_os_system('gh pr view')

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_git_blocked(self):
        with pytest.raises(PermissionError, match='Policy violation'):
            _guarded_os_system('git status')


class TestAllBlockedBinaries:

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_all_binaries_blocked(self):
        """Every binary in BLOCKED_BINARIES raises PermissionError."""
        for binary in BLOCKED_BINARIES:
            with pytest.raises(PermissionError, match='Policy violation'):
                _guarded_run([binary, '--help'])


class TestInstallVerification:
    """Verify that install() actually patches subprocess.run etc."""

    def setup_method(self):
        uninstall()  # start clean

    def teardown_method(self):
        uninstall()  # restore originals

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_subprocess_run_is_patched(self):
        """After install(), subprocess.run IS the guarded wrapper."""
        install()
        assert subprocess.run is _guarded_run

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_os_system_is_patched(self):
        """After install(), os.system IS the guarded wrapper."""
        install()
        assert os.system is _guarded_os_system

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_uninstall_restores(self):
        """After uninstall(), subprocess.run is NOT the guarded wrapper."""
        install()
        assert subprocess.run is _guarded_run
        uninstall()
        assert subprocess.run is not _guarded_run


class TestViolationCallback:
    """Verify that violation callback fires on blocked attempts."""

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_callback_fires_on_block(self):
        """Violation callback receives the blocked binary name."""
        fired = []
        set_violation_callback(lambda binary: fired.append(binary))
        try:
            with pytest.raises(PermissionError):
                _guarded_run(['gh', 'pr', 'view'])
            assert fired == ['gh']
        finally:
            set_violation_callback(None)

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_callback_exception_does_not_prevent_block(self):
        """Even if callback raises, the PermissionError still fires."""
        def bad_callback(binary):
            raise RuntimeError("callback crashed")
        set_violation_callback(bad_callback)
        try:
            with pytest.raises(PermissionError, match='Policy violation'):
                _guarded_run(['git', 'status'])
        finally:
            set_violation_callback(None)

    @patch('lab.config.ALLOW_LOCAL_SHELL', False)
    def test_no_callback_on_allowed(self):
        """Callback does NOT fire for allowed binaries."""
        fired = []
        set_violation_callback(lambda binary: fired.append(binary))
        try:
            with patch('lab.shell_guard._original_run',
                       return_value=MagicMock(returncode=0)):
                _guarded_run(['df', '-h'])
            assert fired == []
        finally:
            set_violation_callback(None)
