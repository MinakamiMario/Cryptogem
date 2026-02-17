#!/usr/bin/env python3
"""MEXC orderbook snapshot sanity & data quality check."""

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone

DATA_PATH = "/Users/oussama/Cryptogem/data/orderbook_snapshots/mexc_orderbook_001.jsonl"
REPORT_PATH = "/Users/oussama/Cryptogem/reports/hf/mexc_sanity_001.md"
EXPECTED_COINS = 42

def percentile(vals, pct):
    """Compute percentile (e.g. 0.9 for P90) from sorted list."""
    if not vals:
        return None
    s = sorted(vals)
    idx = int(pct * len(s))
    idx = min(idx, len(s) - 1)
    return s[idx]


def load_data(path):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def check_btc_eth_reference(records):
    """Check 1: BTC + ETH reference spreads and slippage."""
    results = {}
    for coin_key in ["BTC", "ETH"]:
        subset = [r for r in records if coin_key in r.get("internal", "")]
        if not subset:
            results[coin_key] = {"count": 0, "error": "NO DATA"}
            continue
        spreads = [r["spread_bps"] for r in subset if r["spread_bps"] is not None]
        slip200 = [r["slippage_200_bps"] for r in subset if r["slippage_200_bps"] is not None]
        results[coin_key] = {
            "count": len(subset),
            "spread_median": round(statistics.median(spreads), 2) if spreads else None,
            "spread_p90": round(percentile(spreads, 0.9), 2) if spreads else None,
            "slip200_median": round(statistics.median(slip200), 2) if slip200 else None,
            "slip200_p90": round(percentile(slip200, 0.9), 2) if slip200 else None,
        }
    # Pass criteria
    btc = results.get("BTC", {})
    btc_pass = (
        btc.get("spread_median") is not None
        and btc["spread_median"] < 5
        and btc.get("spread_p90") is not None
        and btc["spread_p90"] < 10
    )
    return results, btc_pass


def check_anomaly_rates(records):
    """Check 2: Crossed books, extreme spreads, depth shortfalls."""
    total = len(records)
    crossed = sum(1 for r in records if r["bid1"] is not None and r["ask1"] is not None and r["bid1"] >= r["ask1"])
    extreme_spread = sum(1 for r in records if r["spread_bps"] is not None and r["spread_bps"] > 200)

    # Depth shortfall per bucket per tier
    buckets = [200, 500, 2000]
    tiers = sorted(set(r["tier"] for r in records))
    shortfall = {}
    for tier in tiers:
        tier_recs = [r for r in records if r["tier"] == tier]
        tier_n = len(tier_recs)
        shortfall[tier] = {}
        for b in buckets:
            key = f"slippage_{b}_bps"
            none_count = sum(1 for r in tier_recs if r.get(key) is None)
            shortfall[tier][b] = {
                "none_count": none_count,
                "pct": round(100.0 * none_count / tier_n, 2) if tier_n else 0,
            }

    crossed_pct = round(100.0 * crossed / total, 4) if total else 0
    extreme_pct = round(100.0 * extreme_spread / total, 2) if total else 0
    crossed_pass = crossed_pct < 0.1

    return {
        "total": total,
        "crossed": crossed,
        "crossed_pct": crossed_pct,
        "extreme_spread": extreme_spread,
        "extreme_spread_pct": extreme_pct,
        "shortfall": shortfall,
    }, crossed_pass


def check_tier_structure(records):
    """Check 3: Tier structure — T1 spread < T2 spread, T1 depth > T2 depth."""
    by_tier = defaultdict(list)
    for r in records:
        by_tier[r["tier"]].append(r)

    tier_stats = {}
    for tier, recs in sorted(by_tier.items()):
        spreads = [r["spread_bps"] for r in recs if r["spread_bps"] is not None]
        depths = [r["bid_depth_usd"] for r in recs if r["bid_depth_usd"] is not None]
        tier_stats[tier] = {
            "count": len(recs),
            "spread_median": round(statistics.median(spreads), 2) if spreads else None,
            "depth_median": round(statistics.median(depths), 2) if depths else None,
        }

    t1 = tier_stats.get("tier1", {})
    t2 = tier_stats.get("tier2", {})
    spread_pass = (
        t1.get("spread_median") is not None
        and t2.get("spread_median") is not None
        and t1["spread_median"] < t2["spread_median"]
    )
    depth_pass = (
        t1.get("depth_median") is not None
        and t2.get("depth_median") is not None
        and t1["depth_median"] > t2["depth_median"]
    )
    return tier_stats, spread_pass, depth_pass


def check_slippage_monotonicity(records):
    """Check 4: Median slippage 200 < 500 < 2000 per tier."""
    by_tier = defaultdict(list)
    for r in records:
        by_tier[r["tier"]].append(r)

    results = {}
    all_pass = True
    for tier in sorted(by_tier.keys()):
        recs = by_tier[tier]
        medians = {}
        for b in [200, 500, 2000]:
            key = f"slippage_{b}_bps"
            vals = [r[key] for r in recs if r.get(key) is not None]
            medians[b] = round(statistics.median(vals), 2) if vals else None

        mono = True
        if medians[200] is not None and medians[500] is not None:
            if medians[200] >= medians[500]:
                mono = False
        if medians[500] is not None and medians[2000] is not None:
            if medians[500] >= medians[2000]:
                mono = False
        if any(v is None for v in medians.values()):
            mono = False

        results[tier] = {"medians": medians, "monotone": mono}
        if not mono:
            all_pass = False

    return results, all_pass


def check_coverage(records):
    """Check 5: Coin coverage, hour coverage, gaps, snapshot density."""
    unique_coins = sorted(set(r["internal"] for r in records))
    n_coins = len(unique_coins)

    # Hour coverage
    hours = set()
    for r in records:
        dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
        hours.add(dt.hour)
    unique_hours = sorted(hours)

    # Gaps > 5 min per coin
    by_coin = defaultdict(list)
    for r in records:
        by_coin[r["internal"]].append(r["ts"])

    gap_coins = {}
    total_gaps = 0
    for coin in sorted(by_coin.keys()):
        ts_list = sorted(by_coin[coin])
        gaps = []
        for i in range(1, len(ts_list)):
            delta = ts_list[i] - ts_list[i - 1]
            if delta > 300:  # > 5 minutes
                gaps.append(delta)
        if gaps:
            gap_coins[coin] = len(gaps)
            total_gaps += len(gaps)

    # Snapshot density
    all_ts = [r["ts"] for r in records]
    ts_min, ts_max = min(all_ts), max(all_ts)
    duration = ts_max - ts_min
    expected_snaps = n_coins * (duration / 10) if duration > 0 else 0
    density = round(len(records) / expected_snaps, 4) if expected_snaps > 0 else 0

    coin_pass = n_coins >= 40

    return {
        "n_coins": n_coins,
        "expected_coins": EXPECTED_COINS,
        "unique_hours": len(unique_hours),
        "hour_list": unique_hours,
        "duration_sec": duration,
        "duration_min": round(duration / 60, 1),
        "total_snapshots": len(records),
        "expected_snapshots": round(expected_snaps),
        "density": density,
        "gap_coins": gap_coins,
        "total_gaps_gt5min": total_gaps,
    }, coin_pass


def build_report(ref, ref_pass, anom, anom_pass, tier, tier_spread_pass, tier_depth_pass,
                 slip, slip_pass, cov, cov_pass):
    """Build compact markdown report."""
    lines = []
    lines.append("# MEXC Orderbook Sanity Report — `mexc_orderbook_001.jsonl`\n")
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Generated: {ts_now}  |  Records: {anom['total']}\n")

    # 1. BTC + ETH reference
    lines.append("## 1. BTC + ETH Reference\n")
    lines.append("| Coin | N | Spread med | Spread P90 | Slip200 med | Slip200 P90 |")
    lines.append("|------|---|-----------|-----------|------------|------------|")
    for coin in ["BTC", "ETH"]:
        d = ref[coin]
        if d.get("error"):
            lines.append(f"| {coin} | 0 | — | — | — | — |")
        else:
            lines.append(
                f"| {coin} | {d['count']} "
                f"| {d['spread_median']} | {d['spread_p90']} "
                f"| {d['slip200_median']} | {d['slip200_p90']} |"
            )
    verdict = "PASS" if ref_pass else "FAIL"
    lines.append(f"\n**BTC spread gate**: median < 5 bps, P90 < 10 bps → **{verdict}**\n")

    # 2. Anomaly rates
    lines.append("## 2. Anomaly Rates\n")
    lines.append(f"- Crossed books: {anom['crossed']}/{anom['total']} ({anom['crossed_pct']}%) "
                 f"→ **{'PASS' if anom_pass else 'FAIL'}** (< 0.1%)")
    lines.append(f"- Extreme spread (> 200 bps): {anom['extreme_spread']}/{anom['total']} ({anom['extreme_spread_pct']}%)\n")

    lines.append("### Depth shortfall (slippage is None)\n")
    lines.append("| Tier | $200 | $500 | $2000 |")
    lines.append("|------|------|------|-------|")
    for t in sorted(anom["shortfall"].keys()):
        s = anom["shortfall"][t]
        lines.append(
            f"| {t} | {s[200]['none_count']} ({s[200]['pct']}%) "
            f"| {s[500]['none_count']} ({s[500]['pct']}%) "
            f"| {s[2000]['none_count']} ({s[2000]['pct']}%) |"
        )
    lines.append("")

    # 3. Tier structure
    lines.append("## 3. Tier Structure\n")
    lines.append("| Tier | N | Spread med (bps) | Depth med (USD) |")
    lines.append("|------|---|------------------|-----------------|")
    for t in sorted(tier.keys()):
        d = tier[t]
        lines.append(f"| {t} | {d['count']} | {d['spread_median']} | {d['depth_median']} |")
    lines.append(f"\n- T1 spread < T2 spread → **{'PASS' if tier_spread_pass else 'FAIL'}**")
    lines.append(f"- T1 depth > T2 depth → **{'PASS' if tier_depth_pass else 'FAIL'}**\n")

    # 4. Slippage monotonicity
    lines.append("## 4. Slippage Monotonicity\n")
    lines.append("| Tier | Slip200 med | Slip500 med | Slip2000 med | Monotone |")
    lines.append("|------|-----------|-----------|------------|----------|")
    for t in sorted(slip.keys()):
        d = slip[t]
        m = d["medians"]
        mono_str = "YES" if d["monotone"] else "NO"
        lines.append(f"| {t} | {m[200]} | {m[500]} | {m[2000]} | {mono_str} |")
    verdict = "PASS" if slip_pass else "FAIL"
    lines.append(f"\n**All tiers monotone** → **{verdict}**\n")

    # 5. Coverage
    lines.append("## 5. Coverage\n")
    lines.append(f"- Unique coins: **{cov['n_coins']}** / {cov['expected_coins']} expected "
                 f"→ **{'PASS' if cov_pass else 'FAIL'}** (>= 40)")
    lines.append(f"- Unique hours: {cov['unique_hours']} ({cov['hour_list']})")
    lines.append(f"- Duration: {cov['duration_min']} min ({cov['duration_sec']} sec)")
    lines.append(f"- Snapshots: {cov['total_snapshots']} actual / {cov['expected_snapshots']} expected "
                 f"(density={cov['density']})")
    lines.append(f"- Gaps > 5 min: {cov['total_gaps_gt5min']} total across {len(cov['gap_coins'])} coins")
    if cov["gap_coins"]:
        lines.append("\n| Coin | Gaps > 5 min |")
        lines.append("|------|-------------|")
        for coin, n in sorted(cov["gap_coins"].items(), key=lambda x: -x[1])[:10]:
            lines.append(f"| {coin} | {n} |")
        if len(cov["gap_coins"]) > 10:
            lines.append(f"| ... | ({len(cov['gap_coins'])} coins total) |")
    lines.append("")

    # 6. Pass/Fail verdict
    lines.append("## 6. Verdict Summary\n")
    checks = [
        ("BTC median spread < 5 bps, P90 < 10 bps", ref_pass),
        ("Crossed rate < 0.1%", anom_pass),
        ("T1 median spread < T2 median spread", tier_spread_pass),
        ("T1 median depth > T2 median depth", tier_depth_pass),
        ("Slippage monotone per tier", slip_pass),
        (f">= 40 of {EXPECTED_COINS} coins present", cov_pass),
    ]
    lines.append("| Check | Result |")
    lines.append("|-------|--------|")
    all_pass = True
    for name, passed in checks:
        tag = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        lines.append(f"| {name} | **{tag}** |")

    overall = "ALL PASS" if all_pass else "ISSUES FOUND"
    lines.append(f"\n**Overall: {overall}**\n")

    return "\n".join(lines)


def main():
    records = load_data(DATA_PATH)
    print(f"Loaded {len(records)} records")

    ref, ref_pass = check_btc_eth_reference(records)
    anom, anom_pass = check_anomaly_rates(records)
    tier, tier_spread_pass, tier_depth_pass = check_tier_structure(records)
    slip, slip_pass = check_slippage_monotonicity(records)
    cov, cov_pass = check_coverage(records)

    report = build_report(ref, ref_pass, anom, anom_pass, tier, tier_spread_pass, tier_depth_pass,
                          slip, slip_pass, cov, cov_pass)

    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"Report written to {REPORT_PATH}")
    print(report)


if __name__ == "__main__":
    main()
