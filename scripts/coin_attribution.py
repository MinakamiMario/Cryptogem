#!/usr/bin/env python3
"""
COIN ATTRIBUTION ANALYSIS
=========================
Analyzes which coins drive profits/losses, drawdown, and ruin risk
across two universes: RESEARCH_ALL (2090 coins) and LIVE_CURRENT (526 coins).

Outputs:
  reports/coin_attribution.json  -- full per-coin data
  reports/coin_attribution.md   -- human-readable report

Config: C1_TPSL_RSI45
"""
import sys
import json
import time
from pathlib import Path
from copy import deepcopy
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
TRADING_BOT_DIR = BASE_DIR / 'trading_bot'
sys.path.insert(0, str(TRADING_BOT_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)

CFG = {
    'exit_type': 'tp_sl',
    'max_pos': 1,
    'rsi_max': 45,
    'sl_pct': 15,
    'time_max_bars': 15,
    'tp_pct': 15,
    'vol_confirm': True,
    'vol_spike_mult': 3.0,
}

RESEARCH_CACHE = BASE_DIR / 'data' / 'candle_cache_research_all.json'
LIVE_CACHE = TRADING_BOT_DIR / 'candle_cache_532.json'
REPORTS_DIR = BASE_DIR / 'reports'
REPORTS_DIR.mkdir(exist_ok=True)


def load_cache(path):
    with open(path) as f:
        data = json.load(f)
    coins = [k for k in data if not k.startswith('_')]
    return data, coins


def run_bt(data, coins, cfg, fee=KRAKEN_FEE, label=''):
    t0 = time.time()
    print(f"  [{label}] Precomputing indicators for {len(coins)} coins...", flush=True)
    indicators = precompute_all(data, coins)
    t1 = time.time()
    print(f"  [{label}] Precompute done in {t1-t0:.1f}s. Running backtest...", flush=True)
    result = run_backtest(indicators, coins, cfg, fee_override=fee)
    t2 = time.time()
    print(f"  [{label}] Backtest done in {t2-t1:.1f}s. Trades={result['trades']} P&L=${result['pnl']:.2f}", flush=True)
    return result, indicators


def per_coin_analysis(trades):
    by_coin = defaultdict(list)
    for t in trades:
        by_coin[t['pair']].append(t)
    total_pnl = sum(t['pnl'] for t in trades)
    coins = {}
    for pair, coin_trades in by_coin.items():
        pnls = [t['pnl'] for t in coin_trades]
        wins = sum(1 for p in pnls if p > 0)
        n = len(pnls)
        coins[pair] = {
            'trades': n,
            'total_pnl': round(sum(pnls), 2),
            'win_rate': round(wins / n * 100, 1) if n else 0,
            'avg_pnl': round(sum(pnls) / n, 2) if n else 0,
            'max_loss': round(min(pnls), 2) if pnls else 0,
            'max_win': round(max(pnls), 2) if pnls else 0,
            'pnl_contribution_pct': round(sum(pnls) / total_pnl * 100, 2) if total_pnl != 0 else 0,
            'exit_reasons': {},
        }
        for t in coin_trades:
            r = t['reason']
            if r not in coins[pair]['exit_reasons']:
                coins[pair]['exit_reasons'][r] = {'count': 0, 'pnl': 0}
            coins[pair]['exit_reasons'][r]['count'] += 1
            coins[pair]['exit_reasons'][r]['pnl'] = round(
                coins[pair]['exit_reasons'][r]['pnl'] + t['pnl'], 2)
    return coins, total_pnl


def top_bottom(coins_dict, n=10):
    sorted_coins = sorted(coins_dict.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
    top = sorted_coins[:n]
    bottom = sorted_coins[-n:]
    bottom.reverse()
    return top, bottom


def compute_drawdown_contribution(trades):
    if not trades:
        return {}
    sorted_trades = sorted(trades, key=lambda t: t['exit_bar'])
    dd_contributors = defaultdict(float)
    for t in sorted_trades:
        if t['pnl'] < 0:
            dd_contributors[t['pair']] += abs(t['pnl'])
    total_losses = sum(dd_contributors.values())
    if total_losses > 0:
        for pair in dd_contributors:
            dd_contributors[pair] = round(dd_contributors[pair] / total_losses * 100, 2)
    return dict(sorted(dd_contributors.items(), key=lambda x: x[1], reverse=True))


def leave_one_out_analysis(coins_list, cfg, indicators, worst_coins, label=''):
    baseline = run_backtest(indicators, coins_list, cfg)
    baseline_pnl = baseline['pnl']
    baseline_trades = baseline['trades']
    results = {}
    for pair in worst_coins:
        reduced = [c for c in coins_list if c != pair]
        bt = run_backtest(indicators, reduced, cfg)
        improvement = bt['pnl'] - baseline_pnl
        results[pair] = {
            'baseline_pnl': round(baseline_pnl, 2),
            'without_pnl': round(bt['pnl'], 2),
            'improvement': round(improvement, 2),
            'baseline_trades': baseline_trades,
            'without_trades': bt['trades'],
            'trades_removed': baseline_trades - bt['trades'],
        }
        print(f"    LOO [{label}] {pair}: ${baseline_pnl:.0f} -> ${bt['pnl']:.0f} (d=${improvement:+.0f})", flush=True)
    return dict(sorted(results.items(), key=lambda x: x[1]['improvement'], reverse=True))


def friction_sensitivity(coins_list, cfg, indicators, top_traded_coins, label=''):
    base_fee = KRAKEN_FEE
    friction_fee = KRAKEN_FEE * 2 + 0.002
    results = {}
    for pair in top_traded_coins:
        bt_base = run_backtest(indicators, [pair], cfg, fee_override=base_fee)
        bt_fric = run_backtest(indicators, [pair], cfg, fee_override=friction_fee)
        base_pnl = bt_base['pnl']
        fric_pnl = bt_fric['pnl']
        flipped = base_pnl > 0 and fric_pnl <= 0
        results[pair] = {
            'trades': bt_base['trades'],
            'pnl_base': round(base_pnl, 2),
            'pnl_friction': round(fric_pnl, 2),
            'pnl_delta': round(fric_pnl - base_pnl, 2),
            'flipped_to_loss': flipped,
        }
    return dict(sorted(results.items(), key=lambda x: x[1]['pnl_delta']))


def build_markdown(report, top_r, bottom_r, top_l, bottom_l,
                   new_top, new_bottom, only_research, new_coins_pnl,
                   loo_r, loo_l, fric_r, fric_l, elapsed,
                   coins_l, total_pnl_r):
    md = []
    md.append("# Coin Attribution Analysis")
    md.append("")
    md.append("**Config**: C1_TPSL_RSI45 (`tp_sl`, RSI<45, TP/SL 15%, TM 15 bars, VolSpike 3.0x)")
    md.append("**Date**: " + time.strftime('%Y-%m-%d %H:%M'))
    md.append("**Runtime**: " + str(int(elapsed)) + "s")
    md.append("")

    # Section 1
    md.append("---")
    md.append("## 1. RESEARCH_ALL Coin Analysis")
    md.append("")
    s = report['research_all']['summary']
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append("| Universe size | {} |".format(s['coins_in_universe']))
    md.append("| Coins traded | {} |".format(s['coins_traded']))
    md.append("| Total trades | {} |".format(s['total_trades']))
    md.append("| Total P&L | ${:,.2f} |".format(s['total_pnl']))
    md.append("| Win rate | {}% |".format(s['win_rate']))
    md.append("| Max DD | {}% |".format(s['max_dd']))
    md.append("| Winning coins | {} (${:,.2f}) |".format(s['winning_coins'], s['total_win_from_winners']))
    md.append("| Losing coins | {} (${:,.2f}) |".format(s['losing_coins'], s['total_loss_from_losers']))
    md.append("")

    md.append("### Top 10 Winners")
    md.append("| # | Coin | Trades | P&L | WR% | Avg P&L | Max Win | Contribution |")
    md.append("|---|------|--------|-----|-----|---------|---------|--------------|")
    for i, (pair, v) in enumerate(top_r, 1):
        md.append("| {} | {} | {} | ${:,.2f} | {}% | ${:.2f} | ${:.2f} | {:.1f}% |".format(
            i, pair, v['trades'], v['total_pnl'], v['win_rate'],
            v['avg_pnl'], v['max_win'], v['pnl_contribution_pct']))
    md.append("")

    md.append("### Bottom 10 Losers")
    md.append("| # | Coin | Trades | P&L | WR% | Avg P&L | Max Loss | Contribution |")
    md.append("|---|------|--------|-----|-----|---------|----------|--------------|")
    for i, (pair, v) in enumerate(bottom_r, 1):
        md.append("| {} | {} | {} | ${:,.2f} | {}% | ${:.2f} | ${:.2f} | {:.1f}% |".format(
            i, pair, v['trades'], v['total_pnl'], v['win_rate'],
            v['avg_pnl'], v['max_loss'], v['pnl_contribution_pct']))
    md.append("")

    md.append("### New MEXC/RESEARCH Coins (not in LIVE)")
    nc = report['new_coins']
    md.append("- **Total new coins**: {}".format(nc['count']))
    md.append("- **New coins traded**: {}".format(nc['coins_traded']))
    md.append("- **New coins P&L**: ${:,.2f}".format(nc['total_pnl']))
    md.append("- **Winners**: {} (${:,.2f})".format(nc['winning_count'], nc['win_pnl']))
    md.append("- **Losers**: {} (${:,.2f})".format(nc['losing_count'], nc['loss_pnl']))
    md.append("")
    if new_top:
        md.append("#### Top 10 New Coin Winners")
        md.append("| # | Coin | Trades | P&L | WR% |")
        md.append("|---|------|--------|-----|-----|")
        for i, (pair, v) in enumerate(new_top[:10], 1):
            md.append("| {} | {} | {} | ${:,.2f} | {}% |".format(
                i, pair, v['trades'], v['total_pnl'], v['win_rate']))
        md.append("")
    if new_bottom:
        md.append("#### Bottom 10 New Coin Losers")
        md.append("| # | Coin | Trades | P&L | WR% |")
        md.append("|---|------|--------|-----|-----|")
        for i, (pair, v) in enumerate(new_bottom[:10], 1):
            md.append("| {} | {} | {} | ${:,.2f} | {}% |".format(
                i, pair, v['trades'], v['total_pnl'], v['win_rate']))
        md.append("")

    # Section 2
    md.append("---")
    md.append("## 2. LIVE_CURRENT Coin Analysis")
    md.append("")
    s = report['live_current']['summary']
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append("| Universe size | {} |".format(s['coins_in_universe']))
    md.append("| Coins traded | {} |".format(s['coins_traded']))
    md.append("| Total trades | {} |".format(s['total_trades']))
    md.append("| Total P&L | ${:,.2f} |".format(s['total_pnl']))
    md.append("| Win rate | {}% |".format(s['win_rate']))
    md.append("| Max DD | {}% |".format(s['max_dd']))
    md.append("| Winning coins | {} (${:,.2f}) |".format(s['winning_coins'], s['total_win_from_winners']))
    md.append("| Losing coins | {} (${:,.2f}) |".format(s['losing_coins'], s['total_loss_from_losers']))
    md.append("")

    md.append("### Top 10 Winners")
    md.append("| # | Coin | Trades | P&L | WR% | Avg P&L | Max Win | Contribution |")
    md.append("|---|------|--------|-----|-----|---------|---------|--------------|")
    for i, (pair, v) in enumerate(top_l, 1):
        md.append("| {} | {} | {} | ${:,.2f} | {}% | ${:.2f} | ${:.2f} | {:.1f}% |".format(
            i, pair, v['trades'], v['total_pnl'], v['win_rate'],
            v['avg_pnl'], v['max_win'], v['pnl_contribution_pct']))
    md.append("")

    md.append("### Bottom 10 Losers")
    md.append("| # | Coin | Trades | P&L | WR% | Avg P&L | Max Loss | Contribution |")
    md.append("|---|------|--------|-----|-----|---------|----------|--------------|")
    for i, (pair, v) in enumerate(bottom_l, 1):
        md.append("| {} | {} | {} | ${:,.2f} | {}% | ${:.2f} | ${:.2f} | {:.1f}% |".format(
            i, pair, v['trades'], v['total_pnl'], v['win_rate'],
            v['avg_pnl'], v['max_loss'], v['pnl_contribution_pct']))
    md.append("")

    # Section 3
    md.append("---")
    md.append("## 3. Comparison: LIVE vs RESEARCH")
    md.append("")
    r_s = report['research_all']['summary']
    l_s = report['live_current']['summary']
    md.append("| Metric | RESEARCH_ALL | LIVE_CURRENT | Delta |")
    md.append("|--------|-------------|-------------|-------|")
    md.append("| Universe | {} | {} | +{} |".format(r_s['coins_in_universe'], l_s['coins_in_universe'], r_s['coins_in_universe']-l_s['coins_in_universe']))
    md.append("| Traded | {} | {} | +{} |".format(r_s['coins_traded'], l_s['coins_traded'], r_s['coins_traded']-l_s['coins_traded']))
    md.append("| Trades | {} | {} | +{} |".format(r_s['total_trades'], l_s['total_trades'], r_s['total_trades']-l_s['total_trades']))
    md.append("| P&L | ${:,.2f} | ${:,.2f} | ${:+,.2f} |".format(r_s['total_pnl'], l_s['total_pnl'], r_s['total_pnl']-l_s['total_pnl']))
    md.append("| Win Rate | {}% | {}% | {:+.1f}pp |".format(r_s['win_rate'], l_s['win_rate'], r_s['win_rate']-l_s['win_rate']))
    md.append("| Max DD | {}% | {}% | {:+.1f}pp |".format(r_s['max_dd'], l_s['max_dd'], r_s['max_dd']-l_s['max_dd']))
    md.append("")

    live_losers = sorted(
        [(p, v) for p, v in coins_l.items() if v['total_pnl'] < 0],
        key=lambda x: x[1]['total_pnl']
    )
    md.append("### LIVE coins that are hurting (worst 10)")
    md.append("| Coin | Trades | P&L | Avg P&L |")
    md.append("|------|--------|-----|---------|")
    for pair, v in live_losers[:10]:
        md.append("| {} | {} | ${:,.2f} | ${:.2f} |".format(pair, v['trades'], v['total_pnl'], v['avg_pnl']))
    md.append("")

    # Section 4
    md.append("---")
    md.append("## 4. Leave-One-Out Analysis (Worst 20 Coins)")
    md.append("")
    md.append("### RESEARCH_ALL")
    md.append("| Coin | Baseline P&L | Without P&L | Improvement | Trades Removed |")
    md.append("|------|-------------|-------------|-------------|----------------|")
    for pair, v in list(loo_r.items())[:20]:
        md.append("| {} | ${:,.2f} | ${:,.2f} | ${:+,.2f} | {} |".format(
            pair, v['baseline_pnl'], v['without_pnl'], v['improvement'], v['trades_removed']))
    md.append("")

    md.append("### LIVE_CURRENT")
    md.append("| Coin | Baseline P&L | Without P&L | Improvement | Trades Removed |")
    md.append("|------|-------------|-------------|-------------|----------------|")
    for pair, v in list(loo_l.items())[:20]:
        md.append("| {} | ${:,.2f} | ${:,.2f} | ${:+,.2f} | {} |".format(
            pair, v['baseline_pnl'], v['without_pnl'], v['improvement'], v['trades_removed']))
    md.append("")

    # Section 5
    md.append("---")
    md.append("## 5. Friction Sensitivity (Top 20 Most-Traded Coins)")
    md.append("")
    md.append("Friction: 2x fees (0.52%) + 20bps slippage = 0.72% total per side")
    md.append("")

    md.append("### RESEARCH_ALL")
    md.append("| Coin | Trades | Base P&L | Friction P&L | Delta | Flipped? |")
    md.append("|------|--------|----------|-------------|-------|----------|")
    for pair, v in fric_r.items():
        flip = "YES" if v['flipped_to_loss'] else ""
        md.append("| {} | {} | ${:,.2f} | ${:,.2f} | ${:+,.2f} | {} |".format(
            pair, v['trades'], v['pnl_base'], v['pnl_friction'], v['pnl_delta'], flip))
    md.append("")

    md.append("### LIVE_CURRENT")
    md.append("| Coin | Trades | Base P&L | Friction P&L | Delta | Flipped? |")
    md.append("|------|--------|----------|-------------|-------|----------|")
    for pair, v in fric_l.items():
        flip = "YES" if v['flipped_to_loss'] else ""
        md.append("| {} | {} | ${:,.2f} | ${:,.2f} | ${:+,.2f} | {} |".format(
            pair, v['trades'], v['pnl_base'], v['pnl_friction'], v['pnl_delta'], flip))
    md.append("")

    # Section 6
    md.append("---")
    md.append("## 6. Key Insight: Is RESEARCH_ALL NO-GO Systemic or Concentrated?")
    md.append("")
    sa = report['systemic_analysis']
    sar = sa['research_all']
    sal = sa['live_current']

    md.append("### RESEARCH_ALL Systemic Indicators")
    md.append("- **% coins losing**: {}%".format(sar['pct_coins_losing']))
    md.append("- **% coins winning**: {}%".format(sar['pct_coins_winning']))
    md.append("- **Avg P&L per coin**: ${:.2f}".format(sar['avg_pnl_per_coin']))
    md.append("- **Median coin P&L**: ${:.2f}".format(sar['median_coin_pnl']))
    md.append("- **New coins P&L share**: {:.1f}% of total".format(sar['new_coins_pnl_share']))
    md.append("")

    md.append("### LIVE_CURRENT Systemic Indicators")
    md.append("- **% coins losing**: {}%".format(sal['pct_coins_losing']))
    md.append("- **% coins winning**: {}%".format(sal['pct_coins_winning']))
    md.append("- **Avg P&L per coin**: ${:.2f}".format(sal['avg_pnl_per_coin']))
    md.append("- **Median coin P&L**: ${:.2f}".format(sal['median_coin_pnl']))
    md.append("")

    md.append("### Verdict")
    md.append("")

    top5_loo_r = list(loo_r.items())[:5]
    top5_loo_l = list(loo_l.items())[:5]
    top5_loo_sum_r = sum(v['improvement'] for _, v in top5_loo_r)
    top5_loo_sum_l = sum(v['improvement'] for _, v in top5_loo_l)
    flipped_r = sum(1 for v in fric_r.values() if v['flipped_to_loss'])
    flipped_l = sum(1 for v in fric_l.values() if v['flipped_to_loss'])

    if total_pnl_r < 0:
        if sar['pct_coins_losing'] > 60:
            md.append("**SYSTEMIC PROBLEM**: The majority of coins are losing money in RESEARCH_ALL. "
                      "The issue is not caused by a few bad actors but is a broad pattern across the expanded universe.")
        elif abs(new_coins_pnl) > abs(total_pnl_r) * 0.5:
            md.append("**CONCENTRATED in NEW COINS**: The new MEXC/research coins are responsible for "
                      "a large portion of losses. The {} new coins contribute ${:,.2f} to total P&L.".format(
                          len(only_research), new_coins_pnl))
        else:
            md.append("**MIXED**: Losses are spread across both new and existing coins. "
                      "The expanded universe adds both winners and losers.")
    elif total_pnl_r >= 0:
        if total_pnl_r < report['live_current']['summary']['total_pnl']:
            md.append("**DILUTION**: RESEARCH_ALL is profitable but less so than LIVE_CURRENT. "
                      "The extra coins dilute performance.")
        else:
            md.append("**POSITIVE**: RESEARCH_ALL is profitable and improves on LIVE_CURRENT.")

    md.append("")
    md.append("- **LOO top 5 improvement (RESEARCH)**: ${:+,.2f} (removing 5 worst coins)".format(top5_loo_sum_r))
    md.append("- **LOO top 5 improvement (LIVE)**: ${:+,.2f} (removing 5 worst coins)".format(top5_loo_sum_l))
    md.append("- **Friction flips (RESEARCH)**: {}/{} coins flip to loss".format(flipped_r, len(fric_r)))
    md.append("- **Friction flips (LIVE)**: {}/{} coins flip to loss".format(flipped_l, len(fric_l)))
    md.append("")

    return md


def main():
    t_start = time.time()
    print("=" * 70)
    print("COIN ATTRIBUTION ANALYSIS")
    print("=" * 70)

    print("\n[1/6] Loading caches...")
    data_research, coins_research = load_cache(RESEARCH_CACHE)
    data_live, coins_live = load_cache(LIVE_CACHE)
    print("  RESEARCH_ALL: {} coins".format(len(coins_research)))
    print("  LIVE_CURRENT: {} coins".format(len(coins_live)))

    overlap = set(coins_research) & set(coins_live)
    only_research = sorted(set(coins_research) - set(coins_live))
    only_live = sorted(set(coins_live) - set(coins_research))
    print("  Overlap: {}, Only RESEARCH: {}, Only LIVE: {}".format(len(overlap), len(only_research), len(only_live)))

    print("\n[2/6] Running backtests...")
    bt_research, ind_research = run_bt(data_research, coins_research, CFG, label='RESEARCH_ALL')
    bt_live, ind_live = run_bt(data_live, coins_live, CFG, label='LIVE_CURRENT')

    trades_research = bt_research['trade_list']
    trades_live = bt_live['trade_list']

    print("\n[3/6] Per-coin analysis...")
    coins_r, total_pnl_r = per_coin_analysis(trades_research)
    coins_l, total_pnl_l = per_coin_analysis(trades_live)
    print("  RESEARCH_ALL: {} coins traded, total P&L ${:.2f}".format(len(coins_r), total_pnl_r))
    print("  LIVE_CURRENT: {} coins traded, total P&L ${:.2f}".format(len(coins_l), total_pnl_l))

    top_r, bottom_r = top_bottom(coins_r, 10)
    top_l, bottom_l = top_bottom(coins_l, 10)

    new_coin_trades = [t for t in trades_research if t['pair'] in set(only_research)]
    if new_coin_trades:
        new_coins_analysis, new_coins_pnl = per_coin_analysis(new_coin_trades)
        new_top, new_bottom = top_bottom(new_coins_analysis, 10)
    else:
        new_coins_analysis, new_coins_pnl = {}, 0
        new_top, new_bottom = [], []

    print("\n[4/6] Drawdown contribution analysis...")
    dd_contrib_r = compute_drawdown_contribution(trades_research)
    dd_contrib_l = compute_drawdown_contribution(trades_live)

    print("\n[5/6] Leave-one-out analysis (worst 20 coins)...")
    worst_20_r = [p for p, _ in sorted(coins_r.items(), key=lambda x: x[1]['total_pnl'])[:20]]
    worst_20_l = [p for p, _ in sorted(coins_l.items(), key=lambda x: x[1]['total_pnl'])[:20]]
    loo_r = leave_one_out_analysis(coins_research, CFG, ind_research, worst_20_r, 'RESEARCH')
    loo_l = leave_one_out_analysis(coins_live, CFG, ind_live, worst_20_l, 'LIVE')

    print("\n[6/6] Friction sensitivity analysis (top 20 most-traded)...")
    most_traded_r = sorted(coins_r.items(), key=lambda x: x[1]['trades'], reverse=True)[:20]
    most_traded_l = sorted(coins_l.items(), key=lambda x: x[1]['trades'], reverse=True)[:20]
    fric_r = friction_sensitivity(coins_research, CFG, ind_research, [p for p, _ in most_traded_r], 'RESEARCH')
    fric_l = friction_sensitivity(coins_live, CFG, ind_live, [p for p, _ in most_traded_l], 'LIVE')

    # Systemic metrics
    losing_coins_r = {p: v for p, v in coins_r.items() if v['total_pnl'] < 0}
    winning_coins_r = {p: v for p, v in coins_r.items() if v['total_pnl'] > 0}
    losing_coins_l = {p: v for p, v in coins_l.items() if v['total_pnl'] < 0}
    winning_coins_l = {p: v for p, v in coins_l.items() if v['total_pnl'] > 0}
    total_loss_r = sum(v['total_pnl'] for v in losing_coins_r.values())
    total_win_r = sum(v['total_pnl'] for v in winning_coins_r.values())
    total_loss_l = sum(v['total_pnl'] for v in losing_coins_l.values())
    total_win_l = sum(v['total_pnl'] for v in winning_coins_l.values())
    new_losing = {p: v for p, v in new_coins_analysis.items() if v['total_pnl'] < 0}
    new_loss_total = sum(v['total_pnl'] for v in new_losing.values())
    new_winning = {p: v for p, v in new_coins_analysis.items() if v['total_pnl'] > 0}
    new_win_total = sum(v['total_pnl'] for v in new_winning.values())

    elapsed = time.time() - t_start

    # Build JSON report
    report = {
        'meta': {
            'config': CFG,
            'config_label': 'C1_TPSL_RSI45',
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'runtime_seconds': round(elapsed, 1),
        },
        'research_all': {
            'summary': {
                'coins_in_universe': len(coins_research),
                'coins_traded': len(coins_r),
                'total_trades': bt_research['trades'],
                'total_pnl': round(total_pnl_r, 2),
                'win_rate': round(bt_research['wr'], 1),
                'max_dd': round(bt_research['dd'], 1),
                'winning_coins': len(winning_coins_r),
                'losing_coins': len(losing_coins_r),
                'total_win_from_winners': round(total_win_r, 2),
                'total_loss_from_losers': round(total_loss_r, 2),
            },
            'per_coin': coins_r,
            'top_10_winners': {p: v for p, v in top_r},
            'bottom_10_losers': {p: v for p, v in bottom_r},
            'dd_contribution': dd_contrib_r,
            'leave_one_out': loo_r,
            'friction_sensitivity': fric_r,
        },
        'live_current': {
            'summary': {
                'coins_in_universe': len(coins_live),
                'coins_traded': len(coins_l),
                'total_trades': bt_live['trades'],
                'total_pnl': round(total_pnl_l, 2),
                'win_rate': round(bt_live['wr'], 1),
                'max_dd': round(bt_live['dd'], 1),
                'winning_coins': len(winning_coins_l),
                'losing_coins': len(losing_coins_l),
                'total_win_from_winners': round(total_win_l, 2),
                'total_loss_from_losers': round(total_loss_l, 2),
            },
            'per_coin': coins_l,
            'top_10_winners': {p: v for p, v in top_l},
            'bottom_10_losers': {p: v for p, v in bottom_l},
            'dd_contribution': dd_contrib_l,
            'leave_one_out': loo_l,
            'friction_sensitivity': fric_l,
        },
        'new_coins': {
            'description': 'Coins in RESEARCH_ALL but NOT in LIVE_CURRENT',
            'count': len(only_research),
            'coins_traded': len(new_coins_analysis),
            'total_pnl': round(new_coins_pnl, 2),
            'winning_count': len(new_winning),
            'losing_count': len(new_losing),
            'win_pnl': round(new_win_total, 2),
            'loss_pnl': round(new_loss_total, 2),
            'top_10': {p: v for p, v in new_top} if new_top else {},
            'bottom_10': {p: v for p, v in new_bottom} if new_bottom else {},
        },
        'systemic_analysis': {
            'research_all': {
                'pct_coins_losing': round(len(losing_coins_r) / len(coins_r) * 100, 1) if coins_r else 0,
                'pct_coins_winning': round(len(winning_coins_r) / len(coins_r) * 100, 1) if coins_r else 0,
                'avg_pnl_per_coin': round(total_pnl_r / len(coins_r), 2) if coins_r else 0,
                'median_coin_pnl': round(sorted([v['total_pnl'] for v in coins_r.values()])[len(coins_r)//2], 2) if coins_r else 0,
                'new_coins_pnl_share': round(new_coins_pnl / total_pnl_r * 100, 2) if total_pnl_r != 0 else 0,
            },
            'live_current': {
                'pct_coins_losing': round(len(losing_coins_l) / len(coins_l) * 100, 1) if coins_l else 0,
                'pct_coins_winning': round(len(winning_coins_l) / len(coins_l) * 100, 1) if coins_l else 0,
                'avg_pnl_per_coin': round(total_pnl_l / len(coins_l), 2) if coins_l else 0,
                'median_coin_pnl': round(sorted([v['total_pnl'] for v in coins_l.values()])[len(coins_l)//2], 2) if coins_l else 0,
            },
        },
    }

    json_path = REPORTS_DIR / 'coin_attribution.json'
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2)
    print("\n  Saved: {}".format(json_path))

    # Build and save markdown
    md = build_markdown(report, top_r, bottom_r, top_l, bottom_l,
                        new_top, new_bottom, only_research, new_coins_pnl,
                        loo_r, loo_l, fric_r, fric_l, elapsed,
                        coins_l, total_pnl_r)

    md_path = REPORTS_DIR / 'coin_attribution.md'
    with open(md_path, 'w') as f:
        f.write('\n'.join(md))
    print("  Saved: {}".format(md_path))

    print("\n" + "=" * 70)
    print("DONE in {:.0f}s".format(elapsed))
    print("=" * 70)


if __name__ == '__main__':
    main()
