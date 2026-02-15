#!/usr/bin/env python3
"""
V4 Parameter Sweep - Multi-parameter optimization on top of V3 baseline.

V3 Baseline: 19 trades | WR 78.9% | P&L $5,090 | PF 18.16 | DD 5.8%
V3 Params: RSI 40, VolSpike 2.0x, ATR stop 2.0x, BE trigger 3%, time_max 16,
           Donchian 20, BB dev 2.0, cooldown 4/8, max SL 15%
           1x$2000, signal ranking, vol spike + BE + time_max all ON
"""
import sys
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from backtest_combined_winner import (
    CombinedWinnerStrategy, run_portfolio_backtest, vol_filter_p50
)

# Load cache once
print("Loading candle cache...")
with open(BASE_DIR / 'candle_cache_60d.json') as f:
    DATA = json.load(f)
print(f"Cache loaded: {len([k for k in DATA if not k.startswith('_')])} coins")


def run_test(label, **strategy_overrides):
    """Run a single backtest with V3 defaults + overrides."""
    # V3 baseline defaults
    defaults = dict(
        donchian_period=20,
        bb_period=20,
        bb_dev=2.0,
        rsi_period=14,
        rsi_max=40,
        rsi_sell=70,
        atr_period=14,
        atr_stop_mult=2.0,
        max_stop_loss_pct=15.0,
        cooldown_bars=4,
        cooldown_after_stop=8,
        volume_min_pct=0.5,
        use_volume_spike=True,
        volume_spike_mult=2.0,
        use_breakeven_stop=True,
        breakeven_trigger_pct=3.0,
        use_time_max=True,
        time_max_bars=16,
    )
    defaults.update(strategy_overrides)

    def factory(params=defaults):
        return CombinedWinnerStrategy(**params)

    result = run_portfolio_backtest(
        DATA, factory,
        max_positions=1,
        position_size=2000,
        use_signal_ranking=True,
        coin_filter_fn=None,
        label=label,
    )
    return result


def print_result(r):
    """Print one result line."""
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    print(f"  {r['label']:<55} | {r['trades']:>3} | {r['win_rate']:>5.1f}% | "
          f"${r['total_pnl']:>+9.0f} | {pf_str:>7} | {r['max_dd']:>5.1f}% | {r['score']:>5.1f}")


def print_header():
    print(f"  {'CONFIG':<55} | {'#TR':>3} | {'WR':>6} | {'P&L':>10} | {'PF':>7} | {'DD':>6} | {'SCORE':>5}")
    print("  " + "-" * 105)


# ============================================================
# SWEEP A: TIME MAX BARS
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP A: TIME MAX BARS fijnafstemming")
print("=" * 110)
print_header()

baseline = run_test("V3 BASELINE (time_max=16)")
print_result(baseline)

sweep_a_results = [baseline]
for tmb in [10, 12, 14, 18, 20, 24]:
    r = run_test(f"time_max={tmb}", time_max_bars=tmb)
    print_result(r)
    sweep_a_results.append(r)

best_a = max(sweep_a_results, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best TIME MAX: {best_a['label']} (PF {best_a['pf']:.2f}, DD {best_a['max_dd']:.1f}%)")

# Extract best time_max value
best_time_max = 16  # default
for r in sweep_a_results:
    if r == best_a:
        for tmb in [10, 12, 14, 16, 18, 20, 24]:
            if f"time_max={tmb}" in r['label'] or (tmb == 16 and "BASELINE" in r['label']):
                best_time_max = tmb
                break

# ============================================================
# SWEEP B: ATR STOP MULTIPLIER
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP B: ATR STOP MULTIPLIER fijnafstemming")
print("=" * 110)
print_header()

sweep_b_results = []
for atr_m in [1.5, 1.75, 2.0, 2.25, 2.5]:
    r = run_test(f"atr_stop_mult={atr_m}", atr_stop_mult=atr_m)
    print_result(r)
    sweep_b_results.append(r)

best_b = max(sweep_b_results, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best ATR STOP: {best_b['label']} (PF {best_b['pf']:.2f}, DD {best_b['max_dd']:.1f}%)")

best_atr_mult = 2.0
for atr_m in [1.5, 1.75, 2.0, 2.25, 2.5]:
    if f"atr_stop_mult={atr_m}" in best_b['label']:
        best_atr_mult = atr_m
        break

# ============================================================
# SWEEP C: BREAK-EVEN TRIGGER
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP C: BREAK-EVEN TRIGGER fijnafstemming")
print("=" * 110)
print_header()

sweep_c_results = []
for be_pct in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    r = run_test(f"breakeven_trigger={be_pct}%", breakeven_trigger_pct=be_pct)
    print_result(r)
    sweep_c_results.append(r)

best_c = max(sweep_c_results, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best BE TRIGGER: {best_c['label']} (PF {best_c['pf']:.2f}, DD {best_c['max_dd']:.1f}%)")

best_be_trigger = 3.0
for be_pct in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    if f"breakeven_trigger={be_pct}%" in best_c['label']:
        best_be_trigger = be_pct
        break

# ============================================================
# SWEEP D: COMBINATION of best params
# ============================================================
print("\n" + "=" * 110)
print(f"  SWEEP D: COMBINATIE — time_max={best_time_max}, atr_stop={best_atr_mult}, be_trigger={best_be_trigger}%")
print("=" * 110)
print_header()

# V3 baseline for reference
print_result(baseline)

# Best combo from individual sweeps
combo_r = run_test(
    f"COMBO: tmb={best_time_max} + atr={best_atr_mult} + be={best_be_trigger}%",
    time_max_bars=best_time_max,
    atr_stop_mult=best_atr_mult,
    breakeven_trigger_pct=best_be_trigger,
)
print_result(combo_r)

# Also test a few promising 2-param combos
# Best time_max + best ATR
combo2a = run_test(
    f"tmb={best_time_max} + atr={best_atr_mult}",
    time_max_bars=best_time_max,
    atr_stop_mult=best_atr_mult,
)
print_result(combo2a)

# Best time_max + best BE
combo2b = run_test(
    f"tmb={best_time_max} + be={best_be_trigger}%",
    time_max_bars=best_time_max,
    breakeven_trigger_pct=best_be_trigger,
)
print_result(combo2b)

# Best ATR + best BE
combo2c = run_test(
    f"atr={best_atr_mult} + be={best_be_trigger}%",
    atr_stop_mult=best_atr_mult,
    breakeven_trigger_pct=best_be_trigger,
)
print_result(combo2c)

# Also try some aggressive combos with tighter time
for tmb_extra in [10, 12]:
    for atr_extra in [1.5, 1.75]:
        r = run_test(
            f"AGGRO: tmb={tmb_extra} + atr={atr_extra} + be={best_be_trigger}%",
            time_max_bars=tmb_extra,
            atr_stop_mult=atr_extra,
            breakeven_trigger_pct=best_be_trigger,
        )
        print_result(r)

sweep_d_all = [baseline, combo_r, combo2a, combo2b, combo2c]
best_d = max(sweep_d_all, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best COMBO: {best_d['label']} (PF {best_d['pf']:.2f}, DD {best_d['max_dd']:.1f}%)")


# ============================================================
# SWEEP E: TRAILING TAKE PROFIT
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP E: TRAILING TAKE PROFIT — experimenteel")
print("  Idee: Als trade > +X% is, zet trailing stop op +Y% (nooit minder)")
print("=" * 110)
print()
print("  NOTE: Dit vereist een aangepaste strategy class.")
print("  We maken een subclass van CombinedWinnerStrategy met trailing TP logic.")
print()

# Create a subclass with trailing take profit
from backtest_combined_winner import KRAKEN_FEE
from strategy import Signal

class TrailingTPStrategy(CombinedWinnerStrategy):
    """Extended strategy with trailing take profit."""
    def __init__(self, trailing_tp_trigger_pct=5.0, trailing_tp_floor_pct=3.0, **kwargs):
        super().__init__(**kwargs)
        self.trailing_tp_trigger_pct = trailing_tp_trigger_pct
        self.trailing_tp_floor_pct = trailing_tp_floor_pct

    def analyze(self, candles, position, pair):
        """Override analyze to add trailing TP before normal exit logic."""
        # First check trailing TP condition
        if position and position.side == 'long':
            entry_price = position.entry_price
            close = candles[-1]['close']
            highest = position.highest_price

            # Update highest
            if close > highest:
                highest = close

            # Check if we ever reached the trigger
            highest_profit_pct = (highest - entry_price) / entry_price * 100
            current_profit_pct = (close - entry_price) / entry_price * 100

            if highest_profit_pct >= self.trailing_tp_trigger_pct:
                # We reached the trigger! Now enforce the floor
                if current_profit_pct < self.trailing_tp_floor_pct:
                    return Signal('SELL', pair, close,
                                  f'TRAIL TP (was +{highest_profit_pct:.1f}%, now +{current_profit_pct:.1f}%)',
                                  confidence=0.9)

        # Fall through to normal logic
        return super().analyze(candles, position, pair)


def run_trailing_tp_test(label, trigger_pct, floor_pct, **extra_overrides):
    """Run backtest with trailing TP strategy."""
    defaults = dict(
        donchian_period=20,
        bb_period=20,
        bb_dev=2.0,
        rsi_period=14,
        rsi_max=40,
        rsi_sell=70,
        atr_period=14,
        atr_stop_mult=2.0,
        max_stop_loss_pct=15.0,
        cooldown_bars=4,
        cooldown_after_stop=8,
        volume_min_pct=0.5,
        use_volume_spike=True,
        volume_spike_mult=2.0,
        use_breakeven_stop=True,
        breakeven_trigger_pct=3.0,
        use_time_max=True,
        time_max_bars=16,
    )
    defaults.update(extra_overrides)

    def factory(params=defaults, tp_trig=trigger_pct, tp_floor=floor_pct):
        return TrailingTPStrategy(
            trailing_tp_trigger_pct=tp_trig,
            trailing_tp_floor_pct=tp_floor,
            **params
        )

    result = run_portfolio_backtest(
        DATA, factory,
        max_positions=1,
        position_size=2000,
        use_signal_ranking=True,
        coin_filter_fn=None,
        label=label,
    )
    return result


print_header()
print_result(baseline)

sweep_e_results = [baseline]

# Test different trigger/floor combos
tp_combos = [
    (5.0, 3.0, "trigger=5%/floor=3%"),
    (5.0, 2.0, "trigger=5%/floor=2%"),
    (4.0, 2.0, "trigger=4%/floor=2%"),
    (4.0, 2.5, "trigger=4%/floor=2.5%"),
    (3.0, 1.5, "trigger=3%/floor=1.5%"),
    (6.0, 4.0, "trigger=6%/floor=4%"),
    (7.0, 5.0, "trigger=7%/floor=5%"),
    (8.0, 5.0, "trigger=8%/floor=5%"),
]

for trig, flr, desc in tp_combos:
    r = run_trailing_tp_test(f"TrailTP {desc}", trig, flr)
    print_result(r)
    sweep_e_results.append(r)

# Also test trailing TP combined with best params from sweep D
print()
print("  Trailing TP + best combo params:")
print_header()

for trig, flr, desc in [(5.0, 3.0, "5/3"), (4.0, 2.0, "4/2"), (3.0, 1.5, "3/1.5")]:
    r = run_trailing_tp_test(
        f"TrailTP {desc} + tmb={best_time_max} atr={best_atr_mult} be={best_be_trigger}",
        trig, flr,
        time_max_bars=best_time_max,
        atr_stop_mult=best_atr_mult,
        breakeven_trigger_pct=best_be_trigger,
    )
    print_result(r)
    sweep_e_results.append(r)

best_e = max(sweep_e_results, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best TRAIL TP: {best_e['label']} (PF {best_e['pf']:.2f}, DD {best_e['max_dd']:.1f}%)")


# ============================================================
# GRAND SUMMARY
# ============================================================
print("\n" + "=" * 110)
print("  GRAND SUMMARY — V4 Sweep Results vs V3 Baseline")
print("=" * 110)
print(f"\n  V3 BASELINE: {baseline['trades']} trades | WR {baseline['win_rate']:.1f}% | "
      f"P&L ${baseline['total_pnl']:+,.0f} | PF {baseline['pf']:.2f} | DD {baseline['max_dd']:.1f}%")
print()

# Collect all best results
all_bests = [
    ("A: Best TIME MAX", best_a),
    ("B: Best ATR STOP", best_b),
    ("C: Best BE TRIGGER", best_c),
    ("D: Best COMBO", best_d),
    ("E: Best TRAIL TP", best_e),
]

print(f"  {'SWEEP':<25} | {'CONFIG':<55} | {'#TR':>3} | {'WR':>6} | {'P&L':>10} | {'PF':>7} | {'DD':>6}")
print("  " + "-" * 125)

for sweep_name, r in all_bests:
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    improved = ""
    if r['pf'] > baseline['pf'] and r['trades'] >= 5:
        improved = " <<<< BETTER PF"
    if r['max_dd'] < baseline['max_dd'] and r['pf'] >= baseline['pf'] * 0.9:
        improved += " <<<< BETTER DD"
    print(f"  {sweep_name:<25} | {r['label']:<55} | {r['trades']:>3} | {r['win_rate']:>5.1f}% | "
          f"${r['total_pnl']:>+9.0f} | {pf_str:>7} | {r['max_dd']:>5.1f}%{improved}")

# Find the overall winner
all_results = sweep_a_results + sweep_b_results + sweep_c_results + sweep_e_results + [combo_r, combo2a, combo2b, combo2c]
# Filter for >= 5 trades
valid_results = [r for r in all_results if r['trades'] >= 5]

if valid_results:
    # Winner by PF
    winner_pf = max(valid_results, key=lambda x: x['pf'])
    # Winner by DD (lowest DD with PF >= 90% of baseline)
    good_pf = [r for r in valid_results if r['pf'] >= baseline['pf'] * 0.9]
    winner_dd = min(good_pf, key=lambda x: x['max_dd']) if good_pf else None
    # Winner by composite score
    winner_score = max(valid_results, key=lambda x: x['score'])

    print(f"\n  WINNERS:")
    print(f"  -------")
    pf_str = f"{winner_pf['pf']:.2f}" if winner_pf['pf'] < 9999 else "INF"
    print(f"  Best PF:    {winner_pf['label']} → PF {pf_str}, {winner_pf['trades']} trades, DD {winner_pf['max_dd']:.1f}%")
    if winner_dd:
        pf_str = f"{winner_dd['pf']:.2f}" if winner_dd['pf'] < 9999 else "INF"
        print(f"  Best DD:    {winner_dd['label']} → DD {winner_dd['max_dd']:.1f}%, PF {pf_str}, {winner_dd['trades']} trades")
    print(f"  Best Score: {winner_score['label']} → Score {winner_score['score']:.1f}, PF {winner_score['pf']:.2f}, DD {winner_score['max_dd']:.1f}%")

print("\n" + "=" * 110)
print("  SWEEP COMPLETE")
print("=" * 110)
