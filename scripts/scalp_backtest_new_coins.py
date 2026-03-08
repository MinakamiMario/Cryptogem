#!/usr/bin/env python3
"""
Backtest FVG scalp on all available 1m coin data.
Runs the verified fvg_x2027 config on each coin.

OPTIMIZED: Lightweight indicator computation for 43K+ bar datasets.
Only computes what FVG fill signal needs: RSI14, ATR14, closes, FVG snapshots.
Skips: OB, BoS, LiqZones, swings, BB, EMA, VWAP (not used by signal_mssb).

Outputs: reports/pipeline/scalp_universe_backtest.json
"""
import sys, json, time
from pathlib import Path
from copy import copy
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.indicators import _calc_rsi, _calc_atr
from strategies.scalp.harness import run_backtest

DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'

# fvg_x2027 — verified primary config
PARAMS = {
    'max_fvg_age': 25,
    'fill_depth': 0.75,
    'rsi_max': 40,
    'tp_atr': 2.5,
    'sl_atr': 0.75,
    'time_limit': 15,
}

# Spread data from live scan (bps)
KNOWN_SPREADS = {
    # Original 13 (measured 2026-03-05)
    'BTC': 0.0, 'ETH': 0.4, 'XRP': 1.4, 'ZEC': 0.4,
    'HBAR': 1.0, 'SUI': 1.0, 'SOL': 1.1, 'LTC': 1.8,
    'BCH': 2.2, 'CHZ': 2.6, 'LINK': 3.2, 'TRX': 3.5,
    'ADA': 3.6, 'AVAX': 2.2, 'FIL': 4.8,
    # Batch 2 (measured 2026-03-07)
    'DOGE': 1.1, 'AAVE': 1.8, 'UNI': 2.6, 'ONDO': 5.2,
    'PEPE': 6.1, 'NEAR': 6.5, 'DOT': 6.8, 'FET': 6.9,
    'ARB': 7.2, 'RENDER': 7.2, 'TON': 7.6, 'OP': 8.5,
    'APT': 8.5, 'ATOM': 11.1,
}

MAX_FVG_AGE = PARAMS['max_fvg_age']

# ─── Lightweight FVG dataclass ───────────────────────────────────

@dataclass
class FVG:
    bar_created: int
    direction: str
    gap_high: float
    gap_low: float
    filled: bool = False
    fill_bar: int | None = None


def _calc_fvg_fast(highs, lows, closes, atr, min_gap_atr=0.3, max_age=50):
    """Optimized FVG computation for large datasets.

    Key optimizations vs calc_fair_value_gaps:
    1. Prunes active list every 500 bars (removes filled + old FVGs)
    2. Only copies unfilled FVGs within max_age for snapshots
    3. Memory stays bounded: O(max_age) per snapshot instead of O(total_fvgs)
    """
    n = len(highs)
    snapshots = [[] for _ in range(n)]
    active = []

    for bar in range(n):
        # Create new FVGs
        if bar >= 2:
            cur_atr = atr[bar] if atr[bar] is not None else None

            # Bullish FVG
            if highs[bar - 2] < lows[bar]:
                gap_size = lows[bar] - highs[bar - 2]
                if cur_atr and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(
                        bar_created=bar, direction="bullish",
                        gap_high=lows[bar], gap_low=highs[bar - 2],
                    ))

            # Bearish FVG
            if lows[bar - 2] > highs[bar]:
                gap_size = lows[bar - 2] - highs[bar]
                if cur_atr and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(
                        bar_created=bar, direction="bearish",
                        gap_high=lows[bar - 2], gap_low=highs[bar],
                    ))

        # Snapshot: copy only unfilled + within max_age
        snapshots[bar] = [
            copy(fvg) for fvg in active
            if not fvg.filled and (bar - fvg.bar_created) <= max_age
        ]

        # Check fills
        for fvg in active:
            if fvg.filled:
                continue
            if fvg.direction == "bullish":
                if closes[bar] <= fvg.gap_high and bar > fvg.bar_created:
                    fvg.filled = True
                    fvg.fill_bar = bar
            else:
                if closes[bar] >= fvg.gap_low and bar > fvg.bar_created:
                    fvg.filled = True
                    fvg.fill_bar = bar

        # Prune: remove filled/old FVGs from active list every 500 bars
        if bar % 500 == 0 and bar > 0:
            active = [
                fvg for fvg in active
                if not fvg.filled and (bar - fvg.bar_created) <= max_age
            ]

    return snapshots


def get_active_bullish_fvgs(fvg_snapshots, bar, max_age=40):
    """Return unfilled bullish FVGs at bar, filtered by max age."""
    if bar < 0 or bar >= len(fvg_snapshots):
        return []
    return [
        fvg for fvg in fvg_snapshots[bar]
        if fvg.direction == "bullish" and (bar - fvg.bar_created) <= max_age
    ]


# ─── Signal function (inlined to avoid import chain) ────────────

def signal_mssb(candles, bar, indicators, params):
    """FVG Fill signal — identical logic to ms_hypotheses.signal_mssb."""
    max_fvg_age = params.get('max_fvg_age', 15)
    fill_depth = params.get('fill_depth', 0.50)
    rsi_max = params.get('rsi_max', 0)
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit_v = params.get('time_limit', 20)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    closes = indicators['closes']
    atr_arr = indicators['atr']
    fvg_snapshots = indicators['fvg_snapshots']

    close = closes[bar]
    cur_atr = atr_arr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    active_fvgs = get_active_bullish_fvgs(fvg_snapshots, bar, max_age=max_fvg_age)
    if not active_fvgs:
        return None

    if rsi_max > 0:
        rsi = indicators.get('rsi14', [None] * (bar + 1))
        cur_rsi = rsi[bar] if bar < len(rsi) else None
        if cur_rsi is None or cur_rsi > rsi_max:
            return None

    best_fvg = None
    best_depth = 0.0

    for fvg in active_fvgs:
        gap_size = fvg.gap_high - fvg.gap_low
        if gap_size <= 0:
            continue
        if close > fvg.gap_high:
            continue
        depth = (fvg.gap_high - close) / gap_size
        depth = min(1.0, max(0.0, depth))
        if depth >= fill_depth and depth > best_depth:
            best_depth = depth
            best_fvg = fvg

    if best_fvg is None:
        return None

    strength = best_depth * (1.0 + (bar - best_fvg.bar_created) / max_fvg_age)

    return {
        'stop_price': close - sl_atr * cur_atr,
        'target_price': close + tp_atr * cur_atr,
        'time_limit': time_limit_v,
        'strength': min(strength, 3.0),
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ─── Main ────────────────────────────────────────────────────────

print("=" * 90, flush=True)
print("SCALP FVG BACKTEST — ALL AVAILABLE 1M DATA (OPTIMIZED)", flush=True)
print(f"Config: fvg_x2027 (max_fvg_age=25, fill_depth=0.75, rsi_max=40)", flush=True)
print("=" * 90, flush=True)
print(flush=True)

data_files = sorted(DATA_DIR.glob('*_USDT_1m.json'))
print(f"Found {len(data_files)} coin data files", flush=True)
print(flush=True)

results = []
for data_file in data_files:
    coin_base = data_file.stem.replace('_USDT_1m', '')
    t0 = time.time()

    with open(data_file) as f:
        candles = json.load(f)

    if len(candles) < 1000:
        print(f"  {coin_base}: skipping ({len(candles)} bars, need ≥1000)", flush=True)
        continue

    spread_bps = KNOWN_SPREADS.get(coin_base, 5.0)

    # Lightweight indicator computation
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]

    rsi14 = _calc_rsi(closes, 14)
    atr14 = _calc_atr(highs, lows, closes, 14)
    fvg_snapshots = _calc_fvg_fast(
        highs, lows, closes, atr14,
        min_gap_atr=0.3, max_age=MAX_FVG_AGE + 10,
    )

    indicators = {
        'closes': closes, 'highs': highs, 'lows': lows,
        'atr14': atr14, 'atr': atr14,
        'rsi14': rsi14, 'rsi': rsi14,
        'fvg_snapshots': fvg_snapshots,
    }

    elapsed_ind = time.time() - t0

    # Run backtest
    try:
        res = run_backtest(
            candles=candles,
            signal_fn=signal_mssb,
            params=PARAMS,
            indicators=indicators,
            spread_bps=spread_bps,
            initial_capital=10000,
        )
    except Exception as e:
        print(f"  {coin_base}: backtest error: {e}", flush=True)
        continue

    elapsed = time.time() - t0

    trades_n = res.trades
    pf = res.pf
    wr = res.wr
    dd = res.dd

    result = {
        'coin': coin_base,
        'bars': len(candles),
        'trades': trades_n,
        'pf': round(pf, 3),
        'wr': round(wr, 1),
        'pnl': round(res.pnl, 2),
        'dd': round(dd, 1),
        'spread_bps': spread_bps,
        'avg_hold': round(res.avg_hold, 1),
        'trades_per_day': round(res.trades_per_day, 1),
    }
    results.append(result)

    # Verdict
    if pf >= 1.20 and trades_n >= 50:
        verdict = "🟢 GO_ADV"
    elif pf >= 1.10 and trades_n >= 30:
        verdict = "🟢 GO"
    elif pf >= 1.0 and trades_n >= 20:
        verdict = "🟡 MARGINAL"
    else:
        verdict = "🔴 NO_GO"

    print(f"  {coin_base:<8} {len(candles):>6} bars  {trades_n:>4} trades  "
          f"PF={pf:>5.2f}  WR={wr:>4.1f}%  PnL=${res.pnl:>+8.0f}  "
          f"DD={dd:>5.1f}%  spread={spread_bps:.1f}bp  "
          f"[{verdict}]  ({elapsed:.1f}s)", flush=True)

# Summary
print(flush=True)
print("=" * 90, flush=True)
print("SUMMARY", flush=True)
print("=" * 90, flush=True)

results.sort(key=lambda x: x['pf'], reverse=True)
go_coins = [r for r in results if r['pf'] >= 1.10 and r['trades'] >= 30]
marginal = [r for r in results if 1.0 <= r['pf'] < 1.10 and r['trades'] >= 20]
no_go = [r for r in results if r not in go_coins and r not in marginal]

print(f"\n  GO (PF≥1.10, trades≥30):     {len(go_coins)} coins", flush=True)
for r in go_coins:
    print(f"    {r['coin']:<8} PF={r['pf']:.2f}  trades={r['trades']}  "
          f"PnL=${r['pnl']:+,.0f}  WR={r['wr']:.0f}%  "
          f"DD={r['dd']:.0f}%  spread={r['spread_bps']:.1f}bp  "
          f"avg_hold={r['avg_hold']:.0f}bars  tpd={r['trades_per_day']:.1f}", flush=True)

print(f"\n  MARGINAL (PF≥1.0, trades≥20): {len(marginal)} coins", flush=True)
for r in marginal:
    print(f"    {r['coin']:<8} PF={r['pf']:.2f}  trades={r['trades']}  "
          f"PnL=${r['pnl']:+,.0f}  spread={r['spread_bps']:.1f}bp", flush=True)

print(f"\n  NO_GO:                        {len(no_go)} coins", flush=True)
for r in no_go:
    print(f"    {r['coin']:<8} PF={r['pf']:.2f}  trades={r['trades']}  "
          f"PnL=${r['pnl']:+,.0f}", flush=True)

# Comparison with current (XRP+ETH)
current = [r for r in results if r['coin'] in ('XRP', 'ETH')]
if current:
    print(f"\n  Current scalp coins:", flush=True)
    for r in current:
        print(f"    {r['coin']:<8} PF={r['pf']:.2f}  trades={r['trades']}  "
              f"PnL=${r['pnl']:+,.0f}  WR={r['wr']:.0f}%", flush=True)

# Save results
report = {
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'config': 'fvg_x2027',
    'params': PARAMS,
    'results': results,
    'summary': {
        'go': len(go_coins),
        'marginal': len(marginal),
        'no_go': len(no_go),
        'go_coins': [r['coin'] for r in go_coins],
    }
}
report_dir = ROOT / 'reports' / 'pipeline'
report_dir.mkdir(parents=True, exist_ok=True)
report_file = report_dir / 'scalp_universe_backtest.json'
with open(report_file, 'w') as f:
    json.dump(report, f, indent=2)
print(f"\nReport saved: {report_file}", flush=True)
