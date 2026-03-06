"""
Circuit Breaker — Automated Kill Switch
=========================================
Monitors trading state and trips when risk limits are breached.
On trip: idempotent panic sell + Telegram CRITICAL alert + bot halt.

Invariants:
- panic_sell_all() is IDEMPOTENT (safe to call repeatedly, crash-safe)
- State update ONLY after confirmed fill (no delete-before-confirm)
- Retry with backoff on rate limits / network errors
"""
import time
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger('trading_bot')


# ─── Thresholds ─────────────────────────────────────────────

DD_TRIP_PCT = 0.25              # DD > 25% of peak equity → TRIP
PF_TRIP_FLOOR = 1.0             # PF < 1.0 after MIN_TRADES → TRIP
PF_MIN_TRADES = 30              # minimum trades before PF check
CONSEC_LOSS_TRIP = 8            # 8+ consecutive losses → TRIP
DAILY_LOSS_PAUSE_PCT = 0.05     # daily loss > 5% → PAUSE new entries 24h


class CircuitBreaker:
    """Monitors risk and trips the kill switch when limits are breached."""

    def __init__(self, executor=None, notifier=None):
        """
        Args:
            executor: OrderExecutor for panic selling
            notifier: object with .send_critical(msg) for Telegram alerts
        """
        self.executor = executor
        self.notifier = notifier

    def check(self, state: dict) -> dict:
        """Check all trip conditions. Returns dict of findings.

        Returns:
            {
                'tripped': bool,
                'paused': bool,
                'reasons': list[str],
            }
        """
        if state.get('circuit_breaker') == 'tripped':
            return {'tripped': True, 'paused': False, 'reasons': ['previously tripped']}

        reasons = []
        tripped = False
        paused = False

        # 1. Drawdown check
        equity = state.get('equity', 0)
        peak = state.get('peak_equity', equity)
        if peak > 0:
            dd = (peak - equity) / peak
            if dd >= DD_TRIP_PCT:
                reasons.append(f"DD={dd*100:.1f}% >= {DD_TRIP_PCT*100:.0f}%")
                tripped = True

        # 2. PF check (after enough trades)
        closed = state.get('closed_trades', 0)
        if closed >= PF_MIN_TRADES:
            gw = state.get('gross_wins', 0)
            gl = abs(state.get('gross_losses', 0))
            pf = gw / gl if gl > 0 else 99.0
            if pf < PF_TRIP_FLOOR:
                reasons.append(f"PF={pf:.2f} < {PF_TRIP_FLOOR:.1f} after {closed} trades")
                tripped = True

        # 3. Consecutive losses
        consec = state.get('consecutive_losses', 0)
        if consec >= CONSEC_LOSS_TRIP:
            reasons.append(f"ConsecLoss={consec} >= {CONSEC_LOSS_TRIP}")
            tripped = True

        # 4. Daily loss pause
        daily_loss = self._compute_daily_loss(state)
        if daily_loss >= DAILY_LOSS_PAUSE_PCT and not tripped:
            reasons.append(f"DailyLoss={daily_loss*100:.1f}% >= {DAILY_LOSS_PAUSE_PCT*100:.0f}%")
            paused = True

        return {
            'tripped': tripped,
            'paused': paused,
            'reasons': reasons,
        }

    def is_tripped(self, state: dict) -> bool:
        """Check if circuit breaker is already tripped."""
        return state.get('circuit_breaker') == 'tripped'

    def trip(self, state: dict, reasons: list) -> dict:
        """Trip the circuit breaker. Returns updated state.

        1. Mark state as tripped (atomic)
        2. Panic sell all positions (idempotent)
        3. Send Telegram CRITICAL alert
        """
        msg = f"CIRCUIT BREAKER TRIPPED: {'; '.join(reasons)}"
        logger.critical(msg)

        # Mark tripped FIRST (persists across crashes)
        state['circuit_breaker'] = 'tripped'
        state['circuit_breaker_time'] = datetime.now(timezone.utc).isoformat()
        state['circuit_breaker_reasons'] = reasons

        # Panic sell all open positions
        if state.get('positions'):
            self.panic_sell_all(state)

        # Telegram alert
        if self.notifier:
            try:
                self.notifier.send_critical(msg)
            except Exception as e:
                logger.error(f"Failed to send Telegram alert: {e}")

        return state

    def panic_sell_all(self, state: dict) -> list:
        """Sell all open positions. IDEMPOTENT — safe to call repeatedly.

        Flow per position:
        1. Check if sell order already pending (order_id in position)
        2. If pending: poll status → if filled, update state
        3. If not pending: place market sell via executor (with retry)
        4. After confirmed fill ONLY: update state + P&L

        Returns list of sell results.
        """
        if not self.executor:
            logger.error("Cannot panic sell: no executor configured")
            return []

        results = []
        positions = dict(state.get('positions', {}))

        for pair, pos in positions.items():
            try:
                result = self._sell_position(state, pair, pos)
                results.append({'pair': pair, 'result': result})

                if result.filled:
                    # Update P&L and remove position ONLY after confirmed fill
                    entry_price = pos['entry_price']
                    size_usd = pos['size_usd']
                    gross = size_usd * (result.fill_price / entry_price - 1.0)
                    net_pnl = gross - result.fees
                    fee_rate = self.executor.fee_rate if self.executor else 0.001
                    entry_fee = size_usd * fee_rate
                    net_pnl = gross - entry_fee - result.fees

                    state['equity'] += net_pnl
                    state['total_pnl'] += net_pnl
                    state['closed_trades'] += 1

                    if net_pnl >= 0:
                        state['wins'] += 1
                        state['gross_wins'] += net_pnl
                    else:
                        state['losses'] += 1
                        state['gross_losses'] += net_pnl

                    # Now safe to remove
                    del state['positions'][pair]
                    logger.info(
                        f"  PANIC SELL {pair}: filled @ ${result.fill_price:.6f} "
                        f"P&L=${net_pnl:+.2f}"
                    )
                else:
                    logger.error(
                        f"  PANIC SELL FAILED {pair}: {result.error} "
                        f"(position NOT removed from state)"
                    )

            except Exception as e:
                logger.error(f"  PANIC SELL exception for {pair}: {e}")
                results.append({'pair': pair, 'result': None, 'error': str(e)})

        return results

    def _sell_position(self, state: dict, pair: str, pos: dict):
        """Sell a single position. Handles pending orders."""
        # Check for existing pending sell order
        pending_sell_id = pos.get('pending_sell_order_id')
        if pending_sell_id:
            # Poll existing order
            logger.info(f"  Checking pending sell {pending_sell_id} for {pair}")
            order = self.executor.client.fetch_order(pending_sell_id, pair)
            if order and order.get('status') == 'closed':
                from trading_bot.order_executor import OrderResult
                avg_price = float(order.get('average', 0) or order.get('price', 0) or 0)
                filled_qty = float(order.get('filled', 0) or 0)
                fee_cost = 0.0
                fee_info = order.get('fee')
                if fee_info and isinstance(fee_info, dict):
                    fee_cost = float(fee_info.get('cost', 0) or 0)
                return OrderResult(
                    filled=True, fill_price=avg_price, fill_qty=filled_qty,
                    order_id=pending_sell_id, fees=fee_cost,
                )

        # Get current price for sell
        ticker = self.executor.client.get_ticker(pair)
        if not ticker:
            from trading_bot.order_executor import OrderResult
            return OrderResult(filled=False, error=f"Cannot get ticker for {pair}")

        current_price = ticker['last']
        qty = pos['size_usd'] / pos['entry_price']

        # Execute sell via executor (has retry built in)
        result = self.executor.sell(pair, qty, current_price)

        # Track pending order for crash recovery
        if not result.filled and result.order_id:
            pos['pending_sell_order_id'] = result.order_id

        return result

    def pause_entries(self, state: dict, hours: int = 24) -> dict:
        """Pause new entries for N hours."""
        resume_time = datetime.now(timezone.utc).timestamp() + (hours * 3600)
        state['entries_paused_until'] = resume_time
        logger.warning(f"Entries paused for {hours}h")
        return state

    def is_paused(self, state: dict) -> bool:
        """Check if entries are currently paused."""
        paused_until = state.get('entries_paused_until', 0)
        return time.time() < paused_until

    def _compute_daily_loss(self, state: dict) -> float:
        """Compute loss in current calendar day as fraction of peak equity."""
        trade_log = state.get('trade_log', [])
        if not trade_log:
            return 0.0

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        daily_pnl = sum(
            t.get('pnl', 0) for t in trade_log
            if t.get('exit_time', '').startswith(today)
        )

        peak = state.get('peak_equity', 1)
        if peak <= 0:
            return 0.0

        if daily_pnl >= 0:
            return 0.0
        return abs(daily_pnl) / peak
