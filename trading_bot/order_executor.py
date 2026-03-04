"""
Order Executor — Paper/Live Order Abstraction
==============================================
Unified order execution with slippage-aware paper mode and
retry-capable live mode.

Invariants:
- Idempotent sell: state update ONLY after confirmed fill
- Retry with exponential backoff on network/429 errors
- Slippage tracking on every trade (expected vs actual)
"""
import math
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger('trading_bot')


@dataclass
class OrderResult:
    """Result of a buy/sell execution."""
    filled: bool
    fill_price: float = 0.0
    fill_qty: float = 0.0
    order_id: str = ''
    fees: float = 0.0
    slippage_bps: float = 0.0      # vs expected price
    expected_price: float = 0.0
    error: str = ''


class OrderExecutor:
    """Paper/live order executor with retry and slippage tracking.

    Paper mode: slippage-aware simulation using sqrt impact model
                from HF research (costs_mexc_v3).
    Live mode:  real MEXC orders via exchange_manager + fill polling.
    """

    MAX_RETRIES = 3
    RETRY_DELAYS = [1.0, 2.0, 4.0]   # exponential backoff
    POLL_INTERVAL = 5.0               # seconds between fill polls
    POLL_TIMEOUT = 60.0               # max seconds to wait for fill

    def __init__(self, client, mode: str = 'paper', fee_rate: float = 0.0010):
        """
        Args:
            client: MEXCExchangeClient instance
            mode: 'paper' or 'live'
            fee_rate: fee per side as decimal (0.0010 = 10bps)
        """
        if mode not in ('paper', 'live'):
            raise ValueError(f"mode must be 'paper' or 'live', got '{mode}'")
        self.client = client
        self.mode = mode
        self.fee_rate = fee_rate
        # Slippage tracking
        self._slippage_history: list = []

    # ─── Public API ─────────────────────────────────────────────

    def buy(self, pair: str, usd_amount: float, current_price: float,
            bar_volume_usd: float = 0.0) -> OrderResult:
        """Execute a buy order.

        Args:
            pair: trading pair (e.g. 'FET/USDT')
            usd_amount: amount in USD to spend
            current_price: current market price
            bar_volume_usd: 24h quote volume for slippage estimation (paper mode)
        """
        if self.mode == 'paper':
            return self._paper_buy(pair, usd_amount, current_price, bar_volume_usd)
        return self._live_buy(pair, usd_amount, current_price)

    def sell(self, pair: str, qty: float, current_price: float,
             bar_volume_usd: float = 0.0) -> OrderResult:
        """Execute a sell order.

        Args:
            pair: trading pair
            qty: quantity of base asset to sell
            current_price: current market price
            bar_volume_usd: 24h quote volume for slippage estimation (paper mode)
        """
        if self.mode == 'paper':
            return self._paper_sell(pair, qty, current_price, bar_volume_usd)
        return self._live_sell(pair, qty, current_price)

    def get_avg_slippage_bps(self, n: int = 20) -> float:
        """Average slippage over last n trades."""
        if not self._slippage_history:
            return 0.0
        recent = self._slippage_history[-n:]
        return sum(abs(s) for s in recent) / len(recent)

    # ─── Paper Mode ─────────────────────────────────────────────

    def _estimate_slippage_bps(self, trade_size_usd: float,
                                bar_volume_usd: float) -> float:
        """Estimate market impact using sqrt model from HF research.

        Source: costs_mexc_v3.py — validated on MEXC orderbook data.
        Formula: slippage_bps = sqrt(trade_size / volume) * scale_factor
        Scale factor calibrated at 50 (conservative for 4H bars).
        """
        if bar_volume_usd <= 0:
            return 5.0  # default 5bps when volume unknown
        ratio = trade_size_usd / bar_volume_usd
        return math.sqrt(ratio) * 50.0  # scale factor from HF calibration

    def _paper_buy(self, pair: str, usd_amount: float,
                   current_price: float, bar_volume_usd: float) -> OrderResult:
        slip_bps = self._estimate_slippage_bps(usd_amount, bar_volume_usd)
        fill_price = current_price * (1 + slip_bps / 10_000)
        qty = usd_amount / fill_price
        fees = usd_amount * self.fee_rate

        self._slippage_history.append(slip_bps)
        logger.info(f"  [PAPER] BUY {pair}: {qty:.6f} @ ${fill_price:.6f} "
                    f"(slip={slip_bps:.1f}bps, fee=${fees:.2f})")

        return OrderResult(
            filled=True,
            fill_price=fill_price,
            fill_qty=qty,
            order_id=f"paper_{int(time.time()*1000)}",
            fees=fees,
            slippage_bps=slip_bps,
            expected_price=current_price,
        )

    def _paper_sell(self, pair: str, qty: float,
                    current_price: float, bar_volume_usd: float) -> OrderResult:
        slip_bps = self._estimate_slippage_bps(qty * current_price, bar_volume_usd)
        fill_price = current_price * (1 - slip_bps / 10_000)
        usd_value = qty * fill_price
        fees = usd_value * self.fee_rate

        self._slippage_history.append(slip_bps)
        logger.info(f"  [PAPER] SELL {pair}: {qty:.6f} @ ${fill_price:.6f} "
                    f"(slip={slip_bps:.1f}bps, fee=${fees:.2f})")

        return OrderResult(
            filled=True,
            fill_price=fill_price,
            fill_qty=qty,
            order_id=f"paper_{int(time.time()*1000)}",
            fees=fees,
            slippage_bps=slip_bps,
            expected_price=current_price,
        )

    # ─── Live Mode ──────────────────────────────────────────────

    def _live_buy(self, pair: str, usd_amount: float,
                  current_price: float) -> OrderResult:
        # Check market info for min order size
        market_info = self.client.get_market_info(pair)
        if market_info:
            min_cost = market_info.get('min_cost', 0)
            if min_cost > 0 and usd_amount < min_cost:
                return OrderResult(
                    filled=False,
                    error=f"Order ${usd_amount:.2f} below min cost ${min_cost:.2f}",
                    expected_price=current_price,
                )
            # Round qty to exchange precision
            # amount_precision can be step size (0.001) or decimal count (3)
            raw_prec = market_info.get('amount_precision', 8)
            if isinstance(raw_prec, float) and raw_prec < 1:
                # Step size (e.g. 0.001) → convert to decimal places (3)
                import math as _math
                precision = max(0, -int(_math.floor(_math.log10(raw_prec))))
            else:
                precision = int(raw_prec)
            qty = round(usd_amount / current_price, precision)

            # Enforce minimum amount
            min_amount = market_info.get('min_amount', 0)
            if min_amount and qty < min_amount:
                return OrderResult(
                    filled=False,
                    error=f"qty {qty} below min_amount {min_amount} for {pair}",
                    expected_price=current_price,
                )
        else:
            qty = usd_amount / current_price

        # Place order with retry
        order_id = self._retry_order(
            lambda: self.client.place_market_buy(pair, qty),
            f"BUY {pair} qty={qty}"
        )
        if not order_id:
            return OrderResult(
                filled=False,
                error=f"Failed to place buy order for {pair} after {self.MAX_RETRIES} retries",
                expected_price=current_price,
            )

        # Poll for fill
        return self._poll_for_fill(order_id, pair, current_price, qty)

    def _live_sell(self, pair: str, qty: float,
                   current_price: float) -> OrderResult:
        # Round qty to exchange precision
        market_info = self.client.get_market_info(pair)
        if market_info:
            raw_prec = market_info.get('amount_precision', 8)
            if isinstance(raw_prec, float) and raw_prec < 1:
                import math as _math
                precision = max(0, -int(_math.floor(_math.log10(raw_prec))))
            else:
                precision = int(raw_prec)
            qty = round(qty, precision)

        # Place order with retry
        order_id = self._retry_order(
            lambda: self.client.place_market_sell(pair, qty),
            f"SELL {pair} qty={qty}"
        )
        if not order_id:
            return OrderResult(
                filled=False,
                error=f"Failed to place sell order for {pair} after {self.MAX_RETRIES} retries",
                expected_price=current_price,
            )

        # Poll for fill
        return self._poll_for_fill(order_id, pair, current_price, qty)

    def _retry_order(self, order_fn, desc: str) -> Optional[str]:
        """Retry order placement with exponential backoff."""
        for attempt in range(self.MAX_RETRIES):
            try:
                order_id = order_fn()
                if order_id:
                    logger.info(f"  [LIVE] {desc} → order_id={order_id}")
                    return order_id
                logger.warning(f"  [LIVE] {desc} returned None (attempt {attempt+1}/{self.MAX_RETRIES})")
            except Exception as e:
                logger.warning(f"  [LIVE] {desc} error (attempt {attempt+1}): {e}")

            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[attempt]
                logger.info(f"  Retrying in {delay}s...")
                time.sleep(delay)

        return None

    def _poll_for_fill(self, order_id: str, pair: str,
                       expected_price: float, expected_qty: float) -> OrderResult:
        """Poll exchange until order is filled or timeout."""
        start = time.time()

        while (time.time() - start) < self.POLL_TIMEOUT:
            try:
                order = self.client.fetch_order(order_id, pair)
                if order is None:
                    logger.warning(f"  [LIVE] fetch_order returned None for {order_id}")
                    time.sleep(self.POLL_INTERVAL)
                    continue

                status = order.get('status', '')
                filled_qty = float(order.get('filled', 0) or 0)
                avg_price = float(order.get('average', 0) or order.get('price', 0) or 0)
                fee_cost = 0.0
                fee_info = order.get('fee')
                if fee_info and isinstance(fee_info, dict):
                    fee_cost = float(fee_info.get('cost', 0) or 0)

                if status == 'closed':
                    # Fully filled
                    slip_bps = 0.0
                    if expected_price > 0 and avg_price > 0:
                        slip_bps = (avg_price / expected_price - 1) * 10_000

                    self._slippage_history.append(slip_bps)

                    if filled_qty < expected_qty * 0.95:
                        logger.warning(
                            f"  [LIVE] Partial fill: got {filled_qty:.6f} "
                            f"of {expected_qty:.6f} for {pair}"
                        )

                    logger.info(
                        f"  [LIVE] FILLED {pair}: {filled_qty:.6f} @ ${avg_price:.6f} "
                        f"(slip={slip_bps:.1f}bps, fee=${fee_cost:.4f})"
                    )
                    return OrderResult(
                        filled=True,
                        fill_price=avg_price,
                        fill_qty=filled_qty,
                        order_id=order_id,
                        fees=fee_cost,
                        slippage_bps=slip_bps,
                        expected_price=expected_price,
                    )

                elif status == 'canceled':
                    return OrderResult(
                        filled=False,
                        order_id=order_id,
                        error=f"Order {order_id} was canceled",
                        expected_price=expected_price,
                    )

            except Exception as e:
                logger.warning(f"  [LIVE] Poll error for {order_id}: {e}")

            time.sleep(self.POLL_INTERVAL)

        # Timeout
        logger.error(f"  [LIVE] TIMEOUT waiting for fill: {order_id} ({pair})")
        return OrderResult(
            filled=False,
            order_id=order_id,
            error=f"Timeout after {self.POLL_TIMEOUT}s waiting for fill",
            expected_price=expected_price,
        )
