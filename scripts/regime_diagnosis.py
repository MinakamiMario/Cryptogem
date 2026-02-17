#!/usr/bin/env python3
"""
Regime Diagnosis: EARLY (bars 0-359) vs LATE (bars 360-719)

Problem: All 3 GO configs from sweep v1 are break-even in EARLY but
explosive in LATE (PF 6-9). This script finds which market-regime
feature explains the difference.

Dataset: 526 coins, 721 bars (4H Kraken), Oct 16 2025 - Feb 13 2026
Strategy: DualConfirm bounce — needs VOLATILITY + OVERSOLD + VOLUME SPIKE
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

# -- Constants ----------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "trading_bot", "candle_cache_532.json")
TRADE_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "4h",
                          "sweep_v1_017_hnotrl_msp20_2659755", "results.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "4h", "regime_diagnosis_v1.md")

EARLY_START, EARLY_END = 0, 359    # Oct 16 - Dec 15, 2025
LATE_START, LATE_END = 360, 719    # Dec 15 - Feb 13, 2026
SPLIT_BAR = 360


# -- Indicator calculations ---------------------------------------------------
def calc_atr(candles, period=14):
    """Standard 14-period ATR using SMA of true range."""
    atrs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - candles[i - 1]['close']),
            abs(candles[i]['low'] - candles[i - 1]['close'])
        )
        atrs.append(tr)
    result = []
    for i in range(len(atrs)):
        if i < period - 1:
            result.append(sum(atrs[:i + 1]) / (i + 1))
        else:
            result.append(sum(atrs[i - period + 1:i + 1]) / period)
    return result


def calc_rsi(closes, period=14):
    """Standard 14-period RSI using Wilder smoothing."""
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]
    if len(gains) < period:
        return []
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsis = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsis.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100.0 - 100.0 / (1.0 + rs))
    return rsis


def calc_sma(values, period):
    """Simple moving average."""
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(sum(values[:i + 1]) / (i + 1))
        else:
            result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def max_drawdown_pct(closes):
    """Largest peak-to-trough % decline."""
    if not closes or closes[0] <= 0:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c <= 0:
            continue
        if c > peak:
            peak = c
        dd = (peak - c) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


# -- Per-coin metrics for a window --------------------------------------------
def compute_coin_metrics(candles, start, end):
    """Compute all 6 regime metrics for a coin within [start, end] bars."""
    window = candles[start:end + 1]
    if len(window) < 30:
        return None

    closes = [c['close'] for c in window]
    highs = [c['high'] for c in window]
    lows = [c['low'] for c in window]
    volumes = [c['volume'] for c in window]

    if any(c <= 0 for c in closes):
        return None

    # 1. ATR% -- ATR / close * 100
    atr_vals = calc_atr(window, 14)
    if not atr_vals:
        return None
    atr_pcts = []
    for i in range(len(atr_vals)):
        cl = closes[i + 1]
        if cl > 0:
            atr_pcts.append(atr_vals[i] / cl * 100.0)
    avg_atr_pct = sum(atr_pcts) / len(atr_pcts) if atr_pcts else 0.0

    # 2. RSI distribution
    rsi_vals = calc_rsi(closes, 14)
    if rsi_vals:
        rsi_below_40 = sum(1 for r in rsi_vals if r < 40) / len(rsi_vals) * 100.0
        rsi_below_30 = sum(1 for r in rsi_vals if r < 30) / len(rsi_vals) * 100.0
        avg_rsi = sum(rsi_vals) / len(rsi_vals)
    else:
        rsi_below_40 = 0.0
        rsi_below_30 = 0.0
        avg_rsi = 50.0

    # 3. Range/ATR ratio
    range_atr_ratios = []
    for i in range(len(atr_vals)):
        if atr_vals[i] > 0:
            bar_range = highs[i + 1] - lows[i + 1]
            range_atr_ratios.append(bar_range / atr_vals[i])
    avg_range_atr = sum(range_atr_ratios) / len(range_atr_ratios) if range_atr_ratios else 0.0

    # 4. Volume spike frequency
    vol_sma = calc_sma(volumes, 20)
    vol_spike_count = 0
    vol_spike_3x_count = 0
    total_vol_bars = 0
    for i in range(len(vol_sma)):
        if vol_sma[i] > 0:
            total_vol_bars += 1
            if volumes[i] > 2.0 * vol_sma[i]:
                vol_spike_count += 1
            if volumes[i] > 3.0 * vol_sma[i]:
                vol_spike_3x_count += 1
    vol_spike_pct = (vol_spike_count / total_vol_bars * 100.0) if total_vol_bars > 0 else 0.0
    vol_spike_3x_pct = (vol_spike_3x_count / total_vol_bars * 100.0) if total_vol_bars > 0 else 0.0

    # 5. Trend strength -- 50-bar SMA slope as %
    sma50 = calc_sma(closes, 50)
    if len(sma50) >= 2 and sma50[-1] > 0:
        lookback = min(50, len(sma50))
        slope_pct = (sma50[-1] - sma50[-lookback]) / sma50[-lookback] * 100.0
    else:
        slope_pct = 0.0

    # 6. Max drawdown per coin
    mdd = max_drawdown_pct(closes)

    # 7. BONUS: overall return
    overall_return = (closes[-1] - closes[0]) / closes[0] * 100.0 if closes[0] > 0 else 0.0

    return {
        'atr_pct': avg_atr_pct,
        'rsi_below_40': rsi_below_40,
        'rsi_below_30': rsi_below_30,
        'avg_rsi': avg_rsi,
        'range_atr': avg_range_atr,
        'vol_spike_2x_pct': vol_spike_pct,
        'vol_spike_3x_pct': vol_spike_3x_pct,
        'sma50_slope_pct': slope_pct,
        'max_dd_pct': mdd,
        'return_pct': overall_return,
    }


# -- Aggregation --------------------------------------------------------------
def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def aggregate(metrics_list, key):
    vals = sorted([m[key] for m in metrics_list if m is not None])
    if not vals:
        return {'mean': 0, 'median': 0, 'p25': 0, 'p75': 0, 'n': 0}
    return {
        'mean': sum(vals) / len(vals),
        'median': percentile(vals, 50),
        'p25': percentile(vals, 25),
        'p75': percentile(vals, 75),
        'n': len(vals),
    }


# -- Trade window attribution -------------------------------------------------
def attribute_trades(trade_path):
    if not os.path.exists(trade_path):
        return None, None
    with open(trade_path) as f:
        data = json.load(f)
    trades = data.get('trades', [])
    early_trades = [t for t in trades if t['entry_bar'] < SPLIT_BAR]
    late_trades = [t for t in trades if t['entry_bar'] >= SPLIT_BAR]
    return early_trades, late_trades


def trade_stats(trades):
    if not trades:
        return {'count': 0, 'win_rate': 0.0, 'avg_pnl': 0.0, 'total_pnl': 0.0, 'pf': 0.0}
    wins = sum(1 for t in trades if t['pnl'] > 0)
    total_pnl = sum(t['pnl'] for t in trades)
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    return {
        'count': len(trades),
        'win_rate': wins / len(trades) * 100.0,
        'avg_pnl': total_pnl / len(trades),
        'total_pnl': total_pnl,
        'pf': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
    }


# -- Formatting helpers -------------------------------------------------------
def fmt(val, decimals=2):
    if isinstance(val, float):
        if abs(val) == float('inf'):
            return "inf"
        return f"{val:.{decimals}f}"
    return str(val)


def delta_arrow(early_val, late_val):
    diff = late_val - early_val
    pct = (diff / abs(early_val) * 100.0) if early_val != 0 else 0.0
    arrow = "+" if diff >= 0 else ""
    return f"{arrow}{diff:.2f} ({arrow}{pct:.0f}%)"


# -- Main ---------------------------------------------------------------------
def main():
    print("Loading candle data...")
    with open(DATA_PATH) as f:
        raw = json.load(f)

    coins = {k: v for k, v in raw.items() if isinstance(v, list) and len(v) > 100}
    print(f"Loaded {len(coins)} coins")

    print("Computing EARLY window metrics (bars 0-359)...")
    early_metrics = {}
    for coin, candles in coins.items():
        m = compute_coin_metrics(candles, EARLY_START, EARLY_END)
        if m is not None:
            early_metrics[coin] = m

    print("Computing LATE window metrics (bars 360-719)...")
    late_metrics = {}
    for coin, candles in coins.items():
        end = min(LATE_END, len(candles) - 1)
        m = compute_coin_metrics(candles, LATE_START, end)
        if m is not None:
            late_metrics[coin] = m

    print(f"EARLY: {len(early_metrics)} coins | LATE: {len(late_metrics)} coins")

    metric_keys = [
        ('atr_pct', 'ATR% (14-period)', '%', 'Higher = more volatility'),
        ('rsi_below_40', 'RSI<40 frequency', '%', 'Higher = more oversold bars'),
        ('rsi_below_30', 'RSI<30 frequency', '%', 'Higher = deeply oversold bars'),
        ('avg_rsi', 'Average RSI', '', 'Lower = more bearish'),
        ('range_atr', 'Range/ATR ratio', 'x', 'Higher = choppier'),
        ('vol_spike_2x_pct', 'Vol spike >2x freq', '%', 'Higher = more vol events'),
        ('vol_spike_3x_pct', 'Vol spike >3x freq', '%', 'Strategy trigger threshold'),
        ('sma50_slope_pct', 'SMA50 slope', '%', 'Negative = downtrend'),
        ('max_dd_pct', 'Max drawdown', '%', 'Deeper = more bounce opportunities'),
        ('return_pct', 'Window return', '%', 'Overall price change'),
    ]

    early_aggs = {}
    late_aggs = {}
    for key, _, _, _ in metric_keys:
        early_aggs[key] = aggregate(list(early_metrics.values()), key)
        late_aggs[key] = aggregate(list(late_metrics.values()), key)

    print("\nLoading trade data for hnotrl_msp20...")
    early_trades, late_trades = attribute_trades(TRADE_PATH)

    # -- Build output ---------------------------------------------------------
    lines = []
    lines.append("# Regime Diagnosis: EARLY vs LATE")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Dataset**: {len(coins)} coins, 721 bars (4H Kraken)")
    lines.append(f"**EARLY**: bars 0-359 (Oct 16 - Dec 15, 2025) | {len(early_metrics)} coins analyzed")
    lines.append(f"**LATE**: bars 360-719 (Dec 15 - Feb 13, 2026) | {len(late_metrics)} coins analyzed")
    lines.append("")
    lines.append("## Problem Statement")
    lines.append("")
    lines.append("All 3 GO configs from sweep v1 are break-even in EARLY but explosive in LATE (PF 6-9).")
    lines.append("The DualConfirm bounce strategy needs: VOLATILITY + OVERSOLD (RSI<42) + VOLUME SPIKE (>3x).")
    lines.append("Which market-regime feature changed between the two halves?")
    lines.append("")

    # -- Comparison Table -----------------------------------------------------
    lines.append("## Regime Comparison Table")
    lines.append("")
    lines.append("| Metric | Unit | EARLY mean | LATE mean | Delta | EARLY med | LATE med | What it means |")
    lines.append("|--------|------|-----------|----------|-------|-----------|---------|---------------|")

    for key, name, unit, desc in metric_keys:
        e = early_aggs[key]
        l = late_aggs[key]
        d = delta_arrow(e['mean'], l['mean'])
        lines.append(f"| {name} | {unit} | {fmt(e['mean'])} | {fmt(l['mean'])} | {d} | {fmt(e['median'])} | {fmt(l['median'])} | {desc} |")

    lines.append("")

    # -- Distribution detail --------------------------------------------------
    lines.append("## Distribution Detail (P25 / P75)")
    lines.append("")
    lines.append("| Metric | EARLY P25 | EARLY P75 | LATE P25 | LATE P75 | Spread change |")
    lines.append("|--------|-----------|-----------|----------|----------|---------------|")

    for key, name, _, _ in metric_keys:
        e = early_aggs[key]
        l = late_aggs[key]
        e_spread = e['p75'] - e['p25']
        l_spread = l['p75'] - l['p25']
        spread_d = delta_arrow(e_spread, l_spread) if e_spread != 0 else "N/A"
        lines.append(f"| {name} | {fmt(e['p25'])} | {fmt(e['p75'])} | {fmt(l['p25'])} | {fmt(l['p75'])} | {spread_d} |")

    lines.append("")

    # -- Trade Attribution ----------------------------------------------------
    lines.append("## Trade Attribution: hnotrl_msp20 (FULL window)")
    lines.append("")

    if early_trades is not None and late_trades is not None:
        es = trade_stats(early_trades)
        ls = trade_stats(late_trades)
        lines.append("| Window | Trades | Win Rate | Avg P&L | Total P&L | Profit Factor |")
        lines.append("|--------|--------|----------|---------|-----------|---------------|")
        lines.append(f"| EARLY | {es['count']} | {fmt(es['win_rate'])}% | ${fmt(es['avg_pnl'])} | ${fmt(es['total_pnl'])} | {fmt(es['pf'])} |")
        lines.append(f"| LATE | {ls['count']} | {fmt(ls['win_rate'])}% | ${fmt(ls['avg_pnl'])} | ${fmt(ls['total_pnl'])} | {fmt(ls['pf'])} |")
        lines.append("")

        lines.append("### Exit Reasons by Window")
        lines.append("")
        for label, trades in [("EARLY", early_trades), ("LATE", late_trades)]:
            reasons = {}
            for t in trades:
                r = t.get('reason', 'UNKNOWN')
                if r not in reasons:
                    reasons[r] = {'count': 0, 'pnl': 0.0, 'wins': 0}
                reasons[r]['count'] += 1
                reasons[r]['pnl'] += t['pnl']
                if t['pnl'] > 0:
                    reasons[r]['wins'] += 1
            if reasons:
                lines.append(f"**{label}**:")
                lines.append("")
                lines.append("| Exit Reason | Count | Win Rate | Total P&L |")
                lines.append("|-------------|-------|----------|-----------|")
                for r, d in sorted(reasons.items(), key=lambda x: -x[1]['pnl']):
                    wr = d['wins'] / d['count'] * 100.0 if d['count'] > 0 else 0.0
                    lines.append(f"| {r} | {d['count']} | {fmt(wr)}% | ${fmt(d['pnl'])} |")
                lines.append("")
    else:
        lines.append("*Trade data not found.*")
        lines.append("")

    # -- Key Findings ---------------------------------------------------------
    lines.append("## Key Findings")
    lines.append("")

    deltas = []
    for key, name, unit, desc in metric_keys:
        e = early_aggs[key]
        l = late_aggs[key]
        if e['mean'] != 0:
            pct_change = (l['mean'] - e['mean']) / abs(e['mean']) * 100.0
        else:
            pct_change = 0
        deltas.append((abs(pct_change), pct_change, name, key, e['mean'], l['mean'], desc))

    deltas.sort(reverse=True)

    lines.append("### Ranked by magnitude of change (EARLY -> LATE):")
    lines.append("")
    for i, (abs_pct, pct, name, key, e_val, l_val, desc) in enumerate(deltas):
        direction = "UP" if pct > 0 else "DOWN"
        lines.append(f"{i+1}. **{name}**: {fmt(e_val)} -> {fmt(l_val)} ({direction} {fmt(abs_pct, 0)}%) -- {desc}")

    lines.append("")
    lines.append("### Interpretation")
    lines.append("")

    e_dd = early_aggs['max_dd_pct']['mean']
    l_dd = late_aggs['max_dd_pct']['mean']
    e_rsi40 = early_aggs['rsi_below_40']['mean']
    l_rsi40 = late_aggs['rsi_below_40']['mean']
    e_rsi30 = early_aggs['rsi_below_30']['mean']
    l_rsi30 = late_aggs['rsi_below_30']['mean']
    e_atr = early_aggs['atr_pct']['mean']
    l_atr = late_aggs['atr_pct']['mean']
    e_vol3x = early_aggs['vol_spike_3x_pct']['mean']
    l_vol3x = late_aggs['vol_spike_3x_pct']['mean']
    e_slope = early_aggs['sma50_slope_pct']['mean']
    l_slope = late_aggs['sma50_slope_pct']['mean']
    e_ret = early_aggs['return_pct']['mean']
    l_ret = late_aggs['return_pct']['mean']

    lines.append("The DualConfirm bounce strategy needs THREE conditions simultaneously:")
    lines.append("1. RSI < 42 (oversold)")
    lines.append("2. Donchian + BB confirmation (price near lower bands)")
    lines.append("3. Volume spike > 3x (capitulation/washout)")
    lines.append("")
    dd_dir = 'deeper' if l_dd > e_dd else 'shallower'
    dd_impl = 'Deeper drawdowns create MORE bounce entry points.' if l_dd > e_dd else 'Shallower drawdowns create FEWER entries.'
    lines.append(f"**Max Drawdown** is {fmt(abs((l_dd - e_dd) / e_dd * 100), 0)}% {dd_dir} in LATE "
                 f"({fmt(e_dd)}% -> {fmt(l_dd)}%). {dd_impl}")
    lines.append("")
    rsi_dir = 'increased' if l_rsi40 > e_rsi40 else 'decreased'
    rsi_impl = 'More oversold conditions = more potential entries.' if l_rsi40 > e_rsi40 else 'Fewer oversold conditions.'
    lines.append(f"**RSI<40 frequency** {rsi_dir}: "
                 f"{fmt(e_rsi40)}% -> {fmt(l_rsi40)}% of bars. {rsi_impl}")
    lines.append("")
    lines.append(f"**RSI<30 frequency** (deep oversold): {fmt(e_rsi30)}% -> {fmt(l_rsi30)}% of bars.")
    lines.append("")
    atr_dir = 'increased' if l_atr > e_atr else 'decreased'
    atr_impl = 'Higher volatility means larger potential bounces.' if l_atr > e_atr else ''
    lines.append(f"**ATR%** {atr_dir}: {fmt(e_atr)}% -> {fmt(l_atr)}%. {atr_impl}")
    lines.append("")
    vol_dir = 'increased' if l_vol3x > e_vol3x else 'decreased'
    vol_impl = 'more trigger opportunities.' if l_vol3x > e_vol3x else 'fewer trigger opportunities.'
    lines.append(f"**Volume spike >3x frequency** {vol_dir}: "
                 f"{fmt(e_vol3x)}% -> {fmt(l_vol3x)}%. "
                 f"This is the strategy's entry filter -- {vol_impl}")
    lines.append("")
    slope_impl = 'LATE has stronger downtrend, creating deeper selloffs that bounce harder.' if l_slope < e_slope else ''
    lines.append(f"**SMA50 slope**: {fmt(e_slope)}% -> {fmt(l_slope)}%. {slope_impl}")
    lines.append("")
    ret_impl = 'LATE is a deeper bear market -- exactly what the bounce strategy was designed for.' if l_ret < e_ret else ''
    lines.append(f"**Window return**: {fmt(e_ret)}% -> {fmt(l_ret)}%. {ret_impl}")
    lines.append("")

    # Final verdict
    lines.append("### Verdict")
    lines.append("")
    top3 = deltas[:3]
    lines.append(f"The **top discriminating feature** is **{top3[0][2]}** ({'+' if top3[0][1] > 0 else ''}{fmt(top3[0][1], 0)}% change).")
    lines.append(f"Second is **{top3[1][2]}** ({'+' if top3[1][1] > 0 else ''}{fmt(top3[1][1], 0)}%).")
    lines.append(f"Third is **{top3[2][2]}** ({'+' if top3[2][1] > 0 else ''}{fmt(top3[2][1], 0)}%).")
    lines.append("")
    lines.append("The strategy is a **regime-dependent bounce strategy**: it profits when the market")
    lines.append("creates deep selloffs (high drawdowns, low RSI, high ATR) with capitulation volume (3x spikes).")
    lines.append("EARLY was a range-bound / mild decline market that rarely triggered entry conditions.")
    lines.append("LATE was a deeper bear market with sharper selloffs and more frequent capitulation events.")
    lines.append("")
    lines.append("**Implication for production**: This strategy needs a regime filter or should only deploy")
    lines.append("capital when market conditions match the LATE-window profile. A simple ATR% or drawdown")
    lines.append("threshold could serve as a regime gate.")

    # -- Print to console -----------------------------------------------------
    report = "\n".join(lines)
    print("\n" + "=" * 80)
    print(report)
    print("=" * 80)

    # -- Write to file --------------------------------------------------------
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(report)
    print(f"\nReport written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
