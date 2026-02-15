#!/usr/bin/env python3
"""
V9 TP/SL SWEEP — Optimale Profit Target / Stop Loss Ratio
==========================================================
Test ALLE combinaties van TP en SL percentages in een volledige portfolio backtest.

V9 Exit logica (intra-bar priority):
  1. SL check op LOW   → als low <= entry * (1 - SL%) → exit at SL price
  2. TP check op HIGH  → als high >= entry * (1 + TP%) → exit at TP price
  3. TimeMax check op CLOSE → bars >= TM → exit at close
  4. Anders: HOLD

TP:  2, 3, 4, 5, 6, 7, 8, 10%
SL:  3, 5, 8, 10, 12, 15, 20, 25%
TimeMax: 8 bars (vast)

Portfolio: 1 positie, $2000, volume ranking voor selectie.

Gebruik:
    python backtest_v9_tpsl_sweep.py
"""
import sys
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

# ============================================================
# PARAMETERS
# ============================================================
TP_VALUES = [2, 3, 4, 5, 6, 7, 8, 10]
SL_VALUES = [3, 5, 8, 10, 12, 15, 20, 25]
TIME_MAX = 8
POS_SIZE = 2000
MAX_POS = 1
START_BAR = 50

# Entry parameters (V4 DualConfirm)
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
RSI_MAX = 40
ATR_PERIOD = 14
VOL_SPIKE_MULT = 2.0
VOL_CONFIRM_MULT = 1.0
VOL_MIN_PCT = 0.5
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8


# ============================================================
# PRECOMPUTE INDICATORS PER COIN (run once, reuse across configs)
# ============================================================

def precompute_indicators(data, coins):
    """Precompute all indicators per coin per bar. Saves massive time."""
    indicators = {}
    for pair in coins:
        candles = data[pair]
        n = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        ind = {
            'closes': closes,
            'highs': highs,
            'lows': lows,
            'volumes': volumes,
            'n': n,
            # Per-bar precomputed values
            'rsi': [None] * n,
            'atr': [None] * n,
            'dc_prev_low': [None] * n,
            'dc_mid': [None] * n,
            'bb_mid': [None] * n,
            'bb_lower': [None] * n,
            'vol_avg': [None] * n,
            'entry_ok': [False] * n,  # Pre-check entry conditions
        }

        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5

        for bar in range(min_bars, n):
            window_closes = closes[:bar + 1]
            window_highs = highs[:bar + 1]
            window_lows = lows[:bar + 1]
            window_volumes = volumes[:bar + 1]

            rsi = calc_rsi(window_closes, RSI_PERIOD)
            atr = calc_atr(window_highs, window_lows, window_closes, ATR_PERIOD)
            _, prev_lowest, _ = calc_donchian(window_highs[:-1], window_lows[:-1], DC_PERIOD)
            _, _, mid_channel = calc_donchian(window_highs, window_lows, DC_PERIOD)
            bb_mid, _, bb_lower = calc_bollinger(window_closes, BB_PERIOD, BB_DEV)

            if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
                continue

            ind['rsi'][bar] = rsi
            ind['atr'][bar] = atr
            ind['dc_prev_low'][bar] = prev_lowest
            ind['dc_mid'][bar] = mid_channel
            ind['bb_mid'][bar] = bb_mid
            ind['bb_lower'][bar] = bb_lower

            # Volume average
            vol_slice = window_volumes[-20:]
            vol_avg = sum(vol_slice) / len(vol_slice) if vol_slice else 0
            ind['vol_avg'][bar] = vol_avg

            # Pre-check entry (everything except cooldown and position check)
            close = closes[bar]
            low = lows[bar]
            prev_close = closes[bar - 1] if bar > 0 else close
            cur_vol = volumes[bar]
            prev_vol = volumes[bar - 1] if bar > 0 else 0

            # Base volume filter
            if vol_avg > 0 and cur_vol < vol_avg * VOL_MIN_PCT:
                continue

            # Dual confirm
            dc_sig = (low <= prev_lowest and rsi < RSI_MAX and close > prev_close)
            bb_sig = (close <= bb_lower and rsi < RSI_MAX and close > prev_close)
            if not (dc_sig and bb_sig):
                continue

            # Volume spike
            if vol_avg > 0 and cur_vol < vol_avg * VOL_SPIKE_MULT:
                continue

            # Volume confirm (bar-to-bar)
            if prev_vol > 0 and cur_vol / prev_vol < VOL_CONFIRM_MULT:
                continue

            ind['entry_ok'][bar] = True

        indicators[pair] = ind

    return indicators


# ============================================================
# FAST PORTFOLIO BACKTEST (uses precomputed indicators)
# ============================================================

@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float


def run_backtest(indicators, coins, tp_pct, sl_pct, tm_bars):
    """Run a single portfolio backtest with given TP/SL/TM parameters."""

    # Per-coin cooldown state
    last_exit_bar = {p: -999 for p in coins}
    last_exit_was_stop = {p: False for p in coins}

    position = None  # Single position
    trades = []

    max_bars = max(indicators[p]['n'] for p in coins)

    for bar in range(START_BAR, max_bars):
        # ---- CHECK EXIT first ----
        if position is not None:
            pair = position.pair
            ind = indicators[pair]
            if bar < ind['n']:
                entry_price = position.entry_price
                bars_in = bar - position.entry_bar

                low = ind['lows'][bar]
                high = ind['highs'][bar]
                close = ind['closes'][bar]

                sl_price = entry_price * (1 - sl_pct / 100)
                tp_price = entry_price * (1 + tp_pct / 100)

                exit_price = None
                reason = None

                # 1. SL check on LOW (worst case first)
                if low <= sl_price:
                    exit_price = sl_price
                    reason = 'SL'

                # 2. TP check on HIGH
                # If SL was NOT hit, check TP
                # If BOTH could be hit same bar: SL wins (conservative)
                if exit_price is None and high >= tp_price:
                    exit_price = tp_price
                    reason = 'TP'

                # 3. TimeMax check on CLOSE
                if exit_price is None and bars_in >= tm_bars:
                    exit_price = close
                    reason = 'TM'

                if exit_price is not None:
                    gross = (exit_price - entry_price) / entry_price * position.size_usd
                    fee_entry = position.size_usd * KRAKEN_FEE
                    fee_exit = (position.size_usd + gross) * KRAKEN_FEE
                    net = gross - fee_entry - fee_exit

                    is_stop = (reason == 'SL')
                    last_exit_bar[pair] = bar
                    last_exit_was_stop[pair] = is_stop

                    trades.append({
                        'pair': pair,
                        'entry': entry_price,
                        'exit': exit_price,
                        'pnl': net,
                        'reason': reason,
                        'bars': bars_in,
                        'entry_bar': position.entry_bar,
                        'exit_bar': bar,
                    })
                    position = None

        # ---- CHECK ENTRIES (only if no position) ----
        if position is None:
            candidates = []
            for pair in coins:
                ind = indicators[pair]
                if bar >= ind['n']:
                    continue
                if not ind['entry_ok'][bar]:
                    continue

                # Cooldown check
                cd = COOLDOWN_AFTER_STOP if last_exit_was_stop[pair] else COOLDOWN_BARS
                if (bar - last_exit_bar[pair]) < cd:
                    continue

                # Volume ratio for ranking
                vol_avg = ind['vol_avg'][bar]
                cur_vol = ind['volumes'][bar]
                vol_ratio = cur_vol / vol_avg if vol_avg and vol_avg > 0 else 0

                candidates.append((pair, vol_ratio))

            if candidates:
                # Volume ranking: highest spike ratio wins
                candidates.sort(key=lambda x: x[1], reverse=True)
                best_pair = candidates[0][0]
                entry_price = indicators[best_pair]['closes'][bar]

                position = Pos(
                    pair=best_pair,
                    entry_price=entry_price,
                    entry_bar=bar,
                    size_usd=POS_SIZE,
                )

    # Close remaining position at last bar
    if position is not None:
        pair = position.pair
        ind = indicators[pair]
        last_close = ind['closes'][-1]
        entry_price = position.entry_price
        gross = (last_close - entry_price) / entry_price * position.size_usd
        fee_entry = position.size_usd * KRAKEN_FEE
        fee_exit = (position.size_usd + gross) * KRAKEN_FEE
        net = gross - fee_entry - fee_exit
        trades.append({
            'pair': pair,
            'entry': entry_price,
            'exit': last_close,
            'pnl': net,
            'reason': 'END',
            'bars': max_bars - position.entry_bar,
            'entry_bar': position.entry_bar,
            'exit_bar': max_bars,
        })

    # ---- METRICS ----
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    n_trades = len(trades)
    wr = len(wins) / n_trades * 100 if n_trades else 0
    avg_w = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    # Max drawdown
    equity = POS_SIZE
    peak = equity
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Without top trade
    if n_trades > 1:
        sorted_t = sorted(trades, key=lambda x: x['pnl'], reverse=True)
        top_trade = sorted_t[0]
        pnl_no_top = total_pnl - top_trade['pnl']
        trades_no_top = sorted_t[1:]
        wins_nt = [t for t in trades_no_top if t['pnl'] > 0]
        wr_no_top = len(wins_nt) / len(trades_no_top) * 100
        ev_no_top = pnl_no_top / len(trades_no_top)
    elif n_trades == 1:
        top_trade = trades[0]
        pnl_no_top = 0
        wr_no_top = 0
        ev_no_top = 0
    else:
        top_trade = None
        pnl_no_top = 0
        wr_no_top = 0
        ev_no_top = 0

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'n': 0, 'pnl': 0, 'wins': 0, 'avg_pnl': 0}
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1
    for r in reasons:
        reasons[r]['avg_pnl'] = reasons[r]['pnl'] / reasons[r]['n'] if reasons[r]['n'] else 0
        reasons[r]['wr'] = reasons[r]['wins'] / reasons[r]['n'] * 100 if reasons[r]['n'] else 0

    return {
        'tp': tp_pct,
        'sl': sl_pct,
        'tm': tm_bars,
        'trades': n_trades,
        'wr': wr,
        'pnl': total_pnl,
        'pf': pf,
        'dd': max_dd,
        'avg_w': avg_w,
        'avg_l': avg_l,
        'pnl_no_top': pnl_no_top,
        'ev_no_top': ev_no_top,
        'wr_no_top': wr_no_top,
        'top_trade': top_trade,
        'reasons': reasons,
        'trade_list': trades,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    t0 = time.time()

    print("=" * 120)
    print("V9 TP/SL SWEEP — Optimale Profit Target / Stop Loss Ratio")
    print("=" * 120)

    # Load data
    if not CACHE_FILE.exists():
        print(f"FOUT: Cache niet gevonden: {CACHE_FILE}")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins, {max(len(data[c]) for c in coins)} bars")

    # Precompute indicators
    print("\nPrecomputing indicators voor alle coins...")
    t1 = time.time()
    indicators = precompute_indicators(data, coins)
    t2 = time.time()

    # Count total entries available
    total_entries = sum(sum(ind['entry_ok']) for ind in indicators.values())
    print(f"Precompute klaar in {t2-t1:.1f}s — {total_entries} potentiele entries gevonden")

    # Run all combinations
    combos = [(tp, sl) for tp in TP_VALUES for sl in SL_VALUES]
    print(f"\nTesting {len(combos)} TP/SL combinaties (TimeMax={TIME_MAX} vast)...")
    print()

    results = []
    for i, (tp, sl) in enumerate(combos):
        r = run_backtest(indicators, coins, tp, sl, TIME_MAX)
        results.append(r)
        if (i + 1) % 16 == 0:
            print(f"  {i+1}/{len(combos)} klaar...")

    t3 = time.time()
    print(f"\nAlle backtests klaar in {t3-t2:.1f}s (totaal {t3-t0:.1f}s)")

    # Sort by EV without top trade
    results.sort(key=lambda x: x['ev_no_top'], reverse=True)

    # ============================================================
    # TOP 20 RESULTS
    # ============================================================
    print(f"\n{'=' * 140}")
    print(f"TOP 20 — Gesorteerd op EV per trade zonder top trade")
    print(f"{'=' * 140}")
    hdr = (
        f"{'#':>3} | {'TP%':>4} | {'SL%':>4} | {'Ratio':>5} | "
        f"{'Tr':>3} | {'WR%':>5} | {'P&L':>9} | {'PF':>6} | {'DD%':>5} | "
        f"{'AvgW':>7} | {'AvgL':>7} | {'NoTop$':>9} | {'EV/t':>7} | "
        f"{'WR_nt':>5} | {'TP#':>3} {'SL#':>3} {'TM#':>3} | {'TopTrade':>20}"
    )
    print(hdr)
    print("-" * 140)

    for i, r in enumerate(results[:20]):
        ratio = r['tp'] / r['sl'] if r['sl'] > 0 else 99
        pf_str = f"{r['pf']:6.2f}" if r['pf'] < 999 else "   INF"
        tp_n = r['reasons'].get('TP', {}).get('n', 0)
        sl_n = r['reasons'].get('SL', {}).get('n', 0)
        tm_n = r['reasons'].get('TM', {}).get('n', 0)
        top_str = ""
        if r['top_trade']:
            top_str = f"{r['top_trade']['pair'][:12]:>12} ${r['top_trade']['pnl']:+.0f}"

        print(
            f"{i+1:3d} | {r['tp']:4d} | {r['sl']:4d} | {ratio:5.2f} | "
            f"{r['trades']:3d} | {r['wr']:5.1f} | ${r['pnl']:+8.0f} | {pf_str} | {r['dd']:5.1f} | "
            f"${r['avg_w']:+6.0f} | ${r['avg_l']:+6.0f} | ${r['pnl_no_top']:+8.0f} | ${r['ev_no_top']:+6.1f} | "
            f"{r['wr_no_top']:5.1f} | {tp_n:3d} {sl_n:3d} {tm_n:3d} | {top_str}"
        )

    # ============================================================
    # BOTTOM 5 RESULTS
    # ============================================================
    print(f"\n--- BOTTOM 5 (slechtste configs) ---")
    print(hdr)
    print("-" * 140)

    for i, r in enumerate(results[-5:]):
        ratio = r['tp'] / r['sl'] if r['sl'] > 0 else 99
        pf_str = f"{r['pf']:6.2f}" if r['pf'] < 999 else "   INF"
        tp_n = r['reasons'].get('TP', {}).get('n', 0)
        sl_n = r['reasons'].get('SL', {}).get('n', 0)
        tm_n = r['reasons'].get('TM', {}).get('n', 0)
        top_str = ""
        if r['top_trade']:
            top_str = f"{r['top_trade']['pair'][:12]:>12} ${r['top_trade']['pnl']:+.0f}"

        rank = len(results) - 4 + i
        print(
            f"{rank:3d} | {r['tp']:4d} | {r['sl']:4d} | {ratio:5.2f} | "
            f"{r['trades']:3d} | {r['wr']:5.1f} | ${r['pnl']:+8.0f} | {pf_str} | {r['dd']:5.1f} | "
            f"${r['avg_w']:+6.0f} | ${r['avg_l']:+6.0f} | ${r['pnl_no_top']:+8.0f} | ${r['ev_no_top']:+6.1f} | "
            f"{r['wr_no_top']:5.1f} | {tp_n:3d} {sl_n:3d} {tm_n:3d} | {top_str}"
        )

    # ============================================================
    # EXIT REASON ANALYSIS (voor top 5)
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"EXIT REASON BREAKDOWN — Top 5 configs")
    print(f"{'=' * 100}")

    for i, r in enumerate(results[:5]):
        ratio = r['tp'] / r['sl'] if r['sl'] > 0 else 99
        print(f"\n  #{i+1} TP{r['tp']}% SL{r['sl']}% (ratio {ratio:.2f}) — {r['trades']} trades, EV/t ${r['ev_no_top']:+.1f}")
        for reason in ['TP', 'SL', 'TM', 'END']:
            rd = r['reasons'].get(reason, {})
            if rd.get('n', 0) > 0:
                print(
                    f"    {reason:>3}: {rd['n']:3d} trades ({rd['n']/r['trades']*100:5.1f}%) | "
                    f"WR {rd['wr']:5.1f}% | P&L ${rd['pnl']:+8.0f} | Avg ${rd['avg_pnl']:+7.1f}"
                )

    # ============================================================
    # HEATMAP (TP x SL matrix) — EV no top
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"HEATMAP — EV per trade zonder top (TP x SL)")
    print(f"{'=' * 100}")

    # Build lookup
    ev_map = {}
    for r in results:
        ev_map[(r['tp'], r['sl'])] = r['ev_no_top']

    # Header
    print(f"{'':>8}", end="")
    for sl in SL_VALUES:
        print(f" SL{sl:>2}%  ", end="")
    print()
    print("-" * (8 + len(SL_VALUES) * 8))

    for tp in TP_VALUES:
        print(f"TP{tp:>2}% |", end="")
        for sl in SL_VALUES:
            ev = ev_map.get((tp, sl), 0)
            if ev > 5:
                marker = " *** "
            elif ev > 0:
                marker = "  +  "
            elif ev > -5:
                marker = "  .  "
            else:
                marker = "  -  "
            print(f"{ev:+6.1f}{marker[0]}", end="")
        print()

    # ============================================================
    # TRADE COUNT HEATMAP
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"HEATMAP — Aantal trades (TP x SL)")
    print(f"{'=' * 100}")

    tr_map = {}
    for r in results:
        tr_map[(r['tp'], r['sl'])] = r['trades']

    print(f"{'':>8}", end="")
    for sl in SL_VALUES:
        print(f" SL{sl:>2}%", end="")
    print()
    print("-" * (8 + len(SL_VALUES) * 6))

    for tp in TP_VALUES:
        print(f"TP{tp:>2}% |", end="")
        for sl in SL_VALUES:
            tr = tr_map.get((tp, sl), 0)
            print(f"  {tr:3d} ", end="")
        print()

    # ============================================================
    # P&L HEATMAP
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"HEATMAP — Totale P&L (TP x SL)")
    print(f"{'=' * 100}")

    pnl_map = {}
    for r in results:
        pnl_map[(r['tp'], r['sl'])] = r['pnl']

    print(f"{'':>8}", end="")
    for sl in SL_VALUES:
        print(f"  SL{sl:>2}%  ", end="")
    print()
    print("-" * (8 + len(SL_VALUES) * 9))

    for tp in TP_VALUES:
        print(f"TP{tp:>2}% |", end="")
        for sl in SL_VALUES:
            pnl = pnl_map.get((tp, sl), 0)
            print(f" ${pnl:+6.0f} ", end="")
        print()

    # ============================================================
    # SUMMARY
    # ============================================================
    best = results[0]
    worst = results[-1]
    ratio_best = best['tp'] / best['sl'] if best['sl'] > 0 else 99

    print(f"\n{'=' * 100}")
    print(f"SAMENVATTING")
    print(f"{'=' * 100}")
    print(f"  Combinaties getest: {len(combos)}")
    print(f"  Coins: {len(coins)}")
    print(f"  TimeMax: {TIME_MAX} bars (vast)")
    print(f"  Positie: 1x ${POS_SIZE}")
    print(f"  Fee: {KRAKEN_FEE*100:.2f}%")
    print(f"")
    print(f"  BESTE: TP{best['tp']}% SL{best['sl']}% (ratio {ratio_best:.2f})")
    print(f"    Trades: {best['trades']}, WR: {best['wr']:.1f}%, P&L: ${best['pnl']:+.0f}")
    print(f"    P&L zonder top: ${best['pnl_no_top']:+.0f}")
    print(f"    EV per trade (zonder top): ${best['ev_no_top']:+.1f}")
    if best['top_trade']:
        print(f"    Top trade: {best['top_trade']['pair']} ${best['top_trade']['pnl']:+.0f}")
    for reason in ['TP', 'SL', 'TM']:
        rd = best['reasons'].get(reason, {})
        if rd.get('n', 0) > 0:
            print(f"    {reason}: {rd['n']} trades, WR {rd['wr']:.0f}%, avg ${rd['avg_pnl']:+.0f}")
    print(f"")

    # Positieve EV configs
    pos_ev = [r for r in results if r['ev_no_top'] > 0]
    print(f"  Configs met POSITIEVE EV (zonder top): {len(pos_ev)} / {len(results)}")
    if pos_ev:
        print(f"  Range: TP {min(r['tp'] for r in pos_ev)}-{max(r['tp'] for r in pos_ev)}%, "
              f"SL {min(r['sl'] for r in pos_ev)}-{max(r['sl'] for r in pos_ev)}%")

    print(f"\n  Totale runtime: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
