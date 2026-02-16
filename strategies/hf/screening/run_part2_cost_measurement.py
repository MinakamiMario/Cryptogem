#!/usr/bin/env python3
"""
Part 2: Execution Cost Measurement (P0-B)
==========================================
Agent P0-B: Measure real execution costs from candle data and compare
with Kaiko-calibrated v2 model.

Steps:
  1. Baseline backtest -> trade list
  2. Per-trade cost measurement from candle data (spread, slippage, fill-rate)
  3. Cost distribution per tier (P10-P99)
  4. Calm vs volatile split (ATR-based)
  5. Comparison with v2 model
  6. Trade-size sensitivity ($100-$2000)
  7. Re-run backtest with measured P50 and P90 fees -> gate evaluation
  8. Coin flip-list (winners that flip to losers under measured costs)
  9. Breakeven analysis (at what fee multiplier does the strategy break?)

Output:
  reports/hf/part2_cost_measurement.json
  reports/hf/part2_cost_measurement.md

Usage:
    cd /Users/oussama/Cryptogem && python strategies/hf/screening/run_part2_cost_measurement.py
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import (
    get_harness_fee, COST_REGIMES, get_cost_breakdown,
)
from strategies.hf.screening.costs_mexc_v3 import (
    estimate_trade_cost, build_cost_table, summarize_cost_table,
    get_calibrated_regime,
)

BARS_PER_WEEK = 168
BARS_PER_DAY = 24
BASELINE_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}
EXCLUDED_21 = {
    'AI3/USD','ALKIMI/USD','ANIME/USD','CFG/USD','DBR/USD','ESX/USD','GST/USD',
    'HOUSE/USD','KET/USD','LMWR/USD','MXC/USD','ODOS/USD','PERP/USD','PNUT/USD',
    'POLIS/USD','RARI/USD','SUKU/USD','TANSSI/USD','TITCOIN/USD','TOSHI/USD','WMTX/USD',
}
TRADE_SIZES = [100, 200, 500, 1000, 2000]

# ============================================================
# Data Loading (from run_part2_exec_realism_002.py)
# ============================================================
def load_candle_cache(timeframe='1h', require_data=False):
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if cache_path.exists():
        print(f'[Load] Reading {cache_path.name}...')
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
        print(f'[Load] {len(coins_data)} coins loaded (merged cache)')
        return coins_data
    parts_base = ROOT / 'data' / 'cache_parts_hf' / timeframe
    if not parts_base.exists():
        if require_data:
            print('[ERROR] No cache found'); sys.exit(1)
        return None
    print('[Load] Loading from per-coin parts...')
    manifest_path = ROOT / 'data' / f'manifest_hf_{timeframe}.json'
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir(): continue
        for coin_file in sorted(exchange_dir.glob('*.json')):
            symbol = coin_file.stem.replace('_', '/')
            if manifest and symbol in manifest:
                if manifest[symbol].get('status') != 'done': continue
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
    if not coins_data:
        if require_data: sys.exit(1)
        return None
    print(f'[Load] {len(coins_data)} coins loaded (from part files)')
    return coins_data

def load_universe_tiering(require_data=False):
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        if require_data:
            print(f'[ERROR] Tiering not found: {path}'); sys.exit(1)
        return None
    with open(path) as f:
        return json.load(f)

def build_tier_coins(tiering, available_coins):
    tier_coins = {'tier1': [], 'tier2': []}
    tb = tiering.get('tier_breakdown', {})
    if tb:
        for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
            if tier_num in tb:
                coins = tb[tier_num].get('coins', [])
                tier_coins[tier_key] = [c for c in coins if c in available_coins]
        if tier_coins['tier1'] or tier_coins['tier2']:
            return tier_coins
    tiers = tiering.get('tiers', {})
    for tkn in ['tier_1', 'Tier 1 (Liquid)', 'tier1', '1']:
        if tkn in tiers:
            tier_coins['tier1'] = [c for c in tiers[tkn].get('coins', []) if c in available_coins]; break
    for tkn in ['tier_2', 'Tier 2 (Mid)', 'tier2', '2']:
        if tkn in tiers:
            tier_coins['tier2'] = [c for c in tiers[tkn].get('coins', []) if c in available_coins]; break
    return tier_coins

# ============================================================
# Metrics (from run_part2_exec_realism_002.py)
# ============================================================
def compute_metrics(trades, total_bars, initial_capital=2000.0):
    n = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n == 0:
        return dict(trades=0, pnl=0.0, pf=0.0, wr=0.0, dd=0.0,
                    expectancy=0.0, trades_per_week=0.0, exp_per_week=0.0, fee_drag_pct=0.0)
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n
    tpw = n / total_weeks
    epw = expectancy * tpw
    total_fees = 0.0; gross_profit = 0.0
    for t in trades:
        size = t.get('size', 0); entry = t.get('entry', 0); exit_p = t.get('exit', 0)
        tfee = t.get('_fee_per_side', 0.00125)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * tfee + (size + gross) * tfee
            total_fees += fees
            if gross > 0: gross_profit += gross
    fee_drag = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
    equity = initial_capital; peak = equity; max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get('entry_bar', 0)):
        equity += t['pnl']
        if equity > peak: peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    return dict(trades=n, pnl=round(total_pnl, 2), pf=round(pf, 3), wr=round(wr, 1),
                dd=round(max_dd, 1), expectancy=round(expectancy, 4),
                trades_per_week=round(tpw, 2), exp_per_week=round(epw, 4),
                fee_drag_pct=round(fee_drag, 1))

def compute_max_gap(trades, total_bars):
    if len(trades) < 2:
        return total_bars / BARS_PER_DAY if total_bars > 0 else 999.0, 999.0
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    mg = st[0].get('entry_bar', 50) - 50
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i-1].get('exit_bar', 0)
        if g > mg: mg = g
    eg = total_bars - st[-1].get('exit_bar', 0)
    if eg > mg: mg = eg
    return mg, round(mg / BARS_PER_DAY, 2)

def evaluate_gates(metrics, stress_metrics, wf_folds_positive, max_gap_days, top1_fold_conc):
    gates = {
        'G1_trades_per_week': {'value': round(metrics['trades_per_week'], 2), 'threshold': '>=10/wk', 'pass': metrics['trades_per_week'] >= 10},
        'G2_max_gap_days': {'value': max_gap_days, 'threshold': '<=2.5d', 'pass': max_gap_days <= 2.5},
        'G3_exp_per_week': {'value': round(metrics['exp_per_week'], 4), 'threshold': '>$0', 'pass': metrics['exp_per_week'] > 0},
        'G4_stress_exp_per_week': {'value': round(stress_metrics['exp_per_week'], 4), 'threshold': '>$0 (stress 2x)', 'pass': stress_metrics['exp_per_week'] > 0},
        'G5_max_dd_pct': {'value': round(metrics['dd'], 1), 'threshold': '<=20%', 'pass': metrics['dd'] <= 20},
        'G6_wf_folds_positive': {'value': wf_folds_positive, 'threshold': '>=4/5', 'pass': wf_folds_positive >= 4},
        'G8_top1_fold_conc': {'value': round(top1_fold_conc, 4), 'threshold': '<0.35', 'pass': top1_fold_conc < 0.35},
    }
    all_pass = all(g['pass'] for g in gates.values())
    failed = [k for k, g in gates.items() if not g['pass']]
    passed = [k for k, g in gates.items() if g['pass']]
    return gates, all_pass, failed, passed

def compute_fold_concentration(fold_pnls):
    positive_pnls = [max(0, p) for p in fold_pnls]
    total_pos = sum(positive_pnls)
    if total_pos <= 0: return 1.0
    return max(positive_pnls) / total_pos

# ============================================================
# Combined backtest runners
# ============================================================
def run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee, t2_fee, params):
    enriched = {**params, '__market__': market_ctx}
    all_trades = []
    if t1_coins:
        bt = run_backtest(data=data, coins=t1_coins, signal_fn=signal_h20_vwap_deviation, params=enriched, indicators=t1_indicators, fee=t1_fee, max_pos=1)
        for t in bt.trade_list: t['_tier'] = 'tier1'; t['_fee_per_side'] = t1_fee
        all_trades.extend(bt.trade_list)
    if t2_coins:
        bt = run_backtest(data=data, coins=t2_coins, signal_fn=signal_h20_vwap_deviation, params=enriched, indicators=t2_indicators, fee=t2_fee, max_pos=1)
        for t in bt.trade_list: t['_tier'] = 'tier2'; t['_fee_per_side'] = t2_fee
        all_trades.extend(bt.trade_list)
    return all_trades

def run_combined_wf(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee, t2_fee, params, n_folds=5):
    enriched = {**params, '__market__': market_ctx}
    fold_trades = {}
    for tier_key, coins, indicators, fee in [('tier1', t1_coins, t1_indicators, t1_fee), ('tier2', t2_coins, t2_indicators, t2_fee)]:
        if not coins: continue
        results = walk_forward(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation, params=enriched, indicators=indicators, n_folds=n_folds, fee=fee, max_pos=1)
        for idx, fold_bt in enumerate(results):
            if idx not in fold_trades: fold_trades[idx] = []
            for t in fold_bt.trade_list: t['_tier'] = tier_key; t['_fee_per_side'] = fee
            fold_trades[idx].extend(fold_bt.trade_list)
    return fold_trades

def full_gate_eval(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee, t2_fee, total_bars, label):
    print(f'  [{label}] Running baseline (T1={t1_fee*10000:.1f}bps, T2={t2_fee*10000:.1f}bps)...')
    trades = run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee, t2_fee, BASELINE_PARAMS)
    m = compute_metrics(trades, total_bars)
    _, max_gap_days = compute_max_gap(trades, total_bars)
    stress_trades = run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee*2, t2_fee*2, BASELINE_PARAMS)
    sm = compute_metrics(stress_trades, total_bars)
    fold_trades = run_combined_wf(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_ctx, t1_fee, t2_fee, BASELINE_PARAMS, n_folds=5)
    wf_folds_positive = 0; fold_pnls = []; fold_details = []
    for fi in sorted(fold_trades.keys()):
        fpnl = sum(t['pnl'] for t in fold_trades[fi]); fn = len(fold_trades[fi]); pos = fpnl > 0
        if pos: wf_folds_positive += 1
        fold_pnls.append(fpnl)
        fold_details.append({'fold': fi, 'trades': fn, 'pnl': round(fpnl, 2), 'positive': pos})
    top1_conc = compute_fold_concentration(fold_pnls) if fold_pnls else 1.0
    gates, all_pass, failed, passed_g = evaluate_gates(m, sm, wf_folds_positive, max_gap_days, top1_conc)
    gate_count = sum(1 for g in gates.values() if g['pass'])
    print(f'    {m["trades"]}tr PF={m["pf"]:.3f} Exp/wk=${m["exp_per_week"]:.2f} WF={wf_folds_positive}/5 Gates={gate_count}/{len(gates)} {"PASS" if all_pass else "FAIL: "+",".join(failed)}')
    return {'label': label, 'fees': {'t1_bps': round(t1_fee*10000, 1), 't2_bps': round(t2_fee*10000, 1)},
            'baseline': m, 'stress_2x': {'trades': sm['trades'], 'pnl': sm['pnl'], 'pf': sm['pf'], 'exp_per_week': sm['exp_per_week'], 'dd': sm['dd']},
            'walk_forward': {'folds_positive': wf_folds_positive, 'fold_details': fold_details, 'top1_fold_conc': round(top1_conc, 4)},
            'max_gap_days': max_gap_days, 'gates': gates, 'all_gates_pass': all_pass,
            'gates_passed': gate_count, 'gates_total': len(gates), 'failed_gates': failed}

# ============================================================
# Markdown report
# ============================================================
def build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks):
    md = []
    md.append('# Part 2: Execution Cost Measurement (P0-B)\n')
    md.append(f'**Datum**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Agent**: P0-B | **Commit**: {commit}')
    md.append(f'**Universum**: T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins (excl 21 net-negative)')
    md.append(f'**Signaal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weken) | **Runtime**: {elapsed:.1f}s\n')
    md.append('## Doel\n')
    md.append('Meet echte all-in execution costs per trade uit candle data en vergelijk')
    md.append('met het Kaiko-gekalibreerde v2 model.\n')

    bl = report.get('baseline_summary', {})
    md.append('## 1. Baseline Backtest\n')
    md.append(f'- Trades: {bl.get("trades",0)} | P&L: ${bl.get("pnl",0):.2f} | PF: {bl.get("pf",0):.3f} | WR: {bl.get("wr",0):.1f}% | Exp/wk: ${bl.get("exp_per_week",0):.2f}\n')

    md.append('## 2. Gemeten Cost Distributie ($200 trade size)\n')
    summary = report.get('cost_summary', {})
    for tier_label in ['all', 'tier1', 'tier2']:
        td = summary.get(tier_label, {})
        if not td: continue
        md.append(f'### {tier_label.upper()} ({td.get("n_trades",0)} trades)\n')
        md.append('| Component | P10 | P25 | P50 | P75 | P90 | P95 | P99 | Mean |')
        md.append('|-----------|-----|-----|-----|-----|-----|-----|-----|------|')
        for comp in ['spread_bps', 'slippage_bps', 'total_per_side_bps', 'fill_rate', 'bar_volume_usd']:
            pcts = td.get(comp, {})
            if not pcts: continue
            row = f'| {comp} '
            for p in ['P10','P25','P50','P75','P90','P95','P99','mean']:
                row += f'| {pcts.get(p,"-")} '
            md.append(row + '|')
        md.append('')

    md.append('## 3. Calm vs Volatile Split\n')
    cv = report.get('calm_vs_volatile', {})
    for lbl in ['calm', 'volatile']:
        rd = cv.get(lbl, {})
        if not rd: continue
        md.append(f'### {lbl.upper()} ({rd.get("n_trades",0)} trades)\n')
        md.append(f'- Spread: {rd.get("mean_spread_bps",0):.1f} bps | Slippage: {rd.get("mean_slippage_bps",0):.1f} bps | Total: {rd.get("mean_total_bps",0):.1f} bps | Fill: {rd.get("mean_fill_rate",0):.3f}\n')

    md.append('## 4. v3 (gemeten) vs v2 (Kaiko-calibrated)\n')
    comp = report.get('v2_comparison', {})
    md.append('| Component | v2 T1 | v3 T1 P50 | Delta | v2 T2 | v3 T2 P50 | Delta |')
    md.append('|-----------|-------|-----------|-------|-------|-----------|-------|')
    for key in ['spread_bps', 'slippage_bps', 'exchange_fee_bps', 'total_per_side_bps']:
        v2t1 = comp.get('v2_tier1',{}).get(key,0); v3t1 = comp.get('v3_tier1_p50',{}).get(key,0)
        v2t2 = comp.get('v2_tier2',{}).get(key,0); v3t2 = comp.get('v3_tier2_p50',{}).get(key,0)
        md.append(f'| {key} | {v2t1:.1f} | {v3t1:.1f} | {v3t1-v2t1:+.1f} | {v2t2:.1f} | {v3t2:.1f} | {v3t2-v2t2:+.1f} |')
    md.append('')

    md.append('## 5. Trade-Size Sensitivity\n')
    ts = report.get('trade_size_sensitivity', {})
    md.append('| Size | P50 Spread | P50 Slippage | P50 Total/Side | P50 Fill Rate |')
    md.append('|------|-----------|--------------|----------------|---------------|')
    for sz_str, sz_data in sorted(ts.items(), key=lambda x: int(x[0].replace('$',''))):
        s = sz_data.get('all', {})
        md.append(f'| {sz_str} | {s.get("spread_bps",{}).get("P50","-")} | {s.get("slippage_bps",{}).get("P50","-")} | {s.get("total_per_side_bps",{}).get("P50","-")} | {s.get("fill_rate",{}).get("P50","-")} |')
    md.append('')

    md.append('## 6. Gate Evaluatie met Gemeten Fees\n')
    grs = report.get('gate_evaluations', [])
    md.append('| Regime | T1 bps | T2 bps | Trades | PF | Exp/Wk | WF | Gates |')
    md.append('|--------|--------|--------|--------|----|--------|----|----|')
    for gr in grs:
        m = gr['baseline']; wf = gr.get('walk_forward',{}); fees = gr.get('fees',{})
        gp = gr.get('gates_passed',0); gt = gr.get('gates_total',0); ap = gr.get('all_gates_pass',False)
        gs = f'**{gp}/{gt} PASS**' if ap else f'{gp}/{gt} FAIL'
        md.append(f'| {gr["label"]} | {fees.get("t1_bps","-")} | {fees.get("t2_bps","-")} | {m["trades"]} | {m["pf"]:.3f} | ${m["exp_per_week"]:.2f} | {wf.get("folds_positive",0)}/5 | {gs} |')
    md.append('')
    for gr in grs:
        md.append(f'### {gr["label"]}\n')
        md.append('| Gate | Waarde | Drempel | Verdict |')
        md.append('|------|--------|---------|---------|')
        for gn, gi in gr['gates'].items():
            md.append(f'| {gn} | {gi["value"]} | {gi["threshold"]} | {"PASS" if gi["pass"] else "**FAIL**"} |')
        md.append('')

    md.append('## 7. Coin Flip-List\n')
    flips = report.get('flip_list', [])
    if flips:
        md.append(f'{len(flips)} trades flippen van winnaar naar verliezer:\n')
        md.append('| Pair | Bar | v2 PnL | Cost/Side | Adj PnL | Reden |')
        md.append('|------|-----|--------|-----------|---------|-------|')
        for fl in flips[:20]:
            md.append(f'| {fl["pair"]} | {fl["entry_bar"]} | ${fl["v2_pnl"]:.2f} | {fl["measured_total_bps"]:.1f}bps | ${fl["adj_pnl"]:.2f} | {fl["reason"]} |')
        if len(flips) > 20: md.append(f'| ... +{len(flips)-20} meer | | | | | |')
    else:
        md.append('Geen trades flippen.')
    md.append('')

    md.append('## 8. Breakeven Analyse\n')
    be = report.get('breakeven', {})
    md.append(f'Breakeven fee multiplier: **{be.get("breakeven_multiplier","N/A")}x**\n')
    md.append('| Mult | T1 bps | T2 bps | Trades | PF | Exp/Wk | OK? |')
    md.append('|------|--------|--------|--------|----|--------|-----|')
    for step in be.get('steps', []):
        md.append(f'| {step["multiplier"]:.1f}x | {step["t1_bps"]:.1f} | {step["t2_bps"]:.1f} | {step["trades"]} | {step["pf"]:.3f} | ${step["exp_per_week"]:.2f} | {"Ja" if step["exp_per_week"]>0 else "**Nee**"} |')
    md.append('')

    md.append('## Verdict\n')
    for line in report.get('verdict_lines', []):
        md.append(line)
    md.append(f'\n---\n*Gegenereerd op {datetime.now().strftime("%Y-%m-%d %H:%M")}*')
    return '\n'.join(md)

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Part 2: Execution Cost Measurement (P0-B)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Part 2: Execution Cost Measurement (P0-B)')
    print('  Candle-derived cost proxies vs Kaiko v2 model')
    print(sep)
    t0 = time.time()

    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT)).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None: sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None: sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_21],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_21],
    }
    n_t1 = len(tier_coins['tier1']); n_t2 = len(tier_coins['tier2'])
    print(f'[Universe] T1({n_t1}) + T2({n_t2}) = {n_t1+n_t2} coins')
    if args.dry_run: print('--- DRY RUN ---'); sys.exit(0)

    print('[Indicators] Precomputing...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])

    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available_coins and btc not in all_coins: all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)

    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict: ind_dict[coin]['__coin__'] = coin

    total_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > total_bars: total_bars = n
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    t1_indicators = tier_indicators.get('tier1', {}); t2_indicators = tier_indicators.get('tier2', {})
    t1_coins = tier_coins['tier1']; t2_coins = tier_coins['tier2']

    # === STEP 1: Baseline ===
    print(f'\n{sep}\n  STEP 1: Baseline Backtest (v2 P50 fees)\n{sep}')
    t1_fee_v2 = get_harness_fee('mexc_market', 'tier1')
    t2_fee_v2 = get_harness_fee('mexc_market', 'tier2')
    print(f'  v2 fees: T1={t1_fee_v2*10000:.1f}bps, T2={t2_fee_v2*10000:.1f}bps')
    baseline_trades = run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_context, t1_fee_v2, t2_fee_v2, BASELINE_PARAMS)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'  Baseline: {baseline_metrics["trades"]}tr PF={baseline_metrics["pf"]:.3f} P&L=${baseline_metrics["pnl"]:.0f} Exp/wk=${baseline_metrics["exp_per_week"]:.2f}')

    # === STEP 2: Per-trade cost measurement ===
    print(f'\n{sep}\n  STEP 2: Per-Trade Cost Measurement ($200)\n{sep}')
    cost_table = build_cost_table(data, baseline_trades, trade_size=200.0)
    cost_summary = summarize_cost_table(cost_table, by_tier=True)
    for tl in ['all', 'tier1', 'tier2']:
        td = cost_summary.get(tl, {})
        if td:
            print(f'  {tl}: spread_P50={td.get("spread_bps",{}).get("P50","-")}bps slip_P50={td.get("slippage_bps",{}).get("P50","-")}bps total_P50={td.get("total_per_side_bps",{}).get("P50","-")}bps fill_P50={td.get("fill_rate",{}).get("P50","-")}')
    calibrated = get_calibrated_regime(cost_table)
    print(f'  Calibrated P50: T1={calibrated["measured_p50"]["tier1"]["total_per_side_bps"]}bps T2={calibrated["measured_p50"]["tier2"]["total_per_side_bps"]}bps')
    print(f'  Calibrated P90: T1={calibrated["measured_p90"]["tier1"]["total_per_side_bps"]}bps T2={calibrated["measured_p90"]["tier2"]["total_per_side_bps"]}bps')

    # === STEP 3: Calm vs Volatile ===
    print(f'\n{sep}\n  STEP 3: Calm vs Volatile Split\n{sep}')
    atr_values = [c['bar_atr'] for c in cost_table if c['bar_atr'] is not None]
    median_atr = sorted(atr_values)[len(atr_values)//2] if atr_values else 0.0
    calm_trades = [c for c in cost_table if c['bar_atr'] is not None and c['bar_atr'] < median_atr]
    volatile_trades = [c for c in cost_table if c['bar_atr'] is not None and c['bar_atr'] >= median_atr]
    def _mean_of(rows, key):
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0
    calm_stats = {'n_trades': len(calm_trades), 'mean_spread_bps': round(_mean_of(calm_trades, 'spread_bps'), 1), 'mean_slippage_bps': round(_mean_of(calm_trades, 'slippage_bps'), 1), 'mean_total_bps': round(_mean_of(calm_trades, 'total_per_side_bps'), 1), 'mean_fill_rate': round(_mean_of(calm_trades, 'fill_rate'), 3)}
    volatile_stats = {'n_trades': len(volatile_trades), 'mean_spread_bps': round(_mean_of(volatile_trades, 'spread_bps'), 1), 'mean_slippage_bps': round(_mean_of(volatile_trades, 'slippage_bps'), 1), 'mean_total_bps': round(_mean_of(volatile_trades, 'total_per_side_bps'), 1), 'mean_fill_rate': round(_mean_of(volatile_trades, 'fill_rate'), 3)}
    print(f'  Median ATR: {median_atr:.6f}')
    print(f'  Calm ({calm_stats["n_trades"]}tr): total={calm_stats["mean_total_bps"]}bps')
    print(f'  Volatile ({volatile_stats["n_trades"]}tr): total={volatile_stats["mean_total_bps"]}bps')

    # === STEP 4: v2 comparison ===
    print(f'\n{sep}\n  STEP 4: v3 vs v2 Comparison\n{sep}')
    v2_t1 = get_cost_breakdown('mexc_market', 'tier1')
    v2_t2 = get_cost_breakdown('mexc_market', 'tier2')
    v3_t1_p50 = {'spread_bps': cost_summary.get('tier1',{}).get('spread_bps',{}).get('P50',0), 'slippage_bps': cost_summary.get('tier1',{}).get('slippage_bps',{}).get('P50',0), 'exchange_fee_bps': 10.0, 'total_per_side_bps': cost_summary.get('tier1',{}).get('total_per_side_bps',{}).get('P50',0)}
    v3_t2_p50 = {'spread_bps': cost_summary.get('tier2',{}).get('spread_bps',{}).get('P50',0), 'slippage_bps': cost_summary.get('tier2',{}).get('slippage_bps',{}).get('P50',0), 'exchange_fee_bps': 10.0, 'total_per_side_bps': cost_summary.get('tier2',{}).get('total_per_side_bps',{}).get('P50',0)}
    for ck in ['spread_bps', 'slippage_bps', 'total_per_side_bps']:
        print(f'  {ck}: T1 v2={v2_t1.get(ck,0):.1f} v3={v3_t1_p50.get(ck,0):.1f} ({v3_t1_p50.get(ck,0)-v2_t1.get(ck,0):+.1f}) | T2 v2={v2_t2.get(ck,0):.1f} v3={v3_t2_p50.get(ck,0):.1f} ({v3_t2_p50.get(ck,0)-v2_t2.get(ck,0):+.1f})')

    # === STEP 5: Trade-size sensitivity ===
    print(f'\n{sep}\n  STEP 5: Trade-Size Sensitivity\n{sep}')
    trade_size_results = {}
    for sz in TRADE_SIZES:
        ct = build_cost_table(data, baseline_trades, trade_size=float(sz))
        cs = summarize_cost_table(ct, by_tier=True)
        trade_size_results[f'${sz}'] = cs
        print(f'  ${sz}: total_P50={cs.get("all",{}).get("total_per_side_bps",{}).get("P50","-")}bps fill_P50={cs.get("all",{}).get("fill_rate",{}).get("P50","-")}')

    # === STEP 6: Gate evaluation ===
    print(f'\n{sep}\n  STEP 6: Gate Evaluation with Measured Fees\n{sep}')
    gate_evaluations = []
    r_v2 = full_gate_eval(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_context, t1_fee_v2, t2_fee_v2, total_bars, 'v2_baseline_p50')
    gate_evaluations.append(r_v2)
    mp50 = calibrated['measured_p50']
    t1_fee_mp50 = mp50['tier1']['total_per_side_bps'] / 10000; t2_fee_mp50 = mp50['tier2']['total_per_side_bps'] / 10000
    r_mp50 = full_gate_eval(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_context, t1_fee_mp50, t2_fee_mp50, total_bars, 'measured_p50')
    gate_evaluations.append(r_mp50)
    mp90 = calibrated['measured_p90']
    t1_fee_mp90 = mp90['tier1']['total_per_side_bps'] / 10000; t2_fee_mp90 = mp90['tier2']['total_per_side_bps'] / 10000
    r_mp90 = full_gate_eval(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_context, t1_fee_mp90, t2_fee_mp90, total_bars, 'measured_p90')
    gate_evaluations.append(r_mp90)

    # === STEP 7: Flip list ===
    print(f'\n{sep}\n  STEP 7: Coin Flip List\n{sep}')
    flip_list = []
    for i, trade in enumerate(baseline_trades):
        ct_entry = cost_table[i] if i < len(cost_table) else None
        if ct_entry is None: continue
        if trade['pnl'] <= 0: continue
        size = trade.get('size', 200); entry_p = trade.get('entry', 0); exit_p = trade.get('exit', 0)
        if entry_p <= 0: continue
        gross = (exit_p - entry_p) / entry_p * size
        mps = ct_entry['total_per_side_bps'] / 10000
        fees_v3 = size * mps + (size + gross) * mps
        adj_pnl = gross - fees_v3
        if adj_pnl <= 0:
            flip_list.append({'pair': trade['pair'], 'entry_bar': trade.get('entry_bar',0), 'v2_pnl': round(trade['pnl'],2), 'gross_pnl': round(gross,2), 'measured_total_bps': ct_entry['total_per_side_bps'], 'adj_pnl': round(adj_pnl,2), 'reason': trade.get('reason',''), 'tier': trade.get('_tier','')})
    print(f'  {len(flip_list)} trades flip van winnaar naar verliezer')

    # === STEP 8: Breakeven ===
    print(f'\n{sep}\n  STEP 8: Breakeven Analyse\n{sep}')
    breakeven_steps = []; breakeven_mult = None
    for mult_10x in range(10, 100, 5):
        mult = mult_10x / 10.0
        t1_be = t1_fee_v2 * mult; t2_be = t2_fee_v2 * mult
        be_trades = run_combined(data, t1_coins, t2_coins, t1_indicators, t2_indicators, market_context, t1_be, t2_be, BASELINE_PARAMS)
        be_m = compute_metrics(be_trades, total_bars)
        step = {'multiplier': mult, 't1_bps': round(t1_be*10000,1), 't2_bps': round(t2_be*10000,1), 'trades': be_m['trades'], 'pf': be_m['pf'], 'exp_per_week': be_m['exp_per_week'], 'profitable': be_m['exp_per_week'] > 0}
        breakeven_steps.append(step)
        if be_m['exp_per_week'] <= 0 and breakeven_mult is None: breakeven_mult = mult
        print(f'  {mult:.1f}x: T1={step["t1_bps"]:.0f}bps T2={step["t2_bps"]:.0f}bps PF={be_m["pf"]:.3f} Exp/wk=${be_m["exp_per_week"]:.2f} {"BREAK" if be_m["exp_per_week"] <= 0 else "OK"}')
        if be_m['exp_per_week'] <= 0: break
    breakeven_info = {'breakeven_multiplier': breakeven_mult if breakeven_mult else '>9.5', 'breakeven_epw': 0.0, 'steps': breakeven_steps}

    elapsed = time.time() - t0

    # === Verdict ===
    verdict_lines = []
    v3_total_t2_p50 = v3_t2_p50.get('total_per_side_bps', 0)
    v2_total_t2 = v2_t2.get('total_per_side_bps', 0)
    direction = 'HOGER' if v3_total_t2_p50 > v2_total_t2 else 'LAGER'
    delta_pct = ((v3_total_t2_p50 / v2_total_t2) - 1) * 100 if v2_total_t2 > 0 else 0
    verdict_lines.append(f'**v3 gemeten costs zijn {direction} dan v2 Kaiko-model** ({delta_pct:+.0f}%)')
    verdict_lines.append(f'  - v2 T2 total: {v2_total_t2:.1f} bps/side')
    verdict_lines.append(f'  - v3 T2 P50:   {v3_total_t2_p50:.1f} bps/side')
    verdict_lines.append('')
    for gr in gate_evaluations:
        status = 'PASS' if gr['all_gates_pass'] else f'FAIL ({",".join(gr["failed_gates"])})'
        verdict_lines.append(f'- {gr["label"]}: {gr["gates_passed"]}/{gr["gates_total"]} gates {status}')
    verdict_lines.append('')
    verdict_lines.append(f'**Breakeven fee multiplier**: {breakeven_info["breakeven_multiplier"]}x')
    verdict_lines.append(f'**Coin flips**: {len(flip_list)} trades veranderen van winnaar naar verliezer')
    verdict_lines.append('')
    mp50_pass = r_mp50.get('all_gates_pass', False); mp90_pass = r_mp90.get('all_gates_pass', False)
    if mp50_pass and mp90_pass:
        verdict_lines.append('**CONCLUSIE**: Strategie overleeft zowel gemeten P50 als P90 costs. Execution costs zijn GEEN risico.')
    elif mp50_pass:
        verdict_lines.append('**CONCLUSIE**: Strategie overleeft gemeten P50 costs maar NIET P90. Execution costs zijn een MATIG risico.')
    else:
        verdict_lines.append('**CONCLUSIE**: Strategie faalt zelfs bij gemeten P50 costs. Execution costs zijn een HOOG risico.')

    # === Build report ===
    report = {
        'run_header': {'task': 'part2_cost_measurement', 'agent': 'P0-B', 'date': datetime.now().strftime('%Y-%m-%d %H:%M'), 'commit': commit, 'hypothesis': 'H20_VWAP_DEVIATION', 'baseline': 'v5 (dev=2.0, tp=8, sl=5, tl=10)', 'universe': f'T1({n_t1})+T2({n_t2})', 'total_bars': total_bars, 'total_weeks': round(total_weeks, 1), 'runtime_s': round(elapsed, 1)},
        'baseline_summary': baseline_metrics,
        'cost_summary': cost_summary,
        'calibrated_regimes': calibrated,
        'calm_vs_volatile': {'median_atr': median_atr, 'calm': calm_stats, 'volatile': volatile_stats},
        'v2_comparison': {'v2_tier1': {k: v2_t1.get(k, 0) for k in ['spread_bps','slippage_bps','exchange_fee_bps','total_per_side_bps']}, 'v2_tier2': {k: v2_t2.get(k, 0) for k in ['spread_bps','slippage_bps','exchange_fee_bps','total_per_side_bps']}, 'v3_tier1_p50': v3_t1_p50, 'v3_tier2_p50': v3_t2_p50},
        'trade_size_sensitivity': trade_size_results,
        'gate_evaluations': gate_evaluations,
        'flip_list': flip_list,
        'breakeven': breakeven_info,
        'verdict_lines': verdict_lines,
    }

    out_dir = ROOT / 'reports' / 'hf'; out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / 'part2_cost_measurement.json'
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')
    md_text = build_md(report, elapsed, commit, n_t1, n_t2, total_bars, total_weeks)
    md_path = out_dir / 'part2_cost_measurement.md'
    md_path.write_text(md_text)
    print(f'[Report] MD:   {md_path}')

    print(f'\n{sep}\n  COST MEASUREMENT COMPLETE\n{sep}')
    for line in verdict_lines:
        if line: print(f'  {line}')
    print(f'\n  Runtime: {elapsed:.1f}s\n{sep}')

if __name__ == '__main__':
    main()
