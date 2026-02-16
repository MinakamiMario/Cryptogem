#!/usr/bin/env python3
"""
Signal Diagnostics: Per-coin VWAP deviation distribution + trigger/trade analysis.

Purpose: Determine whether H20 VWAP_DEVIATION fails on Bybit because:
  (a) VWAP deviations never cross threshold → threshold mismatch
  (b) Triggers fire but trades are filtered downstream → harness/exit issue

Runs on top-20 MEXC-trade coins (by trade count) using Bybit candle data.
Also runs on full Bybit universe for comparison.

Output: reports/hf/bybit_signal_diagnostics_001.{json,md}
"""
from __future__ import annotations
import json
import sys
import time
import argparse
import statistics
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, precompute_base_indicators,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context


# ============================================================
# Step 1: Find top-20 MEXC coins by trade count
# ============================================================

def find_mexc_top_coins(n_top: int = 20) -> list[str]:
    """Run MEXC backtest to extract per-coin trade counts, return top-N bases."""
    print("[MEXC] Loading candle cache (tradeable)...")
    with open(ROOT / 'data' / 'candle_cache_tradeable.json') as f:
        mexc_data = json.load(f)

    with open(ROOT / 'reports' / 'hf' / 'universe_tiering_001.json') as f:
        mexc_tier = json.load(f)

    # Build coin lists (T1+T2)
    t1_coins = [c for c in mexc_tier['tier_breakdown']['1']['coins']
                if c in mexc_data]
    t2_coins = [c for c in mexc_tier['tier_breakdown']['2']['coins']
                if c in mexc_data]
    all_coins = t1_coins + t2_coins
    print(f"[MEXC] T1={len(t1_coins)}, T2={len(t2_coins)}, total={len(all_coins)}")

    # Precompute indicators
    print("[MEXC] Precomputing indicators...")
    indicators = precompute_base_indicators(mexc_data, all_coins)
    extend_indicators(mexc_data, all_coins, indicators)
    for coin in all_coins:
        if coin in indicators:
            indicators[coin]['__coin__'] = coin

    market_ctx = precompute_market_context(mexc_data, all_coins)
    params = {
        'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
        '__market__': market_ctx,
    }

    # Run backtest with 0 fees to get maximum trade count
    print("[MEXC] Running backtest (0 fee) to find top-trade coins...")
    bt = run_backtest(
        data=mexc_data, coins=all_coins,
        signal_fn=signal_h20_vwap_deviation,
        params=params, indicators=indicators,
        fee=0.0, max_pos=1, initial_capital=2000.0,
    )

    # Count trades per coin
    trade_counts = Counter()
    for t in bt.trade_list:
        trade_counts[t['pair']] += 1

    top = trade_counts.most_common(n_top)
    print(f"[MEXC] Total trades: {len(bt.trade_list)}")
    print(f"[MEXC] Unique coins with trades: {len(trade_counts)}")
    print(f"[MEXC] Top {n_top} coins:")
    for coin, count in top:
        print(f"    {coin:20s}: {count} trades")

    return [coin for coin, _ in top], trade_counts


# ============================================================
# Step 2: Per-coin VWAP deviation diagnostics
# ============================================================

def diagnose_coin(
    coin: str,
    candles: list[dict],
    indicators: dict,
    params: dict,
    start_bar: int = 50,
) -> dict:
    """Compute per-bar VWAP deviation stats + trigger/trade counts for a coin."""
    ind = indicators.get(coin, {})
    n = ind.get('n', 0)
    has_vwap = ind.get('has_vwap', False)
    vwaps = ind.get('vwaps', [])
    atr_list = ind.get('atr', [])

    result = {
        'coin': coin,
        'bars_loaded': n,
        'has_vwap': has_vwap,
        'vwap_coverage_pct': 0.0,
        'dev_distribution': {},
        'trigger_count': 0,      # bars where deviation >= threshold
        'bounce_count': 0,       # bars where deviation >= threshold AND bounce
        'trade_count': 0,        # actual trades from harness
        'bars_with_atr': 0,
        'bars_with_vwap': 0,
    }

    if n == 0:
        return result

    vwap_valid = sum(1 for v in vwaps[:n] if v is not None) if vwaps else 0
    atr_valid = sum(1 for i in range(min(n, len(atr_list))) if atr_list[i] is not None) if atr_list else 0
    result['vwap_coverage_pct'] = (vwap_valid / n * 100) if n > 0 else 0
    result['bars_with_vwap'] = vwap_valid
    result['bars_with_atr'] = atr_valid

    if not has_vwap:
        return result

    # Compute deviation for every bar
    dev_thresh = params['dev_thresh']
    deviations = []
    trigger_bars = []
    bounce_bars = []

    for bar in range(max(1, start_bar), n):
        if bar >= len(vwaps) or vwaps[bar] is None:
            continue
        atr = atr_list[bar] if bar < len(atr_list) else None
        if atr is None or atr <= 0:
            continue

        close = candles[bar]['close']
        prev_close = candles[bar - 1]['close']
        vwap = vwaps[bar]

        deviation = (vwap - close) / atr
        deviations.append(deviation)

        if deviation >= dev_thresh:
            trigger_bars.append(bar)
            if close > prev_close:
                bounce_bars.append(bar)

    result['trigger_count'] = len(trigger_bars)
    result['bounce_count'] = len(bounce_bars)

    if deviations:
        deviations_sorted = sorted(deviations)
        n_dev = len(deviations_sorted)
        result['dev_distribution'] = {
            'count': n_dev,
            'min': round(deviations_sorted[0], 4),
            'p10': round(deviations_sorted[int(n_dev * 0.1)], 4),
            'p25': round(deviations_sorted[int(n_dev * 0.25)], 4),
            'p50': round(deviations_sorted[int(n_dev * 0.5)], 4),
            'p75': round(deviations_sorted[int(n_dev * 0.75)], 4),
            'p90': round(deviations_sorted[min(int(n_dev * 0.9), n_dev - 1)], 4),
            'p95': round(deviations_sorted[min(int(n_dev * 0.95), n_dev - 1)], 4),
            'max': round(deviations_sorted[-1], 4),
            'mean': round(statistics.mean(deviations), 4),
            'pct_above_thresh': round(len(trigger_bars) / n_dev * 100, 2) if n_dev > 0 else 0,
        }

    return result


def run_diagnostics(
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
    label: str = "full",
) -> list[dict]:
    """Run per-coin diagnostics + actual backtests."""
    params = {
        'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
        '__market__': market_ctx,
    }

    # Per-coin diagnostic
    results = []
    for coin in coins:
        candles = data.get(coin, [])
        diag = diagnose_coin(coin, candles, indicators, params)
        results.append(diag)

    # Run actual backtest to get trade counts
    bt = run_backtest(
        data=data, coins=coins,
        signal_fn=signal_h20_vwap_deviation,
        params=params, indicators=indicators,
        fee=0.001, max_pos=1, initial_capital=2000.0,
    )
    trade_counts = Counter()
    for t in bt.trade_list:
        trade_counts[t['pair']] += 1

    for r in results:
        r['trade_count'] = trade_counts.get(r['coin'], 0)

    return results


# ============================================================
# Step 3: Compare MEXC vs Bybit deviations on same coins
# ============================================================

def compare_exchanges(mexc_diags: list[dict], bybit_diags: list[dict]) -> dict:
    """Compare deviation distributions between MEXC and Bybit for same coins."""
    mexc_by_base = {d['coin'].split('/')[0]: d for d in mexc_diags}
    bybit_by_base = {d['coin'].split('/')[0]: d for d in bybit_diags}

    comparison = []
    for base in mexc_by_base:
        if base not in bybit_by_base:
            continue
        m = mexc_by_base[base]
        b = bybit_by_base[base]

        comp = {
            'base': base,
            'mexc_coin': m['coin'],
            'bybit_coin': b['coin'],
            'mexc_triggers': m['trigger_count'],
            'bybit_triggers': b['trigger_count'],
            'mexc_bounces': m['bounce_count'],
            'bybit_bounces': b['bounce_count'],
            'mexc_trades': m['trade_count'],
            'bybit_trades': b['trade_count'],
            'mexc_dev_p50': m.get('dev_distribution', {}).get('p50', None),
            'bybit_dev_p50': b.get('dev_distribution', {}).get('p50', None),
            'mexc_dev_p90': m.get('dev_distribution', {}).get('p90', None),
            'bybit_dev_p90': b.get('dev_distribution', {}).get('p90', None),
            'mexc_dev_max': m.get('dev_distribution', {}).get('max', None),
            'bybit_dev_max': b.get('dev_distribution', {}).get('max', None),
            'mexc_pct_above': m.get('dev_distribution', {}).get('pct_above_thresh', 0),
            'bybit_pct_above': b.get('dev_distribution', {}).get('pct_above_thresh', 0),
        }
        comparison.append(comp)

    return comparison


# ============================================================
# Markdown report
# ============================================================

def build_md(
    mexc_top_diags: list[dict],
    bybit_top_diags: list[dict],
    bybit_full_diags: list[dict],
    comparison: list[dict],
    mexc_trade_counts: dict,
) -> str:
    lines = []
    lines.append("# Bybit Signal Diagnostics Report\n")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Signal**: H20 VWAP_DEVIATION (dev_thresh=2.0)")
    lines.append(f"**Data**: Bybit 1H candles (721 bars, 4.3 weeks)\n")

    # Summary stats for Bybit full universe
    total_triggers = sum(d['trigger_count'] for d in bybit_full_diags)
    total_bounces = sum(d['bounce_count'] for d in bybit_full_diags)
    total_trades = sum(d['trade_count'] for d in bybit_full_diags)
    coins_with_triggers = sum(1 for d in bybit_full_diags if d['trigger_count'] > 0)
    all_p50s = [d['dev_distribution'].get('p50', 0) for d in bybit_full_diags
                if d.get('dev_distribution')]
    all_p90s = [d['dev_distribution'].get('p90', 0) for d in bybit_full_diags
                if d.get('dev_distribution')]

    lines.append("## Bybit Full Universe Summary (454 coins)\n")
    lines.append(f"- Total trigger bars: **{total_triggers}** (deviation >= 2.0)")
    lines.append(f"- Total bounce bars: **{total_bounces}** (trigger + close > prev_close)")
    lines.append(f"- Coins with ≥1 trigger: **{coins_with_triggers}** / {len(bybit_full_diags)}")
    lines.append(f"- Harness trades: **{total_trades}**")
    if all_p50s:
        lines.append(f"- Median VWAP deviation (p50 across coins): **{statistics.median(all_p50s):.3f}**")
    if all_p90s:
        lines.append(f"- Median VWAP deviation (p90 across coins): **{statistics.median(all_p90s):.3f}**")
    lines.append("")

    # Threshold mismatch verdict
    if total_triggers == 0:
        lines.append("### ⚠️ VERDICT: ZERO TRIGGERS — threshold mismatch confirmed\n")
        lines.append("VWAP deviations on Bybit candle data NEVER reach 2.0 ATR.\n")
    elif total_bounces == 0:
        lines.append("### ⚠️ VERDICT: TRIGGERS but ZERO BOUNCES — bounce filter kills all\n")
    elif total_trades == 0:
        lines.append("### ⚠️ VERDICT: BOUNCES but ZERO TRADES — downstream filter\n")
    else:
        lines.append(f"### VERDICT: {total_triggers} triggers → {total_bounces} bounces → {total_trades} trades\n")

    # MEXC vs Bybit comparison (top-20 coins)
    lines.append("\n## MEXC vs Bybit — Top 20 MEXC-Trade Coins\n")
    lines.append("| Base | MEXC triggers | Bybit triggers | MEXC p50 | Bybit p50 | MEXC p90 | Bybit p90 | MEXC trades | Bybit trades |")
    lines.append("|------|--------------|----------------|----------|-----------|----------|-----------|-------------|-------------|")
    for c in sorted(comparison, key=lambda x: x['mexc_triggers'], reverse=True):
        mp50 = f"{c['mexc_dev_p50']:.2f}" if c['mexc_dev_p50'] is not None else "—"
        bp50 = f"{c['bybit_dev_p50']:.2f}" if c['bybit_dev_p50'] is not None else "—"
        mp90 = f"{c['mexc_dev_p90']:.2f}" if c['mexc_dev_p90'] is not None else "—"
        bp90 = f"{c['bybit_dev_p90']:.2f}" if c['bybit_dev_p90'] is not None else "—"
        lines.append(f"| {c['base']} | {c['mexc_triggers']} | {c['bybit_triggers']} | "
                     f"{mp50} | {bp50} | {mp90} | {bp90} | "
                     f"{c['mexc_trades']} | {c['bybit_trades']} |")

    # Aggregate comparison
    mexc_total_trig = sum(c['mexc_triggers'] for c in comparison)
    bybit_total_trig = sum(c['bybit_triggers'] for c in comparison)
    lines.append(f"\n**Aggregate**: MEXC {mexc_total_trig} triggers vs Bybit {bybit_total_trig} triggers on same coins\n")

    # Top-10 Bybit coins by trigger count (full universe)
    lines.append("\n## Top 10 Bybit Coins by Trigger Count (Full Universe)\n")
    top_bybit = sorted(bybit_full_diags, key=lambda x: x['trigger_count'], reverse=True)[:10]
    lines.append("| Coin | Bars | Triggers | Bounces | Trades | Dev p50 | Dev p90 | Dev max | %Above |")
    lines.append("|------|------|----------|---------|--------|---------|---------|---------|--------|")
    for d in top_bybit:
        dd = d.get('dev_distribution', {})
        lines.append(f"| {d['coin']} | {d['bars_loaded']} | {d['trigger_count']} | "
                     f"{d['bounce_count']} | {d['trade_count']} | "
                     f"{dd.get('p50', 0):.2f} | {dd.get('p90', 0):.2f} | "
                     f"{dd.get('max', 0):.2f} | {dd.get('pct_above_thresh', 0):.1f}% |")

    # Deviation distribution summary
    lines.append("\n## Deviation Distribution — Exchange Comparison\n")
    lines.append("*(p50 and p90 of per-coin median deviations)*\n")

    mexc_medians = [d['dev_distribution'].get('p50', 0) for d in mexc_top_diags
                    if d.get('dev_distribution')]
    bybit_medians = [d['dev_distribution'].get('p50', 0) for d in bybit_top_diags
                     if d.get('dev_distribution')]
    if mexc_medians:
        lines.append(f"- **MEXC top-20**: median of p50={statistics.median(mexc_medians):.3f}, "
                     f"max of p90={max(d['dev_distribution'].get('p90', 0) for d in mexc_top_diags if d.get('dev_distribution')):.3f}")
    if bybit_medians:
        lines.append(f"- **Bybit top-20**: median of p50={statistics.median(bybit_medians):.3f}, "
                     f"max of p90={max(d['dev_distribution'].get('p90', 0) for d in bybit_top_diags if d.get('dev_distribution')):.3f}")

    lines.append("\n---")
    lines.append(f"*Generated by signal_diagnostics.py at {time.strftime('%Y-%m-%d %H:%M')}*")
    return '\n'.join(lines)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='H20 VWAP Signal Diagnostics')
    parser.add_argument('--top-n', type=int, default=20,
                        help='Top N MEXC coins to diagnose (default: 20)')
    args = parser.parse_args()
    t0 = time.time()

    # Step 1: Find MEXC top-trade coins
    print("=" * 70)
    print("STEP 1: Finding MEXC top-trade coins")
    print("=" * 70)
    mexc_top_bases_coins, mexc_trade_counts = find_mexc_top_coins(args.top_n)
    mexc_top_bases = [c.split('/')[0] for c in mexc_top_bases_coins]

    # Step 2: Run MEXC diagnostics on top-20 coins
    print("\n" + "=" * 70)
    print("STEP 2: MEXC diagnostics on top coins")
    print("=" * 70)
    with open(ROOT / 'data' / 'candle_cache_tradeable.json') as f:
        mexc_data = json.load(f)
    mexc_top_coins = [c for c in mexc_top_bases_coins if c in mexc_data]
    mexc_indicators = precompute_base_indicators(mexc_data, mexc_top_coins)
    extend_indicators(mexc_data, mexc_top_coins, mexc_indicators)
    for c in mexc_top_coins:
        if c in mexc_indicators:
            mexc_indicators[c]['__coin__'] = c
    mexc_market_ctx = precompute_market_context(mexc_data, mexc_top_coins)
    mexc_top_diags = run_diagnostics(
        mexc_data, mexc_top_coins, mexc_indicators, mexc_market_ctx, "mexc_top"
    )
    print(f"  MEXC top-{args.top_n}: {sum(d['trigger_count'] for d in mexc_top_diags)} triggers, "
          f"{sum(d['trade_count'] for d in mexc_top_diags)} trades")

    # Step 3: Bybit diagnostics on matching coins
    print("\n" + "=" * 70)
    print("STEP 3: Bybit diagnostics on MEXC-matching coins")
    print("=" * 70)
    with open(ROOT / 'data' / 'candle_cache_1h_bybit.json') as f:
        bybit_data = json.load(f)

    # Find Bybit coins matching MEXC top bases
    bybit_top_coins = []
    for coin in bybit_data.keys():
        base = coin.split('/')[0]
        if base in mexc_top_bases:
            bybit_top_coins.append(coin)
    print(f"  Matched {len(bybit_top_coins)}/{args.top_n} MEXC top coins on Bybit")

    bybit_top_indicators = precompute_base_indicators(bybit_data, bybit_top_coins)
    extend_indicators(bybit_data, bybit_top_coins, bybit_top_indicators)
    for c in bybit_top_coins:
        if c in bybit_top_indicators:
            bybit_top_indicators[c]['__coin__'] = c
    bybit_top_market_ctx = precompute_market_context(bybit_data, bybit_top_coins)
    bybit_top_diags = run_diagnostics(
        bybit_data, bybit_top_coins, bybit_top_indicators, bybit_top_market_ctx, "bybit_top"
    )
    print(f"  Bybit top-match: {sum(d['trigger_count'] for d in bybit_top_diags)} triggers, "
          f"{sum(d['trade_count'] for d in bybit_top_diags)} trades")

    # Step 4: Bybit full universe diagnostics
    print("\n" + "=" * 70)
    print("STEP 4: Bybit full universe diagnostics")
    print("=" * 70)
    with open(ROOT / 'reports' / 'hf' / 'universe_tiering_bybit_001.json') as f:
        bybit_tier = json.load(f)

    bybit_all_coins = []
    for tier_num in ('1', '2'):
        for coin in bybit_tier['tier_breakdown'][tier_num]['coins']:
            if coin in bybit_data:
                bybit_all_coins.append(coin)
    print(f"  Bybit universe: {len(bybit_all_coins)} coins")

    bybit_all_indicators = precompute_base_indicators(bybit_data, bybit_all_coins)
    extend_indicators(bybit_data, bybit_all_coins, bybit_all_indicators)
    for c in bybit_all_coins:
        if c in bybit_all_indicators:
            bybit_all_indicators[c]['__coin__'] = c
    bybit_all_market_ctx = precompute_market_context(bybit_data, bybit_all_coins)
    bybit_full_diags = run_diagnostics(
        bybit_data, bybit_all_coins, bybit_all_indicators, bybit_all_market_ctx, "bybit_full"
    )
    total_trig = sum(d['trigger_count'] for d in bybit_full_diags)
    total_trades = sum(d['trade_count'] for d in bybit_full_diags)
    print(f"  Bybit full: {total_trig} triggers, {total_trades} trades")

    # Step 5: Compare
    print("\n" + "=" * 70)
    print("STEP 5: Exchange comparison")
    print("=" * 70)
    comparison = compare_exchanges(mexc_top_diags, bybit_top_diags)

    for c in sorted(comparison, key=lambda x: x['mexc_triggers'], reverse=True):
        print(f"  {c['base']:10s}: MEXC {c['mexc_triggers']:3d} trig / "
              f"Bybit {c['bybit_triggers']:3d} trig | "
              f"MEXC p50={c['mexc_dev_p50'] or 0:.2f} Bybit p50={c['bybit_dev_p50'] or 0:.2f}")

    # Save results
    elapsed = time.time() - t0
    report_json = {
        'meta': {
            'date': time.strftime('%Y-%m-%d %H:%M'),
            'runtime_s': round(elapsed, 1),
            'signal': 'H20_VWAP_DEVIATION',
            'dev_thresh': 2.0,
            'top_n': args.top_n,
        },
        'mexc_top_diagnostics': mexc_top_diags,
        'bybit_top_diagnostics': bybit_top_diags,
        'bybit_full_diagnostics': bybit_full_diags,
        'exchange_comparison': comparison,
        'summary': {
            'bybit_full_triggers': total_trig,
            'bybit_full_trades': total_trades,
            'bybit_full_coins_with_triggers': sum(1 for d in bybit_full_diags if d['trigger_count'] > 0),
            'mexc_top_triggers': sum(d['trigger_count'] for d in mexc_top_diags),
            'mexc_top_trades': sum(d['trade_count'] for d in mexc_top_diags),
        },
    }

    json_path = ROOT / 'reports' / 'hf' / 'bybit_signal_diagnostics_001.json'
    with open(json_path, 'w') as f:
        json.dump(report_json, f, indent=2, default=str)
    print(f"\n[Output] JSON: {json_path}")

    md_content = build_md(
        mexc_top_diags, bybit_top_diags, bybit_full_diags, comparison, mexc_trade_counts,
    )
    md_path = ROOT / 'reports' / 'hf' / 'bybit_signal_diagnostics_001.md'
    with open(md_path, 'w') as f:
        f.write(md_content)
    print(f"[Output] Markdown: {md_path}")
    print(f"\nTotal runtime: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
