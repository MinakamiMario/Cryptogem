#!/usr/bin/env python3
"""
run_superhf_sprint3.py — SuperHF Sprint 3: 1H Entries + 15m Confirmation.

Sprint 1+2 finding: 15m MTF mean reversion with DC exits is 0/24 PF>=1.0.
Sprint 3 pivot: Move entry timeframe to 1H (higher quality signals) and use
15m only for confirmation (e.g. reclaim, volume, momentum). DC-only exits
on 1H timeframe.

Runs 10 configs through harness_s3 with stricter gates:
  G1: trades >= 300       (90 days x 3.3/day minimum)
  G2: PF >= 1.10          (minimum viable edge)
  G3: DD <= 25.0          (deployable drawdown)
  G4: WF >= 2/3           (walk-forward, 3-fold, each fold PF>=1.0 and trades>=5)
  G5: concentration       (top10 coins: trade_pct <= 50%, profit_pct <= 70%)

Kill switch: If 0/10 pass all 5 gates -> NO-GO, SuperHF project CLOSED.

Usage:
    python3 scripts/run_superhf_sprint3.py
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

from strategies.superhf.hypotheses_s3 import build_all_configs_s3
from strategies.superhf.harness_s3 import run_backtest, walk_forward

DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
REPORTS_DIR = ROOT / "reports" / "superhf"

# MEXC fee: 0% maker, 10bps taker -> conservative 10bps/side
MEXC_FEE = 0.001

# Gate thresholds (STRICTER than Sprint 1+2)
GATE_TRADES = 300         # 90 days x 3.3/day minimum
GATE_PF = 1.10            # Minimum viable edge
GATE_DD = 25.0            # Deployable drawdown
GATE_WF_PASS = 2          # Walk-forward folds passing (out of 3)
GATE_CONC_TRADE = 50.0    # Top-10 coin trade concentration %
GATE_CONC_PROFIT = 70.0   # Top-10 coin profit concentration %


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_cache(tf: str) -> dict:
    """Load candle cache from data lake."""
    path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / tf / f"candle_cache_{tf}_mexc_superhf.json"
    if not path.exists():
        print(f"[ERROR] Cache not found: {path}")
        print(f"  Run: python3 scripts/build_superhf_cache.py")
        sys.exit(1)

    print(f"[LOAD] {path.name}...", end=" ", flush=True)
    with open(path, "r") as f:
        data = json.load(f)

    # Extract coin data (skip metadata keys starting with _)
    coins = {k: v for k, v in data.items() if not k.startswith("_")}
    print(f"{len(coins)} coins loaded ({data.get('_timeframe', tf)})")
    return coins


def get_common_coins(data_1h: dict, data_15m: dict,
                     min_bars_1h: int = 50, min_bars_15m: int = 200) -> list[str]:
    """Get coins present in both datasets with enough bars."""
    common = []
    for coin in data_1h:
        if coin not in data_15m:
            continue
        if len(data_1h[coin]) < min_bars_1h:
            continue
        if len(data_15m[coin]) < min_bars_15m:
            continue
        common.append(coin)
    return sorted(common)


# ---------------------------------------------------------------------------
# Gates (STRICTER than Sprint 1+2)
# ---------------------------------------------------------------------------

def apply_gates(result, wf_results: list) -> dict:
    """Apply Sprint 3 screening gates. Returns gate results."""
    gates = {}

    # G1: trades >= 300
    gates["G1_trades"] = {
        "pass": result.trades >= GATE_TRADES,
        "value": result.trades,
        "threshold": GATE_TRADES,
    }

    # G2: PF >= 1.10
    gates["G2_pf"] = {
        "pass": result.pf >= GATE_PF,
        "value": round(result.pf, 3),
        "threshold": GATE_PF,
    }

    # G3: DD <= 25.0%
    gates["G3_dd"] = {
        "pass": result.dd <= GATE_DD,
        "value": round(result.dd, 1),
        "threshold": GATE_DD,
    }

    # G4: Walk-forward >= 2/3 (each fold PF>=1.0 and trades>=5)
    wf_passes = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)
    gates["G4_wf"] = {
        "pass": wf_passes >= GATE_WF_PASS,
        "value": f"{wf_passes}/{len(wf_results)}",
        "threshold": f">={GATE_WF_PASS}/3",
    }

    # G5: Concentration (top10 coins)
    trades = result.trade_list
    if trades:
        coin_trade_counts = Counter(t['pair'] for t in trades)
        top10_coins = [c for c, _ in coin_trade_counts.most_common(10)]
        top10_trade_pct = sum(coin_trade_counts[c] for c in top10_coins) / len(trades) * 100

        # Positive profit attribution
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

        gates["G5_concentration"] = {
            "pass": top10_trade_pct <= GATE_CONC_TRADE and top10_pnl_pct <= GATE_CONC_PROFIT,
            "top10_trade_pct": round(top10_trade_pct, 1),
            "top10_pnl_pct": round(top10_pnl_pct, 1),
            "threshold": f"trades<={GATE_CONC_TRADE}% AND profit<={GATE_CONC_PROFIT}%",
        }
    else:
        gates["G5_concentration"] = {"pass": False, "value": "no trades"}

    # Overall: all 5 gates must pass
    gates["_overall"] = all(
        g.get("pass", False) for k, g in gates.items() if not k.startswith("_")
    )

    return gates


# ---------------------------------------------------------------------------
# Exit breakdown helper
# ---------------------------------------------------------------------------

def exit_breakdown(result) -> dict:
    """Build exit reason breakdown from backtest result."""
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
# Report writers
# ---------------------------------------------------------------------------

def write_json_report(results: list[dict], coins: list[str],
                      total_elapsed: float) -> Path:
    """Write JSON scoreboard report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)
    n_pass = sum(1 for r in results if r.get("gates_pass"))

    report = {
        "_timestamp": int(time.time()),
        "_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_sprint": "Sprint 3: 1H Entries + 15m Confirmation",
        "_universe": "superhf_mexc_top200",
        "_coins_tested": len(coins),
        "_configs_tested": len(results),
        "_configs_pass": n_pass,
        "_total_elapsed_s": round(total_elapsed, 1),
        "results": results_sorted,
    }

    json_path = REPORTS_DIR / "sprint3_scoreboard.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=1)

    return json_path


def write_md_report(results: list[dict], coins: list[str],
                    total_elapsed: float) -> Path:
    """Write Markdown scoreboard report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)
    n_pass = sum(1 for r in results if r.get("gates_pass"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    md_path = REPORTS_DIR / "sprint3_scoreboard.md"
    with open(md_path, "w") as f:
        f.write("# SuperHF Sprint 3 -- 1H Entries + 15m Confirmation\n\n")
        f.write(f"**Date**: {now_str}\n")
        f.write(f"**Universe**: superhf_mexc_top200 ({len(coins)} coins)\n")
        f.write(f"**Configs**: {len(results)} total, **{n_pass} PASS**\n")
        f.write(f"**Total time**: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)\n\n")

        # Scoreboard table
        f.write("## Scoreboard (sorted by PF)\n\n")
        f.write("| # | Config | Family | Trades | PF | P&L | WR | DD | WF | Gates |\n")
        f.write("|---|--------|--------|-------:|---:|----:|---:|---:|---:|:-----:|\n")
        for i, r in enumerate(results_sorted):
            gate_str = "PASS" if r.get("gates_pass") else "FAIL"
            f.write(
                f"| {i+1} | {r['config_id']} | {r['family']} | "
                f"{r['trades']} | {r['pf']:.3f} | ${r['pnl']:.0f} | "
                f"{r['wr']:.1f}% | {r['dd']:.1f}% | "
                f"{r['wf_pass']}/3 | {gate_str} |\n"
            )

        # Exit breakdown for top 3
        f.write("\n## Exit Breakdown (Top 3 by PF)\n\n")
        f.write("| Config | Exit Reason | Class | Trades | P&L | WR |\n")
        f.write("|--------|------------|:-----:|-------:|----:|---:|\n")
        for r in results_sorted[:3]:
            for reason, stats in sorted(r['exit_breakdown'].items(),
                                        key=lambda x: x[1]['pnl'], reverse=True):
                f.write(
                    f"| {r['config_id']} | {reason} | {stats['class']} | "
                    f"{stats['count']} | ${stats['pnl']:.0f} | {stats['wr']:.1f}% |\n"
                )

        # Gate status table
        f.write("\n## Gate Status\n\n")
        f.write("| Config | G1 trades>=300 | G2 PF>=1.10 | G3 DD<=25% | G4 WF>=2/3 | G5 conc | Overall |\n")
        f.write("|--------|:--------------:|:-----------:|:----------:|:----------:|:-------:|:-------:|\n")
        for r in results_sorted:
            g = r['gates']
            g1 = "PASS" if g["G1_trades"]["pass"] else "FAIL"
            g2 = "PASS" if g["G2_pf"]["pass"] else "FAIL"
            g3 = "PASS" if g["G3_dd"]["pass"] else "FAIL"
            g4 = "PASS" if g["G4_wf"]["pass"] else "FAIL"
            g5 = "PASS" if g["G5_concentration"]["pass"] else "FAIL"
            ov = "PASS" if r["gates_pass"] else "FAIL"
            f.write(
                f"| {r['config_id']} | {g1} ({g['G1_trades']['value']}) | "
                f"{g2} ({g['G2_pf']['value']}) | "
                f"{g3} ({g['G3_dd']['value']}%) | "
                f"{g4} ({g['G4_wf']['value']}) | "
                f"{g5} | {ov} |\n"
            )

        # Conclusion
        f.write("\n## Conclusion\n\n")
        if n_pass > 0:
            winners = [r for r in results_sorted if r.get("gates_pass")]
            f.write(f"**{n_pass}/{len(results)} configs PASS all 5 gates.**\n\n")
            f.write("Winners:\n")
            for w in winners:
                f.write(
                    f"- **{w['config_id']}** ({w['family']}): "
                    f"PF={w['pf']:.3f}, {w['trades']} trades, "
                    f"P&L=${w['pnl']:.0f}, DD={w['dd']:.1f}%, "
                    f"WF={w['wf_pass']}/3\n"
                )
            f.write("\n")
        else:
            f.write(f"**0/{len(results)} configs pass all 5 gates.**\n\n")
            # Analyze which gates fail most
            gate_fail_counts = {"G1": 0, "G2": 0, "G3": 0, "G4": 0, "G5": 0}
            for r in results:
                g = r['gates']
                if not g["G1_trades"]["pass"]:
                    gate_fail_counts["G1"] += 1
                if not g["G2_pf"]["pass"]:
                    gate_fail_counts["G2"] += 1
                if not g["G3_dd"]["pass"]:
                    gate_fail_counts["G3"] += 1
                if not g["G4_wf"]["pass"]:
                    gate_fail_counts["G4"] += 1
                if not g["G5_concentration"]["pass"]:
                    gate_fail_counts["G5"] += 1
            f.write("Gate failure analysis:\n")
            for gate, count in sorted(gate_fail_counts.items(),
                                      key=lambda x: x[1], reverse=True):
                f.write(f"- {gate}: {count}/{len(results)} configs fail\n")
            f.write("\n")

        # Kill switch verdict
        f.write("## Verdict\n\n")
        if n_pass > 0:
            f.write(f"**GO** -- {n_pass} config(s) pass all gates. "
                    f"Proceed to Sprint 4 (paper trading).\n")
        else:
            f.write("**NO-GO** -- SuperHF project CLOSED. "
                    f"0/{len(results)} configs pass. "
                    f"Write ADR-SUPERHF-003.\n")

    return md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  SuperHF Sprint 3 -- 1H Entries + 15m Confirmation")
    print("  DC-only exits on 1H timeframe")
    print("  Gates: trades>=300, PF>=1.10, DD<=25%, WF>=2/3, conc")
    print("=" * 60)

    # Load data
    data_1h = load_cache("1h")
    data_15m = load_cache("15m")

    # Find common coins with minimum bar requirements
    coins = get_common_coins(data_1h, data_15m, min_bars_1h=50, min_bars_15m=200)
    print(f"\n[UNIVERSE] {len(coins)} coins (both 1H>=50 bars AND 15m>=200 bars)")

    if len(coins) == 0:
        print("[ERROR] No coins meet minimum bar requirements.")
        sys.exit(1)

    # Build all 10 configs
    configs = build_all_configs_s3()
    print(f"[CONFIGS] Running {len(configs)} configs")

    results = []
    total_start = time.time()

    for hyp in configs:
        config_id = hyp.id
        print(f"\n{'='*50}")
        print(f"[RUN] {config_id}: {hyp.description}")
        print(f"  Family: {hyp.family}")

        start = time.time()

        # Full backtest
        result = run_backtest(
            data_1h=data_1h, data_15m=data_15m, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            fee=MEXC_FEE, max_pos=1,
        )

        # Walk-forward (3-fold)
        wf_results = walk_forward(
            data_1h=data_1h, data_15m=data_15m, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            n_folds=3, fee=MEXC_FEE, max_pos=1,
        )

        elapsed = time.time() - start

        # Apply 5 gates
        gates = apply_gates(result, wf_results)

        # Exit breakdown
        exits = exit_breakdown(result)

        # Walk-forward detail
        wf_detail = []
        for i, wf_r in enumerate(wf_results):
            wf_detail.append({
                "fold": i + 1,
                "trades": wf_r.trades,
                "pf": round(wf_r.pf, 3),
                "pnl": round(wf_r.pnl, 2),
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
            "wf_detail": wf_detail,
            "wf_pass": wf_pass,
            "gates": gates,
            "gates_pass": gates["_overall"],
            "exit_breakdown": exits,
            "elapsed_s": round(elapsed, 1),
        }

        # Print summary
        gate_str = "ALL PASS" if gates["_overall"] else "FAIL"
        print(f"  Trades={result.trades} PF={result.pf:.3f} P&L=${result.pnl:.0f} "
              f"WR={result.wr:.1f}% DD={result.dd:.1f}%")
        print(f"  WF: {wf_pass}/3 | Gates: {gate_str}")

        # Print gate details
        for gname, gdata in gates.items():
            if gname.startswith("_"):
                continue
            status = "PASS" if gdata.get("pass") else "FAIL"
            if "top10_trade_pct" in gdata:
                val_str = f"trade={gdata['top10_trade_pct']:.1f}%, profit={gdata['top10_pnl_pct']:.1f}%"
            else:
                val_str = str(gdata.get("value", ""))
            print(f"    {status} {gname}: {val_str}")

        # Print exit breakdown
        print(f"  Exit breakdown:")
        for reason, stats in sorted(exits.items(), key=lambda x: x[1]['pnl'], reverse=True):
            print(f"    {reason}: {stats['count']} trades, ${stats['pnl']:.0f}, "
                  f"WR={stats['wr']:.1f}% [{stats['class']}]")
        print(f"  Time: {elapsed:.1f}s")

        results.append(entry)

    total_elapsed = time.time() - total_start

    # Sort by PF descending for final display
    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)

    # Write reports
    json_path = write_json_report(results, coins, total_elapsed)
    print(f"\n[SAVED] {json_path}")

    md_path = write_md_report(results, coins, total_elapsed)
    print(f"[SAVED] {md_path}")

    # Final summary
    n_pass = sum(1 for r in results if r.get("gates_pass"))

    print(f"\n{'='*60}")
    print(f"  SPRINT 3 SUMMARY")
    print(f"  Universe: {len(coins)} coins")
    print(f"  Configs: {len(results)} tested, {n_pass} PASS all 5 gates")
    print(f"  Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print()
    print(f"  Top 5 by PF:")
    for i, r in enumerate(results_sorted[:5]):
        g = "PASS" if r["gates_pass"] else "FAIL"
        print(f"  {i+1}. {r['config_id']}: PF={r['pf']:.3f} | "
              f"Trades={r['trades']} | P&L=${r['pnl']:.0f} | "
              f"DD={r['dd']:.1f}% | WF={r['wf_pass']}/3 | {g}")

    # Kill switch
    print()
    print(f"  {'='*50}")
    if n_pass > 0:
        print(f"  GO -- proceed to Sprint 4 (paper trading)")
        winners = [r for r in results_sorted if r.get("gates_pass")]
        for w in winners:
            print(f"    Winner: {w['config_id']} PF={w['pf']:.3f} "
                  f"Trades={w['trades']} DD={w['dd']:.1f}%")
    else:
        print(f"  NO-GO -- SuperHF project CLOSED. "
              f"0/{len(results)} configs pass. Write ADR-SUPERHF-003.")
    print(f"  {'='*50}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
