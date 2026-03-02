#!/usr/bin/env python3
"""
run_superhf_sprint3.py — SuperHF Sprint 3 sweep runner.

Runs all 20 Sprint 3 configs (5 families, 3 tracks) through the
SuperHF harness, applies screening gates, generates scoreboard + coin
contribution.

Tracks:
  Track 1 (Family F): VWAP Deviation on 15m (6 configs)
  Track 2 (Families C/D/E): 1H Entry + 15m Timing (10 configs)
  Track 3 (Family G): DC-Geometry + VWAP Hybrid (4 configs)

Usage:
    python3 scripts/run_superhf_sprint3.py
    python3 scripts/run_superhf_sprint3.py --config SHF-F01 SHF-G01
    python3 scripts/run_superhf_sprint3.py --max-pos 2
    python3 scripts/run_superhf_sprint3.py --track 3
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

from strategies.superhf.hypotheses_s3 import build_all_configs, REGISTRY
from strategies.superhf.harness import run_backtest, walk_forward, START_BAR

DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
REPORTS_DIR = ROOT / "reports" / "superhf"

# MEXC fee: 0% maker, 10bps taker → conservative: 10bps/side
MEXC_FEE = 0.001

# Track → family mapping
TRACK_FAMILIES = {
    1: {"vwap_deviation"},
    2: {"pivot_reclaim_dcgeo", "dc_low_reclaim", "vol_capitulation_15m"},
    3: {"dcgeo_vwap_hybrid"},
}


# ---------------------------------------------------------------------------
# Data loading (shared with Sprint 1)
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
# Screening gates (Sprint 3 gates — relaxed for R&D)
# ---------------------------------------------------------------------------

def apply_gates(result, wf_results: list, config_id: str, n_coins: int) -> dict:
    """Apply Sprint 3 screening gates. Returns gate results.

    Sprint 3 gates are deliberately relaxed (R&D phase):
    - Trades ≥ 80 (same as Sprint 1)
    - PF ≥ 1.0 (KILL gate — was ≥ 1.10 in Sprint 1)
    - WF 2/3 (same)
    - Concentration (same)
    """
    gates = {}

    # Gate 1: trades ≥ 80
    gates["S1_trades"] = {
        "pass": result.trades >= 80,
        "value": result.trades,
        "threshold": 80,
    }

    # Gate 2: PF ≥ 1.0 (KILL — any signal with PF < 1.0 is structurally broken)
    gates["S2_pf"] = {
        "pass": result.pf >= 1.0,
        "value": round(result.pf, 3),
        "threshold": 1.0,
    }

    # Gate 2b: PF ≥ 1.10 (soft — needed for Phase 2 entry)
    gates["S2b_pf_soft"] = {
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
            "threshold": "trades≤50% AND pnl≤70%",
        }
    else:
        gates["S4_concentration"] = {
            "pass": False,
            "value": "no trades",
        }

    # Overall: S2_pf is the KILL gate (PF ≥ 1.0)
    hard_gates = ["S1_trades", "S2_pf"]
    gates["_overall"] = all(gates[g].get("pass", False) for g in hard_gates)

    # Phase 2 eligible: ALL gates pass including soft PF ≥ 1.10
    gates["_phase2_eligible"] = all(
        g.get("pass", False) for k, g in gates.items() if not k.startswith("_")
    )

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
            "params": {k: v for k, v in hyp.params.items()
                       if not k.startswith("_")},  # exclude internal keys
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
            "phase2_eligible": gates["_phase2_eligible"],
            "exit_breakdown": exit_breakdown,
            "top10_coins": coin_table[:10],
            "elapsed_s": round(elapsed, 1),
        }

        # Print summary
        gate_str = "✅ PASS" if gates["_overall"] else "❌ FAIL"
        p2_str = "🟢 Phase2" if gates["_phase2_eligible"] else ""
        print(f"  → Trades={result.trades} PF={result.pf:.3f} P&L=${result.pnl:.0f} "
              f"WR={result.wr:.1f}% DD={result.dd:.1f}%")
        print(f"  → WF: {entry['wf_pass']}/3 | Gates: {gate_str} {p2_str}")
        for gname, gdata in gates.items():
            if gname.startswith("_"):
                continue
            status = "✅" if gdata.get("pass") else "❌"
            print(f"    {status} {gname}: {gdata.get('value', gdata)}")
        if exit_breakdown:
            print(f"  → Exit breakdown:")
            for reason, stats in sorted(exit_breakdown.items(),
                                         key=lambda x: x[1]['count'], reverse=True):
                pct = stats['count'] / result.trades * 100 if result.trades else 0
                print(f"    {reason}: {stats['count']} ({pct:.0f}%) "
                      f"WR={stats['wr']:.0f}% P&L=${stats['pnl']:.0f}")
        print(f"  → Time: {elapsed:.1f}s")

        results.append(entry)

    return results


def write_scoreboard(results: list[dict], coins: list[str], output_dir: Path):
    """Write scoreboard JSON and MD."""
    output_dir.mkdir(parents=True, exist_ok=True)

    results_sorted = sorted(results, key=lambda x: x.get("pf", 0), reverse=True)

    # JSON
    n_pass = sum(1 for r in results if r.get("gates_pass"))
    n_p2 = sum(1 for r in results if r.get("phase2_eligible"))

    report = {
        "_timestamp": int(time.time()),
        "_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "_sprint": "sprint3",
        "_universe": "superhf_mexc_top200",
        "_coins_tested": len(coins),
        "_configs_total": len(results),
        "_configs_pf_gte_1": n_pass,
        "_configs_phase2_eligible": n_p2,
        "_tracks": {
            "track1_vwap": sum(1 for r in results
                               if r["family"] == "vwap_deviation"),
            "track2_1h_entry": sum(1 for r in results
                                   if r["family"] in TRACK_FAMILIES[2]),
            "track3_hybrid": sum(1 for r in results
                                  if r["family"] == "dcgeo_vwap_hybrid"),
        },
        "results": results_sorted,
    }

    json_path = output_dir / "sprint3_scoreboard.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\n[SAVED] {json_path}")

    # Markdown
    md_path = output_dir / "sprint3_scoreboard.md"
    with open(md_path, "w") as f:
        f.write(f"# SuperHF Sprint 3 — Scoreboard\n\n")
        f.write(f"**Date**: {report['_date']}\n")
        f.write(f"**Universe**: {report['_universe']} ({report['_coins_tested']} coins)\n")
        f.write(f"**Configs**: {report['_configs_total']} total, "
                f"**{n_pass} PF≥1.0**, **{n_p2} Phase2-eligible**\n\n")

        # Track summary
        f.write(f"## Track Summary\n\n")
        for track_num, families in TRACK_FAMILIES.items():
            track_results = [r for r in results_sorted if r["family"] in families]
            t_pass = sum(1 for r in track_results if r.get("gates_pass"))
            best_pf = max((r["pf"] for r in track_results), default=0)
            f.write(f"- **Track {track_num}**: {len(track_results)} configs, "
                    f"{t_pass} pass PF≥1.0, best PF={best_pf:.3f}\n")
        f.write(f"\n")

        # Full results table
        f.write(f"## Results\n\n")
        f.write(f"| # | Config | Family | Trades | PF | P&L | WR | DD | WF | Gates | P2 |\n")
        f.write(f"|---|--------|--------|-------:|---:|----:|---:|---:|---:|-------|----|\n")
        for i, r in enumerate(results_sorted):
            gate_str = "✅" if r.get("gates_pass") else "❌"
            p2_str = "🟢" if r.get("phase2_eligible") else ""
            f.write(f"| {i+1} | {r['config_id']} | {r['family'][:15]} | "
                    f"{r['trades']} | {r['pf']:.2f} | ${r['pnl']:.0f} | "
                    f"{r['wr']:.1f}% | {r['dd']:.1f}% | "
                    f"{r['wf_pass']}/3 | {gate_str} | {p2_str} |\n")

        # Exit attribution
        f.write(f"\n## Exit Attribution (all configs)\n\n")
        all_exits = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        for r in results:
            for reason, stats in r.get("exit_breakdown", {}).items():
                all_exits[reason]["count"] += stats["count"]
                all_exits[reason]["pnl"] += stats["pnl"]
                wr = stats["wr"]
                wins = int(stats["count"] * wr / 100)
                all_exits[reason]["wins"] += wins

        total_exits = sum(e["count"] for e in all_exits.values())
        if total_exits > 0:
            f.write(f"| Exit | Count | % | P&L | WR |\n")
            f.write(f"|------|------:|---:|----:|----|\n")
            for reason, e in sorted(all_exits.items(),
                                     key=lambda x: x[1]["count"], reverse=True):
                pct = e["count"] / total_exits * 100
                wr = e["wins"] / e["count"] * 100 if e["count"] else 0
                f.write(f"| {reason} | {e['count']} | {pct:.0f}% | "
                        f"${e['pnl']:.0f} | {wr:.0f}% |\n")

        # Winners
        winners = [r for r in results_sorted if r.get("gates_pass")]
        f.write(f"\n## Winners (PF ≥ 1.0)\n\n")
        if winners:
            for w in winners:
                f.write(f"### {w['config_id']}: {w['description']}\n")
                f.write(f"- PF={w['pf']:.3f}, Trades={w['trades']}, P&L=${w['pnl']:.0f}\n")
                f.write(f"- WR={w['wr']:.1f}%, DD={w['dd']:.1f}%\n")
                f.write(f"- WF: {w['wf_pass']}/3\n")
                p2 = "✅ eligible" if w.get("phase2_eligible") else "❌ not eligible"
                f.write(f"- Phase 2: {p2}\n")
                f.write(f"- Exit breakdown:\n")
                for reason, stats in sorted(w.get("exit_breakdown", {}).items(),
                                             key=lambda x: x[1]['count'], reverse=True):
                    f.write(f"  - {reason}: {stats['count']} trades, "
                            f"WR={stats['wr']:.0f}%, P&L=${stats['pnl']:.0f}\n")
                f.write(f"- Top 5 coins:\n")
                for c in w.get('top10_coins', [])[:5]:
                    f.write(f"  - {c['coin']}: {c['trades']} trades, ${c['pnl']:.0f}, "
                            f"WR={c['wr']:.0f}%\n")
                f.write(f"\n")
        else:
            f.write(f"**No configs passed PF ≥ 1.0.**\n\n")

        # Decision
        f.write(f"## GO/NO-GO Decision\n\n")
        if n_pass == 0:
            f.write(f"**🛑 NO-GO: 0/{len(results)} configs PF ≥ 1.0.**\n")
            f.write(f"SuperHF CLOSED. Pivot to:\n")
            f.write(f"1. HF VWAP_DEV paper trading (CONDITIONAL GO, PF=2.86 maker)\n")
            f.write(f"2. 4H Vol Capitulation 041 (VERIFIED, PF=1.41)\n")
        elif n_p2 > 0:
            f.write(f"**🟢 GO: {n_p2} configs Phase 2 eligible.**\n")
            f.write(f"Next: Signal hardening → truth-pass → DD reduction → OOS.\n")
        else:
            f.write(f"**🟡 CONDITIONAL: {n_pass} configs PF ≥ 1.0 but 0 Phase 2 eligible.**\n")
            f.write(f"Review individual configs for potential improvement.\n")

    print(f"[SAVED] {md_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SuperHF Sprint 3 sweep")
    parser.add_argument("--config", nargs="+", default=None,
                        help="Specific config IDs to run (default: all 20)")
    parser.add_argument("--max-pos", type=int, default=1,
                        help="Max concurrent positions (default: 1)")
    parser.add_argument("--track", type=int, default=None, choices=[1, 2, 3],
                        help="Run only a specific track (1, 2, or 3)")
    args = parser.parse_args()

    print("=" * 60)
    print("  SuperHF Sprint 3 — Signal R&D Sweep")
    print("  3 Tracks × 5 Families × 20 Configs")
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
    elif args.track:
        families = TRACK_FAMILIES[args.track]
        configs = [h for h in all_configs if h.family in families]
        print(f"[TRACK] Running Track {args.track} only: {len(configs)} configs")
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
    n_p2 = sum(1 for r in results if r.get("phase2_eligible"))

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {n_pass}/{len(results)} configs PF ≥ 1.0")
    print(f"           {n_p2}/{len(results)} Phase 2 eligible")

    # Per-track breakdown
    for track_num, families in TRACK_FAMILIES.items():
        track_results = [r for r in results if r["family"] in families]
        if not track_results:
            continue
        t_pass = sum(1 for r in track_results if r.get("gates_pass"))
        best = max(track_results, key=lambda x: x["pf"])
        print(f"  Track {track_num}: {t_pass}/{len(track_results)} pass | "
              f"best={best['config_id']} PF={best['pf']:.3f}")

    print(f"  Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # GO/NO-GO
    if n_pass == 0:
        print(f"\n  🛑 NO-GO: SuperHF CLOSED — pivot to HF VWAP_DEV or 4H VolCap")
    elif n_p2 > 0:
        print(f"\n  🟢 GO: {n_p2} configs ready for Phase 2 hardening")
    else:
        print(f"\n  🟡 CONDITIONAL: review needed")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
