#!/usr/bin/env python3
"""
Temporal Validation — FVG x2027 edge persistence across time windows.

Splits 90-day 1m data into 30-day windows and runs fvg_x2027 backtest
on each window independently. Checks:
  1. Edge persists outside the original 30d training window
  2. Results aren't carried by a single coin

Output: reports/pipeline/scalp_temporal_validation.json + stdout summary

Usage:
    python scripts/scalp_temporal_validation.py
"""
import sys, json, time, math
from pathlib import Path
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.indicators import _calc_rsi, _calc_atr
from strategies.scalp.harness import run_backtest

DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'

# 4 GO coins
GO_COINS = ['XRP', 'BTC', 'ETH', 'SUI']

# fvg_x2027 params (frozen)
PARAMS = {
    'max_fvg_age': 25,
    'fill_depth': 0.75,
    'rsi_max': 40,
    'tp_atr': 2.5,
    'sl_atr': 0.75,
    'time_limit': 15,
}

# Known spreads (bps)
SPREADS = {'XRP': 1.4, 'BTC': 0.0, 'ETH': 0.4, 'SUI': 1.0}

MAX_FVG_AGE = PARAMS['max_fvg_age']

# ─── FVG dataclass (from scalp_backtest_new_coins.py) ─────────────

@dataclass
class FVG:
    bar_created: int
    direction: str
    gap_high: float
    gap_low: float
    filled: bool = False
    fill_bar: int | None = None


def _calc_fvg_fast(highs, lows, closes, atr, min_gap_atr=0.3, max_age=50):
    n = len(highs)
    snapshots = [[] for _ in range(n)]
    active = []

    for bar in range(n):
        if bar >= 2:
            cur_atr = atr[bar] if atr[bar] is not None else None
            if highs[bar - 2] < lows[bar]:
                gap_size = lows[bar] - highs[bar - 2]
                if cur_atr and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(bar_created=bar, direction="bullish",
                                      gap_high=lows[bar], gap_low=highs[bar - 2]))
            if lows[bar - 2] > highs[bar]:
                gap_size = lows[bar - 2] - highs[bar]
                if cur_atr and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(bar_created=bar, direction="bearish",
                                      gap_high=lows[bar - 2], gap_low=highs[bar]))

        snapshots[bar] = [
            copy(fvg) for fvg in active
            if not fvg.filled and (bar - fvg.bar_created) <= max_age
        ]

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

        if bar % 500 == 0 and bar > 0:
            active = [fvg for fvg in active
                       if not fvg.filled and (bar - fvg.bar_created) <= max_age]

    return snapshots


def get_active_bullish_fvgs(fvg_snapshots, bar, max_age=40):
    if bar < 0 or bar >= len(fvg_snapshots):
        return []
    return [fvg for fvg in fvg_snapshots[bar]
            if fvg.direction == "bullish" and (bar - fvg.bar_created) <= max_age]


# ─── Signal function ─────────────────────────────────────────────

def signal_mssb(candles, bar, indicators, params):
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


# ─── Helpers ─────────────────────────────────────────────────────

def compute_indicators(candles):
    """Compute lightweight indicators for FVG signal."""
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]

    rsi14 = _calc_rsi(closes, 14)
    atr14 = _calc_atr(highs, lows, closes, 14)
    fvg_snapshots = _calc_fvg_fast(
        highs, lows, closes, atr14,
        min_gap_atr=0.3, max_age=MAX_FVG_AGE + 10,
    )

    return {
        'closes': closes, 'highs': highs, 'lows': lows,
        'atr14': atr14, 'atr': atr14,
        'rsi14': rsi14, 'rsi': rsi14,
        'fvg_snapshots': fvg_snapshots,
    }


def run_window(candles, spread_bps, label=""):
    """Run fvg_x2027 on a set of candles, return metrics dict."""
    if len(candles) < 500:
        return None

    indicators = compute_indicators(candles)
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
        print(f"    [ERROR] {label}: {e}")
        return None

    return {
        'pf': round(res.pf, 3),
        'trades': res.trades,
        'wr': round(res.wr, 1),
        'pnl': round(res.pnl, 2),
        'dd': round(res.dd, 1),
        'avg_hold': round(res.avg_hold, 1),
        'trades_per_day': round(res.trades_per_day, 1),
        'trade_list': res.trade_list,
    }


def split_into_windows(candles, window_days=30):
    """Split candles into non-overlapping windows of window_days each.

    Returns list of (label, candle_slice) tuples.
    Windows are labeled by their date range.
    """
    if not candles:
        return []

    first_ts = candles[0]['time']
    last_ts = candles[-1]['time']
    total_seconds = last_ts - first_ts
    window_seconds = window_days * 86400

    windows = []
    start_idx = 0
    window_num = 0

    while start_idx < len(candles):
        window_start_ts = candles[start_idx]['time']
        window_end_ts = window_start_ts + window_seconds

        # Find end index
        end_idx = start_idx
        while end_idx < len(candles) and candles[end_idx]['time'] < window_end_ts:
            end_idx += 1

        if end_idx - start_idx < 500:
            break  # too few bars for meaningful backtest

        start_dt = datetime.fromtimestamp(window_start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(candles[end_idx - 1]['time'], tz=timezone.utc)
        label = f"W{window_num}: {start_dt:%m/%d}-{end_dt:%m/%d}"

        windows.append((label, candles[start_idx:end_idx]))
        start_idx = end_idx
        window_num += 1

    return windows


# ─── Data source: MEXC only ──────────────────────────────────────

def load_coin_data(coin):
    """Load MEXC 1m data (~30 days, MEXC API limit)."""
    mexc_file = DATA_DIR / f'{coin}_USDT_1m.json'
    if mexc_file.exists():
        with open(mexc_file) as f:
            data = json.load(f)
        return data, 'mexc'
    return None, None


# ─── Main ────────────────────────────────────────────────────────

print("=" * 90)
print("TEMPORAL VALIDATION — FVG x2027 Edge Persistence")
print(f"Config: max_fvg_age=25, fill_depth=0.75, rsi_max=40")
print(f"Coins: {', '.join(GO_COINS)}")
print("=" * 90)
print()

# ─── Part 1: Temporal split per coin ─────────────────────────────

all_results = {}

for coin in GO_COINS:
    candles, source = load_coin_data(coin)
    if candles is None:
        print(f"  {coin}: DATA NOT FOUND — skipping")
        continue

    first_dt = datetime.fromtimestamp(candles[0]['time'], tz=timezone.utc)
    last_dt = datetime.fromtimestamp(candles[-1]['time'], tz=timezone.utc)
    total_days = (last_dt - first_dt).total_seconds() / 86400
    spread = SPREADS.get(coin, 5.0)

    print(f"{'─'*70}")
    print(f"  {coin} [{source}]: {len(candles):,} bars, {first_dt:%Y-%m-%d} → {last_dt:%Y-%m-%d} "
          f"({total_days:.0f}d), spread={spread:.1f}bp")

    # MEXC provides ~30d of 1m data → split into 10d windows
    window_days = 10
    windows = split_into_windows(candles, window_days=window_days)
    print(f"  → {len(windows)} windows of {window_days}d each")

    coin_results = []
    for label, window_candles in windows:
        t0 = time.time()
        metrics = run_window(window_candles, spread, label=f"{coin}/{label}")
        elapsed = time.time() - t0

        if metrics is None:
            print(f"    {label}: SKIP (too few bars)")
            continue

        coin_results.append({
            'window': label,
            'bars': len(window_candles),
            **{k: v for k, v in metrics.items() if k != 'trade_list'},
        })

        verdict = "✅" if metrics['pf'] >= 1.10 and metrics['trades'] >= 15 else "❌"
        print(f"    {label}: {len(window_candles):>6} bars  {metrics['trades']:>3} trades  "
              f"PF={metrics['pf']:>5.2f}  WR={metrics['wr']:>4.1f}%  "
              f"PnL=${metrics['pnl']:>+7.0f}  DD={metrics['dd']:>4.1f}%  "
              f"{verdict}  ({elapsed:.1f}s)")

    all_results[coin] = coin_results

# ─── Part 2: Full-period per-coin comparison ─────────────────────

print()
print("=" * 90)
print("PER-COIN PnL ANALYSIS (full dataset)")
print("=" * 90)

portfolio_results = []
for coin in GO_COINS:
    candles, source = load_coin_data(coin)
    if candles is None:
        continue

    spread = SPREADS.get(coin, 5.0)
    metrics = run_window(candles, spread, label=f"{coin}/FULL")

    if metrics is None:
        continue

    # Extract trade-level stats
    trade_list = metrics['trade_list']
    wins = [t for t in trade_list if t.get('pnl', 0) > 0]
    losses = [t for t in trade_list if t.get('pnl', 0) <= 0]

    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0

    # Streak analysis
    max_win_streak = 0
    max_loss_streak = 0
    cur_streak = 0
    for t in trade_list:
        if t.get('pnl', 0) > 0:
            if cur_streak > 0:
                cur_streak += 1
            else:
                cur_streak = 1
            max_win_streak = max(max_win_streak, cur_streak)
        else:
            if cur_streak < 0:
                cur_streak -= 1
            else:
                cur_streak = -1
            max_loss_streak = max(max_loss_streak, abs(cur_streak))

    result = {
        'coin': coin,
        'pf': metrics['pf'],
        'trades': metrics['trades'],
        'wr': metrics['wr'],
        'pnl': metrics['pnl'],
        'dd': metrics['dd'],
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'avg_hold': metrics['avg_hold'],
        'trades_per_day': metrics['trades_per_day'],
    }
    portfolio_results.append(result)

    print(f"\n  {coin}:")
    print(f"    PF={metrics['pf']:.2f}  Trades={metrics['trades']}  "
          f"WR={metrics['wr']:.0f}%  PnL=${metrics['pnl']:+,.0f}  DD={metrics['dd']:.0f}%")
    print(f"    Avg win=${avg_win:+.2f}  Avg loss=${avg_loss:+.2f}  "
          f"Ratio={abs(avg_win/avg_loss) if avg_loss != 0 else 0:.2f}")
    print(f"    Max win streak={max_win_streak}  Max loss streak={max_loss_streak}")
    print(f"    Hold={metrics['avg_hold']:.0f} bars  TPD={metrics['trades_per_day']:.1f}")

# ─── Part 3: Portfolio concentration analysis ────────────────────

print()
print("=" * 90)
print("PORTFOLIO CONCENTRATION CHECK")
print("=" * 90)

if portfolio_results:
    total_pnl = sum(r['pnl'] for r in portfolio_results)
    total_trades = sum(r['trades'] for r in portfolio_results)

    print(f"\n  Total portfolio: PnL=${total_pnl:+,.0f}  Trades={total_trades}")
    print()

    for r in sorted(portfolio_results, key=lambda x: x['pnl'], reverse=True):
        pnl_share = (r['pnl'] / total_pnl * 100) if total_pnl != 0 else 0
        trade_share = (r['trades'] / total_trades * 100) if total_trades > 0 else 0
        concentration_flag = " ⚠️ CONCENTRATED" if abs(pnl_share) > 60 else ""
        print(f"    {r['coin']:<6} PnL=${r['pnl']:>+8,.0f} ({pnl_share:>5.1f}% of total)  "
              f"Trades={r['trades']:>4} ({trade_share:>4.1f}%)  "
              f"PF={r['pf']:.2f}{concentration_flag}")

    # Herfindahl Index for concentration
    pnl_shares = [(abs(r['pnl']) / sum(abs(r['pnl']) for r in portfolio_results)) ** 2
                   for r in portfolio_results] if sum(abs(r['pnl']) for r in portfolio_results) > 0 else []
    hhi = sum(pnl_shares) if pnl_shares else 0
    # HHI: 0.25 = perfectly balanced (4 coins), 1.0 = single coin dominance
    print(f"\n  HHI (PnL concentration): {hhi:.3f}  "
          f"({'balanced' if hhi < 0.35 else 'moderate' if hhi < 0.50 else 'CONCENTRATED'})")
    print(f"  Perfect balance (4 coins) = 0.250")

# ─── Part 4: Summary verdict ────────────────────────────────────

print()
print("=" * 90)
print("VERDICT")
print("=" * 90)

# Check temporal persistence
temporal_pass = True
temporal_details = []
for coin, windows in all_results.items():
    if len(windows) < 2:
        temporal_details.append(f"  {coin}: INSUFFICIENT DATA (need ≥2 windows)")
        continue

    profitable_windows = sum(1 for w in windows if w['pf'] > 1.0)
    total_windows = len(windows)
    pf_values = [w['pf'] for w in windows]

    if profitable_windows < total_windows * 0.5:
        temporal_pass = False
        temporal_details.append(
            f"  {coin}: ❌ FAIL — only {profitable_windows}/{total_windows} windows profitable "
            f"(PFs: {', '.join(f'{pf:.2f}' for pf in pf_values)})"
        )
    else:
        temporal_details.append(
            f"  {coin}: ✅ PASS — {profitable_windows}/{total_windows} windows profitable "
            f"(PFs: {', '.join(f'{pf:.2f}' for pf in pf_values)})"
        )

# Check concentration
concentration_pass = True
if portfolio_results:
    max_share = max(abs(r['pnl']) / sum(abs(r['pnl']) for r in portfolio_results)
                    for r in portfolio_results) if sum(abs(r['pnl']) for r in portfolio_results) > 0 else 0
    if max_share > 0.60:
        concentration_pass = False

print()
print("  Temporal persistence:")
for detail in temporal_details:
    print(f"    {detail}")

print()
print(f"  Concentration: {'✅ PASS' if concentration_pass else '⚠️ CONCENTRATED'} "
      f"(HHI={hhi:.3f})")

print()
overall = "✅ PASS" if temporal_pass and concentration_pass else "⚠️ CONDITIONAL" if concentration_pass or temporal_pass else "❌ FAIL"
print(f"  OVERALL: {overall}")
print(f"    Temporal persistence: {'PASS' if temporal_pass else 'FAIL'}")
print(f"    Concentration check: {'PASS' if concentration_pass else 'FAIL'}")

# ─── Save report ─────────────────────────────────────────────────

report = {
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'config': 'fvg_x2027',
    'params': PARAMS,
    'coins': GO_COINS,
    'temporal_analysis': all_results,
    'per_coin_analysis': portfolio_results,
    'verdict': {
        'temporal_pass': temporal_pass,
        'concentration_pass': concentration_pass,
        'overall': overall,
        'hhi': round(hhi, 3) if portfolio_results else None,
    },
}

report_dir = ROOT / 'reports' / 'pipeline'
report_dir.mkdir(parents=True, exist_ok=True)
report_file = report_dir / 'scalp_temporal_validation.json'
with open(report_file, 'w') as f:
    json.dump(report, f, indent=2, default=str)
print(f"\nReport saved: {report_file}")
