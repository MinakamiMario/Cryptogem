"""
Signal-agnostic backtest harness for hypothesis screening.

Faithfully replicates the equity/fee model from trading_bot/agent_team_v3.py
but makes the entry signal a parameter (callable).

Only the tp_sl exit mechanism is supported (universal for all hypotheses).
The signal_fn provides stop_price, target_price, time_limit per trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from trading_bot.strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

# ---------------------------------------------------------------------------
# Engine constants (Parity: engine lines 67-77)
# ---------------------------------------------------------------------------
INITIAL_CAPITAL = 2000               # Parity: engine line 77
KRAKEN_FEE = 0.0026                  # Parity: engine line 67
COOLDOWN_BARS = 4                    # Parity: engine line 75
COOLDOWN_AFTER_STOP = 8              # Parity: engine line 76
START_BAR = 50                       # Parity: engine line 73
VOL_MIN_PCT = 0.5                    # Parity: engine line 74

# Indicator periods (Parity: engine lines 68-72)
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14


# ---------------------------------------------------------------------------
# Position record (Parity: engine lines 292-298)
# ---------------------------------------------------------------------------
@dataclass
class _Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float = 0.0
    target_price: float = 0.0
    time_limit: int = 15


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    trades: int
    pnl: float
    pf: float           # profit factor
    wr: float            # win rate %
    dd: float            # max drawdown %
    final_equity: float
    trade_list: list = field(default_factory=list)
    exit_classes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------
def run_backtest(
    data: dict,                          # candle_cache format: {coin: [candle_dicts]}
    coins: list,                         # list of coin symbols
    signal_fn: Callable,                 # entry signal function
    params: dict,                        # hypothesis parameters
    indicators: dict,                    # precomputed per-coin indicators
    fee: float = 0.0031,                 # per-side fee (T1 default)
    initial_capital: float = 2000.0,
    start_bar: int = 50,
    end_bar: int = None,
    cooldown_bars: int = 4,
    cooldown_after_stop: int = 8,
    max_pos: int = 1,
) -> BacktestResult:
    """
    Signal-agnostic backtest engine with exact parity to agent_team_v3.py
    equity/fee model. Only tp_sl exit mechanism is supported.
    """
    # --- Initialisation (Parity: engine lines 312-325) ---
    coin_list = [c for c in coins if c in indicators]             # Parity: engine line 312
    max_bars = max(indicators[p]['n'] for p in coin_list) if coin_list else 0  # Parity: engine line 313
    if end_bar is not None:                                       # Parity: engine line 314-315
        max_bars = min(max_bars, end_bar)

    positions: dict[str, _Pos] = {}
    trades: list[dict] = []
    equity = float(initial_capital)                               # Parity: engine line 319
    peak_eq = equity                                              # Parity: engine line 320
    max_dd = 0.0                                                  # Parity: engine line 321
    last_exit_bar = {p: -999 for p in coin_list}                  # Parity: engine line 324
    last_exit_was_stop = {p: False for p in coin_list}            # Parity: engine line 325

    # --- Main bar loop (Parity: engine line 327) ---
    for bar in range(start_bar, max_bars):
        if equity < 0:                                            # Parity: engine line 328-330
            break

        # ============ PHASE 1: EXITS (sells) ============
        # Parity: engine lines 346-442
        sells = []
        for pair in list(positions.keys()):                       # Parity: engine line 347
            pos = positions[pair]
            ind = indicators[pair]
            if bar >= ind['n'] or ind['rsi'][bar] is None:        # Parity: engine line 350
                continue
            entry_price = pos.entry_price                         # Parity: engine line 352
            bars_in = bar - pos.entry_bar                         # Parity: engine line 353
            close = ind['closes'][bar]                            # Parity: engine line 354
            low = ind['lows'][bar]                                # Parity: engine line 355
            high = ind['highs'][bar]                              # Parity: engine line 356
            exit_price = None
            reason = None

            # tp_sl exit logic (Parity: engine lines 362-373)
            sl_p = pos.stop_price                                 # signal provides stop_price
            tp_p = pos.target_price                               # signal provides target_price
            tm_bars = pos.time_limit                              # signal provides time_limit
            if low <= sl_p:                                       # Parity: engine line 368
                exit_price, reason = sl_p, 'FIXED STOP'
            elif high >= tp_p:                                    # Parity: engine line 370
                exit_price, reason = tp_p, 'PROFIT TARGET'
            elif bars_in >= tm_bars:                               # Parity: engine line 372
                exit_price, reason = close, 'TIME MAX'

            if exit_price is not None:                            # Parity: engine line 425
                sells.append((pair, exit_price, reason, pos))

        # Process sells (Parity: engine lines 428-442)
        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd  # Parity: engine line 429
            fees = pos.size_usd * fee + (pos.size_usd + gross) * fee                # Parity: engine line 430
            net = gross - fees                                                        # Parity: engine line 431
            equity += pos.size_usd + net                                             # Parity: engine line 432
            last_exit_bar[pair] = bar                                                # Parity: engine line 433
            last_exit_was_stop[pair] = 'STOP' in reason                              # Parity: engine line 434
            trades.append({                                                          # Parity: engine lines 435-441
                'pair': pair, 'entry': pos.entry_price, 'exit': exit_price,
                'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
                'reason': reason, 'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': bar,
                'size': pos.size_usd, 'equity_after': equity,
            })
            del positions[pair]                                                      # Parity: engine line 442

        # ============ PHASE 2: ENTRIES (buys) ============
        # Parity: engine lines 444-481
        buys = []
        for pair in coin_list:                                    # Parity: engine line 445
            if pair in positions:                                  # Parity: engine line 446
                continue
            ind = indicators[pair]
            if bar >= ind['n']:                                   # Parity: engine line 449
                continue
            cd = cooldown_after_stop if last_exit_was_stop.get(pair, False) else cooldown_bars  # Parity: engine line 451
            if (bar - last_exit_bar.get(pair, -999)) < cd:        # Parity: engine line 452
                continue

            # Call signal function instead of check_entry_at_bar
            candles = data.get(pair, [])
            sig = signal_fn(candles, bar, ind, params)
            if sig is not None:
                strength = sig.get('strength', 1.0)
                buys.append((pair, strength, sig))

        # Position sizing (Parity: engine lines 458-481)
        invested = sum(p.size_usd for p in positions.values())    # Parity: engine line 458
        available = equity - invested                              # Parity: engine line 459
        if len(positions) < max_pos and buys and available > 10:  # Parity: engine line 460
            buys.sort(key=lambda x: x[1], reverse=True)           # Parity: engine line 461
            slots = max_pos - len(positions)                       # Parity: engine line 462
            size_per_pos = available / slots                       # Parity: engine line 463
            for pair, _strength, sig in buys:                     # Parity: engine line 464
                if len(positions) >= max_pos:                      # Parity: engine line 465
                    break
                if size_per_pos < 10:                              # Parity: engine line 467
                    break
                ind = indicators[pair]
                ep = ind['closes'][bar]                            # Parity: engine line 470
                equity -= size_per_pos                              # Parity: engine line 479
                positions[pair] = _Pos(                             # Parity: engine lines 480-481
                    pair=pair,
                    entry_price=ep,
                    entry_bar=bar,
                    size_usd=size_per_pos,
                    stop_price=sig['stop_price'],
                    target_price=sig['target_price'],
                    time_limit=sig.get('time_limit', 15),
                )

        # ============ PHASE 3: DRAWDOWN TRACKING ============
        # Parity: engine lines 483-496
        total_value = equity                                       # Parity: engine line 483
        for pair, pos in positions.items():                        # Parity: engine line 484
            ind = indicators[pair]
            if bar < ind['n']:                                     # Parity: engine line 486
                cur_price = ind['closes'][bar]                     # Parity: engine line 487
                unrealized = (cur_price - pos.entry_price) / pos.entry_price * pos.size_usd  # Parity: engine line 488
                total_value += pos.size_usd + unrealized           # Parity: engine line 489
            else:
                total_value += pos.size_usd                        # Parity: engine line 491
        if total_value > peak_eq:                                  # Parity: engine line 492
            peak_eq = total_value
        dd = (peak_eq - total_value) / peak_eq * 100 if peak_eq > 0 else 0  # Parity: engine line 494
        if dd > max_dd:                                            # Parity: engine line 495
            max_dd = dd

    # ============ CLOSE REMAINING POSITIONS ============
    # Parity: engine lines 498-513
    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)                # Parity: engine line 501
        lp = ind['closes'][last_idx]                               # Parity: engine line 502
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd   # Parity: engine line 503
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee          # Parity: engine line 504
        net = gross - fees                                                  # Parity: engine line 505
        equity += pos.size_usd + net                                       # Parity: engine line 506
        trades.append({                                                    # Parity: engine lines 507-513
            'pair': pair, 'entry': pos.entry_price, 'exit': lp,
            'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
            'reason': 'END', 'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar, 'exit_bar': max_bars,
            'size': pos.size_usd, 'equity_after': equity,
        })

    # ============ RESULT COMPUTATION ============
    # Parity: engine lines 515-537
    final_equity = equity                                          # Parity: engine line 515
    total_pnl = final_equity - initial_capital                     # Parity: engine line 516
    n = len(trades)                                                # Parity: engine line 517
    wins = [t for t in trades if t['pnl'] > 0]                    # Parity: engine line 518
    losses = [t for t in trades if t['pnl'] <= 0]                 # Parity: engine line 519
    wr = len(wins) / n * 100 if n else 0                           # Parity: engine line 520
    tw = sum(t['pnl'] for t in wins)                               # Parity: engine line 521
    tl = abs(sum(t['pnl'] for t in losses))                        # Parity: engine line 522
    pf = tw / tl if tl > 0 else float('inf')                       # Parity: engine line 523

    # Exit class analysis (Parity: engine lines 526-536)
    exit_classes: dict = {'A': {}, 'B': {}}
    class_a_reasons = {'RSI RECOVERY', 'DC TARGET', 'BB TARGET', 'PROFIT TARGET'}  # Parity: engine line 527
    for t in trades:
        cls = 'A' if t['reason'] in class_a_reasons else 'B'
        r = t['reason']
        if r not in exit_classes[cls]:
            exit_classes[cls][r] = {'count': 0, 'pnl': 0, 'wins': 0}
        exit_classes[cls][r]['count'] += 1
        exit_classes[cls][r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            exit_classes[cls][r]['wins'] += 1

    return BacktestResult(
        trades=n,
        pnl=total_pnl,
        pf=pf,
        wr=wr,
        dd=max_dd,
        final_equity=final_equity,
        trade_list=trades,
        exit_classes=exit_classes,
    )


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------
def walk_forward(
    data: dict,
    coins: list,
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    n_folds: int = 5,
    embargo: int = 2,
    fee: float = 0.0031,
    initial_capital: float = 2000.0,
    start_bar: int = 50,
    cooldown_bars: int = 4,
    cooldown_after_stop: int = 8,
    max_pos: int = 1,
) -> list[BacktestResult]:
    """
    Walk-forward validation: divide bar range into n_folds equal segments,
    run independent backtests on each fold with embargo bars between them.

    Returns list of BacktestResult, one per fold.
    """
    coin_list = [c for c in coins if c in indicators]
    if not coin_list:
        return []

    max_bars = max(indicators[p]['n'] for p in coin_list)
    total_range = max_bars - start_bar
    if total_range <= 0:
        return []

    fold_size = total_range // n_folds
    if fold_size <= 0:
        return []

    results = []
    for fold_idx in range(n_folds):
        fold_start = start_bar + fold_idx * fold_size
        if fold_idx < n_folds - 1:
            fold_end = fold_start + fold_size - embargo
        else:
            # Last fold runs to the end (no embargo after)
            fold_end = max_bars

        if fold_end <= fold_start:
            continue

        result = run_backtest(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=params,
            indicators=indicators,
            fee=fee,
            initial_capital=initial_capital,
            start_bar=fold_start,
            end_bar=fold_end,
            cooldown_bars=cooldown_bars,
            cooldown_after_stop=cooldown_after_stop,
            max_pos=max_pos,
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Precompute base indicators
# ---------------------------------------------------------------------------
def precompute_base_indicators(data: dict, coins: list, end_bar: int = None) -> dict:
    """
    Compute RSI, ATR, Donchian, Bollinger, vol_avg for given coins.
    Same format as agent_team_v3.py precompute_all().

    Parity: engine lines 213-257
    """
    indicators = {}
    for pair in coins:
        if pair not in data:
            continue
        candles = data[pair]
        n = len(candles)
        if end_bar is not None:                                    # Parity: engine line 221-222
            n = min(n, end_bar)
        closes = [c['close'] for c in candles[:n]]                 # Parity: engine line 223
        highs = [c['high'] for c in candles[:n]]                   # Parity: engine line 224
        lows = [c['low'] for c in candles[:n]]                     # Parity: engine line 225
        volumes = [c.get('volume', 0) for c in candles[:n]]        # Parity: engine line 226
        ind: dict = {                                              # Parity: engine lines 227-234
            'closes': closes, 'highs': highs, 'lows': lows,
            'volumes': volumes, 'n': n,
            'rsi': [None] * n, 'atr': [None] * n,
            'dc_prev_low': [None] * n, 'dc_mid': [None] * n,
            'bb_mid': [None] * n, 'bb_lower': [None] * n,
            'vol_avg': [None] * n,
        }
        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5  # Parity: engine line 235
        for bar in range(min_bars, n):                             # Parity: engine line 236
            wc = closes[:bar + 1]                                  # Parity: engine line 237
            wh = highs[:bar + 1]                                   # Parity: engine line 238
            wl = lows[:bar + 1]                                    # Parity: engine line 239
            wv = volumes[:bar + 1]                                 # Parity: engine line 240
            rsi = calc_rsi(wc, RSI_PERIOD)                         # Parity: engine line 241
            atr = calc_atr(wh, wl, wc, ATR_PERIOD)                # Parity: engine line 242
            _, prev_low, _ = calc_donchian(wh[:-1], wl[:-1], DC_PERIOD)  # Parity: engine line 243
            _, _, mid_ch = calc_donchian(wh, wl, DC_PERIOD)        # Parity: engine line 244
            bb_m, _, bb_l = calc_bollinger(wc, BB_PERIOD, BB_DEV)  # Parity: engine line 245
            if any(v is None for v in [rsi, atr, prev_low, mid_ch, bb_m, bb_l]):  # Parity: engine line 246
                continue
            ind['rsi'][bar] = rsi                                  # Parity: engine line 248
            ind['atr'][bar] = atr                                  # Parity: engine line 249
            ind['dc_prev_low'][bar] = prev_low                     # Parity: engine line 250
            ind['dc_mid'][bar] = mid_ch                            # Parity: engine line 251
            ind['bb_mid'][bar] = bb_m                              # Parity: engine line 252
            ind['bb_lower'][bar] = bb_l                            # Parity: engine line 253
            vol_slice = wv[-20:]                                   # Parity: engine line 254
            ind['vol_avg'][bar] = sum(vol_slice) / len(vol_slice) if vol_slice else 0  # Parity: engine line 255
        indicators[pair] = ind
    return indicators
