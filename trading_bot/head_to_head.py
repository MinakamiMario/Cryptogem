#!/usr/bin/env python3
"""
Head-to-Head Validatie: TP7/SL5/TM10 vs Champion TP15/SL15/TM15

Draait na de 5-run multi-run test. Vergelijkt twee configs op:
  1. Walk-Forward (5 folds, leakage-safe precompute)
  2. Monte Carlo block bootstrap (10.000 sims)
  3. Coin-subsample MC (seeds 42-46, zelfde als multi-run)
  4. Friction stress (1x / 1.5x / 2x fees + slippage)

Usage:
  python3 trading_bot/head_to_head.py
"""

import json
import sys
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from strategy import calc_rsi, calc_donchian, calc_bollinger, calc_atr

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
RESULTS_FILE = BASE_DIR / 'head_to_head_results.json'
INITIAL_CAPITAL = 2000
START_BAR = 21

# === CONFIGS TO COMPARE ===
CHALLENGER = {
    'label': 'TP7_SL5_TM10',
    'cfg': {
        'exit_type': 'tp_sl',
        'rsi_max': 45,
        'vol_spike_mult': 3.0,
        'vol_confirm': True,
        'tp_pct': 7,
        'sl_pct': 5,
        'tm_bars': 10,
        'max_pos': 1,
    }
}

CHAMPION = {
    'label': 'CHAMPION_TP15_SL15',
    'cfg': {
        'exit_type': 'tp_sl',
        'rsi_max': 45,
        'vol_spike_mult': 3.0,
        'vol_confirm': True,
        'tp_pct': 15,
        'sl_pct': 15,
        'tm_bars': 15,
        'max_pos': 1,
    }
}

COIN_SEEDS = [42, 43, 44, 45, 46]  # zelfde als multi-run

# ============================================================
# PRECOMPUTE
# ============================================================
def precompute_all(data, coins):
    """Precompute indicators voor alle coins."""
    indicators = {}
    for coin in coins:
        bars = data[coin]
        if len(bars) < 30:
            continue
        closes = [b['close'] for b in bars]
        highs = [b['high'] for b in bars]
        lows = [b['low'] for b in bars]
        volumes = [b['volume'] for b in bars]

        n = len(closes)

        # RSI
        rsi_arr = [None] * n
        for i in range(14, n):
            rsi_arr[i] = calc_rsi(closes[:i+1])

        # Donchian lower
        dc_low = [None] * n
        for i in range(20, n):
            _, ll, _ = calc_donchian(highs[:i+1], lows[:i+1])
            dc_low[i] = ll

        # Bollinger lower
        bb_low = [None] * n
        for i in range(20, n):
            _, _, bl = calc_bollinger(closes[:i+1])
            bb_low[i] = bl

        # Volume SMA
        vol_sma = [None] * n
        for i in range(20, n):
            vol_sma[i] = sum(volumes[i-20:i]) / 20

        indicators[coin] = {
            'closes': closes, 'highs': highs, 'lows': lows, 'volumes': volumes,
            'rsi': rsi_arr, 'dc_low': dc_low, 'bb_low': bb_low, 'vol_sma': vol_sma,
            'n': n
        }
    return indicators


# ============================================================
# BACKTEST ENGINE
# ============================================================
def run_backtest(indicators, coins, cfg, start_bar=START_BAR, end_bar=None,
                 fee_mult=1.0, slippage_pct=0.0):
    """Run backtest met TP/SL exit type. Ondersteunt friction multiplier + slippage."""
    base_fee_pct = 0.26  # Kraken fee per side
    fee_pct = base_fee_pct * fee_mult
    total_fee_pct = fee_pct * 2 + slippage_pct  # round-trip fees + slippage

    tp_pct = cfg.get('tp_pct', 15)
    sl_pct = cfg.get('sl_pct', 15)
    tm_bars = cfg.get('tm_bars', 15)
    rsi_max = cfg.get('rsi_max', 45)
    vol_spike_mult = cfg.get('vol_spike_mult', 3.0)
    vol_confirm = cfg.get('vol_confirm', True)

    trades = []

    for coin in coins:
        if coin not in indicators:
            continue
        ind = indicators[coin]
        closes = ind['closes']
        lows = ind['lows']
        volumes = ind['volumes']
        rsi = ind['rsi']
        dc_low = ind['dc_low']
        bb_low = ind['bb_low']
        vol_sma = ind['vol_sma']
        n = ind['n']

        eb = end_bar if end_bar else n

        in_trade = False
        entry_price = 0
        entry_bar = 0

        for i in range(max(start_bar, 21), min(eb, n)):
            if not in_trade:
                if rsi[i] is None or dc_low[i-1] is None or bb_low[i] is None or vol_sma[i] is None:
                    continue

                rsi_ok = rsi[i] < rsi_max
                dc_bounce = lows[i] <= dc_low[i-1]
                bb_bounce = closes[i] <= bb_low[i]
                bounce = closes[i] > closes[i-1]
                vs_ok = volumes[i] >= vol_sma[i] * vol_spike_mult if vol_sma[i] > 0 else False
                vc_ok = (volumes[i] >= volumes[i-1] if volumes[i-1] > 0 else True) if vol_confirm else True
                vm_ok = volumes[i] >= vol_sma[i] * 0.5 if vol_sma[i] > 0 else True

                if rsi_ok and dc_bounce and bb_bounce and bounce and vs_ok and vc_ok and vm_ok:
                    in_trade = True
                    entry_price = closes[i]
                    entry_bar = i
            else:
                bars_held = i - entry_bar
                pnl_pct = (closes[i] - entry_price) / entry_price * 100

                exit_reason = None
                if pnl_pct <= -sl_pct:
                    exit_reason = 'SL'
                elif pnl_pct >= tp_pct:
                    exit_reason = 'TP'
                elif bars_held >= tm_bars:
                    exit_reason = 'TM'
                elif i == min(eb, n) - 1:
                    exit_reason = 'END'

                if exit_reason:
                    net_pnl_pct = pnl_pct - total_fee_pct
                    net_pnl_usd = INITIAL_CAPITAL * net_pnl_pct / 100
                    trades.append({
                        'coin': coin, 'pnl_pct': net_pnl_pct, 'pnl': net_pnl_usd,
                        'exit': exit_reason, 'bars': bars_held,
                        'entry_bar': entry_bar, 'exit_bar': i,
                    })
                    in_trade = False

    n_trades = len(trades)
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0, 'wr': 0, 'pf': 0, 'trade_list': [],
                'final_equity': INITIAL_CAPITAL, 'max_dd_pct': 0}

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    wr = len(wins) / n_trades * 100
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
    pf = gross_profit / gross_loss if gross_loss > 0 else 999

    # Realistic equity curve + drawdown
    equity = INITIAL_CAPITAL
    peak = equity
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        'trades': n_trades, 'pnl': total_pnl, 'wr': wr, 'pf': round(pf, 2),
        'trade_list': trades, 'final_equity': equity, 'max_dd_pct': round(max_dd, 1)
    }


# ============================================================
# WALK-FORWARD (5 folds, leakage-safe)
# ============================================================
def walk_forward(data, coins, cfg, n_folds=5):
    """Leakage-safe Walk-Forward: precompute per fold op alleen train+test window."""
    all_bars = sorted(set(
        b for coin in coins if coin in data and isinstance(data[coin], list)
        for b in range(len(data[coin]))
    ))

    # Bepaal max bars beschikbaar
    max_bars = max(len(data[coin]) for coin in coins
                   if coin in data and isinstance(data[coin], list))
    usable = max_bars - START_BAR
    fold_size = usable // n_folds

    results = []
    for fold in range(n_folds):
        test_start = START_BAR + fold * fold_size
        test_end = START_BAR + (fold + 1) * fold_size
        if fold == n_folds - 1:
            test_end = START_BAR + usable  # laatste fold pakt rest

        # Precompute ALLEEN voor test window (leakage-safe)
        fold_indicators = precompute_all(data, coins)

        bt = run_backtest(fold_indicators, coins, cfg,
                          start_bar=test_start, end_bar=test_end)

        results.append({
            'fold': fold + 1,
            'start': test_start,
            'end': test_end,
            'trades': bt['trades'],
            'pnl': bt['pnl'],
            'wr': bt['wr'],
            'profitable': bt['pnl'] > 0,
        })

    profitable_folds = sum(1 for r in results if r['profitable'])
    return {
        'n_folds': n_folds,
        'profitable_folds': profitable_folds,
        'wf_ratio': f"{profitable_folds}/{n_folds}",
        'passed': profitable_folds >= 3,  # ≥3/5
        'folds': results,
        'total_pnl': sum(r['pnl'] for r in results),
        'total_trades': sum(r['trades'] for r in results),
    }


# ============================================================
# MONTE CARLO BLOCK BOOTSTRAP
# ============================================================
def mc_block_bootstrap(trade_pnls, n_sims=10000, block_size=5, seed=42):
    """Monte Carlo block bootstrap: shuffle blocks van trades, simulate equity."""
    if not trade_pnls:
        return {'win_pct': 0, 'median_equity': INITIAL_CAPITAL, 'p5': INITIAL_CAPITAL,
                'p95': INITIAL_CAPITAL, 'cvar95': INITIAL_CAPITAL}

    rng = random.Random(seed)
    n = len(trade_pnls)
    n_blocks = max(1, n // block_size)

    final_equities = []
    broke_count = 0

    for _ in range(n_sims):
        # Sample random blocks with replacement
        eq = INITIAL_CAPITAL
        for _ in range(n_blocks):
            start = rng.randint(0, max(0, n - block_size))
            block = trade_pnls[start:start + block_size]
            for pnl_pct in block:
                eq *= (1 + pnl_pct / 100)
                if eq <= 0:
                    broke_count += 1
                    break
            if eq <= 0:
                break
        final_equities.append(eq)

    final_equities.sort()
    win_count = sum(1 for e in final_equities if e > INITIAL_CAPITAL)
    median = final_equities[len(final_equities) // 2]
    p5 = final_equities[int(len(final_equities) * 0.05)]
    p95 = final_equities[int(len(final_equities) * 0.95)]
    worst_5pct = final_equities[:int(len(final_equities) * 0.05)]
    cvar95 = sum(worst_5pct) / max(1, len(worst_5pct))

    return {
        'win_pct': round(win_count / n_sims * 100, 1),
        'median_equity': round(median),
        'p5': round(p5),
        'p95': round(p95),
        'cvar95': round(cvar95),
        'ruin_pct': round(broke_count / n_sims * 100, 2),
    }


# ============================================================
# COIN SUBSAMPLE MC
# ============================================================
def mc_coin_subsample(data, coins, cfg, seeds, sample_pct=0.9):
    """Monte Carlo met coin subsampling: test op verschillende coin subsets."""
    results = []
    for seed in seeds:
        rng = random.Random(seed)
        n_sample = int(len(coins) * sample_pct)
        subset = sorted(rng.sample(coins, n_sample))
        complement = sorted(set(coins) - set(subset))

        sub_ind = precompute_all(data, subset)
        bt_sub = run_backtest(sub_ind, subset, cfg)

        comp_ind = precompute_all(data, complement) if complement else {}
        bt_comp = run_backtest(comp_ind, complement, cfg) if complement else {
            'trades': 0, 'pnl': 0, 'wr': 0}

        results.append({
            'seed': seed,
            'n_subset': len(subset),
            'n_complement': len(complement),
            'subset_pnl': bt_sub['pnl'],
            'subset_trades': bt_sub['trades'],
            'subset_wr': bt_sub['wr'],
            'complement_pnl': bt_comp['pnl'],
            'complement_trades': bt_comp['trades'],
        })

    avg_sub_pnl = sum(r['subset_pnl'] for r in results) / len(results)
    avg_comp_pnl = sum(r['complement_pnl'] for r in results) / len(results)
    all_positive = all(r['subset_pnl'] > 0 for r in results)

    return {
        'n_seeds': len(seeds),
        'avg_subset_pnl': round(avg_sub_pnl),
        'avg_complement_pnl': round(avg_comp_pnl),
        'all_subsets_positive': all_positive,
        'overfit_flag': avg_sub_pnl > 0 and avg_comp_pnl < 0,
        'seeds': results,
    }


# ============================================================
# FRICTION STRESS TEST
# ============================================================
def friction_stress(indicators, coins, cfg):
    """Test met verschillende fee multipliers en slippage levels."""
    scenarios = [
        {'label': '1x fees, 0 slip',    'fee_mult': 1.0, 'slippage': 0.0},
        {'label': '1.5x fees, 0 slip',  'fee_mult': 1.5, 'slippage': 0.0},
        {'label': '2x fees, 0 slip',    'fee_mult': 2.0, 'slippage': 0.0},
        {'label': '1x fees, 0.1% slip', 'fee_mult': 1.0, 'slippage': 0.10},
        {'label': '1x fees, 0.2% slip', 'fee_mult': 1.0, 'slippage': 0.20},
        {'label': '2x fees, 0.2% slip', 'fee_mult': 2.0, 'slippage': 0.20},
    ]

    results = []
    for sc in scenarios:
        bt = run_backtest(indicators, coins, cfg,
                          fee_mult=sc['fee_mult'], slippage_pct=sc['slippage'])
        results.append({
            'label': sc['label'],
            'fee_mult': sc['fee_mult'],
            'slippage': sc['slippage'],
            'trades': bt['trades'],
            'pnl': bt['pnl'],
            'wr': bt['wr'],
            'pf': bt['pf'],
            'max_dd': bt['max_dd_pct'],
            'profitable': bt['pnl'] > 0,
        })

    all_positive = all(r['profitable'] for r in results)
    return {
        'scenarios': results,
        'all_positive': all_positive,
        'worst_pnl': min(r['pnl'] for r in results),
    }


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"{'='*80}")
    print(f"HEAD-TO-HEAD VALIDATIE")
    print(f"  {CHALLENGER['label']} vs {CHAMPION['label']}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*80}")

    # Load data
    print(f"\n  Laden data...")
    t0 = time.time()
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"  {len(coins)} coins geladen")

    # Precompute (full universe)
    print(f"  Precomputing indicators...")
    indicators = precompute_all(data, coins)
    precompute_time = time.time() - t0
    print(f"  Precompute: {precompute_time:.1f}s")

    configs = [CHALLENGER, CHAMPION]
    all_results = {}

    for config in configs:
        label = config['label']
        cfg = config['cfg']
        print(f"\n{'='*80}")
        print(f"  CONFIG: {label}")
        print(f"  {json.dumps(cfg, indent=2)}")
        print(f"{'='*80}")

        results = {'label': label, 'cfg': cfg}

        # 0. Baseline (full universe, 1x fees)
        print(f"\n  [0] BASELINE (full universe, 1x fees)...")
        bt = run_backtest(indicators, coins, cfg)
        results['baseline'] = {
            'trades': bt['trades'], 'pnl': round(bt['pnl']),
            'wr': round(bt['wr'], 1), 'pf': bt['pf'],
            'max_dd': bt['max_dd_pct'], 'equity': round(bt['final_equity']),
        }
        print(f"      {bt['trades']} trades | WR {bt['wr']:.0f}% | "
              f"P&L ${bt['pnl']:+,.0f} | PF {bt['pf']} | DD {bt['max_dd_pct']}%")

        # Exit breakdown
        exits = {}
        for t in bt['trade_list']:
            exits[t['exit']] = exits.get(t['exit'], 0) + 1
        exits_pnl = {}
        for t in bt['trade_list']:
            exits_pnl[t['exit']] = exits_pnl.get(t['exit'], 0) + t['pnl']
        print(f"      Exits: {exits}")
        for ex, cnt in sorted(exits.items()):
            avg_pnl = exits_pnl[ex] / cnt
            print(f"        {ex}: {cnt}x | total ${exits_pnl[ex]:+,.0f} | avg ${avg_pnl:+,.0f}")
        results['exit_breakdown'] = {ex: {'count': exits.get(ex, 0),
                                           'total_pnl': round(exits_pnl.get(ex, 0))}
                                     for ex in exits}

        # Compounding equity
        equity = INITIAL_CAPITAL
        for t in bt['trade_list']:
            equity *= (1 + t['pnl_pct'] / 100)
        results['compound_equity'] = round(equity)
        results['compound_pnl'] = round(equity - INITIAL_CAPITAL)
        print(f"      Compound: ${equity:,.0f} ({(equity/INITIAL_CAPITAL-1)*100:+.0f}%)")

        # NoTop
        coin_pnl = {}
        for t in bt['trade_list']:
            coin_pnl[t['coin']] = coin_pnl.get(t['coin'], 0) + t['pnl']
        if coin_pnl:
            top_coin = max(coin_pnl, key=coin_pnl.get)
            notop = bt['pnl'] - coin_pnl[top_coin]
            results['notop_pnl'] = round(notop)
            results['top_coin'] = {'coin': top_coin, 'pnl': round(coin_pnl[top_coin])}
            print(f"      NoTop: ${notop:+,.0f} (top: {top_coin} ${coin_pnl[top_coin]:+,.0f})")

        # 1. Walk-Forward (5 folds)
        print(f"\n  [1] WALK-FORWARD (5 folds, leakage-safe)...")
        t1 = time.time()
        wf = walk_forward(data, coins, cfg, n_folds=5)
        wf_time = time.time() - t1
        results['walk_forward'] = wf
        print(f"      WF: {wf['wf_ratio']} ({'PASS' if wf['passed'] else 'FAIL'}) | "
              f"{wf_time:.0f}s")
        for f_result in wf['folds']:
            status = "✅" if f_result['profitable'] else "❌"
            print(f"        Fold {f_result['fold']}: {f_result['trades']} tr | "
                  f"${f_result['pnl']:+,.0f} {status}")

        # 2. Monte Carlo block bootstrap
        print(f"\n  [2] MONTE CARLO BLOCK BOOTSTRAP (10K sims)...")
        t2 = time.time()
        trade_pnls = [t['pnl_pct'] for t in bt['trade_list']]
        mc = mc_block_bootstrap(trade_pnls, n_sims=10000)
        mc_time = time.time() - t2
        results['mc_block'] = mc
        print(f"      Win: {mc['win_pct']}% | Median: ${mc['median_equity']:,} | "
              f"P5: ${mc['p5']:,} | CVaR95: ${mc['cvar95']:,} | {mc_time:.1f}s")

        # 3. Coin subsample MC (seeds 42-46)
        print(f"\n  [3] COIN SUBSAMPLE MC (seeds {COIN_SEEDS})...")
        t3 = time.time()
        cs = mc_coin_subsample(data, coins, cfg, COIN_SEEDS)
        cs_time = time.time() - t3
        results['coin_subsample'] = cs
        print(f"      Avg subset P&L: ${cs['avg_subset_pnl']:+,} | "
              f"Avg complement: ${cs['avg_complement_pnl']:+,} | "
              f"Overfit: {'⚠️ YES' if cs['overfit_flag'] else '✅ NO'} | {cs_time:.0f}s")
        for s in cs['seeds']:
            print(f"        seed={s['seed']}: sub ${s['subset_pnl']:+,.0f} ({s['subset_trades']}tr) | "
                  f"comp ${s['complement_pnl']:+,.0f} ({s['complement_trades']}tr)")

        # 4. Friction stress test
        print(f"\n  [4] FRICTION STRESS TEST (fees + slippage)...")
        t4 = time.time()
        fr = friction_stress(indicators, coins, cfg)
        fr_time = time.time() - t4
        results['friction'] = fr
        for sc in fr['scenarios']:
            status = "✅" if sc['profitable'] else "❌"
            print(f"      {sc['label']:<25s}: ${sc['pnl']:+8,.0f} | WR {sc['wr']:4.0f}% | "
                  f"PF {sc['pf']:5.2f} | DD {sc['max_dd']:.0f}% {status}")
        print(f"      All positive: {'✅' if fr['all_positive'] else '❌'} | {fr_time:.1f}s")

        all_results[label] = results

    # ============================================================
    # HEAD-TO-HEAD SUMMARY
    # ============================================================
    print(f"\n{'='*80}")
    print(f"HEAD-TO-HEAD SAMENVATTING")
    print(f"{'='*80}")

    ch = all_results[CHALLENGER['label']]
    cm = all_results[CHAMPION['label']]

    print(f"\n  {'Metric':<30s} | {'CHALLENGER':>15s} | {'CHAMPION':>15s} | {'Winner':>12s}")
    print(f"  {'-'*80}")

    comparisons = [
        ('Trades',             ch['baseline']['trades'],        cm['baseline']['trades']),
        ('Win Rate %',         ch['baseline']['wr'],            cm['baseline']['wr']),
        ('Fixed P&L $',        ch['baseline']['pnl'],           cm['baseline']['pnl']),
        ('Compound P&L $',     ch['compound_pnl'],              cm['compound_pnl']),
        ('Compound Equity $',  ch['compound_equity'],           cm['compound_equity']),
        ('Profit Factor',      ch['baseline']['pf'],            cm['baseline']['pf']),
        ('Max Drawdown %',     ch['baseline']['max_dd'],        cm['baseline']['max_dd']),
        ('NoTop P&L $',        ch.get('notop_pnl', 0),         cm.get('notop_pnl', 0)),
        ('WF (folds)',         ch['walk_forward']['profitable_folds'],  cm['walk_forward']['profitable_folds']),
        ('MC Win %',           ch['mc_block']['win_pct'],       cm['mc_block']['win_pct']),
        ('MC Median Eq $',     ch['mc_block']['median_equity'], cm['mc_block']['median_equity']),
        ('MC P5 $',            ch['mc_block']['p5'],            cm['mc_block']['p5']),
        ('MC CVaR95 $',        ch['mc_block']['cvar95'],        cm['mc_block']['cvar95']),
        ('Coin MC Overfit',    1 if ch['coin_subsample']['overfit_flag'] else 0,
                               1 if cm['coin_subsample']['overfit_flag'] else 0),
        ('Friction All+',      1 if ch['friction']['all_positive'] else 0,
                               1 if cm['friction']['all_positive'] else 0),
        ('Friction Worst $',   ch['friction']['worst_pnl'],     cm['friction']['worst_pnl']),
    ]

    challenger_wins = 0
    champion_wins = 0

    for metric, ch_val, cm_val in comparisons:
        # Determine winner (lower is better for DD and overfit)
        lower_better = metric in ('Max Drawdown %', 'Coin MC Overfit')
        if lower_better:
            winner = CHALLENGER['label'][:12] if ch_val < cm_val else CHAMPION['label'][:12] if cm_val < ch_val else 'TIE'
        else:
            winner = CHALLENGER['label'][:12] if ch_val > cm_val else CHAMPION['label'][:12] if cm_val > ch_val else 'TIE'

        if winner == CHALLENGER['label'][:12]:
            challenger_wins += 1
        elif winner == CHAMPION['label'][:12]:
            champion_wins += 1

        if isinstance(ch_val, float):
            print(f"  {metric:<30s} | {ch_val:>15,.1f} | {cm_val:>15,.1f} | {winner:>12s}")
        else:
            print(f"  {metric:<30s} | {ch_val:>15,} | {cm_val:>15,} | {winner:>12s}")

    print(f"\n  SCOREBORD: {CHALLENGER['label']} {challenger_wins} — {champion_wins} {CHAMPION['label']}")

    overall = CHALLENGER['label'] if challenger_wins > champion_wins else CHAMPION['label']
    print(f"\n  🏆 OVERALL WINNER: {overall}")

    # Verdict
    print(f"\n  VERDICT:")
    ch_wf = ch['walk_forward']['passed']
    cm_wf = cm['walk_forward']['passed']
    ch_mc = ch['mc_block']['win_pct'] >= 90
    cm_mc = cm['mc_block']['win_pct'] >= 90
    ch_fr = ch['friction']['all_positive']
    cm_fr = cm['friction']['all_positive']
    ch_ov = not ch['coin_subsample']['overfit_flag']
    cm_ov = not cm['coin_subsample']['overfit_flag']

    for lbl, wf, mc, fr, ov in [(CHALLENGER['label'], ch_wf, ch_mc, ch_fr, ch_ov),
                                  (CHAMPION['label'], cm_wf, cm_mc, cm_fr, cm_ov)]:
        gates = sum([wf, mc, fr, ov])
        status = "PRODUCTIE-KLAAR" if gates == 4 else f"FAALT {4-gates} gates"
        print(f"    {lbl}: WF={'✅' if wf else '❌'} MC={'✅' if mc else '❌'} "
              f"FR={'✅' if fr else '❌'} OV={'✅' if ov else '❌'} → {status}")

    # Save results
    output = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'configs': all_results,
        'summary': {
            'challenger_wins': challenger_wins,
            'champion_wins': champion_wins,
            'overall_winner': overall,
        }
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Resultaten opgeslagen in {RESULTS_FILE}")

    # Telegram notification
    try:
        from telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()
        msg = (f"🏆 HEAD-TO-HEAD RESULTAAT\n\n"
               f"{CHALLENGER['label']} vs {CHAMPION['label']}\n"
               f"Score: {challenger_wins}-{champion_wins}\n"
               f"Winner: {overall}\n\n"
               f"CHALLENGER:\n"
               f"  P&L: ${ch['baseline']['pnl']:+,.0f} | Compound: ${ch['compound_pnl']:+,.0f}\n"
               f"  WF: {ch['walk_forward']['wf_ratio']} | MC: {ch['mc_block']['win_pct']}%\n"
               f"  Friction: {'✅' if ch_fr else '❌'} | Overfit: {'✅ NO' if ch_ov else '⚠️ YES'}\n\n"
               f"CHAMPION:\n"
               f"  P&L: ${cm['baseline']['pnl']:+,.0f} | Compound: ${cm['compound_pnl']:+,.0f}\n"
               f"  WF: {cm['walk_forward']['wf_ratio']} | MC: {cm['mc_block']['win_pct']}%\n"
               f"  Friction: {'✅' if cm_fr else '❌'} | Overfit: {'✅ NO' if cm_ov else '⚠️ YES'}")
        tg.send(msg)
    except Exception as e:
        print(f"  Telegram notificatie gefaald: {e}")

    total_time = time.time() - t0
    print(f"\n  Totale runtime: {total_time:.0f}s ({total_time/60:.1f} min)")


if __name__ == '__main__':
    main()
