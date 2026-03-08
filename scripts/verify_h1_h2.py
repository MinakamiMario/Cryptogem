#!/usr/bin/env python3
"""
Verification of H1 (Weekend) and H2 (Time-of-day) — Permutation + Temporal Split.

Two tests per hypothesis:
  1. Permutation test (10,000 shuffles): is observed PF-spread in top 5%?
  2. Temporal split: does pattern hold in first half AND second half?
"""

import sys, json, importlib, random, statistics
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))  # must be first — strategies.4h lives here

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
N_PERMUTATIONS = 10_000
SEED = 42

# ── Helpers ──────────────────────────────────────────────────────

def calc_pf(trades):
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss

def enrich_trades_with_time(trades, data):
    for t in trades:
        pair = t["pair"]
        candles = data[pair]
        if t["entry_bar"] < len(candles):
            ts = candles[t["entry_bar"]]["time"]
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            t["_entry_dt"] = dt
            t["_weekday"] = dt.weekday()
            t["_hour"] = dt.hour
            t["_entry_ts"] = ts
        else:
            t["_entry_dt"] = None
            t["_weekday"] = -1
            t["_hour"] = -1
            t["_entry_ts"] = 0

# ── Permutation test ─────────────────────────────────────────────

def pf_spread_weekend(trades, weekday_labels):
    """PF spread: weekend vs weekday, using provided labels."""
    wk_end = [t for t, w in zip(trades, weekday_labels) if w in (4, 5, 6)]
    wk_day = [t for t, w in zip(trades, weekday_labels) if w in (0, 1, 2, 3)]
    if not wk_end or not wk_day:
        return 0.0
    return calc_pf(wk_end) - calc_pf(wk_day)

def pf_range_hours(trades, hour_labels, min_per_group=10):
    """PF range across 4H windows, using provided labels."""
    groups = defaultdict(list)
    for t, h in zip(trades, hour_labels):
        groups[h].append(t)
    pfs = [calc_pf(trs) for h, trs in groups.items() if len(trs) >= min_per_group]
    if len(pfs) < 3:
        return 0.0
    return max(pfs) - min(pfs)

def run_permutation_test(trades, stat_fn, real_labels, n_perms, seed):
    """Generic permutation test. Returns p-value and null distribution stats."""
    rng = random.Random(seed)
    observed = stat_fn(trades, real_labels)

    null_dist = []
    for _ in range(n_perms):
        shuffled = list(real_labels)
        rng.shuffle(shuffled)
        null_dist.append(stat_fn(trades, shuffled))

    # One-sided p-value: how often is shuffled >= observed?
    count_ge = sum(1 for v in null_dist if v >= observed)
    p_value = count_ge / n_perms
    return observed, p_value, null_dist

# ── Temporal split ───────────────────────────────────────────────

def temporal_split_test(trades, group_fn, group_names_fn, min_per_group=10):
    """Split trades by entry_bar median, check pattern in both halves."""
    sorted_trades = sorted(trades, key=lambda t: t["entry_bar"])
    mid = len(sorted_trades) // 2
    early = sorted_trades[:mid]
    late = sorted_trades[mid:]

    results = {}
    for label, subset in [("early", early), ("late", late)]:
        groups = defaultdict(list)
        for t in subset:
            groups[group_fn(t)].append(t)
        pfs = {}
        for name, trs in groups.items():
            if len(trs) >= min_per_group:
                pfs[name] = calc_pf(trs)
        results[label] = {"pfs": pfs, "n_trades": len(subset)}
    return results

# ── Main ─────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    path = _data_resolver.resolve_dataset(DATASET_ID)
    with open(path) as f:
        data = json.load(f)

    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    print(f"Universe: {len(coins)} coins")

    print("Precomputing indicators...")
    indicators = _ms_indicators.precompute_ms_indicators(data, coins)

    configs = _ms_hypotheses.build_sweep_configs()
    ms_018 = [c for c in configs if "018" in c["id"]][0]

    print("Running backtest...")
    bt = _sprint3_engine.run_backtest(
        data=data, coins=coins,
        signal_fn=ms_018["signal_fn"], params=ms_018["params"],
        indicators=indicators, exit_mode="dc", start_bar=START_BAR,
    )
    trades = bt.trade_list
    enrich_trades_with_time(trades, data)
    print(f"Baseline: {len(trades)} trades, PF={bt.pf:.2f}\n")

    # ═══════════════════════════════════════════════════════════════
    # H1 VERIFICATION: Weekend filter
    # ═══════════════════════════════════════════════════════════════
    print("=" * 70)
    print("  H1 VERIFICATION: Weekend filter")
    print("=" * 70)

    real_weekdays = [t["_weekday"] for t in trades]

    # Permutation test
    print(f"\n  Permutation test ({N_PERMUTATIONS} shuffles)...")
    observed_h1, p_h1, null_h1 = run_permutation_test(
        trades, pf_spread_weekend, real_weekdays, N_PERMUTATIONS, SEED
    )
    null_mean = statistics.mean(null_h1)
    null_std = statistics.stdev(null_h1) if len(null_h1) > 1 else 0
    null_p95 = sorted(null_h1)[int(0.95 * len(null_h1))]

    print(f"  Observed PF spread (weekend - weekday): {observed_h1:+.2f}")
    print(f"  Null distribution: mean={null_mean:.3f}, std={null_std:.3f}, P95={null_p95:.3f}")
    print(f"  p-value: {p_h1:.4f}")
    h1_perm_pass = p_h1 < 0.05
    print(f"  → {'SIGNIFICANT (p < 0.05)' if h1_perm_pass else 'NIET SIGNIFICANT (p >= 0.05)'}")

    # Temporal split
    print(f"\n  Temporal split (early vs late half)...")
    h1_temporal = temporal_split_test(
        trades, lambda t: "weekend" if t["_weekday"] in (4, 5, 6) else "weekday",
        lambda t: t
    )
    for period, info in h1_temporal.items():
        pfs = info["pfs"]
        pf_we = pfs.get("weekend", 0)
        pf_wd = pfs.get("weekday", 0)
        n = info["n_trades"]
        marker = "✅" if pf_we > pf_wd else "❌"
        print(f"  {period:>6}: {n} trades | weekend PF={pf_we:.2f} vs weekday PF={pf_wd:.2f} {marker}")

    h1_early_holds = h1_temporal["early"]["pfs"].get("weekend", 0) > h1_temporal["early"]["pfs"].get("weekday", 0)
    h1_late_holds = h1_temporal["late"]["pfs"].get("weekend", 0) > h1_temporal["late"]["pfs"].get("weekday", 0)
    h1_temporal_pass = h1_early_holds and h1_late_holds
    print(f"  → {'STABIEL in beide helften' if h1_temporal_pass else 'INSTABIEL — patroon houdt niet in beide helften'}")

    h1_verified = h1_perm_pass and h1_temporal_pass
    print(f"\n  H1 EINDOORDEEL: {'✅ VERIFIED' if h1_verified else '❌ NOT VERIFIED'}")
    if not h1_perm_pass:
        print(f"    Reden: permutatie-test niet significant (p={p_h1:.4f})")
    if not h1_temporal_pass:
        print(f"    Reden: patroon instabiel over tijd")

    # ═══════════════════════════════════════════════════════════════
    # H2 VERIFICATION: Time-of-day
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("  H2 VERIFICATION: Time-of-day")
    print("=" * 70)

    real_hours = [t["_hour"] for t in trades]

    # Permutation test
    print(f"\n  Permutation test ({N_PERMUTATIONS} shuffles)...")
    observed_h2, p_h2, null_h2 = run_permutation_test(
        trades, pf_range_hours, real_hours, N_PERMUTATIONS, SEED
    )
    null_mean_h2 = statistics.mean(null_h2)
    null_std_h2 = statistics.stdev(null_h2) if len(null_h2) > 1 else 0
    null_p95_h2 = sorted(null_h2)[int(0.95 * len(null_h2))]

    print(f"  Observed PF range across 4H windows: {observed_h2:.2f}")
    print(f"  Null distribution: mean={null_mean_h2:.3f}, std={null_std_h2:.3f}, P95={null_p95_h2:.3f}")
    print(f"  p-value: {p_h2:.4f}")
    h2_perm_pass = p_h2 < 0.05
    print(f"  → {'SIGNIFICANT (p < 0.05)' if h2_perm_pass else 'NIET SIGNIFICANT (p >= 0.05)'}")

    # Temporal split
    print(f"\n  Temporal split (early vs late half)...")
    h2_temporal = temporal_split_test(
        trades, lambda t: f"{t['_hour']:02d}:00",
        lambda t: t
    )

    # Check: is worst window consistent?
    print(f"\n  {'Period':<8} {'Worst window':<14} {'Worst PF':>10} {'Best window':<14} {'Best PF':>10} {'Range':>8}")
    print(f"  {'-'*8} {'-'*14} {'-'*10} {'-'*14} {'-'*10} {'-'*8}")
    worst_windows = []
    best_windows = []
    for period in ["early", "late"]:
        pfs = h2_temporal[period]["pfs"]
        if pfs:
            worst = min(pfs, key=pfs.get)
            best = max(pfs, key=pfs.get)
            pf_range = pfs[best] - pfs[worst]
            worst_windows.append(worst)
            best_windows.append(best)
            print(f"  {period:<8} {worst:<14} {pfs[worst]:>10.2f} {best:<14} {pfs[best]:>10.2f} {pf_range:>8.2f}")

    # H2 temporal: pattern holds if range > 0.5 in both halves
    h2_ranges = []
    for period in ["early", "late"]:
        pfs = h2_temporal[period]["pfs"]
        if len(pfs) >= 3:
            vals = list(pfs.values())
            h2_ranges.append(max(vals) - min(vals))
    h2_temporal_pass = len(h2_ranges) == 2 and all(r > 0.5 for r in h2_ranges)

    # Also check: is the WORST window the same in both halves?
    worst_consistent = len(worst_windows) == 2 and worst_windows[0] == worst_windows[1]
    print(f"\n  Worst window consistent: {'✅ ' + worst_windows[0] if worst_consistent else '❌ ' + str(worst_windows)}")
    print(f"  Range > 0.5 in both halves: {'✅' if h2_temporal_pass else '❌'} ({', '.join(f'{r:.2f}' for r in h2_ranges)})")

    h2_verified = h2_perm_pass and h2_temporal_pass
    print(f"\n  H2 EINDOORDEEL: {'✅ VERIFIED' if h2_verified else '❌ NOT VERIFIED'}")
    if not h2_perm_pass:
        print(f"    Reden: permutatie-test niet significant (p={p_h2:.4f})")
    if not h2_temporal_pass:
        print(f"    Reden: PF-range niet materieel in beide helften")

    # ═══════════════════════════════════════════════════════════════
    # SAMENVATTING
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'=' * 70}")
    print("  VERIFICATIE SAMENVATTING")
    print("=" * 70)
    results = [
        ("H1: Weekend filter", h1_perm_pass, h1_temporal_pass, h1_verified),
        ("H2: Time-of-day", h2_perm_pass, h2_temporal_pass, h2_verified),
    ]
    print(f"  {'Hypothese':<25} {'Permutatie':>12} {'Temporeel':>12} {'Eindoordeel':>14}")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*14}")
    for name, perm, temp, verified in results:
        p_str = "✅ p<0.05" if perm else "❌ p≥0.05"
        t_str = "✅ stabiel" if temp else "❌ instabiel"
        v_str = "✅ VERIFIED" if verified else "❌ FAILED"
        print(f"  {name:<25} {p_str:>12} {t_str:>12} {v_str:>14}")

    verified_count = sum(1 for _, _, _, v in results if v)
    print(f"\n  {verified_count}/2 hypotheses geverifieerd")

    # Save
    output = {
        "h1_weekend": {
            "observed_spread": round(observed_h1, 3),
            "p_value": round(p_h1, 4),
            "permutation_pass": h1_perm_pass,
            "temporal_pass": h1_temporal_pass,
            "early_weekend_pf": round(h1_temporal["early"]["pfs"].get("weekend", 0), 3),
            "early_weekday_pf": round(h1_temporal["early"]["pfs"].get("weekday", 0), 3),
            "late_weekend_pf": round(h1_temporal["late"]["pfs"].get("weekend", 0), 3),
            "late_weekday_pf": round(h1_temporal["late"]["pfs"].get("weekday", 0), 3),
            "verdict": "VERIFIED" if h1_verified else "FAILED",
        },
        "h2_time_of_day": {
            "observed_range": round(observed_h2, 3),
            "p_value": round(p_h2, 4),
            "permutation_pass": h2_perm_pass,
            "temporal_pass": h2_temporal_pass,
            "worst_windows": worst_windows,
            "worst_consistent": worst_consistent,
            "verdict": "VERIFIED" if h2_verified else "FAILED",
        },
    }
    out_path = REPO_ROOT / "reports" / "tier1_verification_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Opgeslagen: {out_path}")


if __name__ == "__main__":
    main()
