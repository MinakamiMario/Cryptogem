#!/usr/bin/env python3
"""
H8: Cross-Sectional Momentum als Filter op ms_018 — Falsificatie + Verificatie

Mechanisme: Coins in top momentum-quintiel (afgelopen 14 dagen) zouden betere
ms_018 entries moeten geven — momentum anomalie versterkt BoS signals.

Falsificatie: Vergelijk PF van top-50% momentum trades vs ongefilterd.
Als PF gefilterd ≤ PF ongefilterd → verworpen.

Includes permutation test + temporal split.
"""

import sys, json, importlib, random, statistics
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_market_context = importlib.import_module("strategies.4h.sprint2.market_context")

DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
N_PERMUTATIONS = 10_000
SEED = 42

# 14 days = 84 4H bars
MOMENTUM_PERIOD = 84

# ── Helpers ──────────────────────────────────────────────────────

def calc_pf(trades):
    gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl

def calc_wr(trades):
    if not trades:
        return 0.0
    return 100 * sum(1 for t in trades if t["pnl"] > 0) / len(trades)

def calc_pnl(trades):
    return sum(t["pnl"] for t in trades)


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    path = _data_resolver.resolve_dataset(DATASET_ID)
    with open(path) as f:
        data = json.load(f)

    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    n_coins = len(coins)
    print(f"Universe: {n_coins} coins")

    print("Precomputing ms_018 indicators...")
    indicators = _ms_indicators.precompute_ms_indicators(data, coins)

    print(f"Precomputing momentum context (period={MOMENTUM_PERIOD} bars = {MOMENTUM_PERIOD*4//24} days)...")
    ctx = _market_context.precompute_sprint2_context(data, coins, momentum_period=MOMENTUM_PERIOD)

    configs = _ms_hypotheses.build_sweep_configs()
    ms_018 = [c for c in configs if "018" in c["id"]][0]

    print("Running baseline backtest...")
    bt = _sprint3_engine.run_backtest(
        data=data, coins=coins,
        signal_fn=ms_018["signal_fn"], params=ms_018["params"],
        indicators=indicators, exit_mode="dc", start_bar=START_BAR,
    )
    trades = bt.trade_list
    baseline_pf = bt.pf
    print(f"Baseline: {len(trades)} trades, PF={bt.pf:.2f}, WR={bt.wr:.1f}%, P&L=${bt.pnl:+,.0f}")

    # ═══════════════════════════════════════════════════════════════
    # Annotate trades with momentum rank
    # ═══════════════════════════════════════════════════════════════

    for t in trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        rank_arr = ctx["momentum_rank"].get(pair, [])
        n_ranked_arr = ctx["n_ranked"]

        if bar < len(rank_arr) and bar < len(n_ranked_arr) and n_ranked_arr[bar] > 0:
            t["_mom_rank"] = rank_arr[bar]
            t["_mom_percentile"] = rank_arr[bar] / n_ranked_arr[bar]  # 0 = best, 1 = worst
        else:
            t["_mom_rank"] = n_coins  # worst
            t["_mom_percentile"] = 1.0

    # ═══════════════════════════════════════════════════════════════
    # TEST 1: Quintile analysis
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  H8: MOMENTUM QUINTIEL ANALYSE ({MOMENTUM_PERIOD*4//24}-dag momentum)")
    print(f"{'='*70}")

    quintile_groups = defaultdict(list)
    for t in trades:
        pctl = t["_mom_percentile"]
        if pctl <= 0.2:
            quintile_groups["Q1 (top 20% momentum)"].append(t)
        elif pctl <= 0.4:
            quintile_groups["Q2"].append(t)
        elif pctl <= 0.6:
            quintile_groups["Q3"].append(t)
        elif pctl <= 0.8:
            quintile_groups["Q4"].append(t)
        else:
            quintile_groups["Q5 (bottom 20%)"].append(t)

    print(f"\n  {'Quintile':<28} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10} {'EV/tr':>8}")
    print(f"  {'-'*28} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8}")

    q_pfs = {}
    for q_label in ["Q1 (top 20% momentum)", "Q2", "Q3", "Q4", "Q5 (bottom 20%)"]:
        trs = quintile_groups.get(q_label, [])
        if not trs:
            print(f"  {q_label:<28} {0:>7}")
            continue
        pf = calc_pf(trs)
        wr = calc_wr(trs)
        pnl = calc_pnl(trs)
        ev = pnl / len(trs)
        marker = ""
        if pf > baseline_pf * 1.1:
            marker = " ✅"
        elif pf < baseline_pf * 0.9:
            marker = " ❌"
        print(f"  {q_label:<28} {len(trs):>7} {pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {ev:>+8.1f}{marker}")
        q_pfs[q_label] = pf

    # ═══════════════════════════════════════════════════════════════
    # TEST 2: Top 50% filter
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  H8: TOP-50% MOMENTUM FILTER")
    print(f"{'='*70}")

    top50 = [t for t in trades if t["_mom_percentile"] <= 0.5]
    bot50 = [t for t in trades if t["_mom_percentile"] > 0.5]

    pf_top = calc_pf(top50)
    pf_bot = calc_pf(bot50)
    pf_all = baseline_pf

    print(f"\n  {'Group':<28} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10} {'EV/tr':>8}")
    print(f"  {'-'*28} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8}")
    for label, trs in [("Top 50% momentum", top50), ("Bottom 50% momentum", bot50), ("All (baseline)", trades)]:
        pf = calc_pf(trs)
        wr = calc_wr(trs)
        pnl = calc_pnl(trs)
        ev = pnl / len(trs) if trs else 0
        print(f"  {label:<28} {len(trs):>7} {pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {ev:>+8.1f}")

    spread = pf_top - pf_all
    print(f"\n  Filter effect: top50 PF={pf_top:.2f} vs all PF={pf_all:.2f} (spread: {spread:+.2f})")

    # Primary falsification
    h8_raw_pass = pf_top > pf_all
    print(f"  → {'OVERLEEFT — momentum filter verbetert PF' if h8_raw_pass else 'VERWORPEN — momentum filter verslechtert PF'}")

    if not h8_raw_pass:
        print(f"\n  H8 EINDOORDEEL: ❌ VERWORPEN (filter verbetert PF niet)")
        # Save and exit
        _save_results(baseline_pf, pf_top, pf_bot, q_pfs, None, False, False)
        return

    # ═══════════════════════════════════════════════════════════════
    # VERIFICATIE: Permutation test
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  VERIFICATIE: Permutation test")
    print(f"{'='*70}")

    percentiles = [t["_mom_percentile"] for t in trades]

    def pf_spread_momentum(trade_list, pctl_labels):
        top = [t for t, p in zip(trade_list, pctl_labels) if p <= 0.5]
        if len(top) < 10:
            return 0.0
        return calc_pf(top) - baseline_pf

    observed = pf_spread_momentum(trades, percentiles)
    print(f"\n  Observed spread (top50 PF - baseline PF): {observed:+.2f}")

    rng = random.Random(SEED)
    null_dist = []
    for _ in range(N_PERMUTATIONS):
        shuffled = list(percentiles)
        rng.shuffle(shuffled)
        null_dist.append(pf_spread_momentum(trades, shuffled))

    count_ge = sum(1 for v in null_dist if v >= observed)
    p_value = count_ge / N_PERMUTATIONS
    null_mean = statistics.mean(null_dist)
    null_std = statistics.stdev(null_dist)

    print(f"  Null: mean={null_mean:.3f}, std={null_std:.3f}")
    print(f"  p-value: {p_value:.4f}")
    perm_pass = p_value < 0.05
    print(f"  → {'SIGNIFICANT (p < 0.05)' if perm_pass else 'NIET SIGNIFICANT (p >= 0.05)'}")

    # ═══════════════════════════════════════════════════════════════
    # VERIFICATIE: Temporal split
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  VERIFICATIE: Temporal split")
    print(f"{'='*70}")

    sorted_trades = sorted(trades, key=lambda t: t["entry_bar"])
    mid = len(sorted_trades) // 2
    temporal_pass = True

    for label, subset in [("early", sorted_trades[:mid]), ("late", sorted_trades[mid:])]:
        top = [t for t in subset if t["_mom_percentile"] <= 0.5]
        all_sub = subset
        pf_t = calc_pf(top)
        pf_a = calc_pf(all_sub)
        holds = pf_t > pf_a
        if not holds:
            temporal_pass = False
        marker = "✅" if holds else "❌"
        print(f"  {label:>6}: top50 PF={pf_t:.2f} ({len(top)} tr) vs all PF={pf_a:.2f} ({len(all_sub)} tr) {marker}")

    # ═══════════════════════════════════════════════════════════════
    # EINDOORDEEL
    # ═══════════════════════════════════════════════════════════════
    h8_verified = perm_pass and temporal_pass
    print(f"\n{'='*70}")
    print(f"  H8 EINDOORDEEL")
    print(f"{'='*70}")
    verdict = "VERIFIED" if h8_verified else "VERWORPEN"
    icon = "✅" if h8_verified else "❌"
    print(f"\n  H8: {icon} {verdict}")
    if not perm_pass:
        print(f"  Reden: Permutatie-test niet significant (p={p_value:.4f})")
    if not temporal_pass:
        print(f"  Reden: Patroon instabiel over tijd")

    _save_results(baseline_pf, pf_top, pf_bot, q_pfs, p_value, perm_pass, temporal_pass)


def _save_results(baseline_pf, pf_top, pf_bot, q_pfs, p_value, perm_pass, temporal_pass):
    output = {
        "momentum_period_bars": MOMENTUM_PERIOD,
        "momentum_period_days": MOMENTUM_PERIOD * 4 // 24,
        "baseline_pf": round(baseline_pf, 3),
        "top50_pf": round(pf_top, 3),
        "bottom50_pf": round(pf_bot, 3),
        "quintile_pfs": {k: round(v, 3) for k, v in q_pfs.items()},
        "filter_improves": pf_top > baseline_pf,
        "p_value": round(p_value, 4) if p_value is not None else None,
        "permutation_pass": perm_pass,
        "temporal_pass": temporal_pass,
        "verdict": "VERIFIED" if (perm_pass and temporal_pass) else "VERWORPEN",
    }
    out_path = REPO_ROOT / "reports" / "h8_momentum_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Opgeslagen: {out_path}")


if __name__ == "__main__":
    main()
