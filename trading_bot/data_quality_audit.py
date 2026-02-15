#!/usr/bin/env python3
"""Data Quality Audit: per-coin quality across Kraken vs MEXC venues."""
import json, math, time, statistics
from pathlib import Path

t0 = time.time()
RESEARCH_PATH = Path("/Users/oussama/Cryptogem/data/candle_cache_research_all.json")
LIVE_PATH = Path("/Users/oussama/Cryptogem/trading_bot/candle_cache_532.json")
OUT_JSON = Path("/Users/oussama/Cryptogem/reports/data_quality_audit.json")
OUT_MD = Path("/Users/oussama/Cryptogem/reports/data_quality_audit.md")
INTERVAL = 14400

print("Loading RESEARCH_ALL cache...")
with open(RESEARCH_PATH) as fh:
    research = json.load(fh)
print(f"  Loaded {len(research)} keys in {time.time()-t0:.1f}s")

print("Loading LIVE_CURRENT cache...")
with open(LIVE_PATH) as fh:
    live = json.load(fh)
live_coins = {k for k in live if not k.startswith("_")}
print(f"  Loaded {len(live_coins)} Kraken coins")

research_coins = {k: v for k, v in research.items() if not k.startswith("_")}
print(f"  Research coins: {len(research_coins)}")
max_bars = max(len(v) for v in research_coins.values())
print(f"  Max bars in dataset: {max_bars}")

print("Computing per-coin metrics...")
results = []
total = len(research_coins)

for i, (coin, candles) in enumerate(research_coins.items()):
    if (i + 1) % 500 == 0 or i == 0:
        print(f"  Processing {i+1}/{total}...")
    venue = "Kraken" if coin in live_coins else "MEXC"
    bars_count = len(candles)
    if bars_count == 0:
        results.append({"coin": coin, "venue": venue, "bars_count": 0,
            "coverage_pct": 0, "gap_count": 0, "gap_rate_pct": 0,
            "outlier_wick_count": 0, "median_volume_usd": 0,
            "max_gap_hours": 0, "quality_score": 0})
        continue
    coverage_pct = bars_count / max_bars * 100
    times = sorted(c["time"] for c in candles)
    gaps = []
    for j in range(1, len(times)):
        dt = times[j] - times[j - 1]
        if dt > INTERVAL:
            gaps.append(dt)
    gap_count = len(gaps)
    gap_rate_pct = gap_count / bars_count * 100
    max_gap_hours = max(gaps) / 3600 if gaps else 0
    outlier_wick_count = 0
    for c in candles:
        cl = c["close"]
        if cl > 0 and (c["high"] - c["low"]) / cl > 0.20:
            outlier_wick_count += 1
    vol_usds = [c["close"] * c["volume"] for c in candles if c["close"] > 0]
    median_volume_usd = statistics.median(vol_usds) if vol_usds else 0
    cs = coverage_pct * 0.4
    gs = max(0, (100 - gap_rate_pct * 10)) * 0.3
    os2 = max(0, (100 - min(outlier_wick_count, 10) * 10)) * 0.15
    vs = min(math.log10(median_volume_usd + 1) / 5 * 100, 100) * 0.15
    quality_score = cs + gs + os2 + vs
    results.append({"coin": coin, "venue": venue, "bars_count": bars_count,
        "coverage_pct": round(coverage_pct, 2), "gap_count": gap_count,
        "gap_rate_pct": round(gap_rate_pct, 2),
        "outlier_wick_count": outlier_wick_count,
        "median_volume_usd": round(median_volume_usd, 2),
        "max_gap_hours": round(max_gap_hours, 1),
        "quality_score": round(quality_score, 2)})

print(f"  Done in {time.time()-t0:.1f}s")
kraken_list = [r for r in results if r["venue"] == "Kraken"]
mexc_list = [r for r in results if r["venue"] == "MEXC"]

def venue_stats(cl, name):
    n = len(cl)
    if n == 0:
        return {"venue": name, "count": 0}
    return {
        "venue": name, "count": n,
        "avg_coverage_pct": round(sum(c["coverage_pct"] for c in cl)/n, 2),
        "avg_gap_rate_pct": round(sum(c["gap_rate_pct"] for c in cl)/n, 2),
        "avg_quality_score": round(sum(c["quality_score"] for c in cl)/n, 2),
        "coins_below_70_coverage": sum(1 for c in cl if c["coverage_pct"]<70),
        "coins_below_95_coverage": sum(1 for c in cl if c["coverage_pct"]<95),
    }

kraken_stats = venue_stats(kraken_list, "Kraken")
mexc_stats = venue_stats(mexc_list, "MEXC")
all_stats = venue_stats(results, "ALL")

print()
print("--- Venue Summary ---")
for s in [kraken_stats, mexc_stats]:
    v = s["venue"]
    c = s["count"]
    ac = s.get("avg_coverage_pct", "N/A")
    ag = s.get("avg_gap_rate_pct", "N/A")
    aq = s.get("avg_quality_score", "N/A")
    print(f"  {v}: {c} coins | avg cov {ac}% | avg gap {ag}% | avg qual {aq}")

sorted_results = sorted(results, key=lambda x: x["quality_score"])
worst_50 = sorted_results[:50]
total_coins = len(results)
below_95 = sum(1 for r in results if r["coverage_pct"] < 95)
below_95_pct = below_95 / total_coins * 100
coverage_primary = below_95_pct > 50
high_gap_rate = sum(1 for r in results if r["gap_rate_pct"] > 5)
high_gap_pct = high_gap_rate / total_coins * 100

print()
print("--- Coverage Analysis ---")
print(f"  Below 95% coverage: {below_95}/{total_coins} ({below_95_pct:.1f}%)")
print(f"  Gap rate > 5%: {high_gap_rate}/{total_coins} ({high_gap_pct:.1f}%)")
verdict_txt = "JA" if coverage_primary else "NEE"
print(f"  Primary issue is coverage: {verdict_txt}")

# Save JSON
output = {
    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "max_bars_in_dataset": max_bars,
    "venue_summary": [kraken_stats, mexc_stats],
    "coins": sorted(results, key=lambda x: x["coin"]),
}
with open(OUT_JSON, "w") as fh:
    json.dump(output, fh, indent=2)
print(f"\nSaved: {OUT_JSON}")

# Save Markdown
md = []
md.append("# Data Quality Audit: RESEARCH_ALL Cache")
md.append("")
md.append("Generated: " + time.strftime("%Y-%m-%d %H:%M:%S"))
md.append("")
md.append("Max bars in dataset: " + str(max_bars))
md.append("")
md.append("## Venue Summary")
md.append("")
md.append("| Venue | Count | Avg Coverage% | Avg Gap Rate% | Avg Quality | Below 70% Cov | Below 95% Cov |")
md.append("|-------|-------|---------------|---------------|-------------|---------------|---------------|")
for s in [kraken_stats, mexc_stats]:
    row = "| {} | {} | {} | {} | {} | {} | {} |".format(
        s["venue"], s["count"],
        s.get("avg_coverage_pct","N/A"), s.get("avg_gap_rate_pct","N/A"),
        s.get("avg_quality_score","N/A"), s.get("coins_below_70_coverage","N/A"),
        s.get("coins_below_95_coverage","N/A"))
    md.append(row)
row = "| **ALL** | {} | {} | {} | {} | {} | {} |".format(
    all_stats["count"],
    all_stats.get("avg_coverage_pct","N/A"), all_stats.get("avg_gap_rate_pct","N/A"),
    all_stats.get("avg_quality_score","N/A"), all_stats.get("coins_below_70_coverage","N/A"),
    all_stats.get("coins_below_95_coverage","N/A"))
md.append(row)
md.append("")
md.append("## Top 50 Worst Quality Coins")
md.append("")
md.append("| # | Coin | Venue | Bars | Coverage% | Gap Rate% | Max Gap (h) | Outlier Wicks | Median Vol $ | Quality |")
md.append("|---|------|-------|------|-----------|-----------|-------------|---------------|--------------|---------|")
for i, r in enumerate(worst_50):
    row = "| {} | {} | {} | {} | {} | {} | {} | {} | {:,.0f} | {} |".format(
        i+1, r["coin"], r["venue"], r["bars_count"], r["coverage_pct"],
        r["gap_rate_pct"], r["max_gap_hours"], r["outlier_wick_count"],
        r["median_volume_usd"], r["quality_score"])
    md.append(row)
md.append("")
md.append("## Coverage Distribution")
md.append("")
buckets = [(0,10),(10,20),(20,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,90),(90,95),(95,100),(100,100.01)]
blabels = ["0-10%","10-20%","20-30%","30-40%","40-50%","50-60%","60-70%","70-80%","80-90%","90-95%","95-100%","100%"]
md.append("| Coverage Bucket | Total | Kraken | MEXC |")
md.append("|-----------------|-------|--------|------|")
for (lo,hi),lab in zip(buckets,blabels):
    t2=sum(1 for r in results if lo<=r["coverage_pct"]<hi)
    k2=sum(1 for r in kraken_list if lo<=r["coverage_pct"]<hi)
    m2=sum(1 for r in mexc_list if lo<=r["coverage_pct"]<hi)
    md.append("| {} | {} | {} | {} |".format(lab, t2, k2, m2))
md.append("")
md.append("## Conclusion")
md.append("")
verdict = "**JA**" if coverage_primary else "**NEE**"
md.append("**RESEARCH_ALL faalt primair door coverage?** " + verdict)
md.append("")
md.append("- Coins below 95% coverage: {}/{} ({:.1f}%)".format(below_95, total_coins, below_95_pct))
md.append("- Coins with gap_rate > 5%: {}/{} ({:.1f}%)".format(high_gap_rate, total_coins, high_gap_pct))
if coverage_primary:
    md.append("- Over half of coins have less than 95% coverage. Coverage is the dominant quality issue.")
    kr_b = kraken_stats.get("coins_below_95_coverage", 0)
    mx_b = mexc_stats.get("coins_below_95_coverage", 0)
    md.append("- Kraken: {}/{} below 95% | MEXC: {}/{} below 95%".format(
        kr_b, kraken_stats["count"], mx_b, mexc_stats["count"]))
else:
    md.append("- Majority of coins have sufficient coverage (>=95%). Coverage is NOT the primary issue.")
    if high_gap_pct > 20:
        md.append("- Gap rate is a more significant concern ({:.1f}% of coins with >5% gap rate).".format(high_gap_pct))
md.append("")

with open(OUT_MD, "w") as fh:
    fh.write("\n".join(md))
print(f"Saved: {OUT_MD}")
print(f"\nTotal runtime: {time.time()-t0:.1f}s")
