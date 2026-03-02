"""Lab Telegram notifier — uses dedicated lab bot (@datakingbot_bot).

Supports inline keyboard buttons for task approval/rejection via Telegram.
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from lab.config import GITHUB_REPO, REPO_ROOT, WIP_CAPS

# Import existing notifier class for reuse
sys.path.insert(0, str(REPO_ROOT / 'trading_bot'))
try:
    from telegram_notifier import TelegramNotifier
except ImportError:
    TelegramNotifier = None

logger = logging.getLogger('lab.notifier')


def _load_lab_bot_token() -> str | None:
    """Load LAB_TELEGRAM_BOT_TOKEN from trading_bot/.env."""
    import os
    # Check env var first
    token = os.environ.get('LAB_TELEGRAM_BOT_TOKEN')
    if token:
        return token
    # Fall back to .env file
    env_path = REPO_ROOT / 'trading_bot' / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith('LAB_TELEGRAM_BOT_TOKEN=') and not line.endswith('='):
                return line.split('=', 1)[1].strip()
    return None


def _load_github_token() -> str | None:
    """Load GITHUB_TOKEN from env or .env (optional, for private repos)."""
    import os
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        return token
    env_path = REPO_ROOT / 'trading_bot' / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith('GITHUB_TOKEN=') and not line.endswith('='):
                return line.split('=', 1)[1].strip()
    return None


# Chat ID — same as trading bot (your personal chat)
_CHAT_ID = 537907585


class LabNotifier:
    """Lab-specific Telegram wrapper using dedicated @datakingbot_bot.

    Supports inline keyboard buttons for Telegram-based task approval.
    """

    PREFIX = '[LAB]'

    def __init__(self, enabled: bool = True):
        self._tg = None
        self._token = None
        self.enabled = False
        if not enabled or TelegramNotifier is None:
            logger.info("Telegram notifier disabled (flag or missing import)")
            return
        token = _load_lab_bot_token()
        if not token:
            logger.info("Telegram notifier disabled (LAB_TELEGRAM_BOT_TOKEN not set)")
            return
        try:
            self._tg = TelegramNotifier(token=token, chat_id=_CHAT_ID)
            self._token = token
            self._base_url = f'https://api.telegram.org/bot{token}'
            self._last_update_id = 0
            self._update_id_loaded = False  # Lazy-load from DB on first poll
            self._pending_messages: dict[int, int] = {}  # task_id → message_id
            self.enabled = True
            logger.info("Lab Telegram notifier active (@datakingbot_bot)")
        except Exception as e:
            logger.warning(f"Telegram init failed: {e}")

    # ── Core API ───────────────────────────────────────────

    def _api(self, method: str, params: dict | None = None,
             json_body: dict | None = None) -> dict | None:
        """Direct Telegram Bot API call with JSON body support."""
        url = f'{self._base_url}/{method}'
        try:
            if json_body:
                data = json.dumps(json_body).encode('utf-8')
                req = urllib.request.Request(
                    url, data=data,
                    headers={'Content-Type': 'application/json'},
                )
            elif params:
                data = urllib.parse.urlencode(params).encode('utf-8')
                req = urllib.request.Request(url, data=data)
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            logger.warning(f"Telegram API error ({method}): {e}")
            return None

    def _send(self, text: str) -> int | None:
        """Send plain text message. Returns message_id."""
        if not self.enabled:
            logger.info(f"[TG disabled] {text}")
            return None
        try:
            msg_id = self._tg.send(f"{self.PREFIX} {text}")
            return msg_id
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")
            return None

    def _send_with_buttons(self, text: str,
                           buttons: list[list[dict]]) -> int | None:
        """Send message with inline keyboard buttons.

        Args:
            text: HTML-formatted message
            buttons: 2D list of button dicts with 'text' and 'callback_data'
                     e.g. [[{'text': '✅ Approve', 'callback_data': 'approve:42'}]]
        """
        if not self.enabled:
            logger.info(f"[TG disabled] {text}")
            return None
        result = self._api('sendMessage', json_body={
            'chat_id': _CHAT_ID,
            'text': f"{self.PREFIX} {text}",
            'parse_mode': 'HTML',
            'reply_markup': {
                'inline_keyboard': buttons,
            },
        })
        if result and result.get('ok'):
            return result['result']['message_id']
        return None

    def _send_html(self, text: str) -> int | None:
        """Send HTML-formatted message via raw API. Returns message_id."""
        if not self.enabled:
            logger.info(f"[TG disabled] {text}")
            return None
        result = self._api('sendMessage', json_body={
            'chat_id': _CHAT_ID,
            'text': f"{self.PREFIX} {text}",
            'parse_mode': 'HTML',
        })
        if result and result.get('ok'):
            return result['result']['message_id']
        return None

    def _edit_message(self, message_id: int, text: str) -> None:
        """Edit an existing message (remove buttons after action)."""
        self._api('editMessageText', json_body={
            'chat_id': _CHAT_ID,
            'message_id': message_id,
            'text': f"{self.PREFIX} {text}",
            'parse_mode': 'HTML',
        })

    def _answer_callback(self, callback_id: str, text: str = '') -> None:
        """Acknowledge a callback query (removes loading spinner).

        Silently ignores errors — callbacks expire after ~30s which is normal.
        """
        try:
            self._api('answerCallbackQuery', {
                'callback_query_id': callback_id,
                'text': text,
            })
        except Exception:
            pass  # Expired callbacks are normal, edit_message still works

    # ── Telegram Polling (callbacks + text messages) ─────

    def check_approvals(self, db) -> int:
        """Poll for updates and process them. Legacy wrapper for poll_telegram."""
        actions, _ = self.poll_telegram(db)
        return actions

    def poll_telegram(self, db=None) -> tuple[int, list[str]]:
        """Poll all Telegram updates: callbacks AND text messages.

        Returns (actions_processed, list_of_incoming_text_messages).
        Persists _last_update_id to DB to prevent duplicate processing
        after daemon restarts (v1.1.1).
        """
        if not self.enabled:
            return 0, []

        # Lazy-load _last_update_id from DB on first poll
        if not self._update_id_loaded and db:
            stored = db.get_setting('tg_last_update_id', '0')
            try:
                self._last_update_id = int(stored)
            except (ValueError, TypeError):
                self._last_update_id = 0
            self._update_id_loaded = True

        actions = 0
        incoming_messages: list[str] = []

        result = self._api('getUpdates', {
            'offset': self._last_update_id,
            'timeout': 2,
        })
        if not result or not result.get('ok'):
            return 0, []

        prev_update_id = self._last_update_id

        for update in result.get('result', []):
            self._last_update_id = update['update_id'] + 1

            # ── Handle callback queries (inline buttons) ──
            cb = update.get('callback_query')
            if cb:
                from_chat = cb.get('message', {}).get('chat', {}).get('id')
                if from_chat != _CHAT_ID:
                    continue

                data = cb.get('data', '')
                callback_id = cb['id']
                message_id = cb.get('message', {}).get('message_id')

                if db and data.startswith('approve:'):
                    task_id = int(data.split(':')[1])
                    actions += self._handle_approve(
                        db, task_id, callback_id, message_id)
                elif db and data.startswith('reject:'):
                    task_id = int(data.split(':')[1])
                    actions += self._handle_reject(
                        db, task_id, callback_id, message_id)
                elif db and data.startswith('status:'):
                    self._answer_callback(callback_id, 'Rapport wordt geladen...')
                    self._send_status_summary(db)
                    actions += 1
                elif data.startswith('ci:'):
                    self._handle_ci(callback_id)
                    actions += 1
                elif data.startswith('rh:'):
                    self._handle_remote_hands(callback_id)
                    actions += 1
                elif db and data.startswith('trends:'):
                    self._answer_callback(callback_id,
                                          'Trends worden geladen...')
                    self._handle_trends(db)
                    actions += 1
                elif db and data.startswith('gates:'):
                    self._answer_callback(callback_id,
                                          'Gate health wordt geladen...')
                    self._handle_gates(db)
                    actions += 1
                continue

            # ── Handle text messages from user ──
            msg = update.get('message')
            if msg and msg.get('chat', {}).get('id') == _CHAT_ID:
                text = msg.get('text', '').strip()
                if text:
                    incoming_messages.append(text)

        # Persist update_id to DB if it changed
        if db and self._last_update_id != prev_update_id:
            try:
                db.set_setting('tg_last_update_id',
                               str(self._last_update_id))
            except Exception:
                pass  # Best effort — next poll will re-process at worst

        return actions, incoming_messages

    def _handle_approve(self, db, task_id: int,
                        callback_id: str, message_id: int) -> int:
        """Process task approval from Telegram button.

        TG buttons appear at 'approved' state — user confirms → done.
        """
        task = db.get_task(task_id)
        if not task:
            self._answer_callback(callback_id, f'Taak #{task_id} niet gevonden')
            return 0

        try:
            if task.status == 'approved':
                db.transition(task_id, 'done', actor='user')
                self._answer_callback(callback_id, f'✅ Taak #{task_id} goedgekeurd!')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"✅ <b>GOEDGEKEURD</b> (via Telegram) — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: done"
                    )
                logger.info(f"Telegram approval: task #{task_id} → done")
                return 1
            elif task.status == 'backlog':
                db.transition(task_id, 'todo', actor='user')
                self._answer_callback(callback_id, f'✅ Taak #{task_id} → todo')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"📝 <b>GEACTIVEERD</b> — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: todo"
                    )
                logger.info(f"Telegram approval: task #{task_id} → todo")
                return 1
            elif task.status == 'done':
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al goedgekeurd')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"✅ <b>GOEDGEKEURD</b> — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: done"
                    )
                return 0
            else:
                self._answer_callback(
                    callback_id,
                    f"Taak #{task_id} is '{task.status}', verwacht 'approved'")
                return 0
        except ValueError as e:
            self._answer_callback(callback_id, f'Fout: {str(e)[:100]}')
            logger.error(f"Telegram approve failed: {e}")
            return 0

    def _handle_reject(self, db, task_id: int,
                       callback_id: str, message_id: int) -> int:
        """Process task rejection from Telegram button.

        TG buttons appear at 'approved' state — user rejects → in_progress.
        """
        task = db.get_task(task_id)
        if not task:
            self._answer_callback(callback_id, f'Taak #{task_id} niet gevonden')
            return 0

        try:
            if task.status == 'approved':
                db.transition(task_id, 'in_progress', actor='user')
                db.add_comment(
                    task_id, 'user',
                    '❌ Afgekeurd via Telegram — terug naar in_progress',
                    'rejection'
                )
                self._answer_callback(callback_id, f'❌ Taak #{task_id} afgekeurd')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"❌ <b>AFGEKEURD</b> (via Telegram) — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: in_progress (retry)"
                    )
                logger.info(f"Telegram rejection: task #{task_id} → in_progress")
                return 1
            elif task.status == 'done':
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al goedgekeurd')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"✅ <b>GOEDGEKEURD</b> — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: done"
                    )
                return 0
            elif task.status == 'in_progress':
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al afgekeurd')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"❌ <b>AFGEKEURD</b> — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: in_progress (retry)"
                    )
                return 0
            else:
                self._answer_callback(
                    callback_id,
                    f"Taak #{task_id} is '{task.status}', verwacht 'approved'")
                return 0
        except ValueError as e:
            self._answer_callback(callback_id, f'Fout: {str(e)[:100]}')
            logger.error(f"Telegram reject failed: {e}")
            return 0

    def _send_status_summary(self, db) -> None:
        """Send full health report when 📊 button is pressed.

        Uses LabInspector for comprehensive output. Falls back to
        basic dashboard if inspector fails.
        """
        try:
            from lab.inspector import LabInspector
            inspector = LabInspector(db)
            report = inspector.format_health_report()
            self._send_html(f'📊 <b>STATUS REPORT</b>\n\n{report}')
        except Exception:
            # Fallback to basic dashboard
            self.send_dashboard(db)

    def _handle_ci(self, callback_id: str) -> None:
        """Show latest CI/CD workflow runs from GitHub Actions."""
        self._answer_callback(callback_id, 'CI status wordt geladen...')

        token = _load_github_token()
        url = (f'https://api.github.com/repos/{GITHUB_REPO}'
               f'/actions/runs?per_page=5')
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            self._send(f'GitHub API fout: {e}')
            return

        icons = {
            'success': '✅', 'failure': '❌', 'in_progress': '🔄',
            'cancelled': '⏹', 'queued': '⏳',
        }
        lines = ['🔄 <b>CI/CD Status</b>\n']
        for run in data.get('workflow_runs', [])[:5]:
            conclusion = run.get('conclusion') or run.get('status', '?')
            icon = icons.get(conclusion, '⚪')
            name = run.get('name', '?')
            branch = run.get('head_branch', '?')
            lines.append(f'{icon} {name} — {branch}')

        if not data.get('workflow_runs'):
            lines.append('Geen recente runs gevonden')

        self._send_html('\n'.join(lines))

    def _handle_remote_hands(self, callback_id: str) -> None:
        """Run Remote Hands healthcheck and send output to Telegram."""
        self._answer_callback(callback_id, 'Healthcheck wordt uitgevoerd...')
        try:
            from lab.tools.remote_hands_healthcheck import (
                check_tailscale_running, check_rustdesk_listening,
                check_pf_enabled,
            )
            checks = [
                ('Tailscale', check_tailscale_running),
                ('RustDesk', check_rustdesk_listening),
                ('Firewall', check_pf_enabled),
            ]
            lines = ['🖥 <b>Remote Hands Healthcheck</b>\n']
            all_ok = True
            for name, fn in checks:
                ok, detail = fn()
                icon = '✅' if ok else '❌'
                lines.append(f'{icon} <b>{name}</b>: {detail}')
                if not ok:
                    all_ok = False
            verdict = '✅ ALL PASS' if all_ok else '❌ FAIL'
            lines.append(f'\n<b>{verdict}</b>')
            self._send_html('\n'.join(lines))
        except Exception as e:
            self._send(f'Remote Hands healthcheck fout: {e}')

    def _handle_gates(self, db) -> None:
        """Send gate rejection summary via Telegram."""
        try:
            from lab.inspector import LabInspector
            inspector = LabInspector(db)
            gate = inspector.gate_health(hours=24)

            lines = ['🚧 <b>GATE HEALTH (24h)</b>\n']

            total = gate['total_rejections']
            if total == 0:
                lines.append('✅ Geen gate rejections in de afgelopen 24 uur.')
                self._send_html('\n'.join(lines))
                return

            lines.append(f'<b>Totaal</b>: {total} rejections\n')

            # By gate type
            if gate['by_gate']:
                lines.append('<b>Per gate</b>')
                for g, cnt in sorted(gate['by_gate'].items(),
                                     key=lambda x: x[1], reverse=True):
                    pct = cnt / total * 100
                    lines.append(f'  {g}: {cnt} ({pct:.0f}%)')

            # Most-blocked tasks
            if gate['top_blocked_tasks']:
                lines.append('\n<b>Meest geblokkeerd</b>')
                for tid, cnt in gate['top_blocked_tasks'][:5]:
                    lines.append(f'  Task #{tid}: {cnt} rejections')

            # Recent rejections
            if gate['recent']:
                lines.append('\n<b>Recent</b>')
                for r in gate['recent'][:5]:
                    reason_short = r['reason'][:80]
                    lines.append(
                        f'  {r["gate"]}: {r["from"]}→{r["to"]} '
                        f'({r["actor"]}) — {reason_short}'
                    )

            self._send_html('\n'.join(lines))
        except Exception as e:
            logger.warning(f"Gate health report failed: {e}")
            self._send(f'Gate health rapport fout: {e}')

    def _handle_trends(self, db) -> None:
        """Send 24h trend analytics via Telegram."""
        try:
            stats = db.get_cycle_metrics_stats(hours=24)
            cycles = stats['cycles']

            lines = ['📈 <b>TRENDS (24h)</b>\n']

            if cycles == 0:
                lines.append('Geen cycle data beschikbaar.')
                self._send_html('\n'.join(lines))
                return

            # Throughput
            lines.append('<b>Throughput</b>')
            lines.append(
                f'  Cycles: {cycles} | '
                f'Tasks: {stats["total_tasks"]} | '
                f'Reviews: {stats["total_reviews"]}'
            )
            err_rate = stats['total_errors'] / cycles if cycles else 0
            lines.append(
                f'  Errors: {stats["total_errors"]} '
                f'({err_rate:.1f}/cycle)'
            )

            # Cycle duration
            lines.append('\n<b>Cycle Duration</b>')
            lines.append(
                f'  Avg: {stats["avg_duration_s"]:.1f}s | '
                f'Min: {stats["min_duration_s"]:.1f}s | '
                f'Max: {stats["max_duration_s"]:.1f}s'
            )

            # Drain mode
            if stats['drain_pct'] > 0:
                lines.append(
                    f'\n⚠️ <b>Drain</b>: {stats["drain_pct"]:.0f}% '
                    f'of cycles'
                )

            # Per-agent timing (top 5 slowest)
            agent_times = stats.get('avg_agent_time', {})
            if agent_times:
                lines.append('\n<b>Agent Timing (avg)</b>')
                sorted_agents = sorted(
                    agent_times.items(), key=lambda x: x[1],
                    reverse=True)
                for name, avg_t in sorted_agents[:5]:
                    bar_len = min(int(avg_t / 2), 10)  # 2s per block
                    bar = '█' * bar_len + '░' * (10 - bar_len)
                    lines.append(f'  {bar} {avg_t:.1f}s {name}')

                if stats['slowest_agent']:
                    lines.append(
                        f'\n🐢 Slowest: {stats["slowest_agent"]} '
                        f'({agent_times[stats["slowest_agent"]]:.1f}s avg)'
                    )

            # Capacity forecast
            try:
                from lab.inspector import LabInspector
                inspector = LabInspector(db)
                forecast = inspector.capacity_forecast()
                approaching = {
                    s: c for s, c in forecast.items()
                    if c is not None and c <= 10
                }
                if approaching:
                    lines.append('\n📈 <b>Capacity Forecast</b>')
                    for status, cyc in sorted(approaching.items(),
                                              key=lambda x: x[1]):
                        if cyc == 0:
                            lines.append(f'  {status}: ⚠️ BREACHED')
                        else:
                            lines.append(
                                f'  {status}: ~{cyc} cycles to breach')
            except Exception:
                pass  # Forecast is optional enrichment

            self._send_html('\n'.join(lines))
        except Exception as e:
            logger.warning(f"Trends report failed: {e}")
            self._send(f'Trends rapport fout: {e}')

    def send_dashboard(self, db) -> None:
        """Send compact dashboard to Telegram."""
        summary = db.get_status_summary()
        tc = summary.get('tasks', {})
        agents_info = summary.get('agents', {})
        goals_info = summary.get('goals', [])

        lines = ['📊 <b>CRYPTOGEM LAB DASHBOARD</b>\n']

        # ── Task counts (all 8 statussen, compact grid) ──
        lines.append('<b>Taken</b>')
        lines.append(
            f'  proposal: {tc.get("proposal", 0)} | '
            f'todo: {tc.get("todo", 0)} | '
            f'in_progress: {tc.get("in_progress", 0)}'
        )
        lines.append(
            f'  peer_review: {tc.get("peer_review", 0)} | '
            f'review: {tc.get("review", 0)} | '
            f'approved: {tc.get("approved", 0)}'
        )
        lines.append(
            f'  done: {tc.get("done", 0)} | '
            f'blocked: {tc.get("blocked", 0)}'
        )

        # ── Approved queue (wacht op user actie) ──
        approved_tasks = db.get_tasks_by_status('approved')
        if approved_tasks:
            lines.append(
                f'\n⏳ <b>Wacht op jouw actie ({len(approved_tasks)})</b>')
            for t in approved_tasks[:5]:
                lines.append(f'  #{t.id} {t.title[:35]} ({t.assigned_to})')
            if len(approved_tasks) > 5:
                lines.append(f'  ... en {len(approved_tasks) - 5} meer')

        # ── Agents: name status (HH:MM) ──
        if agents_info:
            lines.append('\n<b>Agents</b>')
            for name, info in sorted(agents_info.items()):
                hb = info.get('last_heartbeat')
                if hb:
                    # Parse "YYYY-MM-DD HH:MM:SS" → "HH:MM"
                    try:
                        hb_short = hb.split(' ')[1][:5]
                    except (IndexError, AttributeError):
                        hb_short = 'never'
                else:
                    hb_short = 'never'
                lines.append(f'  {name} {info["status"]} ({hb_short})')

        # ── Goals progress ──
        if goals_info:
            lines.append('\n<b>Goals</b>')
            for g in goals_info:
                t_total = g['total_tasks']
                t_done = g['done']
                pct = round(t_done / t_total * 100) if t_total else 0
                bar_filled = int(pct / 10)
                bar = '█' * bar_filled + '░' * (10 - bar_filled)
                lines.append(f'  {bar} {pct}% — {g["title"][:30]}')

        self._send_with_buttons('\n'.join(lines), buttons=[
            [
                {'text': '📈 Trends', 'callback_data': 'trends:0'},
                {'text': '🚧 Gates', 'callback_data': 'gates:0'},
            ],
            [
                {'text': '📊 CI Status', 'callback_data': 'ci:0'},
                {'text': '🖥 Remote Hands', 'callback_data': 'rh:0'},
            ],
        ])

    # ── Guardrail v1 — Flow Control Notifications ────────

    def daily_digest(self, db) -> None:
        """Send daily digest with task counts, throughput, drain history.

        Called once per 24h by the scheduler/orchestrator.
        Uses LabInspector for richer metrics when cycle_metrics are available.
        """
        try:
            from lab.inspector import LabInspector
            inspector = LabInspector(db)
            report = inspector.format_health_report()
            self._send_html(f'📊 <b>DAILY DIGEST</b>\n\n{report}')
            return
        except Exception:
            pass  # Fall back to basic digest

        # ── Fallback: basic digest without inspector ──────
        counts = db.get_task_counts_by_status()
        breaches = db.get_cap_breaches()
        drain = db.is_drain_mode()

        lines = ['📊 <b>DAILY DIGEST</b>\n']

        # Task counts with cap indicators
        lines.append('<b>Taken per status</b>')
        for status, cap in WIP_CAPS.items():
            count = counts.get(status, 0)
            indicator = ' ⚠️' if count >= cap else ''
            lines.append(f'  {status}: {count}/{cap}{indicator}')

        # Non-capped statuses
        for status in ['todo', 'backlog', 'done']:
            if status in counts and status not in WIP_CAPS:
                lines.append(f'  {status}: {counts.get(status, 0)}')

        # Cap breaches
        if breaches:
            lines.append('\n🚨 <b>Cap Breaches</b>')
            for status, (count, cap) in breaches.items():
                over = count - cap
                lines.append(
                    f'  {status}: {count}/{cap} '
                    f'(+{over} over cap)'
                )

        # Approved queue
        approved_tasks = db.get_tasks_by_status('approved')
        if approved_tasks:
            lines.append(
                f'\n⏳ <b>Wacht op jouw actie ({len(approved_tasks)})</b>')
            for t in approved_tasks[:5]:
                lines.append(f'  #{t.id} {t.title[:35]} ({t.assigned_to})')
            if len(approved_tasks) > 5:
                lines.append(f'  ... en {len(approved_tasks) - 5} meer')

        # Drain mode status
        drain_icon = '🔴' if drain else '🟢'
        drain_text = 'ACTIVE' if drain else 'INACTIVE'
        lines.append(f'\n{drain_icon} <b>Drain Mode</b>: {drain_text}')

        self._send_html('\n'.join(lines))

    def cap_breach_alert(self, status: str, count: int, cap: int) -> None:
        """Immediate alert for persistent cap breach (>2 heartbeat cycles).

        Called by orchestrator when breach persists beyond 2 cycles.
        """
        self._send(
            f"⚠️ <b>CAP BREACH</b> — status: {status}, "
            f"count: {count}/{cap} (>2 cycles)"
        )

    def drain_mode_entered(self, breaches: dict) -> None:
        """Alert when drain mode activates with recovery guidance."""
        breach_lines = ', '.join(
            f"{s}: {c}/{cap}" for s, (c, cap) in breaches.items()
        )
        # Build recovery hints per breached status
        recovery = []
        for status, (count, cap) in breaches.items():
            if status in ('in_progress', 'peer_review'):
                recovery.append(
                    f"  {status}: review/complete existing tasks")
            elif status == 'review':
                recovery.append(
                    f"  {status}: boss must approve or reject")
            elif status == 'approved':
                recovery.append(
                    f"  {status}: user TG ✅/❌ to clear queue")
            else:
                recovery.append(
                    f"  {status}: clear {count - cap + 1}+ task(s)")
        recovery_text = '\n'.join(recovery) if recovery else ''
        self._send(
            f"🔴 <b>DRAIN MODE ACTIVATED</b>\n"
            f"Breaches: {breach_lines}\n"
            f"Intake transitions blocked until caps clear.\n"
            f"\n<b>Recovery</b>:\n{recovery_text}"
        )

    def drain_mode_exited(self) -> None:
        """Alert when drain mode deactivates."""
        self._send(
            "🟢 <b>DRAIN MODE CLEARED</b>\n"
            "All caps within limits. Normal operation resumed."
        )

    # ── CLI → Telegram mirroring ─────────────────────────

    def send_output(self, text: str) -> None:
        """Mirror CLI output to Telegram as preformatted text."""
        if not self.enabled or not text.strip():
            return
        import html
        escaped = html.escape(text.strip())
        # Telegram has 4096 char limit — truncate if needed
        if len(escaped) > 3800:
            escaped = escaped[:3800] + '\n... (afgekapt)'
        self._send(f"<pre>{escaped}</pre>")

    # ── Message types ──────────────────────────────────────

    def task_created(self, task_id: int, title: str, assigned_to: str,
                     goal_title: str = '') -> None:
        self._send(
            f"📋 Nieuwe taak #{task_id}: <b>{title}</b>\n"
            f"Toegewezen aan: {assigned_to}\n"
            f"Goal: {goal_title}"
        )

    def task_promoted(self, task_id: int, title: str) -> None:
        """Task promoted to approved — send with approve/reject buttons."""
        msg_id = self._send_with_buttons(
            f"📈 Taak #{task_id} klaar voor jouw goedkeuring:\n"
            f"<b>{title}</b>",
            buttons=[
                [
                    {'text': '✅ Goedkeuren', 'callback_data': f'approve:{task_id}'},
                    {'text': '❌ Afkeuren', 'callback_data': f'reject:{task_id}'},
                ],
                [
                    {'text': '📊 Status', 'callback_data': 'status:0'},
                ],
            ],
        )
        if msg_id:
            self._pending_messages[task_id] = msg_id

    def notify_task_done(self, task_id: int, title: str,
                         via: str = 'cli') -> None:
        """Notify Telegram that a task was approved (via CLI or other).

        Edits the original approval message to remove buttons.
        Called by CLI approve so Telegram stays in sync.
        """
        # Edit the original message if we have it
        msg_id = self._pending_messages.pop(task_id, None)
        if msg_id:
            self._edit_message(
                msg_id,
                f"✅ <b>GOEDGEKEURD</b> (via {via}) — Taak #{task_id}: "
                f"{title}\n\nStatus: done"
            )
        else:
            # No tracked message — send a new confirmation
            self._send(
                f"✅ Taak #{task_id} goedgekeurd via {via}: "
                f"<b>{title}</b>"
            )

    def notify_task_rejected(self, task_id: int, title: str,
                             via: str = 'cli') -> None:
        """Notify Telegram that a task was rejected via CLI."""
        msg_id = self._pending_messages.pop(task_id, None)
        if msg_id:
            self._edit_message(
                msg_id,
                f"❌ <b>AFGEKEURD</b> (via {via}) — Taak #{task_id}: "
                f"{title}\n\nStatus: in_progress (retry)"
            )
        else:
            self._send(
                f"❌ Taak #{task_id} afgekeurd via {via}: "
                f"<b>{title}</b>"
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

    def shell_violation(self, binary: str, agent: str) -> None:
        """Alert: a blocked shell command was attempted."""
        self._send(
            f"🚨 <b>SHELL VIOLATION</b>\n"
            f"Agent: {agent}\n"
            f"Blocked: <code>{binary}</code>\n"
            f"Actie: PermissionError raised"
        )

    def agent_circuit_open(self, agent: str, errors: int,
                           open_count: int) -> None:
        """Alert: agent circuit breaker tripped to OPEN."""
        self._send(
            f"🔌 <b>CIRCUIT OPEN</b> — Agent: {agent}\n"
            f"Consecutive errors: {errors}\n"
            f"Times opened: {open_count}\n"
            f"Agent paused for 5m cooldown."
        )

    def agent_circuit_escalation(self, agent: str, open_count: int,
                                  last_error: str) -> None:
        """Alert: agent circuit breaker needs human attention."""
        self._send(
            f"🚨 <b>CIRCUIT ESCALATION</b> — Agent: {agent}\n"
            f"Circuit opened {open_count}× — needs attention!\n"
            f"Last error: {last_error[:300]}"
        )

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
        msg = f"{icon} Infrastructure check: {'PASS' if passed else 'FAIL'}"
        if details:
            msg += f"\n{details[:500]}"
        self._send(msg)

    # ── Future agent hooks (prepared, not yet wired) ─────
    # Called by: live_monitor agent (rule-based, implemented)
    # Wired when: live_monitor.heartbeat() detects drift
    def live_drift(self, metric: str, expected: str, actual: str) -> None:
        """Alert on live metric drift. Called by live_monitor agent."""
        self._send(
            f"🔍 Live drift gedetecteerd:\n"
            f"Metric: <b>{metric}</b>\n"
            f"Verwacht: {expected}\n"
            f"Actueel: {actual}"
        )

    # Called by: deployment_judge agent (rule-based, implemented)
    # Wired when: deployment_judge.heartbeat() evaluates GO/NO-GO
    def deployment_verdict(self, task_id: int, verdict: str,
                           details: str = '') -> None:
        """Alert on deployment verdict. Called by deployment_judge agent."""
        icons = {'GO': '🟢', 'NO-GO': '🔴', 'PAPERTRADE': '🟡'}
        icon = icons.get(verdict, '⚪')
        self._send(
            f"{icon} Deployment verdict: <b>{verdict}</b>\n"
            f"Taak #{task_id}\n{details[:500]}"
        )
