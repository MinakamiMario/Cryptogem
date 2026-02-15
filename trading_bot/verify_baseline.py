#!/usr/bin/env python3
"""
Verify Baseline - Reproduce and lock C1_TPSL_RSI45 on both caches.
Agent 1 deliverable: exact evidence for two universes.
"""
import sys
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path("/Users/oussama/Cryptogem/trading_bot")))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)
from robustness_harness import (
    purged_walk_forward, friction_stress, monte_carlo_shuffle,
    param_jitter, universe_shift,
)

CONFIG = {
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 15,
    "time_max_bars": 15,
    "tp_pct": 15,
    "vol_confirm": True,
    "vol_spike_mult": 3.0,
}

CACHES = {
    "LIVE_CURRENT": Path("/Users/oussama/Cryptogem/trading_bot/candle_cache_532.json"),
    "RESEARCH_ALL": Path("/Users/oussama/Cryptogem/data/candle_cache_research_all.json"),
}

OUTPUT_DIR = Path("/Users/oussama/Cryptogem/reports")


def md5_hash(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def bt_summary(bt):
    pf = bt["pf"]
    return {
        "trades": bt["trades"],
        "pnl": round(bt["pnl"], 2),
        "wr": round(bt["wr"], 1),
        "dd": round(bt["dd"], 1),
        "pf": round(pf, 2) if pf < 999 else "INF",
        "final_equity": round(bt["final_equity"], 2),
    }


def run_for_cache(cache_name, cache_path):
    print(f"\n{'='*70}")
    print(f"  CACHE: {cache_name}")
    print(f"  Path:  {cache_path}")
    print(f"{'='*70}")

    t0 = time.time()
    file_hash = md5_hash(cache_path)
    file_size = cache_path.stat().st_size
    print(f"  MD5: {file_hash}")
    print(f"  Size: {file_size:,} bytes")

    print(f"  Loading cache...", flush=True)
    with open(cache_path) as f:
        data = json.load(f)

    all_coins = sorted(k for k, v in data.items() if isinstance(v, list) and len(v) > 50)
    n_coins = len(all_coins)

    bar_counts = [len(data[c]) for c in all_coins]
    min_bars = min(bar_counts) if bar_counts else 0
    max_bars_val = max(bar_counts) if bar_counts else 0
    avg_bars = sum(bar_counts) / len(bar_counts) if bar_counts else 0
    print(f"  Coins: {n_coins} (min_bars={min_bars}, max_bars={max_bars_val}, avg={avg_bars:.0f})")
    print(f"  Loaded in {time.time()-t0:.1f}s")

    print(f"  Precomputing indicators...", flush=True)
    t1 = time.time()
    indicators = precompute_all(data, all_coins)
    precompute_time = time.time() - t1
    print(f"  Precomputed in {precompute_time:.1f}s")

    cfg = normalize_cfg(dict(CONFIG))

    print(f"  Running baseline backtest...", flush=True)
    t2 = time.time()
    base_bt = run_backtest(indicators, all_coins, cfg)
    bt_time = time.time() - t2
    base = bt_summary(base_bt)
    print(f"  Baseline: {base['trades']}tr ${base['pnl']} WR{base['wr']}% DD{base['dd']}% PF{base['pf']} ({bt_time:.1f}s)")

    exit_classes = base_bt.get("exit_classes", {})
    trades = base_bt.get("trade_list", [])
    total_profit = sum(max(0, t["pnl"]) for t in trades)
    coin_profit = {}
    for t in trades:
        coin_profit[t["pair"]] = coin_profit.get(t["pair"], 0) + max(0, t["pnl"])
    sorted_coins_profit = sorted(coin_profit.items(), key=lambda x: x[1], reverse=True)
    top1_share = sorted_coins_profit[0][1] / total_profit if total_profit > 0 and sorted_coins_profit else 0
    top3_profit = sum(v for _, v in sorted_coins_profit[:3])
    top3_share = top3_profit / total_profit if total_profit > 0 else 0
    notop_pnl = base_bt["pnl"] - (sorted_coins_profit[0][1] if sorted_coins_profit else 0)

    print(f"  Top1: {sorted_coins_profit[0][0] if sorted_coins_profit else 'N/A'} ({top1_share*100:.1f}%) | Top3: {top3_share*100:.1f}% | NoTop P&L: ${notop_pnl:.0f}")

    print(f"  [1/5] Purged Walk-Forward (5-fold, embargo=2)...", flush=True)
    t3 = time.time()
    wf = purged_walk_forward(indicators, all_coins, cfg, n_folds=5, embargo=2)
    wf_time = time.time() - t3
    for fold in wf["folds"]:
        sym = "PASS" if fold["pass"] else "FAIL"
        print(f"    F{fold['fold']}: {fold['test_bars']} -> {fold['test_trades']}tr ${fold['test_pnl']} DD{fold['test_dd']}% [{sym}]")
    print(f"    WF result: {wf['wf_label']} ({wf_time:.1f}s)")

    print(f"  [2/5] Friction stress...", flush=True)
    t4 = time.time()
    fric = friction_stress(indicators, all_coins, cfg)
    fric_time = time.time() - t4
    go_key = fric["go_scenario"]
    go_pnl = fric["go_pnl"]
    sym = "GO" if fric["go"] else "NO-GO"
    print(f"    {go_key}: ${go_pnl} [{sym}] ({fric_time:.1f}s)")
    fric_2x20 = fric["matrix"].get("2.0x_fee+20bps", {})

    print(f"  [3/5] Monte Carlo shuffle (1000x)...", flush=True)
    t5 = time.time()
    mc = monte_carlo_shuffle(indicators, all_coins, cfg, n_sims=1000, seed=42)
    mc_time = time.time() - t5
    if "error" not in mc:
        print(f"    Win%={mc['equity']['win_pct']}% Ruin={mc['ruin_prob_pct']}% p95DD={mc['max_dd']['p95']}% ({mc_time:.1f}s)")
    else:
        print(f"    {mc['error']} ({mc_time:.1f}s)")

    print(f"  [4/5] Param jitter (50 variants)...", flush=True)
    t6 = time.time()
    jit = param_jitter(indicators, all_coins, cfg, n_variants=50, seed=42)
    jit_time = time.time() - t6
    print(f"    {jit['n_positive']}/{jit['n_variants']} positive ({jit['positive_pct']}%) ({jit_time:.1f}s)")

    print(f"  [5/5] Universe shift + concentration...", flush=True)
    t7 = time.time()
    univ = universe_shift(indicators, all_coins, cfg, n_random=100, seed=42)
    univ_time = time.time() - t7
    conc = univ["concentration"]
    print(f"    Top1={conc['top1_coin']} {conc['top1_share']*100:.1f}% Top3={conc['top3_share']*100:.1f}% NoTop=${conc['notop_pnl']} ({univ_time:.1f}s)")

    total_time = time.time() - t0

    result = {
        "cache_name": cache_name,
        "cache_path": str(cache_path),
        "cache_md5": file_hash,
        "cache_size_bytes": file_size,
        "n_coins": n_coins,
        "bar_stats": {"min": min_bars, "max": max_bars_val, "avg": round(avg_bars, 0)},
        "config": cfg,
        "settings": {"KRAKEN_FEE": KRAKEN_FEE, "INITIAL_CAPITAL": INITIAL_CAPITAL, "START_BAR": START_BAR},
        "baseline": base,
        "exit_classes": {cls: {reason: stats for reason, stats in reasons.items()} for cls, reasons in exit_classes.items()},
        "concentration": {
            "top1_coin": sorted_coins_profit[0][0] if sorted_coins_profit else "N/A",
            "top1_share": round(min(1.0, top1_share), 4),
            "top3_coins": [c for c, _ in sorted_coins_profit[:3]],
            "top3_share": round(min(1.0, top3_share), 4),
            "notop_pnl": round(notop_pnl, 2),
            "unique_coins_traded": len(coin_profit),
        },
        "walk_forward": {
            "n_folds": wf["n_folds"], "embargo_bars": wf["embargo_bars"],
            "passed_folds": wf["passed_folds"], "wf_label": wf["wf_label"],
            "max_test_dd": wf["max_test_dd"], "go": wf["go"], "soft_go": wf["soft_go"],
            "folds": wf["folds"],
        },
        "friction": {
            "go_scenario": fric["go_scenario"], "go_pnl": fric["go_pnl"], "go": fric["go"],
            "detail_2x_20bps": fric_2x20,
            "matrix_summary": {k: {"pnl": v["pnl"], "trades": v["trades"], "wr": v["wr"]} for k, v in fric["matrix"].items()},
        },
        "monte_carlo": mc,
        "param_jitter": {
            "n_variants": jit["n_variants"], "n_positive": jit["n_positive"],
            "positive_pct": jit["positive_pct"], "median_pnl": jit["median_pnl"],
            "worst_pnl": jit["worst_pnl"], "best_pnl": jit["best_pnl"],
            "p10_pnl": jit["p10_pnl"], "go": jit["go"],
        },
        "universe": {
            "concentration": univ["concentration"], "subsets": univ["subsets"],
            "n_positive_subsets": univ["n_positive_subsets"],
            "go_universe": univ["go_universe"], "go_concentration": univ["go_concentration"],
            "go": univ["go"],
        },
        "timing": {
            "precompute_s": round(precompute_time, 1), "backtest_s": round(bt_time, 1),
            "wf_s": round(wf_time, 1), "friction_s": round(fric_time, 1),
            "mc_s": round(mc_time, 1), "jitter_s": round(jit_time, 1),
            "universe_s": round(univ_time, 1), "total_s": round(total_time, 1),
        },
    }

    print(f"\n  Total time for {cache_name}: {total_time:.1f}s")
    return result


def generate_markdown(results, json_path):
    lines = [
        "# Verify Baseline -- C1_TPSL_RSI45 on Two Universes",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"JSON: `{json_path}`",
        "",
        "## Config",
        "```json",
        json.dumps(CONFIG, indent=2, sort_keys=True),
        "```",
        "",
        "## Settings",
        f"- KRAKEN_FEE: {KRAKEN_FEE}",
        f"- INITIAL_CAPITAL: ${INITIAL_CAPITAL}",
        f"- START_BAR: {START_BAR}",
        "",
        "## Cache Metadata",
        "",
        "| Property | LIVE_CURRENT | RESEARCH_ALL |",
        "|----------|-------------|--------------|",
    ]

    r1 = results["LIVE_CURRENT"]
    r2 = results["RESEARCH_ALL"]

    lines.append(f"| File | `{Path(r1['cache_path']).name}` | `{Path(r2['cache_path']).name}` |")
    lines.append(f"| MD5 | `{r1['cache_md5'][:16]}...` | `{r2['cache_md5'][:16]}...` |")
    lines.append(f"| Size | {r1['cache_size_bytes']:,} bytes | {r2['cache_size_bytes']:,} bytes |")
    lines.append(f"| Coins | {r1['n_coins']} | {r2['n_coins']} |")
    lines.append(f"| Max Bars | {r1['bar_stats']['max']} | {r2['bar_stats']['max']} |")
    lines.append(f"| Min Bars | {r1['bar_stats']['min']} | {r2['bar_stats']['min']} |")

    lines.extend(["", "## Baseline Results", "",
        "| Metric | LIVE_CURRENT | RESEARCH_ALL |",
        "|--------|-------------|--------------|"])

    b1, b2 = r1["baseline"], r2["baseline"]
    lines.append(f"| Trades | {b1['trades']} | {b2['trades']} |")
    lines.append(f"| P&L | ${b1['pnl']:,.2f} | ${b2['pnl']:,.2f} |")
    lines.append(f"| Win Rate | {b1['wr']}% | {b2['wr']}% |")
    lines.append(f"| Profit Factor | {b1['pf']} | {b2['pf']} |")
    lines.append(f"| Max DD | {b1['dd']}% | {b2['dd']}% |")
    lines.append(f"| Final Equity | ${b1['final_equity']:,.2f} | ${b2['final_equity']:,.2f} |")

    c1, c2 = r1["concentration"], r2["concentration"]
    lines.append(f"| Top1 Coin | {c1['top1_coin']} ({c1['top1_share']*100:.1f}%) | {c2['top1_coin']} ({c2['top1_share']*100:.1f}%) |")
    lines.append(f"| Top3 Share | {c1['top3_share']*100:.1f}% | {c2['top3_share']*100:.1f}% |")
    lines.append(f"| NoTop P&L | ${c1['notop_pnl']:,.2f} | ${c2['notop_pnl']:,.2f} |")
    lines.append(f"| Unique Coins | {c1['unique_coins_traded']} | {c2['unique_coins_traded']} |")

    lines.extend(["", "## Robustness Tests", "",
        "| Test | LIVE_CURRENT | RESEARCH_ALL |",
        "|------|-------------|--------------|"])

    wf1, wf2 = r1["walk_forward"], r2["walk_forward"]
    lines.append(f"| WF (5-fold) | {wf1['wf_label']} (maxDD {wf1['max_test_dd']}%) | {wf2['wf_label']} (maxDD {wf2['max_test_dd']}%) |")

    fr1, fr2 = r1["friction"], r2["friction"]
    lines.append(f"| Friction 2x+20bps | ${fr1['go_pnl']} ({'GO' if fr1['go'] else 'NO-GO'}) | ${fr2['go_pnl']} ({'GO' if fr2['go'] else 'NO-GO'}) |")

    mc1, mc2 = r1["monte_carlo"], r2["monte_carlo"]
    mc1_str = f"ruin={mc1['ruin_prob_pct']}% win={mc1['equity']['win_pct']}%" if "error" not in mc1 else mc1["error"]
    mc2_str = f"ruin={mc2['ruin_prob_pct']}% win={mc2['equity']['win_pct']}%" if "error" not in mc2 else mc2["error"]
    lines.append(f"| MC 1000 shuffles | {mc1_str} | {mc2_str} |")

    j1, j2 = r1["param_jitter"], r2["param_jitter"]
    lines.append(f"| Jitter (50 var) | {j1['positive_pct']}% positive | {j2['positive_pct']}% positive |")

    u1, u2 = r1["universe"], r2["universe"]
    lines.append(f"| Universe shift | {u1['n_positive_subsets']}/4 positive | {u2['n_positive_subsets']}/4 positive |")

    lines.extend(["", "## Walk-Forward Fold Detail", "", "### LIVE_CURRENT", "",
        "| Fold | Test Bars | Trades | P&L | WR | DD | Pass |",
        "|------|-----------|--------|-----|-----|-----|------|"])
    for f in wf1["folds"]:
        sym = "PASS" if f["pass"] else "FAIL"
        lines.append(f"| F{f['fold']} | {f['test_bars']} | {f['test_trades']} | ${f['test_pnl']} | {f['test_wr']}% | {f['test_dd']}% | {sym} |")

    lines.extend(["", "### RESEARCH_ALL", "",
        "| Fold | Test Bars | Trades | P&L | WR | DD | Pass |",
        "|------|-----------|--------|-----|-----|-----|------|"])
    for f in wf2["folds"]:
        sym = "PASS" if f["pass"] else "FAIL"
        lines.append(f"| F{f['fold']} | {f['test_bars']} | {f['test_trades']} | ${f['test_pnl']} | {f['test_wr']}% | {f['test_dd']}% | {sym} |")

    lines.extend(["", "## Exit Class Breakdown", ""])
    for cache_name in ["LIVE_CURRENT", "RESEARCH_ALL"]:
        r = results[cache_name]
        lines.append(f"### {cache_name}")
        lines.append("")
        ec = r["exit_classes"]
        if ec:
            lines.append("| Class | Reason | Count | P&L | Wins |")
            lines.append("|-------|--------|-------|-----|------|")
            for cls in sorted(ec.keys()):
                for reason in sorted(ec[cls].keys()):
                    s = ec[cls][reason]
                    lines.append(f"| {cls} | {reason} | {s['count']} | ${s['pnl']:.2f} | {s['wins']} |")
        else:
            lines.append("No exit class data available.")
        lines.append("")

    lines.extend(["", "## Timing", "",
        "| Phase | LIVE_CURRENT | RESEARCH_ALL |",
        "|-------|-------------|--------------|"])
    t1, t2 = r1["timing"], r2["timing"]
    for k in ["precompute_s", "backtest_s", "wf_s", "friction_s", "mc_s", "jitter_s", "universe_s", "total_s"]:
        lines.append(f"| {k} | {t1[k]}s | {t2[k]}s |")

    return "\n".join(lines)


def main():
    print("=" * 70)
    print("  VERIFY BASELINE -- C1_TPSL_RSI45 on Two Universes")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = {}
    total_t0 = time.time()

    for cache_name, cache_path in CACHES.items():
        if not cache_path.exists():
            print(f"\n  ERROR: Cache not found: {cache_path}")
            continue
        results[cache_name] = run_for_cache(cache_name, cache_path)

    total_time = time.time() - total_t0
    print(f"\n  Grand total: {total_time:.1f}s")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "verify_baseline.json"

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": CONFIG,
        "settings": {"KRAKEN_FEE": KRAKEN_FEE, "INITIAL_CAPITAL": INITIAL_CAPITAL, "START_BAR": START_BAR},
        "results": results,
        "total_time_s": round(total_time, 1),
    }

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Saved: {json_path}")

    if len(results) == 2:
        md_path = OUTPUT_DIR / "verify_baseline.md"
        md_content = generate_markdown(results, json_path)
        with open(md_path, "w") as f:
            f.write(md_content)
        print(f"  Saved: {md_path}")
    else:
        md_path = None
        print("  Skipped MD (not all caches available)")

    print(f"\n  Done. JSON: {json_path}")
    if md_path:
        print(f"         MD:   {md_path}")


if __name__ == "__main__":
    main()
