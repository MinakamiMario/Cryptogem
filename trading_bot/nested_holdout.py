#!/usr/bin/env python3
"""
NESTED HOLDOUT VALIDATION - True Out-of-Sample with Inner Grid Search
=====================================================================
Method:
  1. Outer split: last 20% bars = holdout test, first 80% = development set
  2. Inner loop: 4-fold purged walk-forward on development set only
  3. Select best config by average inner-fold test P&L
  4. Run ALL configs on holdout (true OOS) to validate selection
  5. Gates: trades >= 5, P&L > 0, WR > 40%

Grid: tp_pct x sl_pct x vol_spike_mult = 3x4x3 = 36 configs
      All with exit_type=tp_sl, max_pos=1, rsi_max=45, time_max_bars=15, vol_confirm=True
"""
import sys
import json
import time
import hashlib
from pathlib import Path
from itertools import product

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    START_BAR, KRAKEN_FEE, INITIAL_CAPITAL, cfg_hash
)

UNIVERSES = {
    "TRADEABLE": Path("/Users/oussama/Cryptogem/data/candle_cache_tradeable.json"),
    "LIVE_CURRENT": Path("/Users/oussama/Cryptogem/trading_bot/candle_cache_532.json"),
}
EXPECTED_MD5 = {
    "TRADEABLE": "f6fd2ca303b677fe67ceede4a6b8f7ba",
    "LIVE_CURRENT": "3b1dba2eeb4d95ac68d0874b50de3d4d",
}

TP_PCT_VALUES = [10, 12, 15]
SL_PCT_VALUES = [8, 10, 12, 15]
VOL_SPIKE_VALUES = [2.0, 2.5, 3.0]

FIXED_PARAMS = {
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "time_max_bars": 15,
    "vol_confirm": True,
}

N_INNER_FOLDS = 4
EMBARGO_BARS = 2
OOS_MIN_TRADES = 5
OOS_MIN_PNL = 0
OOS_MIN_WR = 40.0
HOLDOUT_FRACTION = 0.20
REPORTS_DIR = Path("/Users/oussama/Cryptogem/reports")


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_grid():
    configs = []
    for tp, sl, vs in product(TP_PCT_VALUES, SL_PCT_VALUES, VOL_SPIKE_VALUES):
        cfg = dict(FIXED_PARAMS)
        cfg["tp_pct"] = tp
        cfg["sl_pct"] = sl
        cfg["vol_spike_mult"] = vs
        configs.append(cfg)
    return configs


def cfg_label(cfg):
    return "tp%s_sl%s_vs%s" % (cfg["tp_pct"], cfg["sl_pct"], cfg["vol_spike_mult"])


def inner_wf_folds(dev_start, dev_end, n_folds, embargo):
    total_bars = dev_end - dev_start
    segment_size = total_bars // (n_folds + 1)
    folds = []
    for i in range(n_folds):
        train_end = dev_start + (i + 1) * segment_size - embargo
        test_start = dev_start + (i + 1) * segment_size
        test_end = dev_start + (i + 2) * segment_size
        if i == n_folds - 1:
            test_end = dev_end
        if train_end <= dev_start or test_start >= dev_end:
            continue
        folds.append({
            "fold": i + 1,
            "train_start": dev_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "embargo": embargo,
        })
    return folds


def passes_oos_gates(result):
    return (
        result["trades"] >= OOS_MIN_TRADES
        and result["pnl"] > OOS_MIN_PNL
        and result["wr"] >= OOS_MIN_WR
    )


def run_nested_holdout():
    grid = build_grid()
    print("Grid size: %d configs" % len(grid))
    print("Grid: tp_pct=%s, sl_pct=%s, vol_spike_mult=%s" % (
        TP_PCT_VALUES, SL_PCT_VALUES, VOL_SPIKE_VALUES))
    print("Fixed: %s" % FIXED_PARAMS)
    print("Inner WF: %d folds, embargo=%d" % (N_INNER_FOLDS, EMBARGO_BARS))
    print("Holdout: %s" % HOLDOUT_FRACTION)
    print("OOS gates: trades>=%d, P&L>$%d, WR>=%s%%" % (
        OOS_MIN_TRADES, OOS_MIN_PNL, OOS_MIN_WR))
    print()

    REPORTS_DIR.mkdir(exist_ok=True)
    all_results = {}

    for universe_name, cache_path in UNIVERSES.items():
        print("=" * 70)
        print("UNIVERSE: %s" % universe_name)
        print("=" * 70)

        if not cache_path.exists():
            print("  ERROR: Cache not found: %s" % cache_path)
            continue

        md5 = file_md5(cache_path)
        expected = EXPECTED_MD5.get(universe_name, "")
        md5_ok = md5 == expected
        print("  File: %s" % cache_path)
        print("  MD5:  %s %s" % (md5, "OK" if md5_ok else "MISMATCH"))

        with open(cache_path) as f:
            raw_data = json.load(f)

        if isinstance(raw_data, dict) and "data" in raw_data:
            data = raw_data["data"]
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            print("  ERROR: Bad cache format")
            continue

        coins = [p for p in data if not p.startswith("_") and isinstance(data[p], list) and len(data[p]) >= START_BAR + 20]
        print("  Coins: %d" % len(coins))

        bar_counts = [len(data[p]) for p in coins]
        max_bars = max(bar_counts) if bar_counts else 0
        median_bars = sorted(bar_counts)[len(bar_counts) // 2]
        print("  Max bars: %d, Median: %d" % (max_bars, median_bars))

        usable_range = max_bars - START_BAR
        holdout_start = START_BAR + int(usable_range * (1 - HOLDOUT_FRACTION))
        dev_start = START_BAR
        dev_end = holdout_start
        holdout_end = max_bars

        print("  Dev set:  bars [%d, %d) = %d bars" % (dev_start, dev_end, dev_end - dev_start))
        print("  Holdout:  bars [%d, %d) = %d bars" % (holdout_start, holdout_end, holdout_end - holdout_start))

        t0 = time.time()
        indicators = precompute_all(data, coins)
        t_precompute = time.time() - t0
        print("  Precompute: %.1fs" % t_precompute)

        folds = inner_wf_folds(dev_start, dev_end, N_INNER_FOLDS, EMBARGO_BARS)
        print("\n  Inner WF Folds (%d):" % len(folds))
        for fold in folds:
            print("    Fold %d: train [%d, %d) -> test [%d, %d)" % (
                fold["fold"], fold["train_start"], fold["train_end"],
                fold["test_start"], fold["test_end"]))

        # PHASE 1: Inner Grid Search
        print("\n  PHASE 1: Inner Grid Search (%d configs x %d folds)" % (len(grid), len(folds)))
        print("  " + "=" * 60)

        inner_results = {}
        t_inner_start = time.time()

        for ci, cfg in enumerate(grid):
            label = cfg_label(cfg)
            fold_pnls = []
            fold_trades_list = []
            fold_wrs = []
            fold_details = []

            for fold in folds:
                bt = run_backtest(indicators, coins, cfg,
                                  start_bar=fold["test_start"],
                                  end_bar=fold["test_end"])
                fold_pnls.append(bt["pnl"])
                fold_trades_list.append(bt["trades"])
                fold_wrs.append(bt["wr"])
                fold_details.append({
                    "fold": fold["fold"],
                    "pnl": round(bt["pnl"], 2),
                    "trades": bt["trades"],
                    "wr": round(bt["wr"], 1),
                    "dd": round(bt["dd"], 1),
                })

            avg_pnl = sum(fold_pnls) / len(fold_pnls) if fold_pnls else 0
            total_trades = sum(fold_trades_list)
            positive_folds = sum(1 for p in fold_pnls if p > 0)

            inner_results[label] = {
                "cfg": cfg,
                "label": label,
                "avg_pnl": round(avg_pnl, 2),
                "total_inner_trades": total_trades,
                "positive_folds": positive_folds,
                "n_folds": len(folds),
                "fold_details": fold_details,
            }

            if (ci + 1) % 12 == 0 or ci == len(grid) - 1:
                print("    [%d/%d] processed..." % (ci + 1, len(grid)))

        t_inner = time.time() - t_inner_start
        print("  Inner grid: %.1fs" % t_inner)

        ranked = sorted(inner_results.values(), key=lambda x: x["avg_pnl"], reverse=True)

        print("\n  Inner Results (top 10 by avg fold P&L):")
        print("  %-25s %10s %8s %10s" % ("Config", "Avg P&L", "Trades", "PosFolds"))
        print("  %s %s %s %s" % ("-" * 25, "-" * 10, "-" * 8, "-" * 10))
        for r in ranked[:10]:
            print("  %-25s %10.2f %8d %5d/%d" % (
                r["label"], r["avg_pnl"], r["total_inner_trades"],
                r["positive_folds"], r["n_folds"]))

        winner = ranked[0]
        winner_cfg = winner["cfg"]
        winner_label = winner["label"]
        print("\n  INNER WINNER: %s (avg P&L: $%.2f)" % (winner_label, winner["avg_pnl"]))

        # PHASE 2: Holdout
        print("\n  PHASE 2: Holdout Test -- TRUE OOS")
        print("  Window: bars [%d, %d)" % (holdout_start, holdout_end))
        print("  " + "=" * 60)

        holdout_results = {}
        t_holdout_start = time.time()

        for ci, cfg in enumerate(grid):
            label = cfg_label(cfg)
            bt = run_backtest(indicators, coins, cfg,
                              start_bar=holdout_start, end_bar=holdout_end)
            gate_pass = passes_oos_gates(bt)
            pf_val = round(bt["pf"], 2) if bt["pf"] != float("inf") else 999.99
            holdout_results[label] = {
                "cfg": cfg,
                "label": label,
                "pnl": round(bt["pnl"], 2),
                "trades": bt["trades"],
                "wr": round(bt["wr"], 1),
                "dd": round(bt["dd"], 1),
                "pf": pf_val,
                "final_equity": round(bt["final_equity"], 2),
                "gates_pass": gate_pass,
                "gate_details": {
                    "trades_ok": bt["trades"] >= OOS_MIN_TRADES,
                    "pnl_ok": bt["pnl"] > OOS_MIN_PNL,
                    "wr_ok": bt["wr"] >= OOS_MIN_WR,
                },
                "inner_rank": next(
                    (i + 1 for i, r in enumerate(ranked) if r["label"] == label), -1),
                "inner_avg_pnl": inner_results[label]["avg_pnl"],
            }

        t_holdout = time.time() - t_holdout_start

        holdout_ranked = sorted(holdout_results.values(), key=lambda x: x["pnl"], reverse=True)

        print("\n  Holdout Results -- ALL %d configs (by OOS P&L):" % len(grid))
        print("  %3s %-25s %10s %5s %6s %6s %7s %6s %7s" % (
            "#", "Config", "OOS P&L", "Tr", "WR%", "DD%", "PF", "Gates", "Inner#"))
        print("  %s %s %s %s %s %s %s %s %s" % (
            "-" * 3, "-" * 25, "-" * 10, "-" * 5, "-" * 6, "-" * 6,
            "-" * 7, "-" * 6, "-" * 7))
        for i, r in enumerate(holdout_ranked):
            marker = " <<< SEL" if r["label"] == winner_label else ""
            gate_str = "PASS" if r["gates_pass"] else "FAIL"
            print("  %3d %-25s %10.2f %5d %6.1f %6.1f %7.2f %6s %7d%s" % (
                i + 1, r["label"], r["pnl"], r["trades"],
                r["wr"], r["dd"], r["pf"], gate_str,
                r["inner_rank"], marker))

        winner_oos = holdout_results[winner_label]
        actual_best = holdout_ranked[0]

        print("\n  SELECTION ANALYSIS:")
        print("    Selected:    %s" % winner_label)
        print("    Sel OOS P&L: $%.2f (tr=%d, WR=%.1f%%)" % (
            winner_oos["pnl"], winner_oos["trades"], winner_oos["wr"]))
        print("    Sel gates:   %s" % ("PASS" if winner_oos["gates_pass"] else "FAIL"))
        print("    Best OOS:    %s" % actual_best["label"])
        print("    Best OOS P&L: $%.2f (tr=%d, WR=%.1f%%)" % (
            actual_best["pnl"], actual_best["trades"], actual_best["wr"]))
        selection_optimal = winner_label == actual_best["label"]
        print("    Optimal?     %s" % ("YES" if selection_optimal else "NO"))
        if not selection_optimal:
            oos_rank = next(
                (i + 1 for i, r in enumerate(holdout_ranked)
                 if r["label"] == winner_label), -1)
            print("    Sel OOS rank: %d/%d" % (oos_rank, len(grid)))

        passing = [r for r in holdout_ranked if r["gates_pass"]]
        print("\n  Passing OOS gates: %d/%d" % (len(passing), len(grid)))
        if passing:
            print("  Best passing: %s (P&L=$%.2f)" % (passing[0]["label"], passing[0]["pnl"]))

        all_results[universe_name] = {
            "cache_file": str(cache_path),
            "md5": md5,
            "md5_verified": md5_ok,
            "n_coins": len(coins),
            "max_bars": max_bars,
            "median_bars": median_bars,
            "dev_range": [dev_start, dev_end],
            "holdout_range": [holdout_start, holdout_end],
            "inner_folds": folds,
            "inner_winner": {
                "label": winner_label,
                "cfg": winner_cfg,
                "avg_inner_pnl": winner["avg_pnl"],
                "positive_folds": winner["positive_folds"],
                "n_folds": winner["n_folds"],
                "fold_details": winner["fold_details"],
            },
            "inner_rankings": [
                {
                    "rank": i + 1,
                    "label": r["label"],
                    "avg_pnl": r["avg_pnl"],
                    "total_trades": r["total_inner_trades"],
                    "positive_folds": r["positive_folds"],
                }
                for i, r in enumerate(ranked)
            ],
            "holdout_results": [
                {
                    "oos_rank": i + 1,
                    "label": r["label"],
                    "cfg": r["cfg"],
                    "pnl": r["pnl"],
                    "trades": r["trades"],
                    "wr": r["wr"],
                    "dd": r["dd"],
                    "pf": r["pf"],
                    "gates_pass": r["gates_pass"],
                    "gate_details": r["gate_details"],
                    "inner_rank": r["inner_rank"],
                    "inner_avg_pnl": r["inner_avg_pnl"],
                }
                for i, r in enumerate(holdout_ranked)
            ],
            "selection_analysis": {
                "inner_selected": winner_label,
                "inner_selected_oos_pnl": winner_oos["pnl"],
                "inner_selected_oos_trades": winner_oos["trades"],
                "inner_selected_gates_pass": winner_oos["gates_pass"],
                "best_oos_config": actual_best["label"],
                "best_oos_pnl": actual_best["pnl"],
                "selection_optimal": selection_optimal,
                "n_passing_gates": len(passing),
            },
            "timing": {
                "precompute_s": round(t_precompute, 1),
                "inner_grid_s": round(t_inner, 1),
                "holdout_s": round(t_holdout, 1),
            },
        }

    json_path = REPORTS_DIR / "nested_holdout.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print("\nJSON: %s" % json_path)

    md_path = REPORTS_DIR / "nested_holdout.md"
    md = generate_markdown(all_results)
    with open(md_path, "w") as f:
        f.write(md)
    print("MD:   %s" % md_path)

    return all_results


def generate_markdown(all_results):
    lines = [
        "# Nested Holdout Validation Report",
        "",
        "## Method",
        "",
        "- **Outer split**: Last 20%% of bars = holdout test (true OOS). First 80%% = development set.",
        "- **Inner loop**: 4-fold purged walk-forward on development set only (embargo=2 bars).",
        "- **Selection**: Config with highest average inner-fold test P&L.",
        "- **Validation**: All configs run on holdout to verify selection quality.",
        "- **Grid**: 3x4x3 = 36 configs (tp_pct=%s, sl_pct=%s, vol_spike_mult=%s)" % (
            TP_PCT_VALUES, SL_PCT_VALUES, VOL_SPIKE_VALUES),
        "- **Fixed params**: exit_type=tp_sl, max_pos=1, rsi_max=45, time_max_bars=15, vol_confirm=True",
        "- **OOS Gates**: trades >= %d, P&L > $%d, WR >= %.1f%%" % (
            OOS_MIN_TRADES, OOS_MIN_PNL, OOS_MIN_WR),
        "",
    ]

    for uname, res in all_results.items():
        lines.extend([
            "## Universe: %s" % uname,
            "",
            "- **Coins**: %d" % res["n_coins"],
            "- **Max bars**: %d (median: %d)" % (res["max_bars"], res["median_bars"]),
            "- **MD5 verified**: %s" % res["md5_verified"],
            "- **Dev set**: bars [%d, %d) = %d bars" % (
                res["dev_range"][0], res["dev_range"][1],
                res["dev_range"][1] - res["dev_range"][0]),
            "- **Holdout**: bars [%d, %d) = %d bars" % (
                res["holdout_range"][0], res["holdout_range"][1],
                res["holdout_range"][1] - res["holdout_range"][0]),
            "",
            "### Inner Walk-Forward Folds",
            "",
        ])
        for fold in res["inner_folds"]:
            lines.append("- Fold %d: train [%d, %d) -> test [%d, %d)" % (
                fold["fold"], fold["train_start"], fold["train_end"],
                fold["test_start"], fold["test_end"]))
        lines.append("")

        iw = res["inner_winner"]
        lines.extend([
            "### Inner Grid Search Winner",
            "",
            "- **Config**: `%s`" % iw["label"],
            "- **Avg inner-fold P&L**: $%.2f" % iw["avg_inner_pnl"],
            "- **Positive folds**: %d/%d" % (iw["positive_folds"], iw["n_folds"]),
            "",
            "| Fold | P&L | Trades | WR |",
            "|------|-----|--------|-----|",
        ])
        for fd in iw["fold_details"]:
            lines.append("| %d | $%.2f | %d | %.1f%% |" % (
                fd["fold"], fd["pnl"], fd["trades"], fd["wr"]))
        lines.append("")

        lines.extend([
            "### Inner Rankings (top 10)",
            "",
            "| # | Config | Avg P&L | Trades | PosFolds |",
            "|---|--------|---------|--------|----------|",
        ])
        for r in res["inner_rankings"][:10]:
            lines.append("| %d | %s | $%.2f | %d | %d/%d |" % (
                r["rank"], r["label"], r["avg_pnl"],
                r["total_trades"], r["positive_folds"], N_INNER_FOLDS))
        lines.append("")

        lines.extend([
            "### Holdout Results (TRUE OOS)",
            "",
            "| # | Config | OOS P&L | Tr | WR | DD | PF | Gates | Inner# |",
            "|---|--------|---------|----|----|----|----|-------|--------|",
        ])
        for r in res["holdout_results"]:
            sel = " **SEL**" if r["label"] == res["inner_winner"]["label"] else ""
            gs = "PASS" if r["gates_pass"] else "FAIL"
            lines.append("| %d | %s%s | $%.2f | %d | %.1f%% | %.1f%% | %.2f | %s | %d |" % (
                r["oos_rank"], r["label"], sel, r["pnl"], r["trades"],
                r["wr"], r["dd"], r["pf"], gs, r["inner_rank"]))
        lines.append("")

        sa = res["selection_analysis"]
        lines.extend([
            "### Selection Analysis",
            "",
            "- **Selected**: `%s`" % sa["inner_selected"],
            "- **Sel OOS P&L**: $%.2f (trades=%d)" % (
                sa["inner_selected_oos_pnl"], sa["inner_selected_oos_trades"]),
            "- **Sel gates**: %s" % ("PASS" if sa["inner_selected_gates_pass"] else "FAIL"),
            "- **Best OOS**: `%s` ($%.2f)" % (sa["best_oos_config"], sa["best_oos_pnl"]),
            "- **Optimal**: %s" % ("YES" if sa["selection_optimal"] else "NO"),
            "- **Passing gates**: %d/%d" % (sa["n_passing_gates"], len(res["holdout_results"])),
            "",
            "### Timing",
            "",
            "- Precompute: %.1fs" % res["timing"]["precompute_s"],
            "- Inner grid: %.1fs" % res["timing"]["inner_grid_s"],
            "- Holdout: %.1fs" % res["timing"]["holdout_s"],
            "",
        ])

    lines.extend(["## Verdict", ""])
    for uname, res in all_results.items():
        sa = res["selection_analysis"]
        v = "PASS" if sa["inner_selected_gates_pass"] else "FAIL"
        lines.append("### %s: **%s**" % (uname, v))
        lines.append("")
        if sa["inner_selected_gates_pass"]:
            lines.append("Selected `%s` passes OOS gates (P&L=$%.2f)." % (
                sa["inner_selected"], sa["inner_selected_oos_pnl"]))
        else:
            lines.append("Selected `%s` FAILS OOS gates (P&L=$%.2f)." % (
                sa["inner_selected"], sa["inner_selected_oos_pnl"]))
        if sa["selection_optimal"]:
            lines.append("Inner selection correctly identified the best OOS config.")
        else:
            lines.append("Inner selection did NOT find best OOS. Best was `%s` ($%.2f)." % (
                sa["best_oos_config"], sa["best_oos_pnl"]))
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print("NESTED HOLDOUT VALIDATION")
    print("=" * 70)
    t_total = time.time()
    results = run_nested_holdout()
    elapsed = time.time() - t_total
    print("\nTotal: %.1fs (%.1fmin)" % (elapsed, elapsed / 60))
