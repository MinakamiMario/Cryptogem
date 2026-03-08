#!/usr/bin/env python3
"""
Phase 0 — Market Structure Pattern Frequency Pre-Count.

Validates that MS structural patterns occur at sufficient frequency
on 1m XRP/USDT data (43K bars) before building hypotheses.

Uses FAST inline counting (no snapshot tracking) for O(n) performance.
The full snapshot-based functions are only needed during backtesting.

GO gate: ≥2 pattern types with ≥100 events.

Usage:
    python scripts/run_scalp_ms_precount.py
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.indicators import _calc_atr
from strategies.ms.indicators import (
    calc_swing_lows,
    calc_swing_highs,
    calc_break_of_structure,
)

# ─── Config ─────────────────────────────────────────────
DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'
OUT_DIR = Path.home() / 'CryptogemData' / 'scalp' / 'ms'
DATA_FILE = DATA_DIR / 'XRP_USDT_1m.json'

SWING_COMBOS = [
    (2, 1),   # fastest — most patterns, most noise
    (3, 1),   # recommended starting point
    (5, 2),   # 4H default — fewer but more reliable
]

FVG_THRESHOLDS = [0.2, 0.3, 0.5]
OB_THRESHOLDS = [1.0, 1.5, 2.0]
LIQ_TOLERANCES = [0.3, 0.5]

GATE_THRESHOLD = 100


def count_non_none(arr: list) -> int:
    return sum(1 for x in arr if x is not None)


def count_bullish_bos(bos_list: list) -> int:
    return sum(1 for b in bos_list if b is not None and b.direction == 'bullish')


def count_bearish_bos(bos_list: list) -> int:
    return sum(1 for b in bos_list if b is not None and b.direction == 'bearish')


# ─── FAST inline counters (O(n), no snapshot tracking) ─────

def count_fvgs_fast(highs, lows, closes, atr, min_gap_atr):
    """Count FVG creation events without building snapshot lists."""
    n = len(highs)
    bull = 0
    bear = 0
    for bar in range(2, n):
        cur_atr = atr[bar]
        if cur_atr is None or cur_atr <= 0:
            continue
        # Bullish FVG: highs[bar-2] < lows[bar]
        if highs[bar - 2] < lows[bar]:
            gap = lows[bar] - highs[bar - 2]
            if gap >= min_gap_atr * cur_atr:
                bull += 1
        # Bearish FVG: lows[bar-2] > highs[bar]
        if lows[bar - 2] > highs[bar]:
            gap = lows[bar - 2] - highs[bar]
            if gap >= min_gap_atr * cur_atr:
                bear += 1
    return bull, bear


def count_obs_fast(opens, highs, lows, closes, atr, min_impulse_atr, lookback_impulse=3):
    """Count Order Block creation events without building snapshot lists."""
    n = len(opens)
    bull = 0
    bear = 0
    seen_bull = set()
    seen_bear = set()

    for bar in range(lookback_impulse + 1, n):
        cur_atr = atr[bar]
        if cur_atr is None or cur_atr <= 0:
            continue

        impulse_start = bar - lookback_impulse + 1
        impulse_high = max(highs[i] for i in range(impulse_start, bar + 1))
        impulse_low = min(lows[i] for i in range(impulse_start, bar + 1))

        # Bullish OB: last bearish candle before impulse
        for ob_bar in range(impulse_start - 1, max(impulse_start - 10, -1), -1):
            if ob_bar < 0:
                break
            if closes[ob_bar] < opens[ob_bar]:
                impulse_size = impulse_high - closes[ob_bar]
                if impulse_size / cur_atr >= min_impulse_atr:
                    if ob_bar not in seen_bull:
                        seen_bull.add(ob_bar)
                        bull += 1
                break

        # Bearish OB: last bullish candle before bearish impulse
        for ob_bar in range(impulse_start - 1, max(impulse_start - 10, -1), -1):
            if ob_bar < 0:
                break
            if closes[ob_bar] > opens[ob_bar]:
                impulse_size = closes[ob_bar] - impulse_low
                if impulse_size / cur_atr >= min_impulse_atr:
                    if ob_bar not in seen_bear:
                        seen_bear.add(ob_bar)
                        bear += 1
                break

    return bull, bear


def count_liq_zones_fast(swing_lows, swing_highs, atr, tolerance_atr, min_touches):
    """Count liquidity zone formation events."""
    n = len(swing_lows)

    def _cluster(swings, direction):
        zones = 0
        confirmed_swings = [(i, swings[i]) for i in range(n) if swings[i] is not None]
        # Group nearby swing prices into clusters
        if not confirmed_swings:
            return 0
        clusters = []
        for bar_idx, price in confirmed_swings:
            cur_atr = atr[bar_idx]
            if cur_atr is None or cur_atr <= 0:
                continue
            tol = tolerance_atr * cur_atr
            merged = False
            for cluster in clusters:
                if abs(price - cluster['avg_price']) <= tol:
                    cluster['touches'] += 1
                    cluster['avg_price'] = (cluster['avg_price'] * (cluster['touches'] - 1) + price) / cluster['touches']
                    merged = True
                    break
            if not merged:
                clusters.append({'avg_price': price, 'touches': 1})
        return sum(1 for c in clusters if c['touches'] >= min_touches)

    low_zones = _cluster(swing_lows, 'low')
    high_zones = _cluster(swing_highs, 'high')
    return low_zones, high_zones


def main():
    print('=' * 80)
    print('Phase 0: Market Structure Pattern Frequency Pre-Count')
    print('=' * 80)

    if not DATA_FILE.exists():
        print(f'[ERROR] Data not found: {DATA_FILE}')
        sys.exit(1)

    print(f'\nLoading candles from {DATA_FILE}...')
    with open(DATA_FILE) as f:
        candles = json.load(f)
    n = len(candles)
    span_days = (candles[-1]['time'] - candles[0]['time']) / 86400
    print(f'  {n:,} bars, {span_days:.1f} days\n')

    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    opens = [c['open'] for c in candles]
    volumes = [c.get('volume', 0) for c in candles]

    print('Computing ATR(14)...')
    atr14 = _calc_atr(highs, lows, closes, 14)
    # Report ATR stats
    atr_vals = [v for v in atr14 if v is not None]
    atr_bps_vals = [v / closes[i] * 10000 for i, v in enumerate(atr14) if v is not None and closes[i] > 0]
    print(f'  ATR(14) median: {sorted(atr_vals)[len(atr_vals)//2]:.6f} '
          f'({sorted(atr_bps_vals)[len(atr_bps_vals)//2]:.1f} bps)\n')

    results = []

    for left, right in SWING_COMBOS:
        print(f'\n{"─" * 70}')
        print(f'Swing params: lookback_left={left}, lookback_right={right}')
        print(f'{"─" * 70}')

        t0 = time.time()

        # 1. Swings (fast — O(n))
        swing_lows = calc_swing_lows(lows, left, right)
        swing_highs = calc_swing_highs(highs, left, right)
        n_swing_lows = count_non_none(swing_lows)
        n_swing_highs = count_non_none(swing_highs)
        print(f'  Swing lows:  {n_swing_lows:6d}   ({n_swing_lows/span_days:.1f}/day)')
        print(f'  Swing highs: {n_swing_highs:6d}   ({n_swing_highs/span_days:.1f}/day)')

        # 2. BoS (fast — O(n))
        bos_events = calc_break_of_structure(closes, swing_highs, swing_lows, atr14)
        n_bull_bos = count_bullish_bos(bos_events)
        n_bear_bos = count_bearish_bos(bos_events)
        print(f'  Bullish BoS: {n_bull_bos:6d}   ({n_bull_bos/span_days:.1f}/day)')
        print(f'  Bearish BoS: {n_bear_bos:6d}   ({n_bear_bos/span_days:.1f}/day)')

        # 3. FVGs — fast inline counter
        for gap_thr in FVG_THRESHOLDS:
            bull_fvg, bear_fvg = count_fvgs_fast(highs, lows, closes, atr14, gap_thr)
            print(f'  FVG bull (gap≥{gap_thr}): {bull_fvg:5d} ({bull_fvg/span_days:.1f}/d)   '
                  f'bear: {bear_fvg:5d} ({bear_fvg/span_days:.1f}/d)')

        # 4. OBs — fast inline counter
        for imp_thr in OB_THRESHOLDS:
            bull_ob, bear_ob = count_obs_fast(opens, highs, lows, closes, atr14, imp_thr)
            print(f'  OB bull (imp≥{imp_thr}): {bull_ob:5d} ({bull_ob/span_days:.1f}/d)   '
                  f'bear: {bear_ob:5d} ({bear_ob/span_days:.1f}/d)')

        # 5. Liquidity zones — fast clustering
        for tol in LIQ_TOLERANCES:
            low_z, high_z = count_liq_zones_fast(swing_lows, swing_highs, atr14, tol, 2)
            print(f'  LiqZone (tol={tol}): low={low_z:5d}  high={high_z:5d}  '
                  f'total={low_z + high_z}')

        elapsed = time.time() - t0

        # Gate evaluation (default thresholds)
        bull_fvg_def, _ = count_fvgs_fast(highs, lows, closes, atr14, 0.3)
        bull_ob_def, _ = count_obs_fast(opens, highs, lows, closes, atr14, 1.5)
        low_z_def, _ = count_liq_zones_fast(swing_lows, swing_highs, atr14, 0.5, 2)

        pattern_counts = {
            'swing_lows': n_swing_lows,
            'swing_highs': n_swing_highs,
            'bullish_bos': n_bull_bos,
            'bullish_fvg_0.3': bull_fvg_def,
            'bullish_ob_1.5': bull_ob_def,
            'liq_zones_low_0.5': low_z_def,
        }

        patterns_passing = sum(1 for v in pattern_counts.values() if v >= GATE_THRESHOLD)

        entry = {
            'swing_left': left,
            'swing_right': right,
            'pattern_counts': pattern_counts,
            'patterns_passing_gate': patterns_passing,
            'gate_threshold': GATE_THRESHOLD,
            'elapsed_s': round(elapsed, 2),
        }
        results.append(entry)

        print(f'\n  Patterns ≥{GATE_THRESHOLD}: {patterns_passing}/6  ({elapsed:.1f}s)')

    # ─── Summary ───
    print('\n' + '=' * 80)
    print('SUMMARY')
    print('=' * 80)

    print(f'\n{"Swing":<12} {"SwL":>6} {"SwH":>6} {"BoS↑":>6} {"FVG↑":>6} '
          f'{"OB↑":>6} {"LiqZ":>6} {"Pass":>6} {"Verdict":<12}')
    print('─' * 80)

    best_combo = None
    best_passing = 0

    for r in results:
        pc = r['pattern_counts']
        p = r['patterns_passing_gate']
        combo = f'({r["swing_left"]},{r["swing_right"]})'
        verdict = 'GO ✅' if p >= 2 else 'NO-GO ❌'
        print(f'{combo:<12} {pc["swing_lows"]:>6} {pc["swing_highs"]:>6} '
              f'{pc["bullish_bos"]:>6} {pc["bullish_fvg_0.3"]:>6} '
              f'{pc["bullish_ob_1.5"]:>6} {pc["liq_zones_low_0.5"]:>6} '
              f'{p:>6} {verdict:<12}')

        if p > best_passing:
            best_passing = p
            best_combo = r

    print(f'\n{"─" * 80}')
    if best_passing >= 2:
        print(f'✅ GO — Best combo ({best_combo["swing_left"]},{best_combo["swing_right"]}) '
              f'has {best_passing} pattern types ≥{GATE_THRESHOLD}')
        print(f'   Proceed to Phase 1 infrastructure + Phase 2 screening.')
    else:
        print(f'❌ NO-GO — No swing combo has ≥2 pattern types with ≥{GATE_THRESHOLD} events.')
        print(f'   MS patterns are too infrequent on 1m XRP/USDT.')
        print(f'   Write ADR-SCALP-002, close project.')

    # Save results
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / 'precount_results.json'
    with open(out_path, 'w') as f:
        json.dump({
            'pair': 'XRP/USDT',
            'bars': n,
            'span_days': round(span_days, 1),
            'gate_threshold': GATE_THRESHOLD,
            'results': results,
            'best_combo': {
                'swing_left': best_combo['swing_left'] if best_combo else None,
                'swing_right': best_combo['swing_right'] if best_combo else None,
                'patterns_passing': best_passing,
            },
            'verdict': 'GO' if best_passing >= 2 else 'NO-GO',
        }, f, indent=2)
    print(f'\nResults saved: {out_path}')


if __name__ == '__main__':
    main()
