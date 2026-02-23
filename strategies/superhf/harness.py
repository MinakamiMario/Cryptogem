"""
SuperHF Harness — Backtest engine with hybrid_notrl exits for 15m MTF strategy.

Derived from strategies/hf/screening/harness.py but uses DC/RSI/BB exits
instead of fixed TP/SL. Signal functions provide entry signals; exits are
managed by the hybrid_notrl exit engine from sprint3.

Equity/fee model has exact parity with agent_team_v3.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from strategies.superhf.indicators import (
    precompute_15m_indicators,
    precompute_1h_indicators,
    map_1h_to_15m,
    _vectorized_donchian_mid,
    _vectorized_donchian_low,
    _vectorized_bollinger,
)


# ---------------------------------------------------------------------------
# Constants (Parity: agent_team_v3.py)
# ---------------------------------------------------------------------------
INITIAL_CAPITAL = 2000.0
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
START_BAR = 100          # need enough bars for 15m + 1H indicator warmup

# Indicator periods
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------
@dataclass
class _Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    trades: int
    pnl: float
    pf: float
    wr: float
    dd: float
    final_equity: float
    trade_list: list = field(default_factory=list)
    exit_classes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# hybrid_notrl exit evaluation (inlined from sprint3/exits.py for speed)
# ---------------------------------------------------------------------------

CLASS_A_REASONS = {"RSI RECOVERY", "DC TARGET", "BB TARGET"}

def _eval_exit(
    entry_price: float,
    entry_bar: int,
    bar: int,
    low: float,
    close: float,
    rsi: Optional[float],
    dc_mid: Optional[float],
    bb_mid: Optional[float],
    max_stop_pct: float,
    time_max_bars: int,
    rsi_recovery: bool,
    rsi_rec_target: float,
    rsi_rec_min_bars: int,
) -> tuple[Optional[float], Optional[str]]:
    """Evaluate hybrid_notrl exit. Returns (exit_price, reason) or (None, None)."""
    bars_in = bar - entry_bar
    hard_stop = entry_price * (1 - max_stop_pct / 100)

    # 1. FIXED STOP
    if low <= hard_stop:
        return hard_stop, "FIXED STOP"

    # 2. TIME MAX
    if bars_in >= time_max_bars:
        return close, "TIME MAX"

    # 3. RSI RECOVERY
    if rsi_recovery and rsi is not None and bars_in >= rsi_rec_min_bars:
        if rsi >= rsi_rec_target:
            return close, "RSI RECOVERY"

    # 4. DC TARGET
    if dc_mid is not None and close >= dc_mid:
        return close, "DC TARGET"

    # 5. BB TARGET
    if bb_mid is not None and close >= bb_mid:
        return close, "BB TARGET"

    return None, None


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    data_15m: dict,              # {coin: [candle_dicts]} 15m
    data_1h: dict,               # {coin: [candle_dicts]} 1h
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    fee: float = 0.001,          # MEXC 10bps/side
    initial_capital: float = INITIAL_CAPITAL,
    start_bar: int = START_BAR,
    end_bar: int = None,
    cooldown_bars: int = COOLDOWN_BARS,
    cooldown_after_stop: int = COOLDOWN_AFTER_STOP,
    max_pos: int = 1,
) -> BacktestResult:
    """Run backtest on 15m candles with 1H support zones and hybrid_notrl exits."""

    # Precompute indicators
    indicators_15m: dict = {}
    indicators_1h: dict = {}
    support_zones: dict = {}

    zone_type = params.get("zone_type", "pivot_only")

    for coin in coins:
        if coin not in data_15m or coin not in data_1h:
            continue

        c15 = data_15m[coin]
        c1h = data_1h[coin]

        if len(c15) < start_bar + 50 or len(c1h) < 30:
            continue

        ind_15m = precompute_15m_indicators(c15)
        ind_1h = precompute_1h_indicators(c1h)

        # Also compute DC/BB on 15m for exit targets (vectorized O(n))
        ind_15m['dc_mid'] = _vectorized_donchian_mid(
            ind_15m['highs'], ind_15m['lows'], DC_PERIOD)
        ind_15m['dc_prev_low'] = _vectorized_donchian_low(
            ind_15m['lows'], DC_PERIOD)
        bb_mid_15m, _, bb_lower_15m = _vectorized_bollinger(
            ind_15m['closes'], BB_PERIOD, BB_DEV)
        ind_15m['bb_mid'] = bb_mid_15m
        ind_15m['bb_lower'] = bb_lower_15m

        indicators_15m[coin] = ind_15m
        indicators_1h[coin] = ind_1h

        # Map 1H support zones to 15m bars
        zones = map_1h_to_15m(c15, ind_1h, c1h,
                              zone_type=zone_type,
                              pivot_lookback=params.get("pivot_lookback", 40))
        support_zones[coin] = zones

    coin_list = [c for c in coins if c in indicators_15m]
    if not coin_list:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0, initial_capital)

    max_bars = max(indicators_15m[p]['n'] for p in coin_list)
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    # Exit parameters
    max_stop_pct = params.get("max_stop_pct", 15.0)
    time_max_bars = params.get("time_max_bars", 60)   # 60 × 15m = 15H
    rsi_recovery = params.get("rsi_recovery", True)
    rsi_rec_target = params.get("rsi_rec_target", 45.0)
    rsi_rec_min_bars = params.get("rsi_rec_min_bars", 8)  # 8 × 15m = 2H

    # Spread proxy gate
    spread_cap_bps = params.get("spread_cap_bps", 40)

    # State
    positions: dict[str, _Pos] = {}
    trades: list[dict] = []
    equity = float(initial_capital)
    peak_eq = equity
    max_dd = 0.0
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(start_bar, max_bars):
        if equity < 0:
            break

        # === EXITS ===
        sells = []
        for pair in list(positions.keys()):
            pos = positions[pair]
            ind = indicators_15m[pair]
            if bar >= ind['n'] or ind['rsi'][bar] is None:
                continue

            close = ind['closes'][bar]
            low = ind['lows'][bar]

            exit_price, reason = _eval_exit(
                entry_price=pos.entry_price,
                entry_bar=pos.entry_bar,
                bar=bar,
                low=low,
                close=close,
                rsi=ind['rsi'][bar],
                dc_mid=ind['dc_mid'][bar],
                bb_mid=ind['bb_mid'][bar],
                max_stop_pct=max_stop_pct,
                time_max_bars=time_max_bars,
                rsi_recovery=rsi_recovery,
                rsi_rec_target=rsi_rec_target,
                rsi_rec_min_bars=rsi_rec_min_bars,
            )

            if exit_price is not None:
                sells.append((pair, exit_price, reason, pos))

        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
            net = gross - fees
            equity += pos.size_usd + net
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = "STOP" in reason
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': exit_price,
                'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
                'reason': reason, 'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': bar,
                'size': pos.size_usd, 'equity_after': equity,
            })
            del positions[pair]

        # === ENTRIES ===
        buys = []
        for pair in coin_list:
            if pair in positions:
                continue
            ind = indicators_15m[pair]
            if bar >= ind['n']:
                continue

            cd = cooldown_after_stop if last_exit_was_stop.get(pair, False) else cooldown_bars
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue

            # Spread proxy: skip if ATR/close > spread_cap_bps
            atr = ind['atr'][bar]
            close = ind['closes'][bar]
            if atr is not None and close > 0 and spread_cap_bps > 0:
                spread_proxy_bps = (atr / close) * 10000 * 0.1  # rough proxy
                if spread_proxy_bps > spread_cap_bps:
                    continue

            # Get support zone for this bar
            zone = support_zones.get(pair, [])
            zone_price = zone[bar] if bar < len(zone) else None

            # Call signal function
            candles = data_15m.get(pair, [])
            sig = signal_fn(candles, bar, ind, params, zone_price)
            if sig is not None:
                strength = sig.get('strength', 1.0)
                buys.append((pair, strength))

        # Position sizing
        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested
        if len(positions) < max_pos and buys and available > 10:
            buys.sort(key=lambda x: x[1], reverse=True)
            slots = max_pos - len(positions)
            size_per_pos = available / slots
            for pair, _strength in buys:
                if len(positions) >= max_pos or size_per_pos < 10:
                    break
                ep = indicators_15m[pair]['closes'][bar]
                equity -= size_per_pos
                positions[pair] = _Pos(pair=pair, entry_price=ep,
                                       entry_bar=bar, size_usd=size_per_pos)

        # === DRAWDOWN ===
        total_value = equity
        for pair, pos in positions.items():
            ind = indicators_15m[pair]
            if bar < ind['n']:
                cur = ind['closes'][bar]
                unrealized = (cur - pos.entry_price) / pos.entry_price * pos.size_usd
                total_value += pos.size_usd + unrealized
            else:
                total_value += pos.size_usd
        if total_value > peak_eq:
            peak_eq = total_value
        dd = (peak_eq - total_value) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # === CLOSE REMAINING ===
    for pair, pos in list(positions.items()):
        ind = indicators_15m[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
        net = gross - fees
        equity += pos.size_usd + net
        trades.append({
            'pair': pair, 'entry': pos.entry_price, 'exit': lp,
            'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
            'reason': 'END', 'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar, 'exit_bar': max_bars,
            'size': pos.size_usd, 'equity_after': equity,
        })

    # === RESULTS ===
    final_equity = equity
    total_pnl = final_equity - initial_capital
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100 if n else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    exit_classes: dict = {'A': {}, 'B': {}}
    for t in trades:
        cls = 'A' if t['reason'] in CLASS_A_REASONS else 'B'
        r = t['reason']
        if r not in exit_classes[cls]:
            exit_classes[cls][r] = {'count': 0, 'pnl': 0, 'wins': 0}
        exit_classes[cls][r]['count'] += 1
        exit_classes[cls][r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            exit_classes[cls][r]['wins'] += 1

    return BacktestResult(
        trades=n, pnl=total_pnl, pf=pf, wr=wr, dd=max_dd,
        final_equity=final_equity, trade_list=trades, exit_classes=exit_classes,
    )


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------

def walk_forward(
    data_15m: dict,
    data_1h: dict,
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    n_folds: int = 3,
    embargo: int = 8,
    **kwargs,
) -> list[BacktestResult]:
    """Walk-forward: split bar range into folds, run independent backtests."""
    # Find max bars across all coins
    max_bars = 0
    for coin in coins:
        if coin in data_15m:
            max_bars = max(max_bars, len(data_15m[coin]))

    if max_bars <= START_BAR:
        return []

    total_range = max_bars - START_BAR
    fold_size = total_range // n_folds
    if fold_size <= 0:
        return []

    results = []
    for fold_idx in range(n_folds):
        fold_start = START_BAR + fold_idx * fold_size
        fold_end = fold_start + fold_size - embargo if fold_idx < n_folds - 1 else max_bars

        if fold_end <= fold_start:
            continue

        result = run_backtest(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=signal_fn, params=params,
            start_bar=fold_start, end_bar=fold_end, **kwargs,
        )
        results.append(result)

    return results
