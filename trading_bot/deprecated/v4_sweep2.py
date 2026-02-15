#!/usr/bin/env python3
"""
V4 Sweep Round 2 - Deeper exploration of additional params.

From Round 1:
- ATR 1.75 improved PF to 18.88 (same DD 5.8%) with +$12 P&L
- time_max=10 improved PF to 19.28 but DD rose to 7.1%
- Combo tmb=10 + atr=1.75 gives PF 20.12 but DD 7.1%
- BE trigger had zero effect (all values identical)
- Trailing TP had zero effect

Now explore:
F) RSI threshold sweep: 30, 35, 38, 40, 42, 45, 50
G) Volume spike multiplier: 1.5, 1.75, 2.0, 2.5, 3.0
H) Cooldown bars: 2/4, 3/6, 4/8, 5/10, 6/12
I) Donchian period: 14, 16, 18, 20, 24, 30
J) BB deviation: 1.5, 1.75, 2.0, 2.25, 2.5
K) Max stop loss: 8%, 10%, 12%, 15%, 20%
L) Grand combo sweep of best from all
"""
import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from backtest_combined_winner import (
    CombinedWinnerStrategy, run_portfolio_backtest
)

print("Loading candle cache...")
with open(BASE_DIR / 'candle_cache_60d.json') as f:
    DATA = json.load(f)
print(f"Cache loaded: {len([k for k in DATA if not k.startswith('_')])} coins")


def run_test(label, **strategy_overrides):
    defaults = dict(
        donchian_period=20, bb_period=20, bb_dev=2.0,
        rsi_period=14, rsi_max=40, rsi_sell=70,
        atr_period=14, atr_stop_mult=2.0,
        max_stop_loss_pct=15.0,
        cooldown_bars=4, cooldown_after_stop=8,
        volume_min_pct=0.5,
        use_volume_spike=True, volume_spike_mult=2.0,
        use_breakeven_stop=True, breakeven_trigger_pct=3.0,
        use_time_max=True, time_max_bars=16,
    )
    defaults.update(strategy_overrides)

    def factory(params=defaults):
        return CombinedWinnerStrategy(**params)

    return run_portfolio_backtest(
        DATA, factory, max_positions=1, position_size=2000,
        use_signal_ranking=True, coin_filter_fn=None, label=label,
    )


def fmt(r):
    pf = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    print(f"  {r['label']:<55} | {r['trades']:>3} | {r['win_rate']:>5.1f}% | "
          f"${r['total_pnl']:>+9.0f} | {pf:>7} | {r['max_dd']:>5.1f}% | {r['score']:>5.1f}")


def hdr():
    print(f"  {'CONFIG':<55} | {'#TR':>3} | {'WR':>6} | {'P&L':>10} | {'PF':>7} | {'DD':>6} | {'SCORE':>5}")
    print("  " + "-" * 105)


baseline = run_test("V3 BASELINE")

# ============================================================
# F: RSI THRESHOLD
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP F: RSI THRESHOLD")
print("=" * 110)
hdr()
fmt(baseline)

sweep_f = []
for rsi in [30, 35, 38, 40, 42, 45, 50]:
    r = run_test(f"rsi_max={rsi}", rsi_max=rsi)
    fmt(r)
    sweep_f.append(r)

best_f = max(sweep_f, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best RSI: {best_f['label']} (PF {best_f['pf']:.2f}, DD {best_f['max_dd']:.1f}%, trades={best_f['trades']})")

# ============================================================
# G: VOLUME SPIKE MULTIPLIER
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP G: VOLUME SPIKE MULTIPLIER")
print("=" * 110)
hdr()
fmt(baseline)

sweep_g = []
for vsm in [1.5, 1.75, 2.0, 2.5, 3.0]:
    r = run_test(f"vol_spike_mult={vsm}x", volume_spike_mult=vsm)
    fmt(r)
    sweep_g.append(r)

best_g = max(sweep_g, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best VOL SPIKE: {best_g['label']} (PF {best_g['pf']:.2f}, DD {best_g['max_dd']:.1f}%, trades={best_g['trades']})")

# ============================================================
# H: COOLDOWN BARS
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP H: COOLDOWN BARS (normal / after_stop)")
print("=" * 110)
hdr()
fmt(baseline)

sweep_h = []
for cd, cd_s in [(2, 4), (3, 6), (4, 8), (5, 10), (6, 12), (2, 8), (4, 12)]:
    r = run_test(f"cooldown={cd}/{cd_s}", cooldown_bars=cd, cooldown_after_stop=cd_s)
    fmt(r)
    sweep_h.append(r)

best_h = max(sweep_h, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best COOLDOWN: {best_h['label']} (PF {best_h['pf']:.2f}, DD {best_h['max_dd']:.1f}%, trades={best_h['trades']})")

# ============================================================
# I: DONCHIAN PERIOD
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP I: DONCHIAN PERIOD")
print("=" * 110)
hdr()
fmt(baseline)

sweep_i = []
for dp in [14, 16, 18, 20, 24, 30]:
    r = run_test(f"donchian_period={dp}", donchian_period=dp)
    fmt(r)
    sweep_i.append(r)

best_i = max(sweep_i, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best DONCHIAN: {best_i['label']} (PF {best_i['pf']:.2f}, DD {best_i['max_dd']:.1f}%, trades={best_i['trades']})")

# ============================================================
# J: BB DEVIATION
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP J: BOLLINGER BAND DEVIATION")
print("=" * 110)
hdr()
fmt(baseline)

sweep_j = []
for bbd in [1.5, 1.75, 2.0, 2.25, 2.5]:
    r = run_test(f"bb_dev={bbd}", bb_dev=bbd)
    fmt(r)
    sweep_j.append(r)

best_j = max(sweep_j, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best BB DEV: {best_j['label']} (PF {best_j['pf']:.2f}, DD {best_j['max_dd']:.1f}%, trades={best_j['trades']})")

# ============================================================
# K: MAX STOP LOSS
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP K: MAX STOP LOSS PCT")
print("=" * 110)
hdr()
fmt(baseline)

sweep_k = []
for msl in [8, 10, 12, 15, 20]:
    r = run_test(f"max_stop_loss={msl}%", max_stop_loss_pct=float(msl))
    fmt(r)
    sweep_k.append(r)

best_k = max(sweep_k, key=lambda x: x['pf'] if x['trades'] >= 5 else 0)
print(f"\n  >> Best MAX SL: {best_k['label']} (PF {best_k['pf']:.2f}, DD {best_k['max_dd']:.1f}%, trades={best_k['trades']})")

# ============================================================
# L: GRAND COMBO from all individual bests
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP L: GRAND COMBO — best from each individual sweep")
print("=" * 110)

# Extract best param values
def extract_val(label, prefix, vals, default):
    for v in vals:
        if f"{prefix}{v}" in label:
            return v
    return default

best_rsi = extract_val(best_f['label'], "rsi_max=", [30,35,38,40,42,45,50], 40)
best_vsm = extract_val(best_g['label'], "vol_spike_mult=", [1.5,1.75,2.0,2.5,3.0], 2.0)
best_dp = extract_val(best_i['label'], "donchian_period=", [14,16,18,20,24,30], 20)
best_bbd = extract_val(best_j['label'], "bb_dev=", [1.5,1.75,2.0,2.25,2.5], 2.0)
best_msl = extract_val(best_k['label'], "max_stop_loss=", [8,10,12,15,20], 15)

# Extract cooldown
best_cd = (4, 8)
for cd, cd_s in [(2,4),(3,6),(4,8),(5,10),(6,12),(2,8),(4,12)]:
    if f"cooldown={cd}/{cd_s}" in best_h['label']:
        best_cd = (cd, cd_s)
        break

print(f"  Individual bests: RSI={best_rsi}, VSM={best_vsm}x, DC={best_dp}, BB={best_bbd}, "
      f"MSL={best_msl}%, CD={best_cd[0]}/{best_cd[1]}")
print(f"  + from Round 1: ATR=1.75, time_max=10")
print()

hdr()
fmt(baseline)

# Full grand combo
gc = run_test(
    f"GRAND: rsi{best_rsi} vsm{best_vsm} dc{best_dp} bb{best_bbd} msl{best_msl} cd{best_cd[0]}/{best_cd[1]} atr1.75 tmb10",
    rsi_max=best_rsi, volume_spike_mult=best_vsm,
    donchian_period=best_dp, bb_dev=best_bbd,
    max_stop_loss_pct=float(best_msl),
    cooldown_bars=best_cd[0], cooldown_after_stop=best_cd[1],
    atr_stop_mult=1.75, time_max_bars=10,
)
fmt(gc)

# Grand combo without round 1 changes (only round 2 bests)
gc2 = run_test(
    f"R2 ONLY: rsi{best_rsi} vsm{best_vsm} dc{best_dp} bb{best_bbd} msl{best_msl} cd{best_cd[0]}/{best_cd[1]}",
    rsi_max=best_rsi, volume_spike_mult=best_vsm,
    donchian_period=best_dp, bb_dev=best_bbd,
    max_stop_loss_pct=float(best_msl),
    cooldown_bars=best_cd[0], cooldown_after_stop=best_cd[1],
)
fmt(gc2)

# ATR 1.75 only (best from round 1 that doesn't hurt DD)
gc3 = run_test(
    f"R1 SAFE: atr1.75 + rsi{best_rsi} vsm{best_vsm} dc{best_dp} bb{best_bbd} msl{best_msl}",
    atr_stop_mult=1.75,
    rsi_max=best_rsi, volume_spike_mult=best_vsm,
    donchian_period=best_dp, bb_dev=best_bbd,
    max_stop_loss_pct=float(best_msl),
    cooldown_bars=best_cd[0], cooldown_after_stop=best_cd[1],
)
fmt(gc3)

# Conservative combos: only params that don't increase DD
# ATR 1.75 was DD-neutral
gc4 = run_test(
    "SAFE COMBO: atr=1.75 (DD-neutral from R1)",
    atr_stop_mult=1.75,
)
fmt(gc4)

# ============================================================
# M: Fine-grain around promising values
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP M: FINE-GRAIN around ATR=1.75 (DD-neutral PF improver)")
print("=" * 110)
hdr()
fmt(baseline)

for atr_m in [1.6, 1.65, 1.7, 1.75, 1.8, 1.85, 1.9]:
    r = run_test(f"atr_fine={atr_m}", atr_stop_mult=atr_m)
    fmt(r)

# ============================================================
# N: Try disabling time_max entirely and relying on other exits
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP N: TIME MAX ON vs OFF")
print("=" * 110)
hdr()
fmt(baseline)

r_no_time = run_test("use_time_max=OFF", use_time_max=False)
fmt(r_no_time)

r_no_be = run_test("use_breakeven_stop=OFF", use_breakeven_stop=False)
fmt(r_no_be)

r_both_off = run_test("time_max=OFF + be=OFF", use_time_max=False, use_breakeven_stop=False)
fmt(r_both_off)

# ============================================================
# O: RSI sell threshold
# ============================================================
print("\n" + "=" * 110)
print("  SWEEP O: RSI SELL THRESHOLD (overbought exit)")
print("=" * 110)
hdr()
fmt(baseline)

for rs in [55, 60, 65, 70, 75, 80]:
    r = run_test(f"rsi_sell={rs}", rsi_sell=rs)
    fmt(r)

# ============================================================
# GRAND SUMMARY
# ============================================================
print("\n" + "=" * 110)
print("  ROUND 2 GRAND SUMMARY")
print("=" * 110)
print(f"\n  V3 BASELINE: 19 trades | WR 78.9% | P&L $+5,090 | PF 18.16 | DD 5.8%\n")

all_bests = [
    ("F: RSI thresh", best_f),
    ("G: Vol spike mult", best_g),
    ("H: Cooldown", best_h),
    ("I: Donchian period", best_i),
    ("J: BB deviation", best_j),
    ("K: Max stop loss", best_k),
    ("L: Grand combo", gc),
    ("L: R2 only", gc2),
    ("L: R1 safe + R2", gc3),
]

print(f"  {'SWEEP':<25} | {'CONFIG':<55} | {'#TR':>3} | {'WR':>6} | {'P&L':>10} | {'PF':>7} | {'DD':>6}")
print("  " + "-" * 125)

for name, r in all_bests:
    pf = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    tag = ""
    if r['pf'] > 18.16 and r['trades'] >= 5:
        tag += " ** BETTER PF"
    if r['max_dd'] < 5.8 and r['trades'] >= 5:
        tag += " ** BETTER DD"
    print(f"  {name:<25} | {r['label']:<55} | {r['trades']:>3} | {r['win_rate']:>5.1f}% | "
          f"${r['total_pnl']:>+9.0f} | {pf:>7} | {r['max_dd']:>5.1f}%{tag}")

print("\n" + "=" * 110)
