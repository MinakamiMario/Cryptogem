#!/usr/bin/env python3
"""
run_superhf_sprint2.py — SuperHF Sprint 2: Exit Priority Reorder.

Sprint 1 finding: RSI RECOVERY on 15m is too noisy (28% WR, -$8.3K)
while DC TARGET (78% WR, +$8.8K) and BB TARGET (65-81% WR) are profitable.

Sprint 2 fix: Reorder exit chain so DC/BB targets fire BEFORE RSI Recovery:
  FIXED STOP → TIME MAX → DC TARGET → BB TARGET → RSI RECOVERY

Runs top-3 configs from Sprint 1 (A01, A06, A03) and compares with baseline.

Usage:
    python3 scripts/run_superhf_sprint2.py
"""
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

# Sprint 1 baseline results for comparison
SPRINT1_BASELINE = {
    "SHF-A01": {"pf": 0.942, "trades": 1071, "pnl": -1038, "wr": 55.7, "dd": 83.0, "wf": "1/3"},
    "SHF-A06": {"pf": 0.882, "trades": 974, "pnl": -1183, "wr": 58.4, "dd": 78.1, "wf": "0/3"},
    "SHF-A03": {"pf": 0.849, "trades": 1296, "pnl": -1468, "wr": 56.0, "dd": 80.3, "wf": "1/3"},
}

TOP3_IDS = ["SHF-A01", "SHF-A06", "SHF-A03"]


# ---------------------------------------------------------------------------
# Data loading (reused from sprint1)
# ---------------------------------------------------------------------------

def load_cache(tf: str) -> dict:
    path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / tf / f"candle_cache_{tf}_mexc_superhf.json"
    if not path.exists():
        print(f"[ERROR] Cache not found: {path}")
        sys.exit(1)
    print(f"[LOAD] {path.name}...", end=" ", flush=True)
    with open(path, "r") as f:
        data = json.load(f)
    coins = {k: v for k, v in data.items() if not k.startswith("_")}
    print(f"{len(coins)} coins loaded ({data.get('_timeframe', tf)})")
    return coins


def get_common_coins(data_15m: dict, data_1h: dict, min_bars_15m: int = 1000) -> list[str]:
    common = []
    for coin in data_15m:
        if coin not in data_1h:
            continue
        if len(data_15m[coin]) < min_bars_15m:
            continue
        if len(data_1h[coin]) < 50:
            continue
        common.append(coin)
    return sorted(common)


# ---------------------------------------------------------------------------
# Gates (same as Sprint 1)
# ---------------------------------------------------------------------------

def apply_gates(result, wf_results, config_id, n_coins):
    gates = {}
    gates["S1_trades"] = {"pass": result.trades >= 80, "value": result.trades, "threshold": 80}
    gates["S2_pf"] = {"pass": result.pf >= 1.10, "value": round(result.pf, 3), "threshold": 1.10}

    wf_passes = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)
    gates["S3_windows"] = {"pass": wf_passes >= 2, "value": f"{wf_passes}/{len(wf_results)}", "threshold": "≥2/3"}

    trades = result.trade_list
    if trades:
        coin_trade_counts = Counter(t['pair'] for t in trades)
        top10_coins = [c for c, _ in coin_trade_counts.most_common(10)]
        top10_trade_pct = sum(coin_trade_counts[c] for c in top10_coins) / len(trades) * 100

        coin_profit = defaultdict(float)
        for t in trades:
            if t['pnl'] > 0:
                coin_profit[t['pair']] += t['pnl']
        total_profit = sum(coin_profit.values())
        if total_profit > 0:
            top10_pnl_coins = sorted(coin_profit, key=coin_profit.get, reverse=True)[:10]
            top10_pnl_pct = sum(coin_profit[c] for c in top10_pnl_coins) / total_profit * 100
        else:
            top10_pnl_pct = 100.0

        gates["S4_concentration"] = {
            "pass": top10_trade_pct <= 50 and top10_pnl_pct <= 70,
            "top10_trade_pct": round(top10_trade_pct, 1),
            "top10_pnl_pct": round(top10_pnl_pct, 1),
        }
    else:
        gates["S4_concentration"] = {"pass": False, "value": "no trades"}

    gates["_overall"] = all(g.get("pass", False) for k, g in gates.items() if not k.startswith("_"))
    return gates


# ---------------------------------------------------------------------------
# Exit breakdown helper
# ---------------------------------------------------------------------------

def exit_breakdown(result):
    breakdown = {}
    for cls in ['A', 'B']:
        for reason, stats in result.exit_classes.get(cls, {}).items():
            breakdown[reason] = {
                "class": cls,
                "count": stats['count'],
                "pnl": round(stats['pnl'], 2),
                "wr": round(stats['wins'] / stats['count'] * 100, 1) if stats['count'] else 0,
            }
    return breakdown


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  SuperHF Sprint 2 — Exit Priority Reorder")
    print("  New chain: STOP/TM → DC TARGET → BB TARGET → RSI RECOVERY")
    print("=" * 60)

    # Load data
    data_15m = load_cache("15m")
    data_1h = load_cache("1h")
    coins = get_common_coins(data_15m, data_1h)
    print(f"\n[UNIVERSE] {len(coins)} coins")

    # Build configs, filter top-3
    all_configs = build_all_configs()
    configs = [h for h in all_configs if h.id in TOP3_IDS]
    print(f"[CONFIGS] Running {len(configs)} configs: {[c.id for c in configs]}")

    results = []
    total_start = time.time()

    for hyp in configs:
        config_id = hyp.id
        baseline = SPRINT1_BASELINE[config_id]
        print(f"\n{'='*50}")
        print(f"[RUN] {config_id}: {hyp.description}")

        start = time.time()

        # Full backtest
        result = run_backtest(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            fee=MEXC_FEE, max_pos=1,
        )

        # Walk-forward
        wf_results = walk_forward(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            n_folds=3, fee=MEXC_FEE, max_pos=1,
        )

        elapsed = time.time() - start
        gates = apply_gates(result, wf_results, config_id, len(coins))
        exits = exit_breakdown(result)

        wf_detail = []
        for i, wf_r in enumerate(wf_results):
            wf_detail.append({
                "fold": i + 1, "trades": wf_r.trades,
                "pf": round(wf_r.pf, 3), "pnl": round(wf_r.pnl, 2),
                "wr": round(wf_r.wr, 1),
            })

        wf_pass = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)

        entry = {
            "config_id": config_id,
            "family": hyp.family,
            "description": hyp.description,
            "trades": result.trades,
            "pf": round(result.pf, 3),
            "pnl": round(result.pnl, 2),
            "wr": round(result.wr, 1),
            "dd": round(result.dd, 1),
            "final_equity": round(result.final_equity, 2),
            "wf_detail": wf_detail,
            "wf_pass": wf_pass,
            "gates": gates,
            "gates_pass": gates["_overall"],
            "exit_breakdown": exits,
            "elapsed_s": round(elapsed, 1),
            # Sprint 1 baseline for comparison
            "baseline": baseline,
            # Delta
            "delta_pf": round(result.pf - baseline["pf"], 3),
            "delta_pnl": round(result.pnl - baseline["pnl"], 0),
            "delta_dd": round(result.dd - baseline["dd"], 1),
        }

        # Print summary with comparison
        gate_str = "✅ ALL PASS" if gates["_overall"] else "❌ FAIL"
        print(f"  Sprint 2: Trades={result.trades} PF={result.pf:.3f} P&L=${result.pnl:.0f} "
              f"WR={result.wr:.1f}% DD={result.dd:.1f}%")
        print(f"  Sprint 1: Trades={baseline['trades']} PF={baseline['pf']:.3f} P&L=${baseline['pnl']:.0f} "
              f"WR={baseline['wr']:.1f}% DD={baseline['dd']:.1f}%")
        pf_arrow = "↑" if entry['delta_pf'] > 0 else "↓" if entry['delta_pf'] < 0 else "="
        pnl_arrow = "↑" if entry['delta_pnl'] > 0 else "↓" if entry['delta_pnl'] < 0 else "="
        dd_arrow = "↓" if entry['delta_dd'] < 0 else "↑" if entry['delta_dd'] > 0 else "="
        print(f"  DELTA: PF {pf_arrow}{entry['delta_pf']:+.3f} | "
              f"P&L {pnl_arrow}${entry['delta_pnl']:+.0f} | "
              f"DD {dd_arrow}{entry['delta_dd']:+.1f}pp")
        print(f"  WF: {wf_pass}/3 | Gates: {gate_str}")
        print(f"  Exit breakdown:")
        for reason, stats in sorted(exits.items(), key=lambda x: x[1]['pnl'], reverse=True):
            print(f"    {reason}: {stats['count']} trades, ${stats['pnl']:.0f}, "
                  f"WR={stats['wr']:.1f}% [{stats['class']}]")
        print(f"  Time: {elapsed:.1f}s")

        results.append(entry)

    total_elapsed = time.time() - total_start

    # Write report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "_timestamp": int(time.time()),
        "_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_sprint": "Sprint 2: Exit Priority Reorder",
        "_change": "STOP/TM → DC TARGET → BB TARGET → RSI RECOVERY (was: STOP/TM → RSI → DC → BB)",
        "_universe": f"superhf_mexc_top200",
        "_coins_tested": len(coins),
        "_configs_tested": len(results),
        "_total_elapsed_s": round(total_elapsed, 1),
        "results": results,
    }

    json_path = REPORTS_DIR / "sprint2_exit_reorder.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\n[SAVED] {json_path}")

    # Markdown report
    md_path = REPORTS_DIR / "sprint2_exit_reorder.md"
    with open(md_path, "w") as f:
        f.write("# SuperHF Sprint 2 — Exit Priority Reorder\n\n")
        f.write(f"**Date**: {report['_date']}\n")
        f.write(f"**Change**: {report['_change']}\n")
        f.write(f"**Universe**: {report['_universe']} ({report['_coins_tested']} coins)\n\n")

        f.write("## Results vs Sprint 1 Baseline\n\n")
        f.write("| Config | Metric | Sprint 1 | Sprint 2 | Delta |\n")
        f.write("|--------|--------|:--------:|:--------:|:-----:|\n")
        for r in results:
            b = r['baseline']
            f.write(f"| **{r['config_id']}** | PF | {b['pf']:.3f} | {r['pf']:.3f} | {r['delta_pf']:+.3f} |\n")
            f.write(f"| | P&L | ${b['pnl']:.0f} | ${r['pnl']:.0f} | ${r['delta_pnl']:+.0f} |\n")
            f.write(f"| | Trades | {b['trades']} | {r['trades']} | {r['trades']-b['trades']:+d} |\n")
            f.write(f"| | WR | {b['wr']:.1f}% | {r['wr']:.1f}% | {r['wr']-b['wr']:+.1f}pp |\n")
            f.write(f"| | DD | {b['dd']:.1f}% | {r['dd']:.1f}% | {r['delta_dd']:+.1f}pp |\n")
            f.write(f"| | WF | {b['wf']} | {r['wf_pass']}/3 | |\n")

        f.write("\n## Exit Class Breakdown (Sprint 2)\n\n")
        f.write("| Config | Exit Reason | Class | Trades | P&L | WR |\n")
        f.write("|--------|------------|:-----:|-------:|----:|---:|\n")
        for r in results:
            for reason, stats in sorted(r['exit_breakdown'].items(),
                                        key=lambda x: x[1]['pnl'], reverse=True):
                f.write(f"| {r['config_id']} | {reason} | {stats['class']} | "
                        f"{stats['count']} | ${stats['pnl']:.0f} | {stats['wr']:.1f}% |\n")

        f.write("\n## Gate Status\n\n")
        f.write("| Config | S1 trades | S2 PF≥1.10 | S3 WF≥2/3 | S4 conc | Overall |\n")
        f.write("|--------|:---------:|:----------:|:---------:|:-------:|:-------:|\n")
        for r in results:
            g = r['gates']
            s1 = "✅" if g["S1_trades"]["pass"] else "❌"
            s2 = "✅" if g["S2_pf"]["pass"] else "❌"
            s3 = "✅" if g["S3_windows"]["pass"] else "❌"
            s4 = "✅" if g["S4_concentration"]["pass"] else "❌"
            ov = "✅" if r["gates_pass"] else "❌"
            f.write(f"| {r['config_id']} | {s1} {g['S1_trades']['value']} | "
                    f"{s2} {g['S2_pf']['value']} | {s3} {g['S3_windows']['value']} | "
                    f"{s4} | {ov} |\n")

        f.write("\n## Conclusion\n\n")
        any_improved = any(r['delta_pf'] > 0 for r in results)
        any_pass_pf1 = any(r['pf'] >= 1.0 for r in results)
        if any_pass_pf1:
            f.write("**Exit priority reorder shows improvement.** Some configs reach PF ≥ 1.0.\n")
        elif any_improved:
            f.write("**Exit priority reorder improves PF but not enough for PF ≥ 1.0.**\n")
        else:
            f.write("**Exit priority reorder did not improve results.**\n")

        f.write("\n## Next Steps\n\n")
        f.write("- If PF improved but < 1.0: test RSI strict variant (rsi_rec_target≥55 or rsi_rec_min_bars=20)\n")
        f.write("- If PF ≥ 1.0: proceed to Sprint 3 execution validation\n")
        f.write("- If no improvement: reconsider signal families\n")

    print(f"[SAVED] {md_path}")

    # Final summary
    print(f"\n{'='*60}")
    print(f"  SPRINT 2 SUMMARY")
    print(f"  Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    for r in results:
        pf_dir = "↑" if r['delta_pf'] > 0 else "↓"
        print(f"  {r['config_id']}: PF {r['pf']:.3f} ({pf_dir}{r['delta_pf']:+.3f}) | "
              f"P&L ${r['pnl']:.0f} | DD {r['dd']:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
