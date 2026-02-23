#!/usr/bin/env python3
"""
run_superhf_sprint2b_norsi.py — SuperHF Sprint 2B: Disable RSI Recovery.

Sprint 2A (exit reorder) showed 0 delta — exits don't overlap.
RSI Recovery fires when price is BELOW dc_mid AND bb_mid (17% WR, -$4K to -$7.5K).
Sprint 2B: Disable RSI Recovery entirely. Remaining exits: STOP/TM → DC → BB.

Runs top-3 configs (A01, A06, A03) + all 12 configs with rsi_recovery=False.

Usage:
    python3 scripts/run_superhf_sprint2b_norsi.py
"""
import copy
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.superhf.hypotheses import build_all_configs
from strategies.superhf.harness import run_backtest, walk_forward, START_BAR

DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
REPORTS_DIR = ROOT / "reports" / "superhf"
MEXC_FEE = 0.001

# Sprint 1 baselines (all 12)
SPRINT1_BASELINE = {
    "SHF-A01": {"pf": 0.942, "trades": 1071, "pnl": -1038, "wr": 55.7, "dd": 83.0, "wf": "1/3"},
    "SHF-A02": {"pf": 0.812, "trades": 1102, "pnl": -1877, "wr": 54.9, "dd": 96.2, "wf": "0/3"},
    "SHF-A03": {"pf": 0.849, "trades": 1296, "pnl": -1468, "wr": 56.0, "dd": 80.3, "wf": "1/3"},
    "SHF-A04": {"pf": 0.811, "trades": 1231, "pnl": -1792, "wr": 55.6, "dd": 91.6, "wf": "0/3"},
    "SHF-A05": {"pf": 0.788, "trades": 753, "pnl": -1516, "wr": 54.2, "dd": 82.0, "wf": "0/3"},
    "SHF-A06": {"pf": 0.882, "trades": 974, "pnl": -1183, "wr": 58.4, "dd": 78.1, "wf": "0/3"},
    "SHF-B01": {"pf": 0.739, "trades": 591, "pnl": -1569, "wr": 53.6, "dd": 82.8, "wf": "0/3"},
    "SHF-B02": {"pf": 0.654, "trades": 778, "pnl": -1794, "wr": 54.4, "dd": 90.2, "wf": "0/3"},
    "SHF-B03": {"pf": 0.635, "trades": 398, "pnl": -1339, "wr": 55.0, "dd": 71.3, "wf": "0/3"},
    "SHF-B04": {"pf": 0.561, "trades": 558, "pnl": -1633, "wr": 55.6, "dd": 82.3, "wf": "1/3"},
    "SHF-B05": {"pf": 0.634, "trades": 339, "pnl": -1247, "wr": 51.0, "dd": 63.6, "wf": "0/3"},
    "SHF-B06": {"pf": 0.430, "trades": 293, "pnl": -1254, "wr": 49.5, "dd": 63.1, "wf": "0/3"},
}


def load_cache(tf: str) -> dict:
    path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / tf / f"candle_cache_{tf}_mexc_superhf.json"
    if not path.exists():
        print(f"[ERROR] Cache not found: {path}")
        sys.exit(1)
    print(f"[LOAD] {path.name}...", end=" ", flush=True)
    with open(path, "r") as f:
        data = json.load(f)
    coins = {k: v for k, v in data.items() if not k.startswith("_")}
    print(f"{len(coins)} coins ({data.get('_timeframe', tf)})")
    return coins


def get_common_coins(data_15m, data_1h, min_bars_15m=1000):
    return sorted([c for c in data_15m
                   if c in data_1h and len(data_15m[c]) >= min_bars_15m and len(data_1h[c]) >= 50])


def apply_gates(result, wf_results):
    gates = {}
    gates["S1_trades"] = {"pass": result.trades >= 80, "value": result.trades}
    gates["S2_pf"] = {"pass": result.pf >= 1.10, "value": round(result.pf, 3)}
    wf_passes = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)
    gates["S3_windows"] = {"pass": wf_passes >= 2, "value": f"{wf_passes}/{len(wf_results)}"}

    trades = result.trade_list
    if trades:
        coin_counts = Counter(t['pair'] for t in trades)
        top10 = [c for c, _ in coin_counts.most_common(10)]
        top10_trade_pct = sum(coin_counts[c] for c in top10) / len(trades) * 100
        coin_profit = defaultdict(float)
        for t in trades:
            if t['pnl'] > 0:
                coin_profit[t['pair']] += t['pnl']
        total_profit = sum(coin_profit.values())
        if total_profit > 0:
            top10_pnl = sorted(coin_profit, key=coin_profit.get, reverse=True)[:10]
            top10_pnl_pct = sum(coin_profit[c] for c in top10_pnl) / total_profit * 100
        else:
            top10_pnl_pct = 100.0
        gates["S4_concentration"] = {
            "pass": top10_trade_pct <= 50 and top10_pnl_pct <= 70,
            "top10_trade_pct": round(top10_trade_pct, 1),
            "top10_pnl_pct": round(top10_pnl_pct, 1),
        }
    else:
        gates["S4_concentration"] = {"pass": False}

    gates["_overall"] = all(g.get("pass", False) for k, g in gates.items() if not k.startswith("_"))
    return gates


def exit_breakdown(result):
    bd = {}
    for cls in ['A', 'B']:
        for reason, stats in result.exit_classes.get(cls, {}).items():
            bd[reason] = {
                "class": cls, "count": stats['count'],
                "pnl": round(stats['pnl'], 2),
                "wr": round(stats['wins'] / stats['count'] * 100, 1) if stats['count'] else 0,
            }
    return bd


def main():
    print("=" * 60)
    print("  SuperHF Sprint 2B — Disable RSI Recovery")
    print("  Exit chain: STOP → TIME MAX → DC TARGET → BB TARGET")
    print("=" * 60)

    data_15m = load_cache("15m")
    data_1h = load_cache("1h")
    coins = get_common_coins(data_15m, data_1h)
    print(f"\n[UNIVERSE] {len(coins)} coins")

    all_configs = build_all_configs()
    print(f"[CONFIGS] Running all {len(all_configs)} configs with rsi_recovery=False")

    results = []
    total_start = time.time()

    for hyp in all_configs:
        config_id = hyp.id
        baseline = SPRINT1_BASELINE.get(config_id, {})

        # Override: disable RSI Recovery
        params = copy.deepcopy(hyp.params)
        params["rsi_recovery"] = False

        print(f"\n{'='*50}")
        print(f"[RUN] {config_id}: {hyp.description} [rsi_recovery=False]")

        start = time.time()

        result = run_backtest(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=params,
            fee=MEXC_FEE, max_pos=1,
        )

        wf_results = walk_forward(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=params,
            n_folds=3, fee=MEXC_FEE, max_pos=1,
        )

        elapsed = time.time() - start
        gates = apply_gates(result, wf_results)
        exits = exit_breakdown(result)

        wf_pass = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)
        wf_detail = [{"fold": i+1, "trades": r.trades, "pf": round(r.pf, 3),
                       "pnl": round(r.pnl, 2), "wr": round(r.wr, 1)}
                      for i, r in enumerate(wf_results)]

        delta_pf = round(result.pf - baseline.get("pf", 0), 3)
        delta_pnl = round(result.pnl - baseline.get("pnl", 0), 0)
        delta_dd = round(result.dd - baseline.get("dd", 0), 1)

        entry = {
            "config_id": config_id, "family": hyp.family,
            "description": hyp.description + " [no RSI Recovery]",
            "trades": result.trades, "pf": round(result.pf, 3),
            "pnl": round(result.pnl, 2), "wr": round(result.wr, 1),
            "dd": round(result.dd, 1), "final_equity": round(result.final_equity, 2),
            "wf_detail": wf_detail, "wf_pass": wf_pass,
            "gates": gates, "gates_pass": gates["_overall"],
            "exit_breakdown": exits, "elapsed_s": round(elapsed, 1),
            "baseline": baseline, "delta_pf": delta_pf,
            "delta_pnl": delta_pnl, "delta_dd": delta_dd,
        }

        gate_str = "✅ ALL PASS" if gates["_overall"] else "❌ FAIL"
        pf_arrow = "↑" if delta_pf > 0 else "↓"
        print(f"  S2B: Trades={result.trades} PF={result.pf:.3f} P&L=${result.pnl:.0f} "
              f"WR={result.wr:.1f}% DD={result.dd:.1f}%")
        print(f"  S1:  Trades={baseline.get('trades','?')} PF={baseline.get('pf','?'):.3f} "
              f"P&L=${baseline.get('pnl','?'):.0f} DD={baseline.get('dd','?'):.1f}%")
        print(f"  DELTA: PF {pf_arrow}{delta_pf:+.3f} | P&L ${delta_pnl:+.0f} | DD {delta_dd:+.1f}pp")
        print(f"  WF: {wf_pass}/3 | Gates: {gate_str}")
        for reason, stats in sorted(exits.items(), key=lambda x: x[1]['pnl'], reverse=True):
            print(f"    {reason}: {stats['count']}tr, ${stats['pnl']:.0f}, WR={stats['wr']:.1f}%")
        print(f"  Time: {elapsed:.1f}s")

        results.append(entry)

    total_elapsed = time.time() - total_start

    # Sort by PF
    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)

    # Save JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "_timestamp": int(time.time()),
        "_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_sprint": "Sprint 2B: RSI Recovery Disabled",
        "_change": "rsi_recovery=False for all configs. Exit chain: STOP → TIME MAX → DC TARGET → BB TARGET",
        "_rationale": "RSI Recovery on 15m fires when price < dc_mid AND < bb_mid (17% WR, -$4K to -$7.5K). Exits don't overlap with DC/BB targets.",
        "_universe": "superhf_mexc_top200",
        "_coins_tested": len(coins),
        "_configs_tested": len(results),
        "_configs_pass": sum(1 for r in results if r["gates_pass"]),
        "_total_elapsed_s": round(total_elapsed, 1),
        "results": results_sorted,
    }

    json_path = REPORTS_DIR / "sprint2b_norsi.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\n[SAVED] {json_path}")

    # Markdown
    md_path = REPORTS_DIR / "sprint2b_norsi.md"
    with open(md_path, "w") as f:
        f.write("# SuperHF Sprint 2B — RSI Recovery Disabled\n\n")
        f.write(f"**Date**: {report['_date']}\n")
        f.write(f"**Change**: {report['_change']}\n")
        f.write(f"**Rationale**: {report['_rationale']}\n")
        f.write(f"**Universe**: {len(coins)} coins\n")
        f.write(f"**Configs**: {len(results)} total, **{report['_configs_pass']} PASS**\n\n")

        f.write("## Scoreboard (sorted by PF)\n\n")
        f.write("| # | Config | Family | Trades | PF | ΔPF | P&L | ΔP&L | WR | DD | ΔDD | WF | Gates |\n")
        f.write("|---|--------|--------|-------:|---:|----:|----:|-----:|---:|---:|----:|---:|:-----:|\n")
        for i, r in enumerate(results_sorted):
            g = "✅" if r["gates_pass"] else "❌"
            f.write(f"| {i+1} | {r['config_id']} | {r['family']} | "
                    f"{r['trades']} | {r['pf']:.3f} | {r['delta_pf']:+.3f} | "
                    f"${r['pnl']:.0f} | ${r['delta_pnl']:+.0f} | "
                    f"{r['wr']:.1f}% | {r['dd']:.1f}% | {r['delta_dd']:+.1f} | "
                    f"{r['wf_pass']}/3 | {g} |\n")

        f.write("\n## Exit Breakdown (top-3 by PF)\n\n")
        f.write("| Config | Exit | Class | Trades | P&L | WR |\n")
        f.write("|--------|------|:-----:|-------:|----:|---:|\n")
        for r in results_sorted[:3]:
            for reason, stats in sorted(r['exit_breakdown'].items(),
                                        key=lambda x: x[1]['pnl'], reverse=True):
                f.write(f"| {r['config_id']} | {reason} | {stats['class']} | "
                        f"{stats['count']} | ${stats['pnl']:.0f} | {stats['wr']:.1f}% |\n")

        f.write("\n## Key Finding\n\n")
        best = results_sorted[0]
        avg_delta_pf = sum(r['delta_pf'] for r in results) / len(results)
        f.write(f"- Average ΔPF: {avg_delta_pf:+.3f}\n")
        f.write(f"- Best config: {best['config_id']} PF={best['pf']:.3f} (was {best['baseline'].get('pf',0):.3f})\n")
        n_improved = sum(1 for r in results if r['delta_pf'] > 0)
        f.write(f"- Improved: {n_improved}/{len(results)} configs\n")
        n_pf1 = sum(1 for r in results if r['pf'] >= 1.0)
        f.write(f"- PF ≥ 1.0: {n_pf1}/{len(results)} configs\n")

    print(f"[SAVED] {md_path}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  SPRINT 2B SUMMARY — RSI Recovery OFF")
    print(f"  Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"  Configs PASS: {report['_configs_pass']}/{len(results)}")
    print(f"\n  Top 5:")
    for i, r in enumerate(results_sorted[:5]):
        print(f"  {i+1}. {r['config_id']}: PF={r['pf']:.3f} ({r['delta_pf']:+.3f}) "
              f"P&L=${r['pnl']:.0f} DD={r['dd']:.1f}% WF={r['wf_pass']}/3")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
