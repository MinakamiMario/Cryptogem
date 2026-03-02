#!/usr/bin/env python3
"""
ROBUSTNESS HARNESS v2 — Definitieve GO/NO-GO validatie
======================================================
Dataset: candle_cache_532.json (526 coins, ~721 bars, 4H candles)
Seed: 42 (alle stochastische tests)

Tests:
  1. Purged Walk-Forward (5-fold, embargo=2 bars rond boundaries)
  2. Fee + Slippage Stress (fees ×1/×2/×3 × slippage 0/10/20/35bps + 1-candle-later)
  3. Monte Carlo trade-order shuffle (1000×, DD dist, ruin prob)
  4. Parameter jitter (±10%, 50 varianten)
  5. Universe shift (top/mid/random50%/exclude-top-winners + coin concentratie)

Artifacts: wf_report.json, friction_report.json, mc_report.json,
           jitter_report.json, universe_report.json, go_nogo.md
"""
import sys
import json
import time
import random
import hashlib
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg, cfg_hash,
    CACHE_FILE, KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)

SEED = 42
DATASET = 'candle_cache_532.json'


def _get_halal_coins():
    """Extract halal coin set from kraken_client.py PAIR_MAP."""
    import re
    kc_path = BASE_DIR / 'kraken_client.py'
    if not kc_path.exists():
        return None
    with open(kc_path) as f:
        content = f.read()
    pairs = set(re.findall(r"'([A-Z0-9]+/USD)'", content))
    return pairs


HALAL_COINS = _get_halal_coins()

# ============================================================
# KANDIDATEN
# ============================================================
CANDIDATES = {
    'C1_TPSL_RSI45': {
        'label': 'tp_sl RSI45 (V3 champion)',
        'cfg': {
            'exit_type': 'tp_sl', 'rsi_max': 45, 'vol_spike_mult': 3.0,
            'vol_confirm': True, 'tp_pct': 15, 'sl_pct': 15,
            'time_max_bars': 15, 'max_pos': 1,
        },
    },
    'C2_TPSL_RSI42': {
        'label': 'tp_sl RSI42',
        'cfg': {
            'exit_type': 'tp_sl', 'rsi_max': 42, 'vol_spike_mult': 3.0,
            'vol_confirm': True, 'tp_pct': 15, 'sl_pct': 15,
            'time_max_bars': 15, 'max_pos': 1,
        },
    },
    'C3_TPSL_RSI35': {
        'label': 'tp_sl RSI35',
        'cfg': {
            'exit_type': 'tp_sl', 'rsi_max': 35, 'vol_spike_mult': 3.0,
            'vol_confirm': True, 'tp_pct': 15, 'sl_pct': 15,
            'time_max_bars': 15, 'max_pos': 1,
        },
    },
    'C4_TRAIL_BEST': {
        'label': 'Trail BEST_KNOWN',
        'cfg': {
            'exit_type': 'trail', 'rsi_max': 42, 'atr_mult': 2.0,
            'vol_spike_mult': 3.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 2.0,
            'time_max_bars': 6, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 12.0, 'max_pos': 1,
        },
    },
    'C5_TRAIL_BASE': {
        'label': 'Trail BASELINE',
        'cfg': {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 3.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 1,
        },
    },
}

# ============================================================
# GO/NO-GO THRESHOLDS
# ============================================================
GO = {
    # WF
    'wf_min_pass': 4,           # ≥4/5 folds positief (streng)
    'wf_soft_pass': 3,          # 3/5 OK als negatieve fold klein/verklaarbaar
    'wf_max_dd': 40.0,         # DD in geen enkele fold >40%
    # Friction
    'friction_go': '2x_fee+20bps',  # must be positive at 2×fee + 0.20% slippage
    # MC
    'mc_p95_dd_max': 50.0,     # 95e percentile DD ≤50%
    'mc_ruin_max': 5.0,        # P(DD>50%) ≤5%
    # Jitter
    'jitter_min_positive_pct': 70.0,  # ≥70% varianten positief
    # Universe
    'univ_min_subsets_positive': 2,   # ≥2/4 subsets positief
    'univ_top1_share_max': 0.50,      # top1 coin <50%
    'univ_top3_share_max': 0.80,      # top3 coins <80%
}

# Kill-switch thresholds voor micro-live
KILL_SWITCH = {
    'max_dd_pct': 30.0,
    'max_consecutive_losses': 6,
    'max_loss_streak_usd': -400,
    'min_trades_before_eval': 10,
    'wr_floor': 40.0,
}


# ============================================================
# HELPERS
# ============================================================
def _bt_summary(bt):
    """Compact backtest summary dict."""
    pf = bt['pf']
    return {
        'trades': bt['trades'],
        'pnl': round(bt['pnl'], 2),
        'wr': round(bt['wr'], 1),
        'dd': round(bt['dd'], 1),
        'pf': round(pf, 2) if pf < 999 else 'INF',
    }


def _dataset_hash(cache_path=None):
    """MD5 van de dataset file voor reproducibility."""
    h = hashlib.md5()
    with open(cache_path or CACHE_FILE, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


# ============================================================
# TEST 1: PURGED WALK-FORWARD
# ============================================================
def purged_walk_forward(indicators, coins, cfg, n_folds=5, embargo=2):
    """
    Purged walk-forward met embargo zone.
    - Per fold: test op 1 segment, train op alle ANDERE segmenten
    - Purge: skip bars [test_start-embargo, test_start) en [test_end, test_end+embargo)
      in het traingedeelte om look-ahead leakage te voorkomen.
    """
    max_bars = max(indicators[p]['n'] for p in coins if p in indicators)
    usable = max_bars - START_BAR
    fold_size = usable // n_folds

    folds = []
    for i in range(n_folds):
        test_start = START_BAR + i * fold_size
        test_end = test_start + fold_size if i < n_folds - 1 else max_bars

        # Purged train zones: alles behalve [test_start-embargo, test_end+embargo]
        purge_start = max(START_BAR, test_start - embargo)
        purge_end = min(max_bars, test_end + embargo)

        # Train zone 1: [START_BAR, purge_start)
        # Train zone 2: [purge_end, max_bars)
        train_pnl = 0.0
        train_trades = 0
        train_dd = 0.0

        if purge_start > START_BAR:
            bt1 = run_backtest(indicators, coins, cfg,
                               start_bar=START_BAR, end_bar=purge_start)
            train_pnl += bt1['pnl']
            train_trades += bt1['trades']
            train_dd = max(train_dd, bt1['dd'])

        if purge_end < max_bars:
            bt2 = run_backtest(indicators, coins, cfg,
                               start_bar=purge_end, end_bar=max_bars)
            train_pnl += bt2['pnl']
            train_trades += bt2['trades']
            train_dd = max(train_dd, bt2['dd'])

        # Test: [test_start, test_end)
        test_bt = run_backtest(indicators, coins, cfg,
                               start_bar=test_start, end_bar=test_end)

        folds.append({
            'fold': i + 1,
            'test_bars': f'{test_start}-{test_end}',
            'purge_zone': f'{purge_start}-{purge_end}',
            'embargo': embargo,
            'train_trades': train_trades,
            'train_pnl': round(train_pnl, 2),
            'train_dd': round(train_dd, 1),
            'test_trades': test_bt['trades'],
            'test_pnl': round(test_bt['pnl'], 2),
            'test_wr': round(test_bt['wr'], 1),
            'test_dd': round(test_bt['dd'], 1),
            'test_pf': round(test_bt['pf'], 2) if test_bt['pf'] < 999 else 'INF',
            'pass': test_bt['pnl'] > 0,
        })

    passed = sum(1 for f in folds if f['pass'])
    max_test_dd = max(f['test_dd'] for f in folds)

    # GO logic
    go = passed >= GO['wf_min_pass'] and max_test_dd <= GO['wf_max_dd']
    soft_go = passed >= GO['wf_soft_pass'] and max_test_dd <= GO['wf_max_dd']

    return {
        'n_folds': n_folds,
        'embargo_bars': embargo,
        'passed_folds': passed,
        'wf_label': f'{passed}/{n_folds}',
        'max_test_dd': round(max_test_dd, 1),
        'folds': folds,
        'go': go,
        'soft_go': soft_go,
    }


# ============================================================
# TEST 2: FEE + SLIPPAGE STRESS
# ============================================================
def friction_stress(indicators, coins, cfg):
    """
    Matrix: fee_mult × slippage_bps.
    Slippage gemodelleerd als extra cost per trade (entry+exit).
    Plus "1-candle-later fill" worst-case.
    """
    fee_mults = [1.0, 2.0, 3.0]
    slip_bps_list = [0, 10, 20, 35]  # basis points per side

    matrix = {}
    for fm in fee_mults:
        for slip in slip_bps_list:
            # Effectieve fee = kraken fee × mult + slippage per side
            eff_fee = KRAKEN_FEE * fm + (slip / 10000)
            bt = run_backtest(indicators, coins, cfg, fee_override=eff_fee)
            key = f'{fm}x_fee+{slip}bps'
            matrix[key] = {
                'fee_mult': fm,
                'slippage_bps': slip,
                'effective_fee_per_side': round(eff_fee, 6),
                **_bt_summary(bt),
            }

    # 1-candle-later fill: entry op next bar's open (= close+1 bar)
    # We simulate this by shifting entry price up by avg 1-candle move
    # Approximation: run with extra 0.5% slippage (worst-case gap)
    eff_fee_1cl = KRAKEN_FEE * 2 + 0.005  # 2× fees + 50bps gap
    bt_1cl = run_backtest(indicators, coins, cfg, fee_override=eff_fee_1cl)
    matrix['2x_fee+1candle_gap'] = {
        'fee_mult': 2.0,
        'slippage_bps': '50bps_gap',
        'effective_fee_per_side': round(eff_fee_1cl, 6),
        **_bt_summary(bt_1cl),
    }

    # GO check: positive at 2×fee + 20bps
    go_key = '2.0x_fee+20bps'
    go = matrix[go_key]['pnl'] > 0

    return {
        'matrix': matrix,
        'go_scenario': go_key,
        'go_pnl': matrix[go_key]['pnl'],
        'go': go,
    }


# ============================================================
# TEST 3: MONTE CARLO TRADE-ORDER SHUFFLE
# ============================================================
def monte_carlo_shuffle(indicators, coins, cfg, n_sims=1000, seed=SEED):
    """
    Shuffle trade-volgorde 1000×.
    Meet: eind-equity distributie, max DD distributie, ruin probability.
    """
    rng = random.Random(seed)

    # Run baseline om trade list te krijgen
    bt = run_backtest(indicators, coins, cfg)
    trades = bt['trade_list']
    if len(trades) < 5:
        return {'error': 'Te weinig trades voor MC', 'go': False}

    pnl_pcts = [t['pnl_pct'] for t in trades]
    n_trades = len(pnl_pcts)

    final_equities = []
    max_dds = []
    broke_count = 0

    for _ in range(n_sims):
        shuffled = pnl_pcts[:]
        rng.shuffle(shuffled)

        eq = float(INITIAL_CAPITAL)
        peak = eq
        worst_dd = 0.0

        for pnl_pct in shuffled:
            eq += eq * (pnl_pct / 100)
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > worst_dd:
                worst_dd = dd
            if eq <= 0:
                broke_count += 1
                eq = 0
                worst_dd = 100.0
                break

        final_equities.append(eq)
        max_dds.append(worst_dd)

    final_equities.sort()
    max_dds.sort()
    n = len(final_equities)

    # Ruin probability: P(max DD > 50%)
    ruin_count = sum(1 for dd in max_dds if dd > 50)
    ruin_prob = ruin_count / n * 100

    p5_dd = max_dds[int(n * 0.05)]
    p50_dd = max_dds[n // 2]
    p95_dd = max_dds[int(n * 0.95)]

    p5_eq = final_equities[int(n * 0.05)]
    p50_eq = final_equities[n // 2]
    p95_eq = final_equities[int(n * 0.95)]
    win_pct = sum(1 for e in final_equities if e > INITIAL_CAPITAL) / n * 100

    # CVaR (expected shortfall) op equity
    worst_5pct = final_equities[:max(1, int(n * 0.05))]
    cvar95 = sum(worst_5pct) / len(worst_5pct)

    go = (p95_dd <= GO['mc_p95_dd_max']) and (ruin_prob <= GO['mc_ruin_max'])

    return {
        'n_sims': n_sims,
        'n_trades': n_trades,
        'seed': seed,
        'equity': {
            'p5': round(p5_eq, 0),
            'median': round(p50_eq, 0),
            'p95': round(p95_eq, 0),
            'win_pct': round(win_pct, 1),
            'cvar95': round(cvar95, 0),
        },
        'max_dd': {
            'p5': round(p5_dd, 1),
            'median': round(p50_dd, 1),
            'p95': round(p95_dd, 1),
        },
        'ruin_prob_pct': round(ruin_prob, 2),
        'broke_pct': round(broke_count / n * 100, 2),
        'go': go,
    }


# ============================================================
# TEST 4: PARAMETER JITTER
# ============================================================
def param_jitter(indicators, coins, cfg, n_variants=50, seed=SEED):
    """
    Jitter alle numerieke params ±10%. Discrete neighbours voor ints.
    GO: ≥70% varianten positief.
    """
    rng = random.Random(seed)

    base_bt = run_backtest(indicators, coins, cfg)
    base_pnl = base_bt['pnl']

    # Identificeer varieerbare params
    skip = {'max_pos', 'vol_confirm', 'rsi_recovery', 'breakeven'}
    jitterable = {k: v for k, v in cfg.items()
                  if isinstance(v, (int, float)) and k not in skip}

    results = []
    for i in range(n_variants):
        jittered = dict(cfg)
        for k, v in jitterable.items():
            pct = rng.uniform(-0.10, 0.10)
            new_val = v * (1 + pct)
            if isinstance(v, int):
                new_val = max(1, round(new_val))
            else:
                new_val = round(new_val, 4)
            jittered[k] = new_val

        bt = run_backtest(indicators, coins, jittered)
        results.append({
            'variant': i + 1,
            'trades': bt['trades'],
            'pnl': round(bt['pnl'], 2),
            'dd': round(bt['dd'], 1),
            'positive': bt['pnl'] > 0,
        })

    n_pos = sum(1 for r in results if r['positive'])
    pos_pct = n_pos / len(results) * 100
    pnls = sorted(r['pnl'] for r in results)

    go = pos_pct >= GO['jitter_min_positive_pct']

    return {
        'base_pnl': round(base_pnl, 2),
        'n_variants': n_variants,
        'seed': seed,
        'n_positive': n_pos,
        'positive_pct': round(pos_pct, 1),
        'median_pnl': round(pnls[len(pnls)//2], 2),
        'worst_pnl': round(pnls[0], 2),
        'best_pnl': round(pnls[-1], 2),
        'p10_pnl': round(pnls[int(len(pnls)*0.1)], 2),
        'go': go,
    }


# ============================================================
# TEST 5: UNIVERSE SHIFT + COIN CONCENTRATIE
# ============================================================
def universe_shift(indicators, coins, cfg, n_random=100, seed=SEED):
    """
    Subsets: top-volume, mid-volume, random 50%, exclude-top-winners.
    Coin concentratie: top1/top3 profit share.
    """
    rng = random.Random(seed)

    # Full baseline voor concentratie
    full_bt = run_backtest(indicators, coins, cfg)
    trades = full_bt['trade_list']
    total_profit = sum(max(0, t['pnl']) for t in trades)

    # Top 1/3 coin share
    coin_profit = {}
    for t in trades:
        coin_profit[t['pair']] = coin_profit.get(t['pair'], 0) + max(0, t['pnl'])
    sorted_coins = sorted(coin_profit.items(), key=lambda x: x[1], reverse=True)

    top1_share = sorted_coins[0][1] / total_profit if total_profit > 0 and sorted_coins else 0
    top3_profit = sum(v for _, v in sorted_coins[:3])
    top3_share = top3_profit / total_profit if total_profit > 0 else 0

    # Volume ranking
    coin_volumes = []
    for pair in coins:
        if pair in indicators:
            vols = [v for v in indicators[pair]['volumes'] if v and v > 0]
            avg_vol = sum(vols) / len(vols) if vols else 0
            coin_volumes.append((pair, avg_vol))
    coin_volumes.sort(key=lambda x: x[1], reverse=True)
    n = len(coin_volumes)

    # Subsets
    top_coins = [c[0] for c in coin_volumes[:n//3]]
    mid_coins = [c[0] for c in coin_volumes[n//3:2*n//3]]

    # Exclude top-3 winning coins
    top_winners = [c for c, _ in sorted_coins[:3]]
    excl_coins = [c for c in coins if c not in top_winners]

    subset_defs = {
        'top_volume': top_coins,
        'mid_volume': mid_coins,
        'random_50pct': None,  # handled below
        'exclude_top_winners': excl_coins,
    }

    subsets = {}
    for name, subset in subset_defs.items():
        if name == 'random_50pct':
            continue
        bt = run_backtest(indicators, subset, cfg)
        subsets[name] = {
            'n_coins': len(subset),
            **_bt_summary(bt),
            'positive': bt['pnl'] > 0,
        }

    # Random 50% MC
    sample_size = n // 2
    rand_eqs = []
    for _ in range(n_random):
        subset = rng.sample(coins, sample_size)
        bt = run_backtest(indicators, subset, cfg)
        rand_eqs.append(bt['final_equity'])
    rand_eqs.sort()
    nn = len(rand_eqs)
    subsets['random_50pct'] = {
        'n_coins': sample_size,
        'n_sims': n_random,
        'win_pct': round(sum(1 for e in rand_eqs if e > INITIAL_CAPITAL) / nn * 100, 1),
        'median_equity': round(rand_eqs[nn//2], 0),
        'p5_equity': round(rand_eqs[int(nn*0.05)], 0),
        'positive': sum(1 for e in rand_eqs if e > INITIAL_CAPITAL) / nn > 0.5,
    }

    n_pos = sum(1 for s in subsets.values() if s.get('positive'))

    go_univ = n_pos >= GO['univ_min_subsets_positive']
    go_conc = top1_share <= GO['univ_top1_share_max'] and top3_share <= GO['univ_top3_share_max']
    go = go_univ and go_conc

    return {
        'concentration': {
            'top1_coin': sorted_coins[0][0] if sorted_coins else 'none',
            'top1_share': round(min(1.0, top1_share), 3),
            'top3_coins': [c for c, _ in sorted_coins[:3]],
            'top3_share': round(min(1.0, top3_share), 3),
            'unique_coins_traded': len(coin_profit),
            'total_profit': round(total_profit, 2),
            'notop_pnl': round(full_bt['pnl'] - (sorted_coins[0][1] if sorted_coins else 0), 2),
        },
        'subsets': subsets,
        'n_positive_subsets': n_pos,
        'go_universe': go_univ,
        'go_concentration': go_conc,
        'go': go,
    }


# ============================================================
# RUNNER: alle tests per config
# ============================================================
def run_candidate(indicators, coins, cfg, cid, label):
    """Run alle 5 tests. Return dict met resultaten + GO/NO-GO."""
    cfg = normalize_cfg(dict(cfg))
    print(f"\n{'='*65}")
    print(f"  {cid} — {label}")
    print(f"  {json.dumps(cfg, sort_keys=True)}")
    print(f"{'='*65}")

    t0 = time.time()

    # Baseline
    base = run_backtest(indicators, coins, cfg)
    baseline = _bt_summary(base)
    print(f"  BASE: {baseline['trades']}tr ${baseline['pnl']} "
          f"WR{baseline['wr']}% DD{baseline['dd']}% PF{baseline['pf']}")

    if baseline['trades'] < 15:
        print(f"  KILLED: <15 trades")
        return {'cid': cid, 'label': label, 'cfg': cfg, 'baseline': baseline,
                'verdict': 'NO-GO', 'reason': '<15 trades'}

    # 1. Purged WF
    print(f"  [1/5] Purged Walk-Forward...", flush=True)
    wf = purged_walk_forward(indicators, coins, cfg)
    for f in wf['folds']:
        sym = '✅' if f['pass'] else '❌'
        print(f"    F{f['fold']}: test {f['test_bars']} → "
              f"{f['test_trades']}tr ${f['test_pnl']} DD{f['test_dd']}% {sym}")
    print(f"    → {wf['wf_label']} {'GO' if wf['go'] else 'SOFT' if wf['soft_go'] else 'NO-GO'}")

    # 2. Friction
    print(f"  [2/5] Fee+Slippage matrix...", flush=True)
    fric = friction_stress(indicators, coins, cfg)
    for key in ['1.0x_fee+0bps', '2.0x_fee+20bps', '3.0x_fee+35bps', '2x_fee+1candle_gap']:
        if key in fric['matrix']:
            r = fric['matrix'][key]
            sym = '✅' if r['pnl'] > 0 else '❌'
            print(f"    {key}: ${r['pnl']} WR{r['wr']}% DD{r['dd']}% {sym}")
    print(f"    → GO scenario ({fric['go_scenario']}): ${fric['go_pnl']} "
          f"{'GO' if fric['go'] else 'NO-GO'}")

    # 3. MC
    print(f"  [3/5] Monte Carlo shuffle (1000×)...", flush=True)
    mc = monte_carlo_shuffle(indicators, coins, cfg)
    if 'error' not in mc:
        print(f"    Equity: p5=${mc['equity']['p5']} med=${mc['equity']['median']} "
              f"p95=${mc['equity']['p95']} win%={mc['equity']['win_pct']}%")
        print(f"    MaxDD: p5={mc['max_dd']['p5']}% med={mc['max_dd']['median']}% "
              f"p95={mc['max_dd']['p95']}%")
        print(f"    Ruin(DD>50%): {mc['ruin_prob_pct']}% {'GO' if mc['go'] else 'NO-GO'}")

    # 4. Jitter
    print(f"  [4/5] Param jitter (50 varianten ±10%)...", flush=True)
    jit = param_jitter(indicators, coins, cfg, n_variants=50)
    print(f"    {jit['n_positive']}/{jit['n_variants']} pos ({jit['positive_pct']}%) "
          f"worst=${jit['worst_pnl']} med=${jit['median_pnl']} "
          f"{'GO' if jit['go'] else 'NO-GO'}")

    # 5. Universe
    print(f"  [5/5] Universe shift + concentratie...", flush=True)
    univ = universe_shift(indicators, coins, cfg)
    c = univ['concentration']
    print(f"    Concentratie: top1={c['top1_coin']} {c['top1_share']*100:.1f}% | "
          f"top3 {c['top3_share']*100:.1f}% | notop=${c['notop_pnl']}")
    for name, s in univ['subsets'].items():
        if 'pnl' in s:
            sym = '✅' if s['positive'] else '❌'
            print(f"    {name}: {s.get('n_coins','')}c {s['trades']}tr ${s['pnl']} {sym}")
        else:
            sym = '✅' if s['positive'] else '❌'
            print(f"    {name}: {s['n_coins']}c win%={s['win_pct']}% "
                  f"med=${s['median_equity']} {sym}")
    print(f"    → univ={'GO' if univ['go_universe'] else 'NO-GO'} "
          f"conc={'GO' if univ['go_concentration'] else 'NO-GO'}")

    elapsed = round(time.time() - t0, 1)

    # --- VERDICT ---
    fails = []
    if not wf['go'] and not wf['soft_go']:
        fails.append(f"WF {wf['wf_label']}")
    if not fric['go']:
        fails.append(f"Friction: ${fric['go_pnl']} at {fric['go_scenario']}")
    if not mc.get('go', False):
        fails.append(f"MC ruin={mc.get('ruin_prob_pct','?')}% p95DD={mc.get('max_dd',{}).get('p95','?')}%")
    if not jit['go']:
        fails.append(f"Jitter {jit['positive_pct']}% < {GO['jitter_min_positive_pct']}%")
    if not univ['go']:
        if not univ['go_concentration']:
            fails.append(f"Conc top1={c['top1_share']*100:.0f}%")
        if not univ['go_universe']:
            fails.append(f"Universe {univ['n_positive_subsets']} subsets positive")

    # Soft GO: WF 3/5 met kleine negatieve fold
    if wf['soft_go'] and not wf['go'] and len(fails) == 0:
        verdict = 'SOFT-GO'
    elif len(fails) == 0:
        verdict = 'GO'
    else:
        verdict = 'NO-GO'

    sym = {'GO': '🟢', 'SOFT-GO': '🟡', 'NO-GO': '🔴'}[verdict]
    print(f"\n  {sym} {verdict}: {cid}")
    if fails:
        for f in fails:
            print(f"    ❌ {f}")
    print(f"  ({elapsed}s)")

    return {
        'cid': cid, 'label': label, 'cfg': cfg,
        'baseline': baseline,
        'walk_forward': wf,
        'friction': fric,
        'monte_carlo': mc,
        'param_jitter': jit,
        'universe': univ,
        'fails': fails,
        'verdict': verdict,
        'elapsed_s': elapsed,
    }


# ============================================================
# ARTIFACT WRITERS
# ============================================================
def write_artifacts(all_results, ds_hash, output_dir=None, dataset_label=None,
                    universe_mode='all', coin_count=0):
    """Schrijf per-test JSON artifacts + go_nogo.md."""
    meta = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'dataset': dataset_label or DATASET,
        'dataset_hash': ds_hash,
        'seed': SEED,
        'universe_mode': universe_mode,
        'coin_count': coin_count,
        'go_thresholds': GO,
        'kill_switch': KILL_SWITCH,
    }

    # Per-test JSONs
    for test_key, filename in [
        ('walk_forward', 'wf_report.json'),
        ('friction', 'friction_report.json'),
        ('monte_carlo', 'mc_report.json'),
        ('param_jitter', 'jitter_report.json'),
        ('universe', 'universe_report.json'),
    ]:
        report = dict(meta)
        report['results'] = {}
        for cid, r in all_results.items():
            if test_key in r:
                report['results'][cid] = r[test_key]
        out = Path(output_dir) if output_dir else BASE_DIR.parent / 'reports'
        path = out / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  💾 {filename}")

    # go_nogo.md
    lines = [
        '# GO/NO-GO Rapport',
        f'Datum: {meta["timestamp"]}',
        f'Dataset: `{meta["dataset"]}` (hash: `{ds_hash}`)',
        f'Seed: {SEED}',
        '',
        '## GO Thresholds',
        '```',
    ]
    for k, v in GO.items():
        lines.append(f'{k}: {v}')
    lines.append('```')
    lines.append('')

    # Summary table
    lines.append('## Resultaten')
    lines.append('')
    lines.append('| Config | Tr | P&L | WR | DD | WF | Fric 2x+20bps | MC ruin% | Jitter pos% | Univ | Top1% | Verdict |')
    lines.append('|--------|-----|------|-----|-----|-----|---------------|----------|-------------|------|-------|---------|')

    go_configs = []
    for cid, r in all_results.items():
        bl = r['baseline']
        wf = r.get('walk_forward', {})
        fric = r.get('friction', {})
        mc = r.get('monte_carlo', {})
        jit = r.get('param_jitter', {})
        univ = r.get('universe', {})
        conc = univ.get('concentration', {})
        fric_pnl = fric.get('go_pnl', '-')
        mc_ruin = mc.get('ruin_prob_pct', '-')
        jit_pct = jit.get('positive_pct', '-')
        top1 = f"{conc.get('top1_share', 0)*100:.0f}" if conc else '-'
        v = r.get('verdict', '?')
        sym = {'GO': '🟢', 'SOFT-GO': '🟡', 'NO-GO': '🔴'}.get(v, '❓')
        lines.append(
            f"| {cid} | {bl['trades']} | ${bl['pnl']} | {bl['wr']}% | "
            f"{bl['dd']}% | {wf.get('wf_label','?')} | ${fric_pnl} | "
            f"{mc_ruin}% | {jit_pct}% | {univ.get('n_positive_subsets','-')}/4 | "
            f"{top1}% | {sym} {v} |"
        )
        if v in ('GO', 'SOFT-GO'):
            go_configs.append((cid, r))

    lines.append('')

    # Top configs detail
    if go_configs:
        lines.append('## GO Configs (aanbeveling)')
        for cid, r in go_configs:
            lines.append(f'### {cid}: {r["label"]}')
            lines.append(f'```json')
            lines.append(json.dumps(r['cfg'], indent=2, sort_keys=True))
            lines.append('```')
            bl = r['baseline']
            lines.append(f'- Baseline: {bl["trades"]}tr, ${bl["pnl"]}, WR {bl["wr"]}%, '
                         f'DD {bl["dd"]}%, PF {bl["pf"]}')
            wf = r['walk_forward']
            lines.append(f'- Purged WF: {wf["wf_label"]} (embargo={wf["embargo_bars"]})')
            mc = r['monte_carlo']
            if 'error' not in mc:
                lines.append(f'- MC: win%={mc["equity"]["win_pct"]}%, '
                             f'p95DD={mc["max_dd"]["p95"]}%, ruin={mc["ruin_prob_pct"]}%')
            jit = r['param_jitter']
            lines.append(f'- Jitter: {jit["positive_pct"]}% positief, '
                         f'worst=${jit["worst_pnl"]}, median=${jit["median_pnl"]}')
            conc = r['universe']['concentration']
            lines.append(f'- Concentratie: top1={conc["top1_coin"]} '
                         f'{conc["top1_share"]*100:.1f}%, notop=${conc["notop_pnl"]}')
            lines.append('')
    else:
        lines.append('## GEEN GO configs gevonden')
        lines.append('')

    # Fails detail
    nogo = [(cid, r) for cid, r in all_results.items() if r.get('verdict') == 'NO-GO']
    if nogo:
        lines.append('## NO-GO Configs')
        for cid, r in nogo:
            lines.append(f'- **{cid}**: {", ".join(r.get("fails", []))}')
        lines.append('')

    # Kill-switch
    lines.append('## Kill-Switch Thresholds (micro-live)')
    lines.append('```')
    for k, v in KILL_SWITCH.items():
        lines.append(f'{k}: {v}')
    lines.append('```')
    lines.append('')
    lines.append('Als een van deze drempels wordt bereikt tijdens micro-live: '
                 'stop trading onmiddellijk, evalueer.')

    out = Path(output_dir) if output_dir else BASE_DIR.parent / 'reports'
    md_path = out / 'go_nogo.md'
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  💾 go_nogo.md")


# ============================================================
# MAIN
# ============================================================
def parse_args():
    """Parse CLI arguments."""
    import argparse
    parser = argparse.ArgumentParser(
        description='Robustness Harness v2 — GO/NO-GO validatie',
        epilog=f'Beschikbare configs: {", ".join(CANDIDATES.keys())}',
    )
    parser.add_argument(
        '--config', '-c', nargs='+', metavar='ID',
        help='Run alleen specifieke config(s), bijv. --config C1_TPSL_RSI45 C3_TPSL_RSI35',
    )
    parser.add_argument(
        '--list', action='store_true',
        help='Toon beschikbare kandidaat configs en exit',
    )
    parser.add_argument(
        '--candle-cache', '-f', metavar='PATH',
        help='Path to candle cache JSON file (default: CACHE_FILE from agent_team_v3)',
    )
    parser.add_argument(
        '--output-dir', '-o', metavar='DIR',
        help='Output directory for reports (default: reports/)',
    )
    parser.add_argument(
        '--universe', '-u', choices=['all', 'halal'],
        default='all',
        help='Universe mode: all (523 coins, default) or halal (286 PAIR_MAP coins)',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # --list: toon kandidaten en exit
    if args.list:
        print(f"Beschikbare kandidaten ({len(CANDIDATES)}):")
        for cid, cand in CANDIDATES.items():
            print(f"  {cid:<18} {cand['label']}")
        sys.exit(0)

    # --config: filter op specifieke config(s)
    if args.config:
        selected = {}
        for cid in args.config:
            if cid not in CANDIDATES:
                print(f"❌ Onbekende config: {cid}")
                print(f"   Beschikbaar: {', '.join(CANDIDATES.keys())}")
                sys.exit(1)
            selected[cid] = CANDIDATES[cid]
        candidates = selected
    else:
        candidates = CANDIDATES

    # Resolve candle cache path
    cache_path = args.candle_cache if args.candle_cache else CACHE_FILE
    dataset_label = Path(cache_path).name

    print("=" * 65)
    print("  ROBUSTNESS HARNESS v2 — GO/NO-GO Validatie")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Dataset: {dataset_label} | Seed: {SEED}")
    print(f"  Universe: {args.universe}")
    print(f"  Configs: {', '.join(candidates.keys())}")
    print("=" * 65)

    # Dataset hash
    ds_hash = _dataset_hash(cache_path)
    print(f"  Dataset hash: {ds_hash}")

    # Load
    print("\n  Loading data...", flush=True)
    t0 = time.time()
    with open(cache_path) as f:
        data = json.load(f)
    all_coins = sorted(k for k, v in data.items() if isinstance(v, list) and len(v) > 50)

    # Universe filtering
    universe_mode = args.universe
    if universe_mode == 'halal' and HALAL_COINS:
        coins = sorted(c for c in all_coins if c in HALAL_COINS)
        print(f"  {len(coins)}/{len(all_coins)} coins (halal filter, {time.time()-t0:.1f}s)")
    else:
        coins = all_coins
        if universe_mode == 'halal' and not HALAL_COINS:
            print(f"  ⚠️  Halal coin list niet beschikbaar, using all")
            universe_mode = 'all'
        print(f"  {len(coins)} coins ({time.time()-t0:.1f}s)")

    # Precompute
    print("  Precomputing indicators...", flush=True)
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Done ({time.time()-t1:.1f}s)")

    # Run per candidate
    all_results = {}
    for cid, cand in candidates.items():
        r = run_candidate(indicators, coins, cand['cfg'], cid, cand['label'])
        all_results[cid] = r

    # Summary
    print("\n\n" + "=" * 100)
    print("  SUMMARY")
    print("=" * 100)
    hdr = (f"{'Config':<18} {'Tr':>3} {'P&L':>7} {'WR':>5} {'DD':>5} "
           f"{'WF':>5} {'Fric':>7} {'MCruin':>6} {'Jit%':>5} {'Univ':>4} "
           f"{'Top1%':>5} {'Verdict':>8}")
    print(hdr)
    print("-" * 100)
    for cid, r in all_results.items():
        bl = r['baseline']
        wf = r.get('walk_forward', {})
        fric = r.get('friction', {})
        mc = r.get('monte_carlo', {})
        jit = r.get('param_jitter', {})
        univ = r.get('universe', {})
        conc = univ.get('concentration', {})
        v = r.get('verdict', '?')
        sym = {'GO': '🟢', 'SOFT-GO': '🟡', 'NO-GO': '🔴'}.get(v, '?')
        fric_pnl = fric.get('go_pnl', 0)
        mc_ruin = mc.get('ruin_prob_pct', 99)
        jit_pct = jit.get('positive_pct', 0)
        top1 = conc.get('top1_share', 0) * 100 if conc else 0
        n_sub = univ.get('n_positive_subsets', 0)
        print(f"{cid:<18} {bl['trades']:>3} {bl['pnl']:>7.0f} {bl['wr']:>5.1f} "
              f"{bl['dd']:>5.1f} {wf.get('wf_label','?'):>5} {fric_pnl:>7.0f} "
              f"{mc_ruin:>5.1f}% {jit_pct:>5.1f} {n_sub:>3}/4 "
              f"{top1:>5.1f} {sym} {v}")
    print("-" * 100)

    # Write artifacts
    print("\n  Writing artifacts...")
    write_artifacts(all_results, ds_hash,
                    output_dir=args.output_dir, dataset_label=dataset_label,
                    universe_mode=universe_mode, coin_count=len(coins))

    total = round(time.time() - t0, 1)
    print(f"\n  Total: {total}s")


if __name__ == '__main__':
    main()
