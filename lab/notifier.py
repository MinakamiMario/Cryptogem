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

from lab.config import REPO_ROOT

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
        """
        if not self.enabled:
            return 0, []

        actions = 0
        incoming_messages: list[str] = []

        result = self._api('getUpdates', {
            'offset': self._last_update_id,
            'timeout': 2,
        })
        if not result or not result.get('ok'):
            return 0, []

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
                continue

            # ── Handle text messages from user ──
            msg = update.get('message')
            if msg and msg.get('chat', {}).get('id') == _CHAT_ID:
                text = msg.get('text', '').strip()
                if text:
                    incoming_messages.append(text)

        return actions, incoming_messages

    def _handle_approve(self, db, task_id: int,
                        callback_id: str, message_id: int) -> int:
        """Process task approval from Telegram button."""
        task = db.get_task(task_id)
        if not task:
            self._answer_callback(callback_id, f'Taak #{task_id} niet gevonden')
            return 0

        try:
            if task.status == 'review':
                db.transition(task_id, 'approved', actor='user')
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
            elif task.status in ('done', 'approved'):
                # Already approved (e.g. via CLI) — just update the message
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al goedgekeurd (via CLI)')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"✅ <b>GOEDGEKEURD</b> (via CLI) — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: {task.status}"
                    )
                return 0
            else:
                self._answer_callback(
                    callback_id,
                    f"Taak #{task_id} is '{task.status}', verwacht 'review'")
                return 0
        except ValueError as e:
            self._answer_callback(callback_id, f'Fout: {str(e)[:100]}')
            logger.error(f"Telegram approve failed: {e}")
            return 0

    def _handle_reject(self, db, task_id: int,
                       callback_id: str, message_id: int) -> int:
        """Process task rejection from Telegram button."""
        task = db.get_task(task_id)
        if not task:
            self._answer_callback(callback_id, f'Taak #{task_id} niet gevonden')
            return 0

        try:
            if task.status == 'review':
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
            elif task.status in ('done', 'approved'):
                # Already approved via other channel — inform user
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al goedgekeurd (via CLI)')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"✅ <b>GOEDGEKEURD</b> (via CLI) — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: {task.status}"
                    )
                return 0
            elif task.status == 'in_progress':
                # Already rejected via other channel
                self._answer_callback(
                    callback_id,
                    f'Taak #{task_id} al afgekeurd')
                self._pending_messages.pop(task_id, None)
                if message_id:
                    self._edit_message(
                        message_id,
                        f"❌ <b>AFGEKEURD</b> (via CLI) — Taak #{task_id}: "
                        f"{task.title}\n\nStatus: in_progress (retry)"
                    )
                return 0
            else:
                self._answer_callback(
                    callback_id,
                    f"Taak #{task_id} is '{task.status}', verwacht 'review'")
                return 0
        except ValueError as e:
            self._answer_callback(callback_id, f'Fout: {str(e)[:100]}')
            logger.error(f"Telegram reject failed: {e}")
            return 0

    def _send_status_summary(self, db) -> None:
        """Send a quick status summary when 📊 button is pressed."""
        self.send_dashboard(db)

    def send_dashboard(self, db) -> None:
        """Send full dashboard to Telegram."""
        summary = db.get_status_summary()
        task_counts = summary.get('tasks', {})
        agents_info = summary.get('agents', {})
        goals_info = summary.get('goals', [])

        lines = ['📊 <b>CRYPTOGEM LAB DASHBOARD</b>\n']

        # ── Task overview ──
        total = sum(task_counts.values())
        done = task_counts.get('done', 0)
        review = task_counts.get('review', 0)
        in_progress = task_counts.get('in_progress', 0)
        peer_review = task_counts.get('peer_review', 0)
        todo = task_counts.get('todo', 0)
        backlog = task_counts.get('backlog', 0)
        blocked = task_counts.get('blocked', 0)

        lines.append('<b>Taken</b>')
        if review:
            lines.append(f'  ⏳ Review: <b>{review}</b>')
        if in_progress:
            lines.append(f'  🔄 In progress: {in_progress}')
        if peer_review:
            lines.append(f'  👀 Peer review: {peer_review}')
        if todo:
            lines.append(f'  📝 Todo: {todo}')
        if blocked:
            lines.append(f'  🚧 Blocked: {blocked}')
        if backlog:
            lines.append(f'  📦 Backlog: {backlog}')
        lines.append(f'  ✅ Done: {done}')
        if total:
            pct = round(done / total * 100)
            lines.append(f'  Totaal: {total} ({pct}% klaar)')

        # ── Review queue details ──
        if review:
            lines.append(f'\n⏳ <b>Wacht op jouw review ({review})</b>')
            review_tasks = db.get_tasks_by_status('review')
            for t in review_tasks[:5]:
                lines.append(f'  #{t.id} {t.title[:35]} ({t.assigned_to})')
            if len(review_tasks) > 5:
                lines.append(f'  ... en {len(review_tasks) - 5} meer')

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

        # ── Agents ──
        if agents_info:
            lines.append('\n<b>Agents</b>')
            working = [a for a, i in agents_info.items() if i['status'] == 'working']
            idle = [a for a, i in agents_info.items() if i['status'] == 'idle']
            errors = [a for a, i in agents_info.items() if i['status'] == 'error']
            if working:
                lines.append(f'  🔄 {", ".join(working)}')
            if errors:
                lines.append(f'  🚨 {", ".join(errors)}')
            lines.append(f'  💤 {len(idle)} idle')

        # ── Blocked tasks ──
        if blocked:
            lines.append(f'\n🚧 <b>Geblokkeerd ({blocked})</b>')
            blocked_tasks = db.get_tasks_by_status('blocked')
            for t in blocked_tasks[:3]:
                lines.append(f'  #{t.id} {t.title[:35]}')

        self._send('\n'.join(lines))

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
        """Task promoted to review — send with approve/reject buttons."""
        msg_id = self._send_with_buttons(
            f"📈 Taak #{task_id} klaar voor jouw review:\n"
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
