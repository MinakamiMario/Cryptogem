#!/usr/bin/env python3
"""
Part 2 -- Agent C5-A3: BTC Regime Analysis
============================================
Analyzes correlation between per-trade P&L and BTC market regime
for the v5 H20 VWAP_DEVIATION strategy.

Approach:
  1. Load BTC/USD 1H candles, compute 48-bar SMA + 48-bar return
  2. Classify each bar into BULL / BEAR / SIDEWAYS regime
  3. Run full v5 backtest on 295-coin universe
  4. Tag each trade by BTC regime at entry bar
  5. Compute per-regime metrics: trade count, P&L, PF, WR
  6. Walk-forward per-regime breakdown
  7. Regime duration analysis (time in each regime)
  8. Conditional filter tests: no-BEAR, BULL-only, SIDEWAYS-only
  9. Full gate evaluation for each conditional filter

Output:
  reports/hf/part2_btc_regime_001.json
  reports/hf/part2_btc_regime_001.md

Usage:
    python -m strategies.hf.screening.run_part2_btc_regime
    python -m strategies.hf.screening.run_part2_btc_regime --dry-run
    python -m strategies.hf.screening.run_part2_btc_regime --require-data
"""
import sys
import json
import time
import argparse
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

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
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BARS_PER_WEEK = 168
BARS_PER_DAY = 24
SMA_PERIOD = 48          # 48 bars = 2 days of 1H candles
RETURN_PERIOD = 48        # 48-bar return for regime classification
RETURN_THRESHOLD = 0.01   # +/-1% for bull/bear classification

PARAMS_V5 = {
    'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10,
}

EXCLUDED_COINS = {
    'AI3/USD', 'ALKIMI/USD', 'ANIME/USD', 'CFG/USD', 'DBR/USD',
    'ESX/USD', 'GST/USD', 'HOUSE/USD', 'KET/USD', 'LMWR/USD',
    'MXC/USD', 'ODOS/USD', 'PERP/USD', 'PNUT/USD', 'POLIS/USD',
    'RARI/USD', 'SUKU/USD', 'TANSSI/USD', 'TITCOIN/USD', 'TOSHI/USD',
    'WMTX/USD',
}

REGIMES = ['BULL', 'BEAR', 'SIDEWAYS']


# ---------------------------------------------------------------------------
# Data loading (reuse patterns from time_of_day script)
# ---------------------------------------------------------------------------
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
            print('[ERROR] No cache found')
            sys.exit(1)
        print('[SKIP] No 1H candle cache found.')
        return None
    print('[Load] Loading from per-coin parts...')
    manifest_path = ROOT / 'data' / f'manifest_hf_{timeframe}.json'
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir():
            continue
        for coin_file in sorted(exchange_dir.glob('*.json')):
            symbol = coin_file.stem.replace('_', '/')
            if manifest and symbol in manifest:
                if manifest[symbol].get('status') != 'done':
                    continue
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
    if not coins_data:
        if require_data:
            sys.exit(1)
        return None
    print(f'[Load] {len(coins_data)} coins loaded (from part files)')
    return coins_data


def load_universe_tiering(require_data=False):
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        if require_data:
            sys.exit(1)
        return None
    with open(tiering_path) as f:
        return json.load(f)


def build_tier_coins(tiering, available_coins):
    tier_coins = {'tier1': [], 'tier2': []}
    tb = tiering.get('tier_breakdown', {})
    for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
        if tier_num in tb:
            coins = tb[tier_num].get('coins', [])
            tier_coins[tier_key] = [c for c in coins if c in available_coins]
    return tier_coins


# ---------------------------------------------------------------------------
# BTC Regime Classification
# ---------------------------------------------------------------------------
def find_btc_key(available_coins):
    """Find BTC key in available coins."""
    for candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if candidate in available_coins:
            return candidate
    return None


def fetch_btc_1h_from_kraken():
    """Fetch BTC/USD 1H OHLC from Kraken public API.

    Returns list of candle dicts in the same format as cache parts:
    [{time, open, high, low, close, vwap, volume, count}, ...]
    """
    print('[BTC] Fetching BTC/USD 1H candles from Kraken API...')
    url = 'https://api.kraken.com/0/public/OHLC'
    params = {'pair': 'XXBTZUSD', 'interval': 60}  # 60 min = 1H
    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        if data.get('error') and data['error']:
            print(f'[BTC] Kraken API error: {data["error"]}')
            return None
        result = data.get('result', {})
        key = [k for k in result.keys() if k != 'last'][0]
        raw = result[key]
        candles = []
        for c in raw:
            candles.append({
                'time': int(c[0]),
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'vwap': float(c[5]),
                'volume': float(c[6]),
                'count': int(c[7]),
            })
        print(f'[BTC] Got {len(candles)} candles from Kraken')
        return candles
    except Exception as e:
        print(f'[BTC] Failed to fetch: {e}')
        return None


def align_btc_to_data(btc_candles, data, reference_coin=None):
    """Align BTC candles to the same bar indices as the altcoin data.

    Builds a timestamp->bar_index mapping from a reference coin, then
    maps BTC candles by timestamp. Returns aligned list where index i
    corresponds to bar i in the altcoin data.

    If timestamps don't fully overlap, pads with None for missing bars.
    """
    # Find a reference coin with good data
    if reference_coin is None:
        for coin in sorted(data.keys()):
            if len(data[coin]) >= 700:
                reference_coin = coin
                break
    if reference_coin is None:
        print('[BTC] No reference coin found for alignment')
        return None

    ref_candles = data[reference_coin]
    n_bars = len(ref_candles)

    # Build timestamp -> bar_index for reference
    ts_to_bar = {}
    for i, c in enumerate(ref_candles):
        ts_to_bar[c['time']] = i

    # Build BTC timestamp -> candle
    btc_by_ts = {}
    for c in btc_candles:
        btc_by_ts[c['time']] = c

    # Align
    aligned = [None] * n_bars
    matched = 0
    for ts, bar_idx in ts_to_bar.items():
        if ts in btc_by_ts:
            aligned[bar_idx] = btc_by_ts[ts]
            matched += 1

    print(f'[BTC] Aligned {matched}/{n_bars} bars by timestamp '
          f'(ref={reference_coin}, {n_bars} bars)')

    if matched < n_bars * 0.8:
        print(f'[BTC] WARNING: Low alignment ({matched}/{n_bars}). '
              f'Checking hourly offset...')
        # Try with small hour offsets (+/-1h, +/-2h)
        for offset in [3600, -3600, 7200, -7200]:
            test_matched = 0
            for ts in ts_to_bar:
                if (ts + offset) in btc_by_ts:
                    test_matched += 1
            if test_matched > matched:
                print(f'[BTC] Better match with offset {offset/3600:.0f}h: '
                      f'{test_matched}/{n_bars}')
                aligned = [None] * n_bars
                for ts, bar_idx in ts_to_bar.items():
                    if (ts + offset) in btc_by_ts:
                        aligned[bar_idx] = btc_by_ts[ts + offset]
                matched = test_matched
                break

    return aligned


def classify_btc_regime_from_aligned(aligned_btc, n_bars):
    """Classify each bar into BULL, BEAR, or SIDEWAYS based on aligned BTC candles.

    Rules:
      - Compute 48-bar SMA of BTC close
      - Compute 48-bar return (close[i] / close[i-48] - 1)
      - BULL:     close > SMA AND 48-bar return > +1%
      - BEAR:     close < SMA AND 48-bar return < -1%
      - SIDEWAYS: everything else

    aligned_btc: list of candle dicts or None, indexed by bar.
    Returns list of regime strings, one per bar.
    """
    regimes = ['SIDEWAYS'] * n_bars

    # Extract closes from aligned data, using None for missing bars
    closes = []
    for bar in range(n_bars):
        if bar < len(aligned_btc) and aligned_btc[bar] is not None:
            closes.append(aligned_btc[bar]['close'])
        else:
            closes.append(None)

    for bar in range(SMA_PERIOD, n_bars):
        # Need close at current bar and at bar - RETURN_PERIOD
        if closes[bar] is None:
            continue
        if bar - RETURN_PERIOD < 0 or closes[bar - RETURN_PERIOD] is None:
            continue

        # 48-bar SMA (using bars [bar-47 .. bar]), skip None values
        sma_window = [c for c in closes[bar - SMA_PERIOD + 1: bar + 1] if c is not None]
        if len(sma_window) < SMA_PERIOD * 0.8:  # require 80% coverage
            continue
        sma = sum(sma_window) / len(sma_window)

        # 48-bar return
        ret_48 = (closes[bar] - closes[bar - RETURN_PERIOD]) / closes[bar - RETURN_PERIOD]
        close = closes[bar]

        if close > sma and ret_48 > RETURN_THRESHOLD:
            regimes[bar] = 'BULL'
        elif close < sma and ret_48 < -RETURN_THRESHOLD:
            regimes[bar] = 'BEAR'
        else:
            regimes[bar] = 'SIDEWAYS'

    return regimes


def classify_btc_regime(data, btc_key):
    """Classify each bar into BULL, BEAR, or SIDEWAYS based on BTC price action.

    Wrapper for when BTC is directly in the data dict.
    """
    candles = data.get(btc_key, [])
    n_bars = len(candles)
    if n_bars == 0:
        return []
    return classify_btc_regime_from_aligned(candles, n_bars)


def compute_regime_duration(regimes, total_bars):
    """Compute how many bars and what fraction of time is in each regime."""
    counts = defaultdict(int)
    classifiable = 0
    for bar in range(SMA_PERIOD, total_bars):
        if bar < len(regimes):
            counts[regimes[bar]] += 1
            classifiable += 1
    result = {}
    for regime in REGIMES:
        c = counts.get(regime, 0)
        pct = c / classifiable * 100 if classifiable > 0 else 0
        result[regime] = {
            'bars': c,
            'hours': c,  # 1H candles = 1 bar = 1 hour
            'days': round(c / 24, 1),
            'pct': round(pct, 1),
        }
    result['total_classifiable_bars'] = classifiable
    return result


# ---------------------------------------------------------------------------
# Trade tagging and filtering
# ---------------------------------------------------------------------------
def tag_trade_regime(trade, regimes):
    """Tag a trade with the BTC regime at its entry bar."""
    entry_bar = trade.get('entry_bar', 0)
    if entry_bar < len(regimes):
        return regimes[entry_bar]
    return 'UNKNOWN'


def group_trades_by_regime(trades, regimes):
    """Group trades into regime buckets."""
    grouped = {r: [] for r in REGIMES}
    grouped['UNKNOWN'] = []
    for t in trades:
        regime = tag_trade_regime(t, regimes)
        grouped.get(regime, grouped['UNKNOWN']).append(t)
    return grouped


def filter_trades_by_regime(trades, allowed_regimes, regimes):
    """Keep only trades whose entry regime is in allowed_regimes."""
    kept = []
    removed = []
    for t in trades:
        regime = tag_trade_regime(t, regimes)
        if regime in allowed_regimes:
            kept.append(t)
        else:
            removed.append(t)
    return kept, removed


# ---------------------------------------------------------------------------
# Backtest helpers (identical to time_of_day)
# ---------------------------------------------------------------------------
def run_variant(data, tier_coins, tier_indicators, market_context,
                tier1_fee, tier2_fee, params=None):
    if params is None:
        params = PARAMS_V5
    signal_params = {**params, '__market__': market_context}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    all_trades = []
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=signal_params, indicators=indicators, fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t['_tier'] = tier_name
            t['_fee_per_side'] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_wf(data, tier_coins, tier_indicators, market_context,
           tier1_fee, tier2_fee, n_folds=5, params=None):
    if params is None:
        params = PARAMS_V5
    signal_params = {**params, '__market__': market_context}
    tier_fees = {'tier1': tier1_fee, 'tier2': tier2_fee}
    tier_fold_trades = {}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, tier1_fee)
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=signal_params, indicators=indicators, n_folds=n_folds,
            fee=fee, max_pos=1,
        )
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t['_tier'] = tier_name
                t['_fee_per_side'] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)
    return tier_fold_trades


def compute_metrics(trades, total_bars):
    n_trades = len(trades)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    if n_trades == 0:
        return {'trades': 0, 'pnl': 0.0, 'pf': 0.0, 'wr': 0.0,
                'trades_per_week': 0.0, 'exp_per_week': 0.0,
                'max_dd_pct': 0.0, 'max_gap_days': 0.0, 'expectancy': 0.0}
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
    expectancy = total_pnl / n_trades
    trades_per_week = n_trades / total_weeks
    exp_per_week = expectancy * trades_per_week
    # Drawdown
    equity = 2000.0
    peak = equity
    max_dd = 0.0
    sorted_trades = sorted(trades, key=lambda x: x.get('entry_bar', 0))
    for t in sorted_trades:
        equity += t['pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    # Max gap
    max_gap_bars = 0
    if len(sorted_trades) > 1:
        for i in range(1, len(sorted_trades)):
            gap = sorted_trades[i].get('entry_bar', 0) - sorted_trades[i-1].get('entry_bar', 0)
            if gap > max_gap_bars:
                max_gap_bars = gap
    max_gap_days = max_gap_bars / BARS_PER_DAY
    return {'trades': n_trades, 'pnl': round(total_pnl, 2), 'pf': round(pf, 3),
            'wr': round(wr, 1), 'trades_per_week': round(trades_per_week, 2),
            'exp_per_week': round(exp_per_week, 4), 'max_dd_pct': round(max_dd, 1),
            'max_gap_days': round(max_gap_days, 2), 'expectancy': round(expectancy, 4)}


def evaluate_gates(metrics, wf_folds_positive, n_folds, stress_metrics, fold_conc):
    gates = {}
    g1_val = metrics['trades_per_week']
    gates['G1'] = {'name': 'Trades/week', 'value': g1_val,
                   'threshold': '>= 10', 'pass': g1_val >= 10}
    g2_val = metrics['max_gap_days']
    gates['G2'] = {'name': 'Max gap (days)', 'value': g2_val,
                   'threshold': '<= 2.5', 'pass': g2_val <= 2.5}
    g3_val = metrics['exp_per_week']
    gates['G3'] = {'name': 'Exp/week (market)', 'value': round(g3_val, 2),
                   'threshold': '> $0', 'pass': g3_val > 0}
    g4_val = stress_metrics['exp_per_week']
    gates['G4'] = {'name': 'Exp/week (P95 stress)', 'value': round(g4_val, 2),
                   'threshold': '> $0', 'pass': g4_val > 0}
    g5_val = metrics['max_dd_pct']
    gates['G5'] = {'name': 'Max DD%', 'value': g5_val,
                   'threshold': '<= 20%', 'pass': g5_val <= 20}
    g6_val = wf_folds_positive
    gates['G6'] = {'name': 'WF folds positive', 'value': f'{g6_val}/{n_folds}',
                   'threshold': f'>= 4/{n_folds}', 'pass': g6_val >= 4}
    g8_val = fold_conc['top1_fold_conc_pct']
    gates['G8'] = {'name': 'Top-1 fold conc.', 'value': f'{g8_val}%',
                   'threshold': '< 35%', 'pass': g8_val < 35}
    n_pass = sum(1 for g in gates.values() if g['pass'])
    return {'gates': gates, 'pass_count': n_pass, 'total_count': len(gates),
            'score': f'{n_pass}/{len(gates)}', 'all_pass': n_pass == len(gates)}


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


# ---------------------------------------------------------------------------
# Full gate evaluation helper
# ---------------------------------------------------------------------------
def run_full_gate_eval(label, trades, data, tier_coins, tier_indicators,
                       market_context, tier1_fee, tier2_fee,
                       stress_tier1_fee, stress_tier2_fee, total_bars,
                       regimes=None, allowed_regimes=None):
    """Run metrics + stress + WF + gates for a set of trades.

    For filtered variants, we post-filter stress and WF trades by regime.
    """
    metrics = compute_metrics(trades, total_bars)

    # Stress test
    stress_trades = run_variant(data, tier_coins, tier_indicators, market_context,
                                stress_tier1_fee, stress_tier2_fee)
    if allowed_regimes and regimes:
        stress_trades, _ = filter_trades_by_regime(stress_trades, allowed_regimes, regimes)
    stress_metrics = compute_metrics(stress_trades, total_bars)

    # Walk-forward
    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5)
    folds_positive = 0
    fold_details = []
    for fold_idx in sorted(fold_trades.keys()):
        ft = fold_trades[fold_idx]
        if allowed_regimes and regimes:
            ft, _ = filter_trades_by_regime(ft, allowed_regimes, regimes)
        fold_pnl = sum(t['pnl'] for t in ft)
        fold_n = len(ft)
        is_pos = fold_pnl > 0
        if is_pos:
            folds_positive += 1
        fold_details.append({'fold': fold_idx, 'trades': fold_n,
                            'pnl': round(fold_pnl, 2), 'positive': is_pos})

    # Fold concentration
    fold_pnls_dict = {}
    for fd in fold_details:
        fold_pnls_dict[fd['fold']] = fd['pnl']
    positive_total = sum(max(0, p) for p in fold_pnls_dict.values())
    if positive_total > 0:
        max_fold_pnl = max(fold_pnls_dict.values())
        top1_fold_conc = max(0, max_fold_pnl) / positive_total * 100
    else:
        top1_fold_conc = 100.0
    fold_conc = {
        'top1_fold_conc_pct': round(top1_fold_conc, 1),
        'fold_pnls': {k: round(v, 2) for k, v in fold_pnls_dict.items()},
    }

    gate_eval = evaluate_gates(metrics, folds_positive, 5, stress_metrics, fold_conc)

    return {
        'label': label,
        'metrics': metrics,
        'stress_metrics': {
            'trades': stress_metrics['trades'],
            'pnl': stress_metrics['pnl'],
            'pf': stress_metrics['pf'],
            'exp_per_week': stress_metrics['exp_per_week'],
        },
        'wf_folds_positive': folds_positive,
        'wf_fold_details': fold_details,
        'fold_concentration': fold_conc,
        'gate_evaluation': gate_eval,
    }


# ---------------------------------------------------------------------------
# Per-regime metrics
# ---------------------------------------------------------------------------
def compute_regime_stats(grouped_trades, total_bars):
    """Compute detailed metrics per regime."""
    stats = {}
    for regime in REGIMES:
        trades = grouped_trades.get(regime, [])
        n = len(trades)
        if n == 0:
            stats[regime] = {
                'regime': regime, 'trades': 0, 'wins': 0, 'losses': 0,
                'wr': 0.0, 'total_pnl': 0.0, 'avg_pnl': 0.0, 'pf': 0.0,
                'worst_trade': None, 'best_trade': None,
                'avg_pnl_pct': 0.0, 'median_pnl': 0.0,
            }
            continue

        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in trades)
        tw = sum(t['pnl'] for t in wins)
        tl = abs(sum(t['pnl'] for t in losses))
        pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
        avg_pnl = total_pnl / n
        avg_pnl_pct = sum(t.get('pnl_pct', 0) for t in trades) / n

        # Sorted P&Ls for worst/best/median
        pnls = sorted([t['pnl'] for t in trades])
        median_pnl = pnls[len(pnls) // 2]

        worst_trade = min(trades, key=lambda t: t['pnl'])
        best_trade = max(trades, key=lambda t: t['pnl'])

        stats[regime] = {
            'regime': regime,
            'trades': n,
            'wins': len(wins),
            'losses': len(losses),
            'wr': round(len(wins) / n * 100, 1),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 2),
            'pf': round(pf, 3) if pf != float('inf') else 999.0,
            'worst_trade': {
                'pair': worst_trade['pair'],
                'pnl': round(worst_trade['pnl'], 2),
                'pnl_pct': round(worst_trade.get('pnl_pct', 0), 2),
                'reason': worst_trade['reason'],
                'entry_bar': worst_trade['entry_bar'],
            },
            'best_trade': {
                'pair': best_trade['pair'],
                'pnl': round(best_trade['pnl'], 2),
                'pnl_pct': round(best_trade.get('pnl_pct', 0), 2),
                'reason': best_trade['reason'],
                'entry_bar': best_trade['entry_bar'],
            },
            'avg_pnl_pct': round(avg_pnl_pct, 2),
            'median_pnl': round(median_pnl, 2),
        }
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Part 2 Agent C5-A3: BTC Regime Analysis',
    )
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--require-data', action='store_true')
    args = parser.parse_args()

    print('=' * 70)
    print('  Part 2 -- BTC Regime Analysis (Agent C5-A3)')
    print('  Objective: Correlate trade P&L with BTC market regime')
    print('=' * 70)
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0_total = time.time()

    # --- Cost model ---
    tier1_fee = get_harness_fee('mexc_market', 'tier1')
    tier2_fee = get_harness_fee('mexc_market', 'tier2')
    stress_tier1_fee = tier1_fee * 2
    stress_tier2_fee = tier2_fee * 2
    print(f'[Costs] Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps')
    print(f'[Costs] Stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps')

    # --- Commit hash ---
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = 'unknown'

    # --- Load data ---
    data = load_candle_cache('1h', require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins_full = build_tier_coins(tiering, available_coins)

    # --- Apply exclusion (295-coin universe) ---
    tier_coins = {
        'tier1': [c for c in tier_coins_full['tier1'] if c not in EXCLUDED_COINS],
        'tier2': [c for c in tier_coins_full['tier2'] if c not in EXCLUDED_COINS],
    }
    n_t1 = len(tier_coins['tier1'])
    n_t2 = len(tier_coins['tier2'])
    n_total = n_t1 + n_t2
    print(f'[Universe] T1={n_t1}, T2={n_t2}, total={n_total} (excl {len(EXCLUDED_COINS)} coins)')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins available.')
        sys.exit(1 if args.require_data else 0)

    # --- Find or fetch BTC data ---
    btc_key = find_btc_key(available_coins)
    btc_fetched_from_api = False
    aligned_btc = None
    if btc_key is not None:
        btc_bars = len(data.get(btc_key, []))
        print(f'[BTC] Key={btc_key}, bars={btc_bars} (from cache)')
    else:
        print('[BTC] BTC not found in 1H cache. Fetching from Kraken API...')
        btc_candles = fetch_btc_1h_from_kraken()
        if btc_candles is None or len(btc_candles) < 100:
            print('[ERROR] Could not fetch BTC 1H data from Kraken!')
            sys.exit(1)
        aligned_btc = align_btc_to_data(btc_candles, data)
        if aligned_btc is None:
            print('[ERROR] Could not align BTC data to altcoin bars!')
            sys.exit(1)
        btc_bars = sum(1 for c in aligned_btc if c is not None)
        btc_key = 'BTC/USD (fetched)'
        btc_fetched_from_api = True
        print(f'[BTC] Key=BTC/USD (API), aligned bars={btc_bars}')

    if args.dry_run:
        print('\n--- DRY RUN ---')
        print(f'  Universe: T1={n_t1}, T2={n_t2}, total={n_total}')
        print(f'  BTC key: {btc_key}, bars: {btc_bars}, fetched={btc_fetched_from_api}')
        print(f'  Params: {PARAMS_V5}')
        print(f'  Regime: SMA({SMA_PERIOD}) + return({RETURN_PERIOD}) > +/-{RETURN_THRESHOLD*100}%')
        sys.exit(0)

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    print('[Indicators] Extending with VWAP fields...')
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]})')

    # --- Market context ---
    print('[Market Context] Precomputing...')
    all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
    for btc_c in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_c in available_coins and btc_c not in all_coins:
            all_coins.append(btc_c)
    market_context = precompute_market_context(data, all_coins)
    print('  Done.')

    # Inject __coin__
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK
    print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

    # ============================================================
    # STEP 1: Classify BTC regime
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 1: Classify BTC regime (SMA-48 + 48-bar return)')
    print('=' * 70)

    if btc_fetched_from_api:
        regimes = classify_btc_regime_from_aligned(aligned_btc, total_bars)
    else:
        regimes = classify_btc_regime(data, btc_key)
    regime_duration = compute_regime_duration(regimes, total_bars)

    print(f'  BTC bars classified: {len(regimes)}')
    for r in REGIMES:
        d = regime_duration[r]
        print(f'    {r:8s}: {d["bars"]:4d} bars ({d["days"]:.1f} days, {d["pct"]:.1f}%)')

    # ============================================================
    # STEP 2: Full baseline backtest
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 2: Full v5 baseline backtest on 295 coins')
    print('=' * 70)

    baseline_trades = run_variant(data, tier_coins, tier_indicators,
                                   market_context, tier1_fee, tier2_fee)
    baseline_metrics = compute_metrics(baseline_trades, total_bars)
    print(f'  Baseline: {baseline_metrics["trades"]} trades, '
          f'PF={baseline_metrics["pf"]:.3f}, P&L=${baseline_metrics["pnl"]:.2f}, '
          f'exp/w=${baseline_metrics["exp_per_week"]:.2f}')

    # ============================================================
    # STEP 3: Per-regime breakdown
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 3: Per-regime breakdown')
    print('=' * 70)

    grouped = group_trades_by_regime(baseline_trades, regimes)
    regime_stats = compute_regime_stats(grouped, total_bars)

    unknown_count = len(grouped.get('UNKNOWN', []))
    if unknown_count > 0:
        print(f'  WARNING: {unknown_count} trades could not be mapped to a regime')

    print(f'\n  {"Regime":>10s} {"Trades":>6s} {"Wins":>5s} {"WR%":>6s} '
          f'{"TotP&L":>9s} {"AvgP&L":>8s} {"PF":>7s} {"MedP&L":>8s}')
    print(f'  {"------":>10s} {"------":>6s} {"-----":>5s} {"------":>6s} '
          f'{"---------":>9s} {"--------":>8s} {"-------":>7s} {"--------":>8s}')
    for r in REGIMES:
        s = regime_stats[r]
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        print(f'  {r:>10s} {s["trades"]:6d} {s["wins"]:5d} {s["wr"]:5.1f}% '
              f'{s["total_pnl"]:+9.2f} {s["avg_pnl"]:+8.2f} {pf_str:>7s} '
              f'{s["median_pnl"]:+8.2f}')

    # Print worst trades per regime
    print('\n  Worst trades per regime:')
    for r in REGIMES:
        s = regime_stats[r]
        if s['worst_trade']:
            wt = s['worst_trade']
            print(f'    {r}: {wt["pair"]} ${wt["pnl"]:+.2f} ({wt["pnl_pct"]:+.1f}%) '
                  f'reason={wt["reason"]} bar={wt["entry_bar"]}')

    # ============================================================
    # STEP 4: Walk-forward per-regime breakdown
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 4: Walk-forward per-regime breakdown')
    print('=' * 70)

    fold_trades = run_wf(data, tier_coins, tier_indicators, market_context,
                         tier1_fee, tier2_fee, n_folds=5)
    wf_regime_breakdown = {}
    for fold_idx in sorted(fold_trades.keys()):
        ft = fold_trades[fold_idx]
        fold_grouped = group_trades_by_regime(ft, regimes)
        fold_regime_data = {}
        for r in REGIMES:
            rt = fold_grouped.get(r, [])
            n = len(rt)
            pnl = sum(t['pnl'] for t in rt)
            wins = sum(1 for t in rt if t['pnl'] > 0)
            fold_regime_data[r] = {
                'trades': n,
                'pnl': round(pnl, 2),
                'wr': round(wins / n * 100, 1) if n > 0 else 0.0,
            }
        total_fold_pnl = sum(t['pnl'] for t in ft)
        fold_regime_data['_total'] = {
            'trades': len(ft),
            'pnl': round(total_fold_pnl, 2),
        }
        wf_regime_breakdown[fold_idx] = fold_regime_data

    # Print WF regime table
    print(f'\n  {"Fold":>4s} | ', end='')
    for r in REGIMES:
        print(f' {r:>10s} (tr/pnl) |', end='')
    print(f' {"TOTAL":>10s} |')
    print(f'  {"----":>4s} | ', end='')
    for _ in REGIMES:
        print(f' {"-"*20} |', end='')
    print(f' {"-"*10} |')
    for fold_idx in sorted(wf_regime_breakdown.keys()):
        fd = wf_regime_breakdown[fold_idx]
        print(f'  {fold_idx:4d} | ', end='')
        for r in REGIMES:
            rd = fd[r]
            print(f' {rd["trades"]:3d} / ${rd["pnl"]:+8.2f} |', end='')
        total = fd['_total']
        print(f' {total["trades"]:3d}/${total["pnl"]:+7.2f} |')

    # ============================================================
    # STEP 5: Full baseline gate evaluation
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 5: Full baseline gate evaluation')
    print('=' * 70)

    full_eval = run_full_gate_eval(
        label='v5_full',
        trades=baseline_trades,
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        tier1_fee=tier1_fee, tier2_fee=tier2_fee,
        stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
        total_bars=total_bars,
    )
    full_ge = full_eval['gate_evaluation']
    print(f'  Gates: {full_ge["score"]}')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = full_ge['gates'][gid]
        status = 'PASS' if g['pass'] else 'FAIL'
        print(f'    {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

    # ============================================================
    # STEP 6: Conditional filter tests
    # ============================================================
    print('\n' + '=' * 70)
    print('  STEP 6: Conditional filter tests')
    print('=' * 70)

    filter_configs = [
        ('no_bear', 'No BTC BEAR trades', {'BULL', 'SIDEWAYS'}),
        ('bull_only', 'Only BTC BULL trades', {'BULL'}),
        ('sideways_only', 'Only SIDEWAYS trades', {'SIDEWAYS'}),
    ]

    filter_evals = {}
    for filter_id, filter_desc, allowed in filter_configs:
        print(f'\n  --- {filter_desc} (allowed={allowed}) ---')

        filtered_trades, removed = filter_trades_by_regime(
            baseline_trades, allowed, regimes)
        print(f'  Kept: {len(filtered_trades)} trades, Removed: {len(removed)} trades')

        if len(filtered_trades) == 0:
            print(f'  SKIP: No trades remain after filtering')
            filter_evals[filter_id] = {
                'label': filter_id,
                'description': filter_desc,
                'allowed_regimes': sorted(allowed),
                'trades_kept': 0,
                'trades_removed': len(removed),
                'metrics': compute_metrics([], total_bars),
                'gate_evaluation': None,
                'skip_reason': 'No trades remain after filtering',
            }
            continue

        filt_eval = run_full_gate_eval(
            label=filter_id,
            trades=filtered_trades,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            tier1_fee=tier1_fee, tier2_fee=tier2_fee,
            stress_tier1_fee=stress_tier1_fee, stress_tier2_fee=stress_tier2_fee,
            total_bars=total_bars,
            regimes=regimes,
            allowed_regimes=allowed,
        )
        filt_ge = filt_eval['gate_evaluation']
        print(f'  Gates: {filt_ge["score"]}')
        for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
            g = filt_ge['gates'][gid]
            status = 'PASS' if g['pass'] else 'FAIL'
            print(f'    {gid}: {g["name"]} = {g["value"]}  ({g["threshold"]}) -> {status}')

        filter_evals[filter_id] = {
            'label': filter_id,
            'description': filter_desc,
            'allowed_regimes': sorted(allowed),
            'trades_kept': len(filtered_trades),
            'trades_removed': len(removed),
            'metrics': filt_eval['metrics'],
            'stress_metrics': filt_eval['stress_metrics'],
            'wf_folds_positive': filt_eval['wf_folds_positive'],
            'wf_fold_details': filt_eval['wf_fold_details'],
            'fold_concentration': filt_eval['fold_concentration'],
            'gate_evaluation': filt_eval['gate_evaluation'],
        }

    elapsed_total = time.time() - t0_total

    # ============================================================
    # Build JSON report
    # ============================================================
    regime_stats_list = [regime_stats[r] for r in REGIMES]

    report = {
        'run_header': {
            'task': 'part2_btc_regime',
            'agent': 'C5-A3',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'commit': commit,
            'hypothesis': 'H20_VWAP_DEVIATION',
            'params': PARAMS_V5,
            'cost_regime': 'MEXC Market',
            'fees_bps': {
                'tier1': round(tier1_fee * 10000, 1),
                'tier2': round(tier2_fee * 10000, 1),
            },
            'stress_fees_bps': {
                'tier1': round(stress_tier1_fee * 10000, 1),
                'tier2': round(stress_tier2_fee * 10000, 1),
            },
            'universe': f'T1({n_t1})+T2({n_t2})',
            'universe_total': n_total,
            'excluded_coins': sorted(EXCLUDED_COINS),
            'timeframe': '1h',
            'total_bars': total_bars,
            'total_weeks': round(total_weeks, 1),
            'runtime_s': round(elapsed_total, 1),
        },
        'btc_regime_config': {
            'btc_key': btc_key,
            'btc_bars': btc_bars,
            'sma_period': SMA_PERIOD,
            'return_period': RETURN_PERIOD,
            'return_threshold_pct': RETURN_THRESHOLD * 100,
        },
        'regime_duration': regime_duration,
        'baseline_metrics': baseline_metrics,
        'regime_breakdown': regime_stats_list,
        'wf_regime_breakdown': {str(k): v for k, v in wf_regime_breakdown.items()},
        'full_evaluation': full_eval,
        'filter_evaluations': filter_evals,
        'verdict': {},
    }

    # --- Build verdict ---
    # Check if BEAR regime is clearly negative
    bear_stats = regime_stats.get('BEAR', {})
    bull_stats = regime_stats.get('BULL', {})
    side_stats = regime_stats.get('SIDEWAYS', {})

    bear_pnl = bear_stats.get('total_pnl', 0)
    bear_trades = bear_stats.get('trades', 0)
    bull_pnl = bull_stats.get('total_pnl', 0)
    side_pnl = side_stats.get('total_pnl', 0)

    # Check if filtering helps gates
    no_bear_eval = filter_evals.get('no_bear', {})
    no_bear_ge = no_bear_eval.get('gate_evaluation')
    full_gates = full_eval['gate_evaluation']['pass_count']

    if no_bear_ge:
        no_bear_gates = no_bear_ge['pass_count']
    else:
        no_bear_gates = 0

    # Determine verdict
    if bear_pnl < 0 and bear_trades >= 3:
        bear_is_negative = True
        bear_impact = f'BEAR trades: {bear_trades} trades, ${bear_pnl:+.2f} total P&L'
    else:
        bear_is_negative = False
        bear_impact = f'BEAR trades: {bear_trades} trades, ${bear_pnl:+.2f} total P&L (NOT consistently negative)'

    if no_bear_ge and no_bear_gates > full_gates:
        filter_helps = True
        filter_verdict = (f'IMPROVEMENT: Removing BEAR trades improves gates from '
                         f'{full_gates}/7 to {no_bear_gates}/7')
    elif no_bear_ge and no_bear_gates == full_gates:
        no_bear_exp = no_bear_eval.get('metrics', {}).get('exp_per_week', 0)
        full_exp = full_eval['metrics']['exp_per_week']
        if no_bear_exp > full_exp * 1.05:
            filter_helps = True
            filter_verdict = (f'MARGINAL: Same gates ({full_gates}/7), but exp/wk '
                             f'improves ${full_exp:.2f} -> ${no_bear_exp:.2f}')
        else:
            filter_helps = False
            filter_verdict = (f'NO BENEFIT: Same gates ({full_gates}/7) and similar exp/wk')
    else:
        filter_helps = False
        filter_verdict = (f'REGRESSION or NO DATA: Filtering BEAR trades does not help')

    # Overall assessment
    regime_concentration = max(regime_duration[r]['pct'] for r in REGIMES)
    dominant_regime = max(REGIMES, key=lambda r: regime_duration[r]['pct'])

    verdict_text = (
        f'{bear_impact}. '
        f'{filter_verdict}. '
        f'Dominant regime: {dominant_regime} ({regime_concentration:.0f}% of time). '
        f'Regime concentration risk: {"HIGH" if regime_concentration > 60 else "MODERATE" if regime_concentration > 40 else "LOW"}.'
    )

    report['verdict'] = {
        'text': verdict_text,
        'bear_is_negative': bear_is_negative,
        'filter_helps': filter_helps,
        'dominant_regime': dominant_regime,
        'regime_concentration_pct': regime_concentration,
        'recommendation': (
            'BTC regime filtering WORTH PURSUING' if filter_helps
            else 'BTC regime filtering NOT recommended -- signal is regime-robust'
        ),
    }

    json_path = ROOT / 'reports' / 'hf' / 'part2_btc_regime_001.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f'\n[Report] JSON: {json_path}')

    # ============================================================
    # Markdown report
    # ============================================================
    md = []
    md.append('# Part 2 -- BTC Regime Analysis (Agent C5-A3)')
    md.append('')
    md.append(f'**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    md.append(f'**Commit**: {commit}')
    md.append(f'**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins (295-coin universe)')
    md.append(f'**Params**: dev={PARAMS_V5["dev_thresh"]}, tp={PARAMS_V5["tp_pct"]}, '
              f'sl={PARAMS_V5["sl_pct"]}, tl={PARAMS_V5["time_limit"]}')
    md.append(f'**Fees**: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps '
              f'(stress 2x: T1={stress_tier1_fee*10000:.1f}bps, T2={stress_tier2_fee*10000:.1f}bps)')
    md.append(f'**Runtime**: {elapsed_total:.1f}s')
    md.append('')

    # Regime definition
    md.append('## 1. BTC Regime Definition')
    md.append('')
    md.append(f'- **SMA Period**: {SMA_PERIOD} bars (2 days)')
    md.append(f'- **Return Period**: {RETURN_PERIOD} bars')
    md.append(f'- **Return Threshold**: +/-{RETURN_THRESHOLD*100:.0f}%')
    md.append(f'- **BTC Key**: {btc_key} ({btc_bars} bars)')
    md.append('')
    md.append('| Regime | Definition |')
    md.append('|--------|-----------|')
    md.append('| BULL | BTC close > SMA(48) AND 48-bar return > +1% |')
    md.append('| BEAR | BTC close < SMA(48) AND 48-bar return < -1% |')
    md.append('| SIDEWAYS | Everything else |')
    md.append('')

    # Regime duration
    md.append('## 2. Regime Duration')
    md.append('')
    md.append('| Regime | Bars | Days | % of Time |')
    md.append('|--------|------|------|-----------|')
    for r in REGIMES:
        d = regime_duration[r]
        md.append(f'| {r} | {d["bars"]} | {d["days"]:.1f} | {d["pct"]:.1f}% |')
    md.append(f'| *Total classifiable* | {regime_duration["total_classifiable_bars"]} | '
              f'{regime_duration["total_classifiable_bars"]/24:.1f} | 100% |')
    md.append('')
    md.append(f'**Dominant regime**: {dominant_regime} ({regime_concentration:.1f}%)')
    if regime_concentration > 60:
        md.append(f'  -- WARNING: High regime concentration risk. '
                  f'Most of the data is in one regime.')
    md.append('')

    # Baseline summary
    md.append('## 3. Baseline Summary')
    md.append('')
    md.append(f'- Trades: {baseline_metrics["trades"]}')
    md.append(f'- P&L: ${baseline_metrics["pnl"]:.2f}')
    md.append(f'- PF: {baseline_metrics["pf"]:.3f}')
    md.append(f'- WR: {baseline_metrics["wr"]:.1f}%')
    md.append(f'- Exp/week: ${baseline_metrics["exp_per_week"]:.2f}')
    md.append('')

    # Per-regime breakdown
    md.append('## 4. Per-Regime Performance')
    md.append('')
    md.append('| Regime | Trades | Wins | WR% | Total P&L | Avg P&L | PF | Median P&L |')
    md.append('|--------|--------|------|-----|-----------|---------|-----|------------|')
    for r in REGIMES:
        s = regime_stats[r]
        pf_str = f'{s["pf"]:.2f}' if s['pf'] < 900 else 'inf'
        md.append(f'| {r} | {s["trades"]} | {s["wins"]} | {s["wr"]:.1f}% '
                  f'| ${s["total_pnl"]:+.2f} | ${s["avg_pnl"]:+.2f} '
                  f'| {pf_str} | ${s["median_pnl"]:+.2f} |')
    md.append('')

    # Worst/best trades per regime
    md.append('### Worst and Best Trades per Regime')
    md.append('')
    md.append('| Regime | Worst Trade | Worst P&L | Best Trade | Best P&L |')
    md.append('|--------|------------|-----------|------------|----------|')
    for r in REGIMES:
        s = regime_stats[r]
        if s['worst_trade'] and s['best_trade']:
            wt = s['worst_trade']
            bt = s['best_trade']
            md.append(f'| {r} | {wt["pair"]} ({wt["reason"]}) | ${wt["pnl"]:+.2f} '
                      f'| {bt["pair"]} ({bt["reason"]}) | ${bt["pnl"]:+.2f} |')
        else:
            md.append(f'| {r} | -- | -- | -- | -- |')
    md.append('')

    # WF regime breakdown
    md.append('## 5. Walk-Forward by Regime')
    md.append('')
    header = '| Fold |'
    for r in REGIMES:
        header += f' {r} Trades | {r} P&L |'
    header += ' Total P&L |'
    md.append(header)
    sep = '|------|'
    for _ in REGIMES:
        sep += '--------|---------|'
    sep += '-----------|'
    md.append(sep)
    for fold_idx in sorted(wf_regime_breakdown.keys()):
        fd = wf_regime_breakdown[fold_idx]
        row = f'| {fold_idx} |'
        for r in REGIMES:
            rd = fd[r]
            row += f' {rd["trades"]} | ${rd["pnl"]:+.2f} |'
        total = fd['_total']
        row += f' ${total["pnl"]:+.2f} |'
        md.append(row)
    md.append('')

    # Full baseline gate evaluation
    md.append('## 6. Full Baseline Gate Evaluation')
    md.append('')
    md.append('| Gate | Metric | Value | Threshold | Verdict |')
    md.append('|------|--------|-------|-----------|---------|')
    for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
        g = full_ge['gates'][gid]
        status = 'PASS' if g['pass'] else '**FAIL**'
        md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
    md.append('')
    fm = full_eval['metrics']
    md.append(f'**Metrics**: {fm["trades"]} trades, PF={fm["pf"]:.3f}, '
              f'exp/wk=${fm["exp_per_week"]:.2f}, DD={fm["max_dd_pct"]:.1f}%')
    md.append(f'**Stress**: PF={full_eval["stress_metrics"]["pf"]:.3f}, '
              f'exp/wk=${full_eval["stress_metrics"]["exp_per_week"]:.2f}')
    md.append(f'**Walk-Forward**: {full_eval["wf_folds_positive"]}/5 folds positive')
    md.append('')

    # Conditional filter tests
    md.append('## 7. Conditional Filter Tests')
    md.append('')
    for filter_id, filter_desc, allowed in filter_configs:
        fe = filter_evals.get(filter_id, {})
        md.append(f'### {filter_desc}')
        md.append('')
        md.append(f'- Allowed regimes: {sorted(allowed)}')
        md.append(f'- Trades kept: {fe.get("trades_kept", 0)}, '
                  f'removed: {fe.get("trades_removed", 0)}')
        md.append('')

        if fe.get('skip_reason'):
            md.append(f'**SKIPPED**: {fe["skip_reason"]}')
            md.append('')
            continue

        fe_ge = fe.get('gate_evaluation')
        if fe_ge:
            md.append('| Gate | Metric | Value | Threshold | Verdict |')
            md.append('|------|--------|-------|-----------|---------|')
            for gid in ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G8']:
                g = fe_ge['gates'][gid]
                status = 'PASS' if g['pass'] else '**FAIL**'
                md.append(f'| {gid} | {g["name"]} | {g["value"]} | {g["threshold"]} | {status} |')
            md.append('')
            fe_m = fe.get('metrics', {})
            md.append(f'**Metrics**: {fe_m.get("trades", 0)} trades, '
                      f'PF={fe_m.get("pf", 0):.3f}, '
                      f'exp/wk=${fe_m.get("exp_per_week", 0):.2f}, '
                      f'DD={fe_m.get("max_dd_pct", 0):.1f}%')
            fe_sm = fe.get('stress_metrics', {})
            md.append(f'**Stress**: PF={fe_sm.get("pf", 0):.3f}, '
                      f'exp/wk=${fe_sm.get("exp_per_week", 0):.2f}')
            md.append(f'**Walk-Forward**: {fe.get("wf_folds_positive", 0)}/5 folds positive')
            md.append(f'**Gates**: {fe_ge["score"]}')
            md.append('')

    # Comparison table
    md.append('### Comparison: Full vs Filtered Variants')
    md.append('')
    md.append('| Variant | Trades | P&L | PF | WR% | Exp/wk | DD% | Gates |')
    md.append('|---------|--------|-----|-----|------|--------|-----|-------|')
    md.append(f'| Full baseline | {fm["trades"]} | ${fm["pnl"]:.2f} | {fm["pf"]:.3f} '
              f'| {fm["wr"]:.1f} | ${fm["exp_per_week"]:.2f} | {fm["max_dd_pct"]:.1f} '
              f'| {full_ge["score"]} |')
    for filter_id, filter_desc, allowed in filter_configs:
        fe = filter_evals.get(filter_id, {})
        fe_m = fe.get('metrics', {})
        fe_ge = fe.get('gate_evaluation')
        if fe_ge:
            md.append(f'| {filter_desc} | {fe_m.get("trades", 0)} '
                      f'| ${fe_m.get("pnl", 0):.2f} | {fe_m.get("pf", 0):.3f} '
                      f'| {fe_m.get("wr", 0):.1f} | ${fe_m.get("exp_per_week", 0):.2f} '
                      f'| {fe_m.get("max_dd_pct", 0):.1f} | {fe_ge["score"]} |')
        else:
            md.append(f'| {filter_desc} | 0 | -- | -- | -- | -- | -- | N/A |')
    md.append('')

    # Verdict
    md.append('## 8. Verdict')
    md.append('')
    md.append(f'**{report["verdict"]["text"]}**')
    md.append('')
    md.append(f'**Recommendation**: {report["verdict"]["recommendation"]}')
    md.append('')

    # Interpretation
    md.append('### Interpretation')
    md.append('')
    if bear_is_negative:
        md.append(f'- BEAR regime trades are net negative (${bear_pnl:+.2f}), '
                  f'suggesting the signal struggles during sustained BTC downtrends.')
    else:
        md.append(f'- BEAR regime trades are NOT consistently negative '
                  f'(${bear_pnl:+.2f}), suggesting the signal works across all regimes.')
    md.append(f'- BULL regime trades: ${bull_pnl:+.2f}')
    md.append(f'- SIDEWAYS regime trades: ${side_pnl:+.2f}')
    md.append(f'- Dominant regime ({dominant_regime}) accounts for '
              f'{regime_concentration:.0f}% of classifiable bars.')
    if regime_concentration > 60:
        md.append(f'- HIGH regime concentration: results may be '
                  f'disproportionately driven by {dominant_regime} regime performance.')
    md.append('')

    md.append('---')
    md.append(f'*Generated by run_part2_btc_regime.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}*')

    md_path = ROOT / 'reports' / 'hf' / 'part2_btc_regime_001.md'
    md_path.write_text('\n'.join(md))
    print(f'[Report] MD:   {md_path}')

    # Final summary
    print(f'\n{"=" * 70}')
    print(f'  COMPLETE: BTC Regime Analysis')
    print(f'  Baseline: {baseline_metrics["trades"]} trades, PF={baseline_metrics["pf"]:.3f}')
    print(f'  Regime duration: BULL={regime_duration["BULL"]["pct"]:.0f}%, '
          f'BEAR={regime_duration["BEAR"]["pct"]:.0f}%, '
          f'SIDEWAYS={regime_duration["SIDEWAYS"]["pct"]:.0f}%')
    for r in REGIMES:
        s = regime_stats[r]
        print(f'  {r}: {s["trades"]} trades, ${s["total_pnl"]:+.2f} P&L, '
              f'WR={s["wr"]:.0f}%, PF={s["pf"]:.2f}')
    print(f'  Full gates: {full_ge["score"]}')
    for filter_id, filter_desc, _ in filter_configs:
        fe = filter_evals.get(filter_id, {})
        fe_ge = fe.get('gate_evaluation')
        if fe_ge:
            print(f'  {filter_desc} gates: {fe_ge["score"]}')
    print(f'  Verdict: {report["verdict"]["recommendation"]}')
    print(f'  Runtime: {elapsed_total:.1f}s')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()
