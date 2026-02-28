"""Lab Telegram notifier — wraps existing TelegramNotifier."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Import existing notifier
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'trading_bot'))
try:
    from telegram_notifier import TelegramNotifier
except ImportError:
    TelegramNotifier = None

logger = logging.getLogger('lab.notifier')


class LabNotifier:
    """Lab-specific Telegram wrapper with topic/prefix support."""

    PREFIX = '[LAB]'

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and TelegramNotifier is not None
        self._tg = TelegramNotifier() if self.enabled else None
        if not self.enabled:
            logger.info("Telegram notifier disabled (missing token or import)")

    def _send(self, text: str) -> None:
        if not self.enabled:
            logger.info(f"[TG disabled] {text}")
            return
        try:
            self._tg.send(f"{self.PREFIX} {text}")
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ── Message types ─────────────────────────────────────

    def task_created(self, task_id: int, title: str, assigned_to: str,
                     goal_title: str = '') -> None:
        self._send(
            f"📋 Nieuwe taak #{task_id}: <b>{title}</b>\n"
            f"Toegewezen aan: {assigned_to}\n"
            f"Goal: {goal_title}"
        )

    def task_promoted(self, task_id: int, title: str) -> None:
        self._send(
            f"📈 Taak #{task_id} klaar voor jouw review:\n"
            f"<b>{title}</b>\n"
            f"Gebruik: <code>python -m lab.main task approve {task_id}</code>"
        )

    def task_stuck(self, task_id: int, title: str, hours: float,
                   assigned_to: str) -> None:
        self._send(
            f"🚨 Taak #{task_id} vast sinds {hours:.0f}h:\n"
            f"<b>{title}</b>\n"
            f"Agent: {assigned_to}"
        )

    def agent_error(self, agent: str, error: str) -> None:
        self._send(f"⚠️ Agent <b>{agent}</b> error:\n{error[:500]}")

    def heartbeat_summary(self, cycle: int, tasks_reviewed: int,
                          tasks_worked: int, tasks_promoted: int) -> None:
        if tasks_reviewed + tasks_worked + tasks_promoted == 0:
            return  # Geen spam bij idle cycli
        self._send(
            f"🔄 Heartbeat #{cycle}:\n"
            f"Reviews: {tasks_reviewed} | Taken: {tasks_worked} | "
            f"Gepromoot: {tasks_promoted}"
        )

    def infra_check(self, passed: bool, details: str = '') -> None:
        icon = '✅' if passed else '🚨'
        self._send(f"{icon} Infrastructure check: {'PASS' if passed else 'FAIL'}"
                    f"\n{details[:500]}" if details else '')

    def live_drift(self, metric: str, expected: str, actual: str) -> None:
        self._send(
            f"🔍 Live drift gedetecteerd:\n"
            f"Metric: <b>{metric}</b>\n"
            f"Verwacht: {expected}\n"
            f"Actueel: {actual}"
        )

    def deployment_verdict(self, task_id: int, verdict: str,
                           details: str = '') -> None:
        icons = {'GO': '🟢', 'NO-GO': '🔴', 'PAPERTRADE': '🟡'}
        icon = icons.get(verdict, '⚪')
        self._send(
            f"{icon} Deployment verdict: <b>{verdict}</b>\n"
            f"Taak #{task_id}\n{details[:500]}"
        )
