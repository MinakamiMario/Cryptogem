"""
Telegram Notifier voor Cryptogem Trading Bot
=============================================
Stuurt status updates, resultaten en toestemmingsverzoeken naar Telegram.

Gebruik:
    from telegram_notifier import TelegramNotifier
    tg = TelegramNotifier()
    tg.send("Hello!")
    tg.status("Run 1/5 gestart")
    tg.champion_update(champion_dict)
    answer = tg.ask_permission("Nieuwe champion gevonden. Accepteren?", timeout=300)
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

# --- Config ---
BOT_TOKEN = '8554710440:AAHyneGLdLNni_asFrnO7zhEDRW8tdjdeh4'
CHAT_ID = 537907585
BASE_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'


class TelegramNotifier:
    """Lightweight Telegram bot voor agent team notificaties."""

    def __init__(self, token=BOT_TOKEN, chat_id=CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f'https://api.telegram.org/bot{token}'
        self._last_update_id = 0

    # ─── Core API ───────────────────────────────────────────

    def _api(self, method, params=None):
        """Telegram Bot API call. Retourneert parsed JSON of None bij fout."""
        url = f'{self.base_url}/{method}'
        try:
            if params:
                data = urllib.parse.urlencode(params).encode('utf-8')
                req = urllib.request.Request(url, data=data)
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"  [TG] API error ({method}): {e}")
            return None

    def send(self, text, parse_mode='HTML'):
        """Stuur een bericht. Retourneert message_id of None."""
        # Telegram limiet = 4096 chars
        if len(text) > 4000:
            text = text[:4000] + '\n...(afgekapt)'
        result = self._api('sendMessage', {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': parse_mode,
        })
        if result and result.get('ok'):
            return result['result']['message_id']
        return None

    def edit(self, message_id, text, parse_mode='HTML'):
        """Bewerk een eerder verstuurd bericht."""
        if len(text) > 4000:
            text = text[:4000] + '\n...(afgekapt)'
        self._api('editMessageText', {
            'chat_id': self.chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode,
        })

    # ─── Status updates ────────────────────────────────────

    def status(self, text):
        """Stuur een status update met timestamp."""
        now = datetime.now().strftime('%H:%M:%S')
        return self.send(f"🔄 <b>[{now}]</b> {text}")

    def success(self, text):
        """Stuur een succes bericht."""
        now = datetime.now().strftime('%H:%M:%S')
        return self.send(f"✅ <b>[{now}]</b> {text}")

    def warning(self, text):
        """Stuur een waarschuwing."""
        now = datetime.now().strftime('%H:%M:%S')
        return self.send(f"⚠️ <b>[{now}]</b> {text}")

    def error(self, text):
        """Stuur een foutmelding."""
        now = datetime.now().strftime('%H:%M:%S')
        return self.send(f"🚨 <b>[{now}]</b> {text}")

    # ─── Agent Team specifiek ──────────────────────────────

    def run_start(self, run_idx, n_runs, n_coins, seed=None):
        """Meld start van een run."""
        seed_str = f" (seed={seed})" if seed is not None else ""
        return self.send(
            f"🚀 <b>Run {run_idx+1}/{n_runs} gestart</b>{seed_str}\n"
            f"📊 {n_coins} coins | {datetime.now().strftime('%H:%M')}"
        )

    def run_done(self, run_idx, n_runs, best_label, best_score,
                 n_promoted, runtime_min):
        """Meld einde van een run."""
        return self.send(
            f"🏁 <b>Run {run_idx+1}/{n_runs} klaar</b> ({runtime_min:.0f}min)\n"
            f"🏆 Best: {best_label} (score {best_score:.1f})\n"
            f"📋 Promoted: {n_promoted} configs"
        )

    def champion_update(self, champion, old_score=None):
        """Meld een nieuwe champion."""
        cfg = champion.get('cfg', {})
        bt = champion.get('backtest', {})
        mc = champion.get('mc_block', {})
        delta = f" (+{champion['score'] - old_score:.1f})" if old_score else ""
        return self.send(
            f"👑 <b>NIEUWE CHAMPION</b>{delta}\n"
            f"Label: <code>{champion.get('label', '?')}</code>\n"
            f"Score: <b>{champion['score']:.1f}</b>\n"
            f"P&L: ${bt.get('pnl', 0):+,.0f} | "
            f"Trades: {bt.get('trades', 0)} | "
            f"WR: {bt.get('wr', 0):.0f}%\n"
            f"MC win: {mc.get('win_pct', 0):.0f}% | "
            f"DD: {bt.get('dd', 0):.0f}%\n"
            f"Exit: {cfg.get('exit_type', '?')} | "
            f"RSI: {cfg.get('rsi_max', '?')} | "
            f"VolSpike: {cfg.get('vol_spike_mult', '?')}"
        )

    def promotion(self, label, score, gates_str):
        """Meld een promoted config."""
        return self.send(
            f"📈 <b>PROMOTED:</b> {label}\n"
            f"Score: {score:.1f} | Gates: {gates_str}"
        )

    def cross_run_summary(self, n_runs, stability_pct, n_universal,
                          n_accepted, top_config=None):
        """Stuur cross-run samenvatting."""
        text = (
            f"📊 <b>CROSS-RUN RESULTAAT</b> ({n_runs} runs)\n"
            f"Champion stabiliteit: {stability_pct:.0f}%\n"
            f"Universele configs: {n_universal}\n"
            f"Geaccepteerd: {n_accepted}"
        )
        if top_config:
            text += f"\n\n🏆 Top: {top_config}"
        return self.send(text)

    def auditor_status(self, run_idx, n_runs, status, n_coins, audit_time_s):
        """Meld Auditor resultaat (1 bericht per run)."""
        icon = '✅' if status == 'OK' else '⚠️' if status.startswith('WARN') else '❌'
        return self.send(
            f"{icon} <b>Run {run_idx+1}/{n_runs} Auditor:</b> {status}\n"
            f"Coins: {n_coins} | {audit_time_s:.0f}s"
        )

    def holdout_result(self, label, full_pnl, complement_pnl, verdict):
        """Meld holdout check resultaat (legacy, per-candidate)."""
        return self.send(
            f"🔬 <b>HOLDOUT:</b> {label}\n"
            f"Full: ${full_pnl:+,.0f} | Complement: ${complement_pnl:+,.0f}\n"
            f"Verdict: {verdict}"
        )

    def holdout_batch(self, results):
        """Meld alle holdout resultaten in 1 bericht.

        Args:
            results: list of dicts met keys: label, full_pnl, complement_pnl, verdict
        """
        if not results:
            return None
        lines = [f"🔬 <b>HOLDOUT CHECK ({len(results)} kandidaten)</b>"]
        for r in results:
            lines.append(
                f"  {r['verdict_icon']} {r['label'][:35]}: "
                f"full=${r['full_pnl']:+,.0f} compl=${r['complement_pnl']:+,.0f}"
            )
        return self.send('\n'.join(lines))

    def ablation_summary(self, ranking):
        """Stuur ablation sensitivity ranking."""
        lines = [f"🧪 <b>ABLATION RANKING:</b>"]
        for i, (param, sens) in enumerate(ranking[:5]):
            lines.append(f"  {i+1}. {param}: {sens:.1f}")
        return self.send('\n'.join(lines))

    # ─── Toestemmingen ─────────────────────────────────────

    def ask_permission(self, question, options=None, timeout=300):
        """
        Stuur een vraag en wacht op antwoord.

        Args:
            question: De vraag
            options: List van opties (bijv. ['ja', 'nee', 'skip'])
            timeout: Max wachttijd in seconden (default 5 min)

        Returns:
            str: Het antwoord van de gebruiker, of 'TIMEOUT' als geen antwoord
        """
        text = f"❓ <b>TOESTEMMING GEVRAAGD</b>\n\n{question}"
        if options:
            text += "\n\nOpties: " + " | ".join(
                f"<code>{o}</code>" for o in options)
            text += "\n\n(typ je keuze)"
        else:
            text += "\n\n(typ <code>ja</code> of <code>nee</code>)"

        self.send(text)

        # Flush bestaande updates
        self._flush_updates()

        # Poll voor antwoord
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(5)
            updates = self._get_new_updates()
            for upd in updates:
                msg = upd.get('message', {})
                if msg.get('chat', {}).get('id') == self.chat_id:
                    answer = msg.get('text', '').strip().lower()
                    if answer:
                        self.send(f"✅ Antwoord ontvangen: <b>{answer}</b>")
                        return answer

        self.send("⏰ Geen antwoord ontvangen (timeout). Ga door met default.")
        return 'TIMEOUT'

    def _flush_updates(self):
        """Verwijder alle bestaande updates (zodat we alleen nieuwe zien)."""
        result = self._api('getUpdates', {'offset': -1})
        if result and result.get('ok') and result['result']:
            last_id = result['result'][-1]['update_id']
            self._last_update_id = last_id + 1
            # Confirm flush
            self._api('getUpdates', {'offset': self._last_update_id})

    def _get_new_updates(self):
        """Haal alleen nieuwe updates op (na _last_update_id)."""
        result = self._api('getUpdates', {
            'offset': self._last_update_id,
            'timeout': 3,
        })
        if not result or not result.get('ok'):
            return []
        updates = result.get('result', [])
        if updates:
            self._last_update_id = updates[-1]['update_id'] + 1
        return updates


# ─── Quick test ────────────────────────────────────────

if __name__ == '__main__':
    tg = TelegramNotifier()
    tg.send("🤖 <b>Cryptogem Bot</b> is online!\nTelegram notificaties werken.")
    print("Test bericht verstuurd!")
