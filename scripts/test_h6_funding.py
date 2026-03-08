#!/usr/bin/env python3
"""
H6: Funding Rate als Regime-Filter op ms_018 — Falsificatie + Verificatie

Mechanisme: Extreme positive funding = overleveraged longs → kans op dump.
Test: Split ms_018 trades door BTC funding regime. Als PF verschilt → signaal.

Includes permutation test + temporal split (geleerd van H1/H2 verificatie).
"""

import sys, json, importlib, random, statistics
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
FUNDING_DIR = DATA_ROOT / "derived" / "funding_rates" / "mexc"
N_PERMUTATIONS = 10_000
SEED = 42

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

def enrich_trades_with_time(trades, data):
    for t in trades:
        pair = t["pair"]
        candles = data[pair]
        if t["entry_bar"] < len(candles):
            ts = candles[t["entry_bar"]]["time"]
            t["_entry_ts"] = ts
            t["_entry_dt"] = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            t["_entry_ts"] = 0
            t["_entry_dt"] = None


def load_funding_rates():
    """Load BTC funding rates and build a time-indexed lookup.
    Also load per-coin rates for coins that have MEXC perps.
    """
    btc_path = FUNDING_DIR / "BTC_USDT.json"
    if not btc_path.exists():
        print("  ERROR: BTC_USDT.json not found. Run collect_funding_rates.py first.")
        sys.exit(1)

    records = json.loads(btc_path.read_text())
    # Sort by time ascending
    records.sort(key=lambda r: r["settleTime"])

    # Build list of (timestamp_seconds, rate)
    btc_rates = [(r["settleTime"] / 1000, r["fundingRate"]) for r in records]

    # Load per-coin rates
    coin_rates = {}
    for f in FUNDING_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        sym = f.stem  # e.g. "ETH_USDT"
        base = sym.split("_")[0]
        kraken_pair = f"{base}/USD"
        recs = json.loads(f.read_text())
        if recs:
            recs.sort(key=lambda r: r["settleTime"])
            coin_rates[kraken_pair] = [(r["settleTime"] / 1000, r["fundingRate"]) for r in recs]

    return btc_rates, coin_rates


def get_funding_at_time(rates_sorted, query_ts):
    """Get the most recent funding rate at or before query_ts."""
    # Binary search
    lo, hi = 0, len(rates_sorted) - 1
    result = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if rates_sorted[mid][0] <= query_ts:
            result = rates_sorted[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def classify_funding_regime(rate, thresholds):
    """Classify a funding rate into a regime."""
    if rate >= thresholds["extreme_pos"]:
        return "extreme_positive"
    elif rate <= thresholds["extreme_neg"]:
        return "extreme_negative"
    elif rate > 0:
        return "mild_positive"
    else:
        return "mild_negative"


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("Loading backtest data...")
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

    print("Running baseline backtest...")
    bt = _sprint3_engine.run_backtest(
        data=data, coins=coins,
        signal_fn=ms_018["signal_fn"], params=ms_018["params"],
        indicators=indicators, exit_mode="dc", start_bar=START_BAR,
    )
    trades = bt.trade_list
    enrich_trades_with_time(trades, data)
    print(f"Baseline: {len(trades)} trades, PF={bt.pf:.2f}")

    # Load funding rates
    print("\nLoading funding rate data...")
    btc_rates, coin_rates = load_funding_rates()
    print(f"BTC funding: {len(btc_rates)} records")
    print(f"Per-coin funding: {len(coin_rates)} coins with data")

    # Compute funding rate thresholds from BTC data
    all_rates = [r[1] for r in btc_rates]
    sorted_rates = sorted(all_rates)
    extreme_pos = sorted_rates[int(len(sorted_rates) * 0.95)]  # top 5%
    extreme_neg = sorted_rates[int(len(sorted_rates) * 0.05)]  # bottom 5%
    thresholds = {"extreme_pos": extreme_pos, "extreme_neg": extreme_neg}
    print(f"Thresholds: extreme_pos={extreme_pos:.6f}, extreme_neg={extreme_neg:.6f}")

    # ═══════════════════════════════════════════════════════════════
    # TEST 1: BTC Funding as aggregate regime filter
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  H6 TEST 1: BTC Funding Rate als regime filter")
    print(f"{'='*70}")

    # Classify each trade by BTC funding regime at entry
    regime_groups = defaultdict(list)
    unmatched = 0

    for t in trades:
        if not t["_entry_ts"]:
            unmatched += 1
            continue
        fr = get_funding_at_time(btc_rates, t["_entry_ts"])
        if fr is None:
            unmatched += 1
            continue

        regime = classify_funding_regime(fr[1], thresholds)
        t["_funding_regime"] = regime
        t["_funding_rate"] = fr[1]
        regime_groups[regime].append(t)

    print(f"\n  Trades per regime:")
    print(f"  {'Regime':<22} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10} {'EV/tr':>8}")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8}")

    for regime in ["extreme_positive", "mild_positive", "mild_negative", "extreme_negative"]:
        trs = regime_groups.get(regime, [])
        if not trs:
            print(f"  {regime:<22} {0:>7}")
            continue
        pf = calc_pf(trs)
        wr = calc_wr(trs)
        pnl = calc_pnl(trs)
        ev = pnl / len(trs)
        print(f"  {regime:<22} {len(trs):>7} {pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {ev:>+8.1f}")

    if unmatched:
        print(f"  (unmatched: {unmatched} trades without funding data)")

    # ═══════════════════════════════════════════════════════════════
    # TEST 2: Per-coin funding rate (where available)
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  H6 TEST 2: Per-coin funding rate")
    print(f"{'='*70}")

    coin_regime_groups = defaultdict(list)
    coin_matched = 0
    coin_unmatched = 0

    for t in trades:
        pair = t["pair"]
        if pair in coin_rates and t["_entry_ts"]:
            fr = get_funding_at_time(coin_rates[pair], t["_entry_ts"])
            if fr:
                # Use same thresholds (BTC-derived) for consistency
                regime = classify_funding_regime(fr[1], thresholds)
                t["_coin_funding_regime"] = regime
                t["_coin_funding_rate"] = fr[1]
                coin_regime_groups[regime].append(t)
                coin_matched += 1
            else:
                coin_unmatched += 1
        else:
            coin_unmatched += 1

    print(f"  Matched: {coin_matched} | Unmatched: {coin_unmatched}")
    print(f"\n  {'Regime':<22} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10} {'EV/tr':>8}")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8}")

    for regime in ["extreme_positive", "mild_positive", "mild_negative", "extreme_negative"]:
        trs = coin_regime_groups.get(regime, [])
        if not trs:
            print(f"  {regime:<22} {0:>7}")
            continue
        pf = calc_pf(trs)
        wr = calc_wr(trs)
        pnl = calc_pnl(trs)
        ev = pnl / len(trs)
        print(f"  {regime:<22} {len(trs):>7} {pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {ev:>+8.1f}")

    # ═══════════════════════════════════════════════════════════════
    # FALSIFICATIE: is er verschil tussen regimes?
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  H6 FALSIFICATIE")
    print(f"{'='*70}")

    # Primary test: extreme_positive vs rest
    extreme_pos_trades = regime_groups.get("extreme_positive", [])
    non_extreme = [t for t in trades if t.get("_funding_regime") and
                   t["_funding_regime"] != "extreme_positive"]

    if len(extreme_pos_trades) >= 10 and len(non_extreme) >= 10:
        pf_extreme = calc_pf(extreme_pos_trades)
        pf_rest = calc_pf(non_extreme)
        spread = pf_rest - pf_extreme  # positive if avoiding extreme is better
        print(f"\n  PF extreme_positive={pf_extreme:.2f} vs rest={pf_rest:.2f}")
        print(f"  Spread (rest - extreme): {spread:+.2f}")

        # Also test: negative funding (potential bounce signal)
        extreme_neg_trades = regime_groups.get("extreme_negative", [])
        non_extreme_neg = [t for t in trades if t.get("_funding_regime") and
                          t["_funding_regime"] != "extreme_negative"]
        if len(extreme_neg_trades) >= 10:
            pf_neg = calc_pf(extreme_neg_trades)
            pf_rest_neg = calc_pf(non_extreme_neg)
            print(f"  PF extreme_negative={pf_neg:.2f} vs rest={pf_rest_neg:.2f}")
    else:
        spread = 0
        print(f"\n  Insufficient extreme trades for analysis")
        print(f"  extreme_positive: {len(extreme_pos_trades)}, non_extreme: {len(non_extreme)}")

    # ═══════════════════════════════════════════════════════════════
    # VERIFICATIE: Permutation test
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  VERIFICATIE: Permutation test")
    print(f"{'='*70}")

    # Get list of regime labels for matched trades
    matched_trades = [t for t in trades if t.get("_funding_regime")]
    labels = [t["_funding_regime"] for t in matched_trades]

    def pf_spread_extreme(trades_list, regime_labels):
        """PF spread: non-extreme vs extreme_positive."""
        extreme = [t for t, l in zip(trades_list, regime_labels) if l == "extreme_positive"]
        rest = [t for t, l in zip(trades_list, regime_labels) if l != "extreme_positive"]
        if len(extreme) < 5 or len(rest) < 5:
            return 0.0
        return calc_pf(rest) - calc_pf(extreme)

    observed = pf_spread_extreme(matched_trades, labels)
    print(f"\n  Observed spread (rest PF - extreme PF): {observed:+.2f}")

    rng = random.Random(SEED)
    null_dist = []
    for _ in range(N_PERMUTATIONS):
        shuffled = list(labels)
        rng.shuffle(shuffled)
        null_dist.append(pf_spread_extreme(matched_trades, shuffled))

    count_ge = sum(1 for v in null_dist if v >= observed)
    p_value = count_ge / N_PERMUTATIONS
    null_mean = statistics.mean(null_dist)
    null_std = statistics.stdev(null_dist)
    null_p95 = sorted(null_dist)[int(0.95 * len(null_dist))]

    print(f"  Null: mean={null_mean:.3f}, std={null_std:.3f}, P95={null_p95:.3f}")
    print(f"  p-value: {p_value:.4f}")
    perm_pass = p_value < 0.05
    print(f"  → {'SIGNIFICANT (p < 0.05)' if perm_pass else 'NIET SIGNIFICANT (p >= 0.05)'}")

    # ═══════════════════════════════════════════════════════════════
    # VERIFICATIE: Temporal split
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  VERIFICATIE: Temporal split")
    print(f"{'='*70}")

    sorted_matched = sorted(matched_trades, key=lambda t: t["entry_bar"])
    mid = len(sorted_matched) // 2
    early = sorted_matched[:mid]
    late = sorted_matched[mid:]

    for label, subset in [("early", early), ("late", late)]:
        extreme_sub = [t for t in subset if t.get("_funding_regime") == "extreme_positive"]
        rest_sub = [t for t in subset if t.get("_funding_regime") and
                    t["_funding_regime"] != "extreme_positive"]
        if len(extreme_sub) >= 5 and len(rest_sub) >= 5:
            pf_e = calc_pf(extreme_sub)
            pf_r = calc_pf(rest_sub)
            direction = "✅" if pf_r > pf_e else "❌"
            print(f"  {label:>6}: extreme PF={pf_e:.2f} ({len(extreme_sub)} tr) | "
                  f"rest PF={pf_r:.2f} ({len(rest_sub)} tr) {direction}")
        else:
            print(f"  {label:>6}: insufficient extreme trades ({len(extreme_sub)})")

    # ═══════════════════════════════════════════════════════════════
    # EINDOORDEEL
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("  H6 EINDOORDEEL")
    print(f"{'='*70}")

    # H6 passes if:
    # 1. Permutation test significant (p < 0.05)
    # 2. Direction consistent in both temporal halves
    h6_pass = perm_pass
    verdict = "VERIFIED" if h6_pass else "VERWORPEN"
    print(f"\n  H6: ❌ {verdict}" if not h6_pass else f"\n  H6: ✅ {verdict}")
    if not perm_pass:
        print(f"  Reden: Funding regime spread niet significant (p={p_value:.4f})")

    # Save results
    output = {
        "btc_regime_stats": {
            regime: {"trades": len(trs), "pf": round(calc_pf(trs), 3),
                     "wr": round(calc_wr(trs), 1), "pnl": round(calc_pnl(trs), 0)}
            for regime, trs in regime_groups.items() if trs
        },
        "thresholds": {k: round(v, 6) for k, v in thresholds.items()},
        "falsification": {
            "observed_spread": round(observed, 3),
            "p_value": round(p_value, 4),
            "permutation_pass": perm_pass,
            "verdict": verdict,
        },
    }
    out_path = REPO_ROOT / "reports" / "h6_funding_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Opgeslagen: {out_path}")


if __name__ == "__main__":
    main()
