#!/usr/bin/env python3
"""
Part 2 -- 2D Parameter Grid on 135-coin subset (Agent A6)
=========================================================
Tests combos of (tp_pct, sl_pct, time_limit) with dev_thresh=2.0 fixed
on the ORIGINAL 135-coin subset (first 135 alphabetically from T1+T2 with data).

Goal: find configs where fold_concentration < 35% AND exp/week > 0 AND WF >= 4/5.

Also diagnoses: is fold dominance structural (always the same fold)?

Output: reports/hf/part2_param_grid_135_001.json + .md
"""
import sys
import json
import time
import os
import subprocess
from pathlib import Path
from datetime import datetime
from itertools import product
from copy import deepcopy

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

BARS_PER_WEEK = 168
TP_VALUES = [6, 8, 10, 12]
SL_VALUES = [3, 4, 5, 7]
TL_VALUES = [6, 8, 10]
DEV_THRESH = 2.0
FOLD_CONC_TARGET = 0.35


def load_data_from_parts(timeframe="1h"):
    cache_path = ROOT / "data" / f"candle_cache_{timeframe}.json"
    if cache_path.exists():
        print(f"[Load] Reading merged cache {cache_path.name}...")
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith("_")}
        print(f"[Load] {len(coins_data)} coins loaded (merged)")
        return coins_data
    parts_base = ROOT / "data" / "cache_parts_hf" / timeframe
    if not parts_base.exists():
        print("[ERROR] No cache found")
        sys.exit(1)
    manifest_path = ROOT / "data" / f"manifest_hf_{timeframe}.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    coins_data = {}
    for exchange_dir in sorted(parts_base.iterdir()):
        if not exchange_dir.is_dir():
            continue
        for coin_file in sorted(exchange_dir.glob("*.json")):
            symbol = coin_file.stem.replace("_", "/")
            if manifest and symbol in manifest:
                if manifest[symbol].get("status") != "done":
                    continue
            with open(coin_file) as f:
                candles = json.load(f)
            if len(candles) >= 30:
                coins_data[symbol] = candles
    if not coins_data:
        print("[ERROR] No coins loaded from part files.")
        sys.exit(1)
    print(f"[Load] {len(coins_data)} coins loaded (from part files)")
    return coins_data


def load_universe_tiering():
    tiering_path = ROOT / "reports" / "hf" / "universe_tiering_001.json"
    if not tiering_path.exists():
        print(f"[ERROR] Tiering not found: {tiering_path}")
        sys.exit(1)
    with open(tiering_path) as f:
        tiering = json.load(f)
    return tiering


def build_135_coin_subset(tiering, available_coins):
    tb = tiering.get("tier_breakdown", {})
    t1_coins = set(tb.get("1", {}).get("coins", []))
    t2_coins = set(tb.get("2", {}).get("coins", []))
    all_t1t2 = sorted(t1_coins | t2_coins)
    with_data = [c for c in all_t1t2 if c in available_coins]
    first_135 = with_data[:135]
    tier_map = {}
    for c in first_135:
        tier_map[c] = "tier1" if c in t1_coins else "tier2"
    tier_coins = {
        "tier1": [c for c in first_135 if tier_map[c] == "tier1"],
        "tier2": [c for c in first_135 if tier_map[c] == "tier2"],
    }
    return first_135, tier_coins, tier_map


def run_variant(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee):
    signal_params = {k: v for k, v in params.items() if k != "label"}
    enriched_params = {**signal_params, "__market__": market_context}
    all_trades = []
    tier_fees = {"tier1": tier1_fee, "tier2": tier2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees[tier_name]
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched_params, indicators=indicators, fee=fee, max_pos=1,
        )
        for t in bt.trade_list:
            t["_tier"] = tier_name
            t["_fee_per_side"] = fee
        all_trades.extend(bt.trade_list)
    return all_trades


def run_walk_forward_variant(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee, n_folds=5):
    signal_params = {k: v for k, v in params.items() if k != "label"}
    enriched_params = {**signal_params, "__market__": market_context}
    tier_fold_trades = {}
    tier_fees = {"tier1": tier1_fee, "tier2": tier2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees[tier_name]
        indicators = tier_indicators.get(tier_name, {})
        fold_results = walk_forward(
            data=data, coins=coins, signal_fn=signal_h20_vwap_deviation,
            params=enriched_params, indicators=indicators, n_folds=n_folds,
            fee=fee, max_pos=1,
        )
        for fold_idx, fold_bt in enumerate(fold_results):
            if fold_idx not in tier_fold_trades:
                tier_fold_trades[fold_idx] = []
            for t in fold_bt.trade_list:
                t["_tier"] = tier_name
                t["_fee_per_side"] = fee
            tier_fold_trades[fold_idx].extend(fold_bt.trade_list)
    return tier_fold_trades


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    n_trades = len(trades)
    if n_trades == 0:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
                "expectancy": 0.0, "trades_per_week": 0.0, "exp_per_week": 0.0, "fee_drag_pct": 0.0}
    total_pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins) / n_trades * 100
    tw = sum(t["pnl"] for t in wins)
    tl = abs(sum(t["pnl"] for t in losses))
    pf = tw / tl if tl > 0 else (float("inf") if tw > 0 else 0.0)
    expectancy = total_pnl / n_trades
    total_weeks = total_bars / BARS_PER_WEEK if total_bars and total_bars > 0 else 1.0
    trades_per_week = n_trades / total_weeks
    exp_per_week = expectancy * trades_per_week
    total_fees = 0.0
    gross_profit = 0.0
    for t in trades:
        size = t.get("size", 0)
        entry = t.get("entry", 0)
        exit_p = t.get("exit", 0)
        fee = t.get("_fee_per_side", 0.0005)
        if entry > 0 and size > 0:
            gross = (exit_p - entry) / entry * size
            fees = size * fee + (size + gross) * fee
            total_fees += fees
            if gross > 0:
                gross_profit += gross
    fee_drag_pct = total_fees / gross_profit * 100 if gross_profit > 0 else 100.0
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.get("entry_bar", 0)):
        equity += t["pnl"]
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return {"trades": n_trades, "pnl": round(total_pnl, 2), "pf": round(pf, 3),
            "wr": round(wr, 2), "dd": round(max_dd, 2), "expectancy": round(expectancy, 4),
            "trades_per_week": round(trades_per_week, 2), "exp_per_week": round(exp_per_week, 4),
            "fee_drag_pct": round(fee_drag_pct, 2)}


def compute_fold_concentration(fold_trades, n_folds=5):
    fold_pnls = []
    fold_trade_counts = []
    fold_details = []
    for fold_idx in range(n_folds):
        trades = fold_trades.get(fold_idx, [])
        pnl = sum(t["pnl"] for t in trades)
        fold_pnls.append(pnl)
        fold_trade_counts.append(len(trades))
        fold_details.append({"fold": fold_idx, "trades": len(trades), "pnl": round(pnl, 2), "positive": pnl > 0})
    folds_positive = sum(1 for p in fold_pnls if p > 0)
    positive_pnls = [p for p in fold_pnls if p > 0]
    total_positive = sum(positive_pnls)
    if total_positive > 0:
        max_fold_pnl = max(positive_pnls)
        fold_concentration = max_fold_pnl / total_positive
    else:
        fold_concentration = 1.0
    dominant_fold = fold_pnls.index(max(fold_pnls))
    return {"fold_pnls": [round(p, 2) for p in fold_pnls], "fold_trade_counts": fold_trade_counts,
            "folds_positive": folds_positive, "fold_concentration": round(fold_concentration, 4),
            "dominant_fold": dominant_fold, "fold_details": fold_details}


def composite_score(exp_per_week, wf_folds_positive, trades, fold_conc, n_folds=5):
    if exp_per_week <= 0:
        return 0.0
    wf_factor = wf_folds_positive / n_folds
    trade_factor = min(1.0, trades / 50)
    conc_penalty = max(0.0, 1.0 - fold_conc)
    return exp_per_week * wf_factor * trade_factor * conc_penalty


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            ind = indicators.get(coin, {})
            n = ind.get("n", 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def build_grid():
    grid = []
    for tp, sl, tl in product(TP_VALUES, SL_VALUES, TL_VALUES):
        grid.append({"dev_thresh": DEV_THRESH, "tp_pct": tp, "sl_pct": sl,
                     "time_limit": tl, "label": f"tp{tp}_sl{sl}_tl{tl}"})
    return grid


def main():
    print("=" * 70)
    print("  Part 2 -- 2D Parameter Grid on 135-coin Subset (Agent A6)")
    print("  Goal: Find fold_concentration < 35% with positive exp/week")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    t0 = time.time()

    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT)).decode().strip()
    except Exception:
        commit = "unknown"

    tier1_fee = get_harness_fee("mexc_market", "tier1")
    tier2_fee = get_harness_fee("mexc_market", "tier2")
    print(f"[Costs] MEXC Market: T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps")

    data = load_data_from_parts("1h")
    available_coins = set(data.keys())
    tiering = load_universe_tiering()
    all_135, tier_coins, tier_map = build_135_coin_subset(tiering, available_coins)
    n_t1 = len(tier_coins["tier1"])
    n_t2 = len(tier_coins["tier2"])
    print(f"[Universe] 135-coin subset: T1={n_t1}, T2={n_t2}")
    print(f"  First 5: {all_135[:5]}")
    print(f"  Last 5:  {all_135[-5:]}")

    grid = build_grid()
    print(f"[Grid] {len(grid)} parameter combos")

    print("[Indicators] Precomputing base indicators...")
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f"  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s")

    print("[Indicators] Extending with VWAP...")
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            print(f"  {tier_name}: VWAP {cov['vwap_pct']:.0f}% ({cov['vwap_available']}/{cov['total_coins']})")

    print("[Market Context] Precomputing...")
    all_coins_for_mc = list(set(all_135))
    for btc_candidate in ("BTC/USD", "XBT/USD", "BTC/USDT"):
        if btc_candidate in available_coins and btc_candidate not in all_coins_for_mc:
            all_coins_for_mc.append(btc_candidate)
    market_context = precompute_market_context(data, all_coins_for_mc)
    print("  Done.")

    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]["__coin__"] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f"[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}")

    print(f"\n--- Running {len(grid)} combos (baseline + WF5) ---")
    header = f"{'#':>3s}  {'Label':18s}  Tr  PF     WR%   Exp/Wk   DD%   WF  FoldConc  DomF  Score"
    print(header)
    print("-" * len(header))

    variant_results = []
    dominant_fold_tally = {}

    for var_idx, params in enumerate(grid):
        t_var = time.time()
        trades = run_variant(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee)
        metrics = compute_metrics(trades, initial_capital=2000.0, total_bars=total_bars)
        fold_trades = run_walk_forward_variant(params, data, tier_coins, tier_indicators, market_context, tier1_fee, tier2_fee, n_folds=5)
        fold_info = compute_fold_concentration(fold_trades, n_folds=5)
        score = composite_score(metrics["exp_per_week"], fold_info["folds_positive"], metrics["trades"], fold_info["fold_concentration"])
        dom_fold = fold_info["dominant_fold"]
        dominant_fold_tally[dom_fold] = dominant_fold_tally.get(dom_fold, 0) + 1
        passes_g8 = (fold_info["fold_concentration"] < FOLD_CONC_TARGET and metrics["exp_per_week"] > 0 and fold_info["folds_positive"] >= 4)
        elapsed_var = time.time() - t_var
        result = {"variant_idx": var_idx, "label": params["label"],
                  "params": {k: v for k, v in params.items() if k != "label"},
                  "metrics": metrics, "fold_info": fold_info,
                  "composite_score": round(score, 6), "passes_g8": passes_g8,
                  "elapsed_s": round(elapsed_var, 1)}
        variant_results.append(result)
        g8_flag = " ***G8***" if passes_g8 else ""
        print(f"{var_idx:3d}  {params['label']:18s}  {metrics['trades']:2d}  {metrics['pf']:5.3f}  {metrics['wr']:4.1f}  ${metrics['exp_per_week']:7.2f}  {metrics['dd']:4.1f}  {fold_info['folds_positive']}/5  {fold_info['fold_concentration']:6.1%}     F{dom_fold}    {score:5.4f}{g8_flag}")

    elapsed_total = time.time() - t0

    print(f"\n--- Dominant Fold Analysis ---")
    for fold_idx in sorted(dominant_fold_tally.keys()):
        count = dominant_fold_tally[fold_idx]
        pct = count / len(grid) * 100
        print(f"  Fold {fold_idx}: dominant in {count}/{len(grid)} combos ({pct:.0f}%)")

    g8_passers = [vr for vr in variant_results if vr["passes_g8"]]
    print(f"\n--- G8 Passers (fold_conc < {FOLD_CONC_TARGET:.0%} AND exp/wk > 0 AND WF >= 4/5) ---")
    if g8_passers:
        for vr in sorted(g8_passers, key=lambda x: x["composite_score"], reverse=True):
            m = vr["metrics"]; fi = vr["fold_info"]
            print(f"  {vr['label']:18s}  trades={m['trades']}  PF={m['pf']:.3f}  exp/wk=${m['exp_per_week']:.2f}  WF={fi['folds_positive']}/5  fold_conc={fi['fold_concentration']:.1%}  score={vr['composite_score']:.4f}")
    else:
        print("  NONE -- no config passes all G8 criteria on 135 coins")

    ranked = sorted(variant_results, key=lambda x: x["composite_score"], reverse=True)
    print(f"\n--- Top 5 by Composite Score ---")
    for i, vr in enumerate(ranked[:5]):
        m = vr["metrics"]; fi = vr["fold_info"]
        print(f"  #{i+1} {vr['label']:18s}  score={vr['composite_score']:.4f}  trades={m['trades']}  PF={m['pf']:.3f}  exp/wk=${m['exp_per_week']:.2f}  WF={fi['folds_positive']}/5  fold_conc={fi['fold_concentration']:.1%}")

    profitable = [vr for vr in variant_results if vr["metrics"]["exp_per_week"] > 0]
    if profitable:
        best_conc = sorted(profitable, key=lambda x: x["fold_info"]["fold_concentration"])
        print(f"\n--- Lowest Fold Concentration (among profitable) ---")
        for i, vr in enumerate(best_conc[:5]):
            m = vr["metrics"]; fi = vr["fold_info"]
            print(f"  #{i+1} {vr['label']:18s}  fold_conc={fi['fold_concentration']:.1%}  trades={m['trades']}  PF={m['pf']:.3f}  exp/wk=${m['exp_per_week']:.2f}  WF={fi['folds_positive']}/5")

    # Build JSON report
    report = {
        "run_header": {
            "task": "part2_param_grid_135", "agent": "A6 Param Explorer",
            "date": datetime.now().strftime("%Y-%m-%d"), "commit": commit,
            "hypothesis": "H20_VWAP_DEVIATION", "dev_thresh": DEV_THRESH,
            "grid_params": {"tp_pct": TP_VALUES, "sl_pct": SL_VALUES, "time_limit": TL_VALUES},
            "total_combos": len(grid), "cost_regime": "MEXC Market",
            "fees": {"tier1_bps": round(tier1_fee * 10000, 1), "tier2_bps": round(tier2_fee * 10000, 1)},
            "universe": f"135-coin subset (T1={n_t1}, T2={n_t2})", "timeframe": "1h",
            "total_bars": total_bars, "total_weeks": round(total_weeks, 1),
            "runtime_s": round(elapsed_total, 1), "g8_target": f"fold_conc < {FOLD_CONC_TARGET:.0%}",
        },
        "scoring_formula": "exp_per_week * (wf/5) * min(1, trades/50) * (1 - fold_conc)",
        "g8_criteria": {"fold_concentration": f"< {FOLD_CONC_TARGET}", "exp_per_week": "> $0", "wf_folds_positive": ">= 4/5"},
        "variant_results": variant_results,
        "g8_passers": [{"label": vr["label"], "params": vr["params"], "metrics": vr["metrics"],
                        "fold_info": vr["fold_info"], "composite_score": vr["composite_score"]}
                       for vr in sorted(g8_passers, key=lambda x: x["composite_score"], reverse=True)],
        "dominant_fold_analysis": {
            "tally": {f"fold_{k}": v for k, v in sorted(dominant_fold_tally.items())},
            "interpretation": "If one fold dominates across all configs, concentration is structural (driven by market period, not parameter choice).",
        },
        "top5_by_score": [{"rank": i+1, "label": vr["label"], "params": vr["params"],
                           "composite_score": vr["composite_score"], "metrics": vr["metrics"],
                           "fold_info": vr["fold_info"]} for i, vr in enumerate(ranked[:5])],
    }

    json_path = ROOT / "reports" / "hf" / "part2_param_grid_135_001.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n[Report] JSON: {json_path}")

    # Build Markdown report
    md = []
    md.append("# Part 2 -- 2D Parameter Grid on 135-coin Subset")
    md.append("")
    md.append(f"**Agent**: A6 Param Explorer")
    md.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    md.append(f"**Commit**: {commit}")
    md.append(f"**Universe**: 135 coins (T1={n_t1}, T2={n_t2}) -- first 135 alphabetically from T1+T2")
    md.append(f"**Hypothesis**: H20 VWAP_DEVIATION (dev_thresh={DEV_THRESH})")
    md.append(f"**Cost Regime**: MEXC Market (T1={tier1_fee*10000:.1f}bps, T2={tier2_fee*10000:.1f}bps)")
    md.append(f"**Grid**: tp_pct={TP_VALUES} x sl_pct={SL_VALUES} x time_limit={TL_VALUES} = {len(grid)} combos")
    md.append(f"**Runtime**: {elapsed_total:.1f}s")
    md.append(f"**G8 Target**: fold_concentration < {FOLD_CONC_TARGET:.0%}")
    md.append("")

    md.append("## G8 Verdict")
    md.append("")
    if g8_passers:
        md.append(f"**{len(g8_passers)} configs pass G8** (fold_conc < {FOLD_CONC_TARGET:.0%} AND exp/wk > $0 AND WF >= 4/5):")
        md.append("")
        md.append("| Label | tp | sl | tl | Trades | PF | Exp/Wk | WF | Fold Conc | Dom Fold | Score |")
        md.append("|-------|----|----|----|----|-----|--------|-----|-----------|----------|-------|")
        for vr in sorted(g8_passers, key=lambda x: x["composite_score"], reverse=True):
            p = vr["params"]; m = vr["metrics"]; fi = vr["fold_info"]
            md.append(f"| {vr['label']} | {p['tp_pct']} | {p['sl_pct']} | {p['time_limit']} | {m['trades']} | {m['pf']:.3f} | ${m['exp_per_week']:.2f} | {fi['folds_positive']}/5 | {fi['fold_concentration']:.1%} | F{fi['dominant_fold']} | {vr['composite_score']:.4f} |")
    else:
        md.append(f"**NO configs pass G8** on 135-coin subset.")
        md.append("This suggests fold concentration is structural (driven by market period).")
    md.append("")

    md.append("## Dominant Fold Analysis")
    md.append("")
    md.append("Which fold dominates PnL across all configs?")
    md.append("")
    md.append("| Fold | Times Dominant | % of Configs |")
    md.append("|------|---------------|--------------|")
    for fold_idx in sorted(dominant_fold_tally.keys()):
        count = dominant_fold_tally[fold_idx]
        pct = count / len(grid) * 100
        md.append(f"| Fold {fold_idx} | {count} | {pct:.0f}% |")
    md.append("")
    max_dom = max(dominant_fold_tally.values()) if dominant_fold_tally else 0
    if max_dom > len(grid) * 0.7:
        dom_fold_id = max(dominant_fold_tally, key=dominant_fold_tally.get)
        md.append(f"**STRUCTURAL**: Fold {dom_fold_id} dominates in {max_dom}/{len(grid)} configs ({max_dom/len(grid)*100:.0f}%). Fold concentration is driven by market period, not parameter choice.")
    else:
        md.append("**PARAMETERIZABLE**: Dominant fold varies across configs. Parameter tuning can influence fold distribution.")
    md.append("")

    md.append("## All Variants")
    md.append("")
    md.append("| # | Label | tp | sl | tl | Tr | PF | WR% | Exp/Wk | DD% | WF | FoldConc | DomF | Score | G8? |")
    md.append("|---|-------|----|----|----|----|-----|------|--------|------|-----|----------|------|-------|-----|")
    for vr in variant_results:
        p = vr["params"]; m = vr["metrics"]; fi = vr["fold_info"]
        g8 = "PASS" if vr["passes_g8"] else "-"
        md.append(f"| {vr['variant_idx']} | {vr['label']} | {p['tp_pct']} | {p['sl_pct']} | {p['time_limit']} | {m['trades']} | {m['pf']:.3f} | {m['wr']:.1f} | ${m['exp_per_week']:.2f} | {m['dd']:.1f} | {fi['folds_positive']}/5 | {fi['fold_concentration']:.1%} | F{fi['dominant_fold']} | {vr['composite_score']:.4f} | {g8} |")
    md.append("")

    md.append("## Fold PnL Distribution (Top 10 by Score)")
    md.append("")
    md.append("| Label | F0 | F1 | F2 | F3 | F4 | Positive | Conc |")
    md.append("|-------|----|----|----|----|----|----|------|")
    for vr in ranked[:10]:
        fi = vr["fold_info"]
        fp = list(fi["fold_pnls"])
        while len(fp) < 5:
            fp.append(0.0)
        md.append(f"| {vr['label']} | ${fp[0]:.0f} | ${fp[1]:.0f} | ${fp[2]:.0f} | ${fp[3]:.0f} | ${fp[4]:.0f} | {fi['folds_positive']}/5 | {fi['fold_concentration']:.1%} |")
    md.append("")

    md.append("## Top 5 by Composite Score")
    md.append("")
    for i, vr in enumerate(ranked[:5]):
        m = vr["metrics"]; fi = vr["fold_info"]; p = vr["params"]
        md.append(f"### #{i+1}: {vr['label']}")
        md.append(f"- **Params**: tp={p['tp_pct']}, sl={p['sl_pct']}, tl={p['time_limit']}, dev={p['dev_thresh']}")
        md.append(f"- **Score**: {vr['composite_score']:.4f}")
        md.append(f"- **Baseline**: {m['trades']} trades, PF={m['pf']:.3f}, WR={m['wr']:.1f}%, Exp/Wk=${m['exp_per_week']:.2f}, DD={m['dd']:.1f}%")
        md.append(f"- **Walk-Forward**: {fi['folds_positive']}/5, fold_conc={fi['fold_concentration']:.1%}, dominant=F{fi['dominant_fold']}")
        md.append(f"- **Fold PnLs**: {fi['fold_pnls']}")
        md.append(f"- **G8**: {'PASS' if vr['passes_g8'] else 'FAIL'}")
        md.append("")

    md.append("---")
    md.append(f"*Generated by strategies/hf/screening/run_part2_param_grid_135.py at {datetime.now().strftime('%Y-%m-%d %H:%M')} -- Agent A6*")

    md_path = ROOT / "reports" / "hf" / "part2_param_grid_135_001.md"
    md_path.write_text("\n".join(md))
    print(f"[Report] MD:   {md_path}")

    print(f"\n{'=' * 70}")
    print(f"  COMPLETE: {len(grid)} combos tested on 135-coin subset")
    print(f"  G8 passers: {len(g8_passers)}/{len(grid)}")
    if ranked:
        print(f"  Top-1: {ranked[0]['label']} (score={ranked[0]['composite_score']:.4f}, fold_conc={ranked[0]['fold_info']['fold_concentration']:.1%})")
    if g8_passers:
        best = sorted(g8_passers, key=lambda x: x["composite_score"], reverse=True)[0]
        print(f"  Best G8 passer: {best['label']} (score={best['composite_score']:.4f})")
    print(f"  Runtime: {elapsed_total:.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
