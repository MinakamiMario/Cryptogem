"""
Optimizer for Bear Bounce Universal "Both (dual confirm)" strategy.
==================================================================
Tests parameter combinations + additional filters to maximize portfolio P&L
under realistic constraints (max positions, budget, commission).

Sweeps:
  1. Base params: RSI thresholds, ATR mult, BB deviation, cooldown
  2. Budget configs: capital per trade × max positions
  3. Additional filters: volume, EMA trend, min bounce strength
  4. Signal ranking: when multiple signals, pick best (lowest RSI, etc.)
"""
import json
import os
import itertools
from datetime import datetime

# === LOAD CACHED DATA ===
CACHE_FILE = '/Users/oussama/Cryptogem/trading_bot/candle_cache_30d.json'
if not os.path.exists(CACHE_FILE):
    print("ERROR: Run backtest_universal.py first")
    exit(1)

with open(CACHE_FILE, 'r') as f:
    ALL_CANDLES = json.load(f)
print(f"Loaded {len(ALL_CANDLES)} coins")

COMMISSION_PCT = 0.1


# === FAST INDICATOR FUNCTIONS ===

def calc_rsi(closes, period):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(highs, lows, closes, period):
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def calc_donchian(highs, lows, period):
    if len(highs) < period:
        return None, None, None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    return hh, ll, (hh + ll) / 2


def calc_bollinger(closes, period, dev):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((x - mid) ** 2 for x in recent) / period
    std = variance ** 0.5
    return mid, mid + dev * std, mid - dev * std


def calc_ema(closes, period):
    if len(closes) < period:
        return None
    mult = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = (c - ema) * mult + ema
    return ema


def calc_avg_volume(volumes, period):
    if len(volumes) < period:
        return 0
    return sum(volumes[-period:]) / period


# === SIGNAL EXTRACTION WITH PARAMS ===

def extract_signals(all_candles, params):
    """Extract all entry/exit signals for dual-confirm mode with given parameters."""
    dc_period = params['dc_period']
    bb_period = params['bb_period']
    bb_dev = params['bb_dev']
    rsi_period = params['rsi_period']
    rsi_dc_max = params['rsi_dc_max']
    rsi_bb_max = params['rsi_bb_max']
    rsi_sell = params.get('rsi_sell', 70)
    atr_period = params['atr_period']
    atr_mult = params['atr_mult']
    cooldown = params['cooldown']
    # Additional filters
    use_ema_filter = params.get('ema_filter', False)
    ema_period = params.get('ema_period', 50)
    use_volume_filter = params.get('volume_filter', False)
    vol_mult = params.get('vol_mult', 1.5)
    min_bounce_pct = params.get('min_bounce_pct', 0)  # min % bounce from low

    min_bars = max(dc_period, bb_period, rsi_period, atr_period, ema_period if use_ema_filter else 0) + 5
    all_events = []

    for pair, candles in all_candles.items():
        if len(candles) < min_bars:
            continue

        last_exit_bar = -999
        position = None
        start_bar = min_bars

        for i in range(start_bar, len(candles)):
            window = candles[:i + 1]
            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]
            volumes = [c['volume'] for c in window]

            rsi = calc_rsi(closes, rsi_period)
            atr = calc_atr(highs, lows, closes, atr_period)

            # Donchian
            _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1], dc_period)
            _, _, mid_channel = calc_donchian(highs, lows, dc_period)

            # Bollinger
            bb_mid, _, bb_lower = calc_bollinger(closes, bb_period, bb_dev)

            current = window[-1]
            prev = window[-2]

            if position is None:
                if (i - last_exit_bar) < cooldown:
                    continue

                # Dual confirm: both Donchian AND BB must signal
                donchian_ok = (
                    prev_lowest is not None and
                    current['low'] <= prev_lowest and
                    rsi < rsi_dc_max and
                    current['close'] > prev['close']
                )
                bb_ok = (
                    bb_lower is not None and
                    current['close'] <= bb_lower and
                    rsi < rsi_bb_max and
                    current['close'] > prev['close']
                )

                if not (donchian_ok and bb_ok):
                    continue

                # Additional filter: EMA trend (only buy if price below EMA = bearish context)
                if use_ema_filter:
                    ema = calc_ema(closes, ema_period)
                    if ema is not None and current['close'] > ema:
                        continue  # Skip if price above EMA (not in bear mode)

                # Additional filter: volume spike
                if use_volume_filter:
                    avg_vol = calc_avg_volume(volumes[:-1], 20)
                    if avg_vol > 0 and current['volume'] < avg_vol * vol_mult:
                        continue  # Skip if volume too low

                # Additional filter: minimum bounce strength
                if min_bounce_pct > 0:
                    bounce = (current['close'] - current['low']) / current['low'] * 100
                    if bounce < min_bounce_pct:
                        continue

                stop = current['close'] - atr * atr_mult
                all_events.append({
                    'time': current['time'],
                    'pair': pair,
                    'type': 'ENTRY',
                    'price': current['close'],
                    'stop': stop,
                    'target_dc': mid_channel,
                    'target_bb': bb_mid,
                    'rsi': rsi,
                    'atr': atr,
                    'bar_idx': i,
                })
                position = {
                    'entry_price': current['close'],
                    'stop_price': stop,
                    'highest_price': current['close'],
                    'entry_bar': i,
                }
            else:
                if current['close'] > position['highest_price']:
                    position['highest_price'] = current['close']
                new_stop = position['highest_price'] - atr * atr_mult
                if new_stop > position['stop_price']:
                    position['stop_price'] = new_stop

                # Target: DC mid OR BB mid
                hit_target = (
                    (mid_channel is not None and current['close'] >= mid_channel) or
                    (bb_mid is not None and current['close'] >= bb_mid)
                )

                exit_type = None
                if hit_target:
                    exit_type = 'TARGET'
                elif rsi > rsi_sell:
                    exit_type = 'RSI'
                elif current['close'] < position['stop_price']:
                    exit_type = 'STOP'

                if exit_type:
                    pnl_pct = (current['close'] - position['entry_price']) / position['entry_price'] * 100
                    all_events.append({
                        'time': current['time'],
                        'pair': pair,
                        'type': 'EXIT',
                        'exit_type': exit_type,
                        'price': current['close'],
                        'entry_price': position['entry_price'],
                        'pnl_pct': pnl_pct,
                        'bar_idx': i,
                    })
                    last_exit_bar = i
                    position = None

        if position:
            last = candles[-1]
            pnl_pct = (last['close'] - position['entry_price']) / position['entry_price'] * 100
            all_events.append({
                'time': last['time'],
                'pair': pair,
                'type': 'EXIT',
                'exit_type': 'OPEN',
                'price': last['close'],
                'entry_price': position['entry_price'],
                'pnl_pct': pnl_pct,
                'bar_idx': len(candles) - 1,
            })

    all_events.sort(key=lambda x: (x['time'], x['type'] == 'ENTRY'))
    return all_events


def simulate_portfolio(events, capital_per_trade, max_positions, use_ranking=False):
    """
    Simulate with position limits.
    use_ranking: if True, when multiple signals at same timestamp and slots full,
                 pick lowest RSI (most oversold = strongest signal).
    """
    positions = {}
    trades = []
    skipped = 0

    # Group entries by timestamp for ranking
    if use_ranking:
        # Process events in time-grouped batches
        from collections import defaultdict
        time_groups = defaultdict(list)
        non_entry_events = []
        for e in events:
            if e['type'] == 'ENTRY':
                time_groups[e['time']].append(e)
            else:
                non_entry_events.append(e)

        # Rebuild events: exits first, then ranked entries
        ranked_events = []
        all_times = sorted(set(e['time'] for e in events))
        for t in all_times:
            # Add exits at this time first
            for e in non_entry_events:
                if e['time'] == t:
                    ranked_events.append(e)
            # Add entries sorted by RSI (lowest = best)
            if t in time_groups:
                sorted_entries = sorted(time_groups[t], key=lambda x: x.get('rsi', 50))
                ranked_events.extend(sorted_entries)
        events = ranked_events

    for event in events:
        if event['type'] == 'ENTRY':
            if len(positions) >= max_positions:
                skipped += 1
                continue
            if event['pair'] in positions:
                continue

            volume = capital_per_trade / event['price']
            commission_entry = capital_per_trade * COMMISSION_PCT / 100
            positions[event['pair']] = {
                'entry_price': event['price'],
                'volume': volume,
                'commission_entry': commission_entry,
            }

        elif event['type'] == 'EXIT':
            if event['pair'] not in positions:
                continue

            pos = positions[event['pair']]
            pnl_usd = pos['volume'] * (event['price'] - pos['entry_price'])
            commission_exit = abs(pos['volume'] * event['price']) * COMMISSION_PCT / 100
            total_commission = pos['commission_entry'] + commission_exit
            pnl_usd -= total_commission
            pnl_pct = (event['price'] - pos['entry_price']) / pos['entry_price'] * 100

            trades.append({
                'pnl_usd': pnl_usd,
                'pnl_pct': pnl_pct,
                'exit_type': event.get('exit_type', '?'),
            })
            del positions[event['pair']]

    total_capital = capital_per_trade * max_positions
    if not trades:
        return {'pnl': 0, 'trades': 0, 'wr': 0, 'pf': 0, 'roi': 0, 'skipped': skipped, 'dd': 0}

    wins = [t for t in trades if t['pnl_usd'] > 0]
    total_pnl = sum(t['pnl_usd'] for t in trades)
    gp = sum(t['pnl_usd'] for t in wins) if wins else 0
    gl = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] <= 0))
    pf = gp / gl if gl > 0 else 999

    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl_usd']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    targets = len([t for t in trades if t['exit_type'] == 'TARGET'])
    stops = len([t for t in trades if t['exit_type'] == 'STOP'])

    return {
        'pnl': round(total_pnl, 2),
        'trades': len(trades),
        'wr': round(len(wins) / len(trades) * 100, 1),
        'pf': round(pf, 2) if pf < 999 else 999,
        'roi': round(total_pnl / total_capital * 100, 2),
        'skipped': skipped,
        'dd': round(max_dd, 2),
        'targets': targets,
        'stops': stops,
        'avg_pnl': round(total_pnl / len(trades), 2),
    }


# === PHASE 1: ANALYZE CURRENT BASELINE ===
print(f"\n{'=' * 110}")
print(f"PHASE 1: BASELINE ANALYSIS (current dual-confirm)")
print(f"{'=' * 110}")

baseline_params = {
    'dc_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
    'rsi_period': 14, 'rsi_dc_max': 35, 'rsi_bb_max': 30, 'rsi_sell': 70,
    'atr_period': 14, 'atr_mult': 2.0, 'cooldown': 4,
}

events_base = extract_signals(ALL_CANDLES, baseline_params)
entry_count = len([e for e in events_base if e['type'] == 'ENTRY'])
print(f"Baseline signals: {entry_count}")

for cap, maxp, label in [(600, 3, "3×$600"), (500, 4, "4×$500"), (400, 5, "5×$400")]:
    r = simulate_portfolio(events_base, cap, maxp)
    print(f"  {label}: P&L=${r['pnl']:+.2f}  WR={r['wr']}%  PF={r['pf']}  trades={r['trades']}  skipped={r['skipped']}  DD=${r['dd']}")


# === PHASE 2: PARAMETER SWEEP ===
print(f"\n{'=' * 110}")
print(f"PHASE 2: PARAMETER SWEEP")
print(f"{'=' * 110}")

# Test configurations
param_tests = []

# 2a: RSI thresholds
for rsi_dc in [30, 35, 40]:
    for rsi_bb in [25, 30, 35]:
        p = {**baseline_params, 'rsi_dc_max': rsi_dc, 'rsi_bb_max': rsi_bb}
        param_tests.append((f"RSI DC<{rsi_dc} BB<{rsi_bb}", p))

# 2b: ATR multiplier (stop tightness)
for atr_m in [1.5, 2.0, 2.5, 3.0]:
    p = {**baseline_params, 'atr_mult': atr_m}
    param_tests.append((f"ATR mult={atr_m}", p))

# 2c: BB deviation
for bb_d in [1.5, 2.0, 2.5, 3.0]:
    p = {**baseline_params, 'bb_dev': bb_d}
    param_tests.append((f"BB dev={bb_d}", p))

# 2d: Donchian period
for dc_p in [15, 20, 25, 30]:
    p = {**baseline_params, 'dc_period': dc_p}
    param_tests.append((f"DC period={dc_p}", p))

# 2e: Cooldown bars
for cd in [2, 4, 6, 8]:
    p = {**baseline_params, 'cooldown': cd}
    param_tests.append((f"Cooldown={cd}", p))

# 2f: RSI sell (exit threshold)
for rsi_s in [60, 65, 70, 75, 80]:
    p = {**baseline_params, 'rsi_sell': rsi_s}
    param_tests.append((f"RSI sell>{rsi_s}", p))

# Run all parameter tests with 3×$600 config
results_sweep = []
for name, params in param_tests:
    events = extract_signals(ALL_CANDLES, params)
    sigs = len([e for e in events if e['type'] == 'ENTRY'])
    r = simulate_portfolio(events, 600, 3)
    results_sweep.append((name, sigs, r))

# Sort by P&L
results_sweep.sort(key=lambda x: x[2]['pnl'], reverse=True)

print(f"\n{'Config':<30} {'Sigs':>5} {'Trades':>6} {'P&L':>10} {'WR%':>6} {'PF':>6} {'DD':>8} {'Skip':>5}")
print("-" * 85)
for name, sigs, r in results_sweep[:25]:
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 100 else "inf"
    print(f"{name:<30} {sigs:>5} {r['trades']:>6} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}% {pf_str:>6} ${r['dd']:>7.2f} {r['skipped']:>5}")

print(f"\n  ... showing top 25 of {len(results_sweep)} tested configs")


# === PHASE 3: ADDITIONAL FILTERS ===
print(f"\n{'=' * 110}")
print(f"PHASE 3: ADDITIONAL FILTERS")
print(f"{'=' * 110}")

filter_tests = []

# 3a: EMA trend filter (only buy below EMA = confirmed bear bounce)
for ema_p in [50, 100, 200]:
    p = {**baseline_params, 'ema_filter': True, 'ema_period': ema_p}
    filter_tests.append((f"EMA{ema_p} filter (buy<EMA)", p))

# 3b: Volume filter
for vm in [1.0, 1.5, 2.0]:
    p = {**baseline_params, 'volume_filter': True, 'vol_mult': vm}
    filter_tests.append((f"Volume>{vm}x avg", p))

# 3c: Minimum bounce strength
for mb in [0.5, 1.0, 2.0]:
    p = {**baseline_params, 'min_bounce_pct': mb}
    filter_tests.append((f"Min bounce {mb}%", p))

# 3d: Combined filters
p = {**baseline_params, 'ema_filter': True, 'ema_period': 50, 'min_bounce_pct': 0.5}
filter_tests.append(("EMA50 + bounce>0.5%", p))

p = {**baseline_params, 'volume_filter': True, 'vol_mult': 1.5, 'min_bounce_pct': 0.5}
filter_tests.append(("Vol>1.5x + bounce>0.5%", p))

# Run filter tests
results_filters = []
for name, params in filter_tests:
    events = extract_signals(ALL_CANDLES, params)
    sigs = len([e for e in events if e['type'] == 'ENTRY'])
    r = simulate_portfolio(events, 600, 3)
    results_filters.append((name, sigs, r))

results_filters.sort(key=lambda x: x[2]['pnl'], reverse=True)

print(f"\n{'Filter':<30} {'Sigs':>5} {'Trades':>6} {'P&L':>10} {'WR%':>6} {'PF':>6} {'DD':>8} {'Skip':>5}")
print("-" * 85)
for name, sigs, r in results_filters:
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 100 else "inf"
    print(f"{name:<30} {sigs:>5} {r['trades']:>6} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}% {pf_str:>6} ${r['dd']:>7.2f} {r['skipped']:>5}")


# === PHASE 4: SIGNAL RANKING ===
print(f"\n{'=' * 110}")
print(f"PHASE 4: SIGNAL RANKING (pick best signal when full)")
print(f"{'=' * 110}")

events_base = extract_signals(ALL_CANDLES, baseline_params)

for cap, maxp, label in [(600, 3, "3×$600"), (500, 4, "4×$500"), (400, 5, "5×$400")]:
    r_no_rank = simulate_portfolio(events_base, cap, maxp, use_ranking=False)
    r_ranked = simulate_portfolio(events_base, cap, maxp, use_ranking=True)
    print(f"  {label} NO RANK: P&L=${r_no_rank['pnl']:+.2f}  WR={r_no_rank['wr']}%  PF={r_no_rank['pf']}")
    print(f"  {label} RANKED:  P&L=${r_ranked['pnl']:+.2f}  WR={r_ranked['wr']}%  PF={r_ranked['pf']}")
    diff = r_ranked['pnl'] - r_no_rank['pnl']
    print(f"  → Ranking effect: ${diff:+.2f}")
    print()


# === PHASE 5: BUDGET OPTIMIZATION ===
print(f"\n{'=' * 110}")
print(f"PHASE 5: BUDGET OPTIMIZATION (find best capital × positions combo)")
print(f"{'=' * 110}")

# Use the best params from sweep
best_params_name, best_sigs, best_r = results_sweep[0]
print(f"Using best params: {best_params_name}")

# Re-extract with best params
best_params = None
for name, params in param_tests:
    if name == best_params_name:
        best_params = params
        break

if best_params is None:
    best_params = baseline_params

events_best = extract_signals(ALL_CANDLES, best_params)

budget_configs = [
    (600, 3, "$1800"),
    (500, 4, "$2000"),
    (400, 5, "$2000"),
    (700, 3, "$2100"),
    (500, 5, "$2500"),
    (600, 4, "$2400"),
    (400, 6, "$2400"),
    (300, 7, "$2100"),
    (800, 3, "$2400"),
    (1000, 2, "$2000"),
    (500, 6, "$3000"),
    (600, 5, "$3000"),
    (400, 7, "$2800"),
    (350, 6, "$2100"),
]

budget_results = []
for cap, maxp, total in budget_configs:
    r = simulate_portfolio(events_best, cap, maxp, use_ranking=True)
    budget_results.append((f"{maxp}×${cap} ({total})", cap, maxp, r))

budget_results.sort(key=lambda x: x[3]['pnl'], reverse=True)

print(f"\n{'Config':<25} {'Trades':>6} {'P&L':>10} {'ROI':>8} {'WR%':>6} {'PF':>6} {'DD':>8} {'Skip':>5} {'$/trade':>8}")
print("-" * 95)
for label, cap, maxp, r in budget_results:
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 100 else "inf"
    avg = f"${r['avg_pnl']:+.2f}" if r['trades'] > 0 else "$0"
    print(f"{label:<25} {r['trades']:>6} ${r['pnl']:>+8.2f} {r['roi']:>7.2f}% {r['wr']:>5.1f}% {pf_str:>6} ${r['dd']:>7.2f} {r['skipped']:>5} {avg:>8}")


# === PHASE 6: COMBINED BEST CONFIG ===
print(f"\n{'=' * 110}")
print(f"PHASE 6: COMBINED OPTIMIZATION")
print(f"{'=' * 110}")

# Top 5 param configs from sweep
top_params = []
for name, params in param_tests:
    events = extract_signals(ALL_CANDLES, params)
    sigs = len([e for e in events if e['type'] == 'ENTRY'])
    # Test with multiple budget configs
    for cap, maxp, total in [(600, 3, "$1800"), (500, 4, "$2000"), (400, 5, "$2000"), (700, 3, "$2100"), (600, 4, "$2400")]:
        r = simulate_portfolio(events, cap, maxp, use_ranking=True)
        top_params.append((f"{name} | {maxp}×${cap}", name, cap, maxp, r, params))

# Also test best filters
for name, params in filter_tests:
    events = extract_signals(ALL_CANDLES, params)
    for cap, maxp, total in [(600, 3, "$1800"), (500, 4, "$2000"), (400, 5, "$2000"), (700, 3, "$2100"), (600, 4, "$2400")]:
        r = simulate_portfolio(events, cap, maxp, use_ranking=True)
        top_params.append((f"{name} | {maxp}×${cap}", name, cap, maxp, r, params))

top_params.sort(key=lambda x: x[4]['pnl'], reverse=True)

print(f"\nTOP 20 OVERALL COMBINATIONS (params + budget + ranking):")
print(f"{'Config':<55} {'Trades':>6} {'P&L':>10} {'WR%':>6} {'PF':>6} {'DD':>8}")
print("-" * 100)
for label, pname, cap, maxp, r, params in top_params[:20]:
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 100 else "inf"
    print(f"{label:<55} {r['trades']:>6} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}% {pf_str:>6} ${r['dd']:>7.2f}")

# Print the winner
winner = top_params[0]
print(f"\n{'=' * 110}")
print(f"WINNER: {winner[0]}")
print(f"{'=' * 110}")
wparams = winner[5]
wr = winner[4]
print(f"Parameters:")
for k, v in wparams.items():
    print(f"  {k}: {v}")
print(f"\nPortfolio: {winner[3]}×${winner[2]}")
print(f"Results: P&L=${wr['pnl']:+.2f} | WR={wr['wr']}% | PF={wr['pf']} | Trades={wr['trades']} | DD=${wr['dd']} | ROI={wr['roi']}%")
print(f"\nBaseline comparison: P&L=$+419.78 (3×$600, no ranking)")
print(f"Improvement: ${wr['pnl'] - 419.78:+.2f}")
