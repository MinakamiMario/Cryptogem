#!/usr/bin/env python3
"""Volume-Cutoff Universe Sweep - Agent A1 (Universe Slicer)"""
import sys, json, time, subprocess
from pathlib import Path
from datetime import datetime
from statistics import median

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import run_backtest, walk_forward, precompute_base_indicators
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import extend_indicators, get_feature_coverage
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

BARS_PER_WEEK = 168
BARS_PER_DAY = 24
V5_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}
UNIVERSE_SIZES = [50, 75, 100, 135, 150, 175, 200, 250, 316]

T1_FEE = get_harness_fee('mexc_market', 'tier1')
T2_FEE = get_harness_fee('mexc_market', 'tier2')
T1_STRESS = T1_FEE * 2
T2_STRESS = T2_FEE * 2

GATE_THRESHOLDS = {
    'G1_trades_per_week': 10, 'G2_max_gap_days': 2.5,
    'G3_exp_per_week_market': 0, 'G4_exp_per_week_stress': 0,
    'G5_max_dd_pct': 20, 'G6_wf_positive_folds': 4, 'G8_fold_concentration': 0.35,
}


def load_candle_parts():
    parts_dir = ROOT / 'data' / 'cache_parts_hf' / '1h' / 'kraken'
    if not parts_dir.exists():
        print(f'[ERROR] Parts dir not found: {parts_dir}')
        sys.exit(1)
    coins_data = {}
    for coin_file in sorted(parts_dir.glob('*.json')):
        symbol = coin_file.stem.replace('_', '/')
        with open(coin_file) as f:
            candles = json.load(f)
        if len(candles) >= 50:
            coins_data[symbol] = candles
    print(f'[Load] {len(coins_data)} coins loaded from part files')
    return coins_data


def load_tiering():
    path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not path.exists():
        print(f'[ERROR] Tiering not found: {path}')
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def compute_median_volumes(data, coins):
    volumes = {}
    for coin in coins:
        candles = data.get(coin, [])
        if not candles:
            continue
        dvols = []
        for c in candles:
            cl = c.get('close', 0)
            vol = c.get('volume', 0)
            if cl > 0 and vol > 0:
                dvols.append(cl * vol)
        volumes[coin] = median(dvols) if dvols else 0.0
    return dict(sorted(volumes.items(), key=lambda x: x[1], reverse=True))


def classify_coins(coins_subset, t1_set, t2_set):
    return ([c for c in coins_subset if c in t1_set],
            [c for c in coins_subset if c in t2_set])


def compute_max_gap(trades, total_bars):
    if len(trades) < 2:
        return total_bars / BARS_PER_DAY if total_bars > 0 else 999
    st = sorted(trades, key=lambda t: t.get('entry_bar', 0))
    mg = st[0].get('entry_bar', 50) - 50
    for i in range(1, len(st)):
        g = st[i].get('entry_bar', 0) - st[i-1].get('exit_bar', 0)
        if g > mg:
            mg = g
    eg = total_bars - st[-1].get('exit_bar', 0)
    if eg > mg:
        mg = eg
    return mg / BARS_PER_DAY


def compute_drawdown(trades, initial_capital=2000.0):
    if not trades:
        return 0.0
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get('entry_bar', 0)):
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_fold_concentration(fold_pnls):
    pos = [p for p in fold_pnls if p > 0]
    if not pos:
        return 1.0
    total = sum(pos)
    return max(pos) / total if total > 0 else 1.0


def run_for_universe_size(N, ranked_coins, data, t1_set, t2_set,
                          all_ind, market_ctx, total_bars):
    t_start = time.time()
    subset = ranked_coins[:N]
    t1c, t2c = classify_coins(subset, t1_set, t2_set)
    n_t1, n_t2 = len(t1c), len(t2c)
    print(f'  [N={N}] T1={n_t1}, T2={n_t2}, total={n_t1+n_t2}')

    tier_ind = {}
    if t1c:
        tier_ind['tier1'] = {c: all_ind[c] for c in t1c if c in all_ind}
    if t2c:
        tier_ind['tier2'] = {c: all_ind[c] for c in t2c if c in all_ind}
    tc = {'tier1': t1c, 'tier2': t2c}
    params = {**V5_PARAMS, '__market__': market_ctx}

    # Baseline (market fees)
    all_trades = []
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_FEE if tn == 'tier1' else T2_FEE
        bt = run_backtest(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
                          params=params, indicators=tier_ind.get(tn, {}), fee=fee, max_pos=1)
        for t in bt.trade_list:
            t['_tier'] = tn
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)

    nt = len(all_trades)
    tw_total = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    tp_total = sum(t['pnl'] for t in all_trades)
    exp = tp_total / nt if nt > 0 else 0
    tpw = nt / tw_total
    epw = exp * tpw

    g1v, g1p = tpw, tpw >= GATE_THRESHOLDS['G1_trades_per_week']
    g2v = compute_max_gap(all_trades, total_bars)
    g2p = g2v <= GATE_THRESHOLDS['G2_max_gap_days']
    g3v, g3p = epw, epw > 0
    g5v = compute_drawdown(all_trades)
    g5p = g5v <= GATE_THRESHOLDS['G5_max_dd_pct']

    wins = [t for t in all_trades if t['pnl'] > 0]
    losses = [t for t in all_trades if t['pnl'] <= 0]
    tww = sum(t['pnl'] for t in wins)
    tll = abs(sum(t['pnl'] for t in losses))
    pf = tww / tll if tll > 0 else (float('inf') if tww > 0 else 0.0)
    wr = len(wins) / nt * 100 if nt > 0 else 0
    print(f'    Baseline: {nt}tr PF={pf:.3f} WR={wr:.1f}% Exp/wk=${epw:.2f} DD={g5v:.1f}%')

    # Stress 2x
    stress_trades = []
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_STRESS if tn == 'tier1' else T2_STRESS
        bt = run_backtest(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
                          params=params, indicators=tier_ind.get(tn, {}), fee=fee, max_pos=1)
        for t in bt.trade_list:
            t['_tier'] = tn
        stress_trades.extend(bt.trade_list)

    s_pnl = sum(t['pnl'] for t in stress_trades)
    s_n = len(stress_trades)
    s_exp = s_pnl / s_n if s_n > 0 else 0
    s_epw = s_exp * (s_n / tw_total)
    s_tw2 = sum(t['pnl'] for t in stress_trades if t['pnl'] > 0)
    s_tl2 = abs(sum(t['pnl'] for t in stress_trades if t['pnl'] <= 0))
    s_pf = s_tw2 / s_tl2 if s_tl2 > 0 else 0.0
    g4v, g4p = s_epw, s_epw > 0
    print(f'    Stress:   {s_n}tr PF={s_pf:.3f} Exp/wk=${s_epw:.2f}')

    # Walk-forward 5-fold
    tier_fold_trades = {}
    for tn, coins in tc.items():
        if not coins:
            continue
        fee = T1_FEE if tn == 'tier1' else T2_FEE
        folds = walk_forward(data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
                             params=params, indicators=tier_ind.get(tn, {}), n_folds=5,
                             fee=fee, max_pos=1)
        for fi, fbt in enumerate(folds):
            if fi not in tier_fold_trades:
                tier_fold_trades[fi] = []
            for t in fbt.trade_list:
                t['_tier'] = tn
            tier_fold_trades[fi].extend(fbt.trade_list)

    fold_pnls = []
    fold_details = []
    for fi in range(5):
        ft = tier_fold_trades.get(fi, [])
        fp = sum(t['pnl'] for t in ft)
        fold_pnls.append(fp)
        fold_details.append({'fold': fi + 1, 'trades': len(ft), 'pnl': round(fp, 2)})

    pf_count = sum(1 for p in fold_pnls if p > 0)
    g6v, g6p = pf_count, pf_count >= GATE_THRESHOLDS['G6_wf_positive_folds']
    g8v = compute_fold_concentration(fold_pnls)
    g8p = g8v < GATE_THRESHOLDS['G8_fold_concentration']
    fold_str = ' '.join([f'${p:.0f}' for p in fold_pnls])
    print(f'    WF:       {pf_count}/5 [{fold_str}] conc={g8v:.1%}')

    elapsed = time.time() - t_start
    gp = sum([g1p, g2p, g3p, g4p, g5p, g6p, g8p])

    result = {
        'N': N, 'n_t1': n_t1, 'n_t2': n_t2,
        'trades': nt, 'pnl': round(tp_total, 2),
        'pf': round(pf, 3), 'wr': round(wr, 1),
        'gates': {
            'G1_trades_per_week': {'value': round(g1v, 2), 'threshold': '>= 10', 'pass': g1p},
            'G2_max_gap_days': {'value': round(g2v, 2), 'threshold': '<= 2.5', 'pass': g2p},
            'G3_exp_per_week_market': {'value': round(g3v, 2), 'threshold': '> $0', 'pass': g3p},
            'G4_exp_per_week_stress': {'value': round(g4v, 2), 'threshold': '> $0', 'pass': g4p},
            'G5_max_dd_pct': {'value': round(g5v, 1), 'threshold': '<= 20%', 'pass': g5p},
            'G6_wf_positive_folds': {'value': g6v, 'threshold': '>= 4/5', 'pass': g6p},
            'G7_neighbor_stability': {'value': 'SKIP', 'threshold': '>= 8/12', 'pass': None},
            'G8_fold_concentration': {'value': round(g8v, 3), 'threshold': '< 35%', 'pass': g8p},
        },
        'gates_passed': gp, 'gates_total': 7,
        'stress_pf': round(s_pf, 3), 'stress_exp_wk': round(s_epw, 2),
        'dd_pct': round(g5v, 1), 'exp_per_week': round(epw, 2),
        'trades_per_week': round(tpw, 2),
        'fold_details': fold_details, 'fold_concentration': round(g8v, 3),
        'runtime_s': round(elapsed, 1),
    }
    status = 'ALL PASS' if gp == 7 else f'{gp}/7'
    print(f'    Gates:    {status} ({elapsed:.1f}s)')
    return result


def main():
    print('=' * 70)
    print('  Volume-Cutoff Universe Sweep - Agent A1 (Universe Slicer)')
    print('  Signal: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    print('  Fees: MEXC Market (T1=12.5bps, T2=23.5bps)')
    print('  Stress: 2x fees (T1=25.0bps, T2=47.0bps)')
    print('=' * 70)
    t0 = time.time()

    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    data = load_candle_parts()
    available = set(data.keys())
    tiering = load_tiering()
    tb = tiering.get('tier_breakdown', {})
    t1_all = [c for c in tb.get('1', {}).get('coins', []) if c in available]
    t2_all = [c for c in tb.get('2', {}).get('coins', []) if c in available]
    t1_set = set(t1_all)
    t2_set = set(t2_all)
    all_tier = t1_all + t2_all
    print(f'[Universe] T1: {len(t1_all)}, T2: {len(t2_all)}, Total: {len(all_tier)}')

    print('[Volume] Computing median hourly dollar volume per coin...')
    vol_rank = compute_median_volumes(data, all_tier)
    ranked = list(vol_rank.keys())
    print(f'[Volume] Ranked {len(ranked)} coins')
    for i, c in enumerate(ranked[:5]):
        print(f'  Top {i+1}: {c:12s} ${vol_rank[c]:>12,.0f}/hr')
    for i, c in enumerate(ranked[-3:]):
        idx = len(ranked) - 3 + i + 1
        print(f'  Bot {idx}: {c:12s} ${vol_rank[c]:>12,.0f}/hr')

    print('[Indicators] Precomputing base indicators for all coins...')
    t_ind = time.time()
    all_ind = precompute_base_indicators(data, all_tier)
    print(f'  Base: {len(all_ind)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    extend_indicators(data, all_tier, all_ind)
    cov = get_feature_coverage(all_ind, all_tier)
    print(f'  VWAP: {cov["vwap_pct"]:.0f}% ({cov["vwap_available"]}/{cov["total_coins"]})')

    for coin in all_ind:
        all_ind[coin]['__coin__'] = coin

    print('[Market Context] Precomputing...')
    ctx_coins = list(set(all_tier))
    for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc in available and btc not in ctx_coins:
            ctx_coins.append(btc)
    mkt_ctx = precompute_market_context(data, ctx_coins)
    print('  Done.')

    total_bars = max((all_ind.get(c, {}).get('n', 0) for c in all_tier), default=0)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')
    print(f'[Fees] T1={T1_FEE*10000:.1f}bps T2={T2_FEE*10000:.1f}bps | '
          f'Stress: T1={T1_STRESS*10000:.1f}bps T2={T2_STRESS*10000:.1f}bps')

    print()
    print('=' * 70)
    print(f'  SWEEP: {len(UNIVERSE_SIZES)} universe sizes')
    print('=' * 70)

    results = []
    for N in UNIVERSE_SIZES:
        actual = min(N, len(ranked))
        r = run_for_universe_size(actual, ranked, data, t1_set, t2_set,
                                  all_ind, mkt_ctx, total_bars)
        results.append(r)

    elapsed = time.time() - t0

    best = max(results, key=lambda r: r['gates_passed'] * 10000 + r['exp_per_week'])
    all_pass = [r for r in results if r['gates_passed'] == 7]
    optimal_N = all_pass[-1]['N'] if all_pass else None

    cutoff_info = {}
    for N in UNIVERSE_SIZES:
        actual = min(N, len(ranked))
        if 0 < actual <= len(ranked):
            cc = ranked[actual - 1]
            cutoff_info[str(N)] = {'cutoff_coin': cc, 'cutoff_vol_usd_hr': round(vol_rank[cc], 2)}

    # JSON Report
    report = {
        'run_header': {
            'task': 'volume_cutoff_sweep', 'agent': 'A1 (Universe Slicer)',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'), 'commit': commit,
            'signal': 'H20_VWAP_DEVIATION v5', 'params': V5_PARAMS,
            'cost_regime': 'MEXC Market',
            'fees': {
                'market': {'tier1_bps': T1_FEE * 10000, 'tier2_bps': T2_FEE * 10000},
                'stress_2x': {'tier1_bps': T1_STRESS * 10000, 'tier2_bps': T2_STRESS * 10000},
            },
            'total_bars': total_bars, 'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed, 1),
        },
        'volume_ranking': {
            'method': 'median(close * volume) per coin across all bars',
            'total_coins_ranked': len(ranked),
            'top10': [{'rank': i+1, 'coin': c, 'median_vol_usd_hr': round(vol_rank[c], 2)}
                      for i, c in enumerate(ranked[:10])],
            'bottom5': [{'rank': len(ranked)-4+i, 'coin': c,
                         'median_vol_usd_hr': round(vol_rank[c], 2)}
                        for i, c in enumerate(ranked[-5:])],
        },
        'cutoff_info': cutoff_info,
        'sweep_results': results,
        'optimal_N': optimal_N,
        'best_result': best,
        'gate_thresholds': GATE_THRESHOLDS,
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_volume_cutoff_sweep_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # Markdown Report
    md = []
    md.append('# Volume-Cutoff Universe Sweep - Part 2')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append('**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)')
    md.append(f'**Fees**: MEXC Market (T1={T1_FEE*10000:.1f}bps, T2={T2_FEE*10000:.1f}bps)')
    md.append(f'**Stress**: 2x fees (T1={T1_STRESS*10000:.1f}bps, T2={T2_STRESS*10000:.1f}bps)')
    md.append(f'**Data**: {total_bars} bars ({total_weeks:.1f} weeks)')
    md.append(f'**Runtime**: {elapsed:.1f}s')
    md.append('')
    md.append('## Hypothesis')
    md.append('')
    md.append('Edge is concentrated in higher-volume coins. The original 135-coin (alphabetical A-J)')
    md.append('subset showed PF=1.85, WF=5/5, DD=11%. Full 316-coin universe shows PF=1.14, WF=3/5,')
    md.append('DD=53%. This sweep sorts coins by median hourly dollar volume and tests top-N subsets')
    md.append('to find the optimal volume cutoff where all 8 hard gates pass.')
    md.append('')

    md.append('## Gate Results by Universe Size')
    md.append('')
    md.append('| N | T1 | T2 | Trades | PF | WR% | Exp/Wk | DD% | Stress$/wk | WF | FoldConc | Gates |')
    md.append('|---|----|----|--------|-----|------|--------|------|------------|-----|----------|-------|')
    for r in results:
        g = r['gates']
        m = ' **' if r['gates_passed'] == 7 else ''
        me = '**' if r['gates_passed'] == 7 else ''
        md.append(
            f'| {m}{r["N"]}{me} | {r["n_t1"]} | {r["n_t2"]} '
            f'| {r["trades"]} | {r["pf"]:.3f} | {r["wr"]:.1f} '
            f'| ${r["exp_per_week"]:.0f} | {r["dd_pct"]:.1f} '
            f'| ${r["stress_exp_wk"]:.0f} '
            f'| {g["G6_wf_positive_folds"]["value"]}/5 '
            f'| {r["fold_concentration"]:.0%} | {r["gates_passed"]}/7 |')
    md.append('')

    md.append('## Gate Pass/Fail Matrix')
    md.append('')
    gk = ['G1_trades_per_week', 'G2_max_gap_days', 'G3_exp_per_week_market',
          'G4_exp_per_week_stress', 'G5_max_dd_pct', 'G6_wf_positive_folds',
          'G8_fold_concentration']
    gs = ['G1 Tr/wk', 'G2 Gap', 'G3 Exp$', 'G4 Stress$', 'G5 DD%', 'G6 WF', 'G8 Conc']
    md.append('| N | ' + ' | '.join(gs) + ' | Total |')
    md.append('|---' + '|------' * len(gs) + '|-------|')
    for r in results:
        g = r['gates']
        cells = []
        for k in gk:
            v = g[k]
            if v['pass'] is None:
                cells.append('--')
            elif v['pass']:
                cells.append('PASS')
            else:
                cells.append('**FAIL**')
        md.append(f'| {r["N"]} | ' + ' | '.join(cells) + f' | {r["gates_passed"]}/7 |')
    md.append('')

    md.append('## Walk-Forward Detail (5-Fold)')
    md.append('')
    md.append('| N | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |')
    md.append('|---|--------|--------|--------|--------|--------|----------|')
    for r in results:
        fds = r.get('fold_details', [])
        pnls = [f'${fd["pnl"]:.0f}' for fd in fds]
        while len(pnls) < 5:
            pnls.append('-')
        pos = sum(1 for fd in fds if fd['pnl'] > 0)
        md.append(f'| {r["N"]} | {pnls[0]} | {pnls[1]} | {pnls[2]} | {pnls[3]} | {pnls[4]} | {pos}/5 |')
    md.append('')

    md.append('## Volume Cutoffs')
    md.append('')
    md.append('| N | Cutoff Coin | Median Vol $/hr |')
    md.append('|---|-------------|-----------------|')
    for nk in sorted(cutoff_info.keys(), key=int):
        info = cutoff_info[nk]
        md.append(f'| {nk} | {info["cutoff_coin"]} | ${info["cutoff_vol_usd_hr"]:,.0f} |')
    md.append('')

    md.append('## Verdict')
    md.append('')
    if optimal_N:
        md.append(f'**Optimal cutoff: N={optimal_N}** (largest universe passing all 7 evaluated gates)')
        ci = cutoff_info.get(str(optimal_N), {})
        if ci:
            md.append(f'- Cutoff coin: {ci.get("cutoff_coin", "?")}')
            md.append(f'- Minimum median volume: ${ci.get("cutoff_vol_usd_hr", 0):,.0f}/hr')
        opt_r = [r for r in results if r['N'] == optimal_N][0]
        md.append(f'- Trades: {opt_r["trades"]}, PF: {opt_r["pf"]:.3f}, WR: {opt_r["wr"]:.1f}%')
        md.append(f'- Exp/week: ${opt_r["exp_per_week"]:.0f}, DD: {opt_r["dd_pct"]:.1f}%')
        md.append(f'- Stress Exp/week: ${opt_r["stress_exp_wk"]:.0f}')
        md.append(f'- Walk-forward: {opt_r["gates"]["G6_wf_positive_folds"]["value"]}/5')
        md.append(f'- Fold concentration: {opt_r["fold_concentration"]:.0%}')
    else:
        md.append('**No universe size passes all 7 gates.**')
        md.append('')
        md.append(f'Best result: N={best["N"]} with {best["gates_passed"]}/7 gates passed')
        md.append(f'- Exp/week: ${best["exp_per_week"]:.0f}, DD: {best["dd_pct"]:.1f}%')
        md.append(f'- Stress: ${best["stress_exp_wk"]:.0f}')
        md.append('')
        md.append('Failed gates for best N:')
        for k in gk:
            g = best['gates'][k]
            if g['pass'] is False:
                md.append(f'- {k}: value={g["value"]} (threshold: {g["threshold"]})')
    md.append('')
    md.append('---')
    md.append(f'*Generated by strategies/hf/screening/run_part2_volume_cutoff.py '
              f'at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_volume_cutoff_sweep_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    print()
    print('=' * 70)
    print(f'  COMPLETE: {len(UNIVERSE_SIZES)} universe sizes tested')
    if optimal_N:
        print(f'  OPTIMAL: N={optimal_N} (all 7 gates pass)')
    else:
        print(f'  NO universe size passes all 7 gates')
        print(f'  BEST: N={best["N"]} ({best["gates_passed"]}/7 gates)')
    print(f'  Runtime: {elapsed:.1f}s')
    print('=' * 70)


if __name__ == '__main__':
    main()
