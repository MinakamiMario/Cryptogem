#!/usr/bin/env python3
"""
run_superhf_sprint1.py — SuperHF Sprint 1 sweep runner.

Runs all 12 configs (2 families × 6) through the SuperHF harness,
applies screening gates, generates scoreboard + coin contribution.

Usage:
    python3 scripts/run_superhf_sprint1.py
    python3 scripts/run_superhf_sprint1.py --config SHF-A01 SHF-B03
    python3 scripts/run_superhf_sprint1.py --max-pos 2
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.superhf.hypotheses import build_all_configs, REGISTRY
from strategies.superhf.harness import run_backtest, walk_forward, START_BAR

DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
REPORTS_DIR = ROOT / "reports" / "superhf"

# MEXC fee: 0% maker, 10bps taker → conservative: 10bps/side
MEXC_FEE = 0.001


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


def get_common_coins(data_15m: dict, data_1h: dict, min_bars_15m: int = 1000) -> list[str]:
    """Get coins present in both datasets with enough bars."""
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
# Screening gates
# ---------------------------------------------------------------------------

def apply_gates(result, wf_results: list, config_id: str, n_coins: int) -> dict:
    """Apply Sprint 1 screening gates. Returns gate results."""
    gates = {}

    # Gate 1: trades ≥ 80
    gates["S1_trades"] = {
        "pass": result.trades >= 80,
        "value": result.trades,
        "threshold": 80,
    }

    # Gate 2: PF ≥ 1.10
    gates["S2_pf"] = {
        "pass": result.pf >= 1.10,
        "value": round(result.pf, 3),
        "threshold": 1.10,
    }

    # Gate 3: 3-way window split ≥ 2/3 profitable
    wf_passes = sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5)
    gates["S3_windows"] = {
        "pass": wf_passes >= 2,
        "value": f"{wf_passes}/{len(wf_results)}",
        "threshold": "≥2/3",
    }

    # Gate 4: Top10 concentration
    trades = result.trade_list
    if trades:
        # Trade concentration
        coin_trade_counts = Counter(t['pair'] for t in trades)
        top10_coins = [c for c, _ in coin_trade_counts.most_common(10)]
        top10_trade_pct = sum(coin_trade_counts[c] for c in top10_coins) / len(trades) * 100

        # PnL concentration (positive profit attribution)
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
            "threshold": "trades≤50% AND pnl≤70%",
        }
    else:
        gates["S4_concentration"] = {
            "pass": False,
            "value": "no trades",
        }

    # Overall
    gates["_overall"] = all(g.get("pass", False) for k, g in gates.items() if not k.startswith("_"))

    return gates


# ---------------------------------------------------------------------------
# Coin contribution table
# ---------------------------------------------------------------------------

def coin_contribution(trades: list[dict]) -> list[dict]:
    """Build per-coin contribution table."""
    coin_stats = defaultdict(lambda: {"trades": 0, "pnl": 0, "wins": 0, "profit": 0})

    for t in trades:
        coin = t['pair']
        coin_stats[coin]["trades"] += 1
        coin_stats[coin]["pnl"] += t['pnl']
        if t['pnl'] > 0:
            coin_stats[coin]["wins"] += 1
            coin_stats[coin]["profit"] += t['pnl']

    result = []
    for coin, s in coin_stats.items():
        result.append({
            "coin": coin,
            "trades": s["trades"],
            "pnl": round(s["pnl"], 2),
            "profit": round(s["profit"], 2),
            "wins": s["wins"],
            "wr": round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0,
        })

    result.sort(key=lambda x: x["pnl"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Scoreboard
# ---------------------------------------------------------------------------

def run_sweep(configs: list, data_15m: dict, data_1h: dict, coins: list[str],
              max_pos: int = 1) -> list[dict]:
    """Run all configs and build scoreboard."""
    results = []

    for hyp in configs:
        config_id = hyp.id
        print(f"\n{'='*50}")
        print(f"[RUN] {config_id}: {hyp.description}")
        print(f"  Family: {hyp.family}")
        print(f"  Params: {hyp.params}")

        start = time.time()

        # Full backtest
        result = run_backtest(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            fee=MEXC_FEE, max_pos=max_pos,
        )

        # Walk-forward (3-way split)
        wf_results = walk_forward(
            data_15m=data_15m, data_1h=data_1h, coins=coins,
            signal_fn=hyp.signal_fn, params=hyp.params,
            n_folds=3, fee=MEXC_FEE, max_pos=max_pos,
        )

        elapsed = time.time() - start

        # Apply gates
        gates = apply_gates(result, wf_results, config_id, len(coins))

        # Coin contribution
        coin_table = coin_contribution(result.trade_list)

        # Exit class breakdown
        exit_breakdown = {}
        for cls in ['A', 'B']:
            for reason, stats in result.exit_classes.get(cls, {}).items():
                exit_breakdown[reason] = {
                    "class": cls,
                    "count": stats['count'],
                    "pnl": round(stats['pnl'], 2),
                    "wr": round(stats['wins'] / stats['count'] * 100, 1) if stats['count'] else 0,
                }

        # WF detail
        wf_detail = []
        for i, wf_r in enumerate(wf_results):
            wf_detail.append({
                "fold": i + 1,
                "trades": wf_r.trades,
                "pf": round(wf_r.pf, 3),
                "pnl": round(wf_r.pnl, 2),
                "wr": round(wf_r.wr, 1),
            })

        entry = {
            "config_id": config_id,
            "name": hyp.name,
            "family": hyp.family,
            "description": hyp.description,
            "params": hyp.params,
            "trades": result.trades,
            "pf": round(result.pf, 3),
            "pnl": round(result.pnl, 2),
            "wr": round(result.wr, 1),
            "dd": round(result.dd, 1),
            "final_equity": round(result.final_equity, 2),
            "wf_detail": wf_detail,
            "wf_pass": sum(1 for r in wf_results if r.pf >= 1.0 and r.trades >= 5),
            "gates": gates,
            "gates_pass": gates["_overall"],
            "exit_breakdown": exit_breakdown,
            "top10_coins": coin_table[:10],
            "elapsed_s": round(elapsed, 1),
        }

        # Print summary
        gate_str = "✅ ALL PASS" if gates["_overall"] else "❌ FAIL"
        print(f"  → Trades={result.trades} PF={result.pf:.3f} P&L=${result.pnl:.0f} "
              f"WR={result.wr:.1f}% DD={result.dd:.1f}%")
        print(f"  → WF: {entry['wf_pass']}/3 | Gates: {gate_str}")
        for gname, gdata in gates.items():
            if gname.startswith("_"):
                continue
            status = "✅" if gdata.get("pass") else "❌"
            print(f"    {status} {gname}: {gdata.get('value', gdata)}")
        print(f"  → Exit breakdown: {exit_breakdown}")
        print(f"  → Time: {elapsed:.1f}s")

        results.append(entry)

    return results


def write_scoreboard(results: list[dict], coins: list[str], output_dir: Path):
    """Write scoreboard JSON and MD."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sort by PF descending
    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)

    # JSON
    report = {
        "_timestamp": int(time.time()),
        "_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_universe": f"superhf_mexc_top200",
        "_coins_tested": len(coins),
        "_configs_total": len(results),
        "_configs_pass": sum(1 for r in results if r.get("gates_pass")),
        "results": results_sorted,
    }

    json_path = output_dir / "sprint1_scoreboard.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\n[SAVED] {json_path}")

    # Markdown
    md_path = output_dir / "sprint1_scoreboard.md"
    with open(md_path, "w") as f:
        f.write(f"# SuperHF Sprint 1 — Scoreboard\n\n")
        f.write(f"**Date**: {report['_date']}\n")
        f.write(f"**Universe**: {report['_universe']} ({report['_coins_tested']} coins)\n")
        f.write(f"**Configs**: {report['_configs_total']} total, "
                f"**{report['_configs_pass']} PASS**\n\n")

        f.write(f"## Results\n\n")
        f.write(f"| # | Config | Family | Trades | PF | P&L | WR | DD | WF | Gates |\n")
        f.write(f"|---|--------|--------|-------:|---:|----:|---:|---:|---:|-------|\n")
        for i, r in enumerate(results_sorted):
            gate_str = "✅" if r.get("gates_pass") else "❌"
            f.write(f"| {i+1} | {r['config_id']} | {r['family']} | "
                    f"{r['trades']} | {r['pf']:.2f} | ${r['pnl']:.0f} | "
                    f"{r['wr']:.1f}% | {r['dd']:.1f}% | "
                    f"{r['wf_pass']}/3 | {gate_str} |\n")

        # Winners shortlist
        winners = [r for r in results_sorted if r.get("gates_pass")]
        f.write(f"\n## Winners Shortlist\n\n")
        if winners:
            for w in winners:
                f.write(f"### {w['config_id']}: {w['description']}\n")
                f.write(f"- PF={w['pf']:.3f}, Trades={w['trades']}, P&L=${w['pnl']:.0f}\n")
                f.write(f"- WR={w['wr']:.1f}%, DD={w['dd']:.1f}%\n")
                f.write(f"- WF: {w['wf_pass']}/3\n")
                f.write(f"- Exit breakdown: {w['exit_breakdown']}\n")
                f.write(f"- Top 5 coins:\n")
                for c in w.get('top10_coins', [])[:5]:
                    f.write(f"  - {c['coin']}: {c['trades']} trades, ${c['pnl']:.0f}, "
                            f"WR={c['wr']:.0f}%\n")
                f.write(f"\n")
        else:
            f.write(f"**No configs passed all gates.**\n\n")

        # Next steps
        f.write(f"## Next Steps\n\n")
        if winners:
            f.write(f"- Sprint 2: Execution validation (fill model, live spread check)\n")
            f.write(f"- Expand universe if needed\n")
            f.write(f"- Fine-tune winner params\n")
        else:
            f.write(f"- Analyze failure modes (which gates fail most?)\n")
            f.write(f"- Consider relaxing gates or pivoting to different families\n")
            f.write(f"- Check if support zones are generating valid levels\n")

    print(f"[SAVED] {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SuperHF Sprint 1 sweep")
    parser.add_argument("--config", nargs="+", default=None,
                        help="Specific config IDs to run (default: all 12)")
    parser.add_argument("--max-pos", type=int, default=1,
                        help="Max concurrent positions (default: 1)")
    args = parser.parse_args()

    print("=" * 60)
    print("  SuperHF Sprint 1 — MTF Mean Reversion Sweep")
    print("=" * 60)

    # Load data
    data_15m = load_cache("15m")
    data_1h = load_cache("1h")

    # Get common coins
    coins = get_common_coins(data_15m, data_1h)
    print(f"\n[UNIVERSE] {len(coins)} coins with both 15m + 1H data")

    if len(coins) == 0:
        print("[ERROR] No coins with both 15m and 1H data found.")
        sys.exit(1)

    # Build configs
    all_configs = build_all_configs()

    if args.config:
        configs = [h for h in all_configs if h.id in args.config]
        if not configs:
            print(f"[ERROR] No matching configs for: {args.config}")
            print(f"  Available: {[h.id for h in all_configs]}")
            sys.exit(1)
    else:
        configs = all_configs

    print(f"[CONFIGS] Running {len(configs)} configs")

    # Run sweep
    start = time.time()
    results = run_sweep(configs, data_15m, data_1h, coins, max_pos=args.max_pos)
    elapsed = time.time() - start

    # Write scoreboard
    write_scoreboard(results, coins, REPORTS_DIR)

    # Summary
    n_pass = sum(1 for r in results if r.get("gates_pass"))
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {n_pass}/{len(results)} configs PASS all gates")
    print(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
