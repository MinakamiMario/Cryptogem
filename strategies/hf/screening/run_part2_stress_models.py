#!/usr/bin/env python3
"""
Part 2 -- Agent A5: Stress Model Analysis
==========================================
Tests v5 (dev=2.0, tp=8, sl=5, tl=10) on full 316 coins under MULTIPLE
stress scenarios to find what fee model makes G4 pass.

Scenarios tested:
  1. Baseline (no stress): T1=12.5bps, T2=23.5bps
  2. Uniform 1.5x: T1=18.75bps, T2=35.25bps
  3. Uniform 2x (current): T1=25bps, T2=47bps
  4. Tiered (T1=1.5x, T2=2x): T1=18.75bps, T2=47bps
  5. Tiered (T1=1x, T2=2.5x): T1=12.5bps, T2=58.75bps
  6. Worst-case (T1=2x, T2=2.5x): T1=25bps, T2=58.75bps
  7. Fee ladder: 0.1x increments from 1.0x to 2.5x
  + Binary search for exact breakeven multiplier

Usage:
    python -m strategies.hf.screening.run_part2_stress_models
    python -m strategies.hf.screening.run_part2_stress_models --dry-run
"""
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    run_backtest, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import get_harness_fee

BARS_PER_WEEK = 168

BASE_T1 = get_harness_fee("mexc_market", "tier1")
BASE_T2 = get_harness_fee("mexc_market", "tier2")

V5_PARAMS = {
    "dev_thresh": 2.0,
    "tp_pct": 8,
    "sl_pct": 5,
    "time_limit": 10,
}

STRESS_SCENARIOS = [
    {"name": "Baseline (1x)",            "t1_mult": 1.0, "t2_mult": 1.0,
     "description": "No stress -- P50 MEXC market costs"},
    {"name": "Uniform 1.5x",            "t1_mult": 1.5, "t2_mult": 1.5,
     "description": "All costs multiplied by 1.5x"},
    {"name": "Uniform 2x (current)",     "t1_mult": 2.0, "t2_mult": 2.0,
     "description": "Current stress model -- 2x all fees"},
    {"name": "Tiered (T1=1.5x, T2=2x)", "t1_mult": 1.5, "t2_mult": 2.0,
     "description": "Moderate T1 stress, full T2 stress"},
    {"name": "Tiered (T1=1x, T2=2.5x)", "t1_mult": 1.0, "t2_mult": 2.5,
     "description": "No T1 stress, extreme T2 stress"},
    {"name": "Worst-case (T1=2x, T2=2.5x)", "t1_mult": 2.0, "t2_mult": 2.5,
     "description": "Maximum stress on both tiers"},
]


def load_candle_cache(timeframe="1h", require_data=False):
    cache_path = ROOT / "data" / f"candle_cache_{timeframe}.json"
    if cache_path.exists():
        print(f"[Load] Reading {cache_path.name}...")
        with open(cache_path) as f:
            data = json.load(f)
        coins_data = {k: v for k, v in data.items() if not k.startswith("_")}
        print(f"[Load] {len(coins_data)} coins loaded (merged cache)")
        return coins_data
    parts_base = ROOT / "data" / "cache_parts_hf" / timeframe
    if not parts_base.exists():
        if require_data:
            print("[ERROR] No cache found")
            sys.exit(1)
        print("[SKIP] No 1H candle cache found.")
        return None
    print("[Load] Loading from per-coin parts...")
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
        if require_data:
            sys.exit(1)
        return None
    print(f"[Load] {len(coins_data)} coins loaded (from part files)")
    return coins_data


def load_universe_tiering(require_data=False):
    tiering_path = ROOT / "reports" / "hf" / "universe_tiering_001.json"
    if not tiering_path.exists():
        if require_data:
            sys.exit(1)
        return None
    with open(tiering_path) as f:
        return json.load(f)


def build_tier_coins(tiering, available_coins):
    tier_coins = {"tier1": [], "tier2": []}
    tb = tiering.get("tier_breakdown", {})
    if tb:
        for tier_num, tier_key in [("1", "tier1"), ("2", "tier2")]:
            if tier_num in tb:
                coins = tb[tier_num].get("coins", [])
                tier_coins[tier_key] = [c for c in coins if c in available_coins]
        if tier_coins["tier1"] or tier_coins["tier2"]:
            return tier_coins
    tiers = tiering.get("tiers", {})
    for k in ["tier_1", "Tier 1 (Liquid)", "tier1", "1"]:
        if k in tiers:
            tier_coins["tier1"] = [c for c in tiers[k].get("coins", []) if c in available_coins]
            break
    for k in ["tier_2", "Tier 2 (Mid)", "tier2", "2"]:
        if k in tiers:
            tier_coins["tier2"] = [c for c in tiers[k].get("coins", []) if c in available_coins]
            break
    return tier_coins


def run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_fee, t2_fee):
    enriched_params = {**V5_PARAMS, "__market__": market_context}
    all_trades = []
    tier_fees = {"tier1": t1_fee, "tier2": t2_fee}
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = tier_fees.get(tier_name, t1_fee)
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


def compute_metrics(trades, initial_capital=2000.0, total_bars=None):
    n_trades = len(trades)
    if n_trades == 0:
        return {"trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0,
                "dd": 0.0, "expectancy": 0.0, "trades_per_week": 0.0,
                "exp_per_week": 0.0, "fee_drag_pct": 0.0}
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
        fee = t.get("_fee_per_side", 0.00125)
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
    return {
        "trades": n_trades, "pnl": round(total_pnl, 2), "pf": round(pf, 3),
        "wr": round(wr, 2), "dd": round(max_dd, 2),
        "expectancy": round(expectancy, 4),
        "trades_per_week": round(trades_per_week, 2),
        "exp_per_week": round(exp_per_week, 4),
        "fee_drag_pct": round(fee_drag_pct, 2),
    }


def estimate_total_bars(tier_indicators, tier_coins):
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            n = indicators.get(coin, {}).get("n", 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def find_breakeven_multiplier(data, tier_coins, tier_indicators, market_context,
                              total_bars, lo=1.0, hi=3.0, tol=0.005, max_iter=25):
    t1_lo, t2_lo = BASE_T1 * lo, BASE_T2 * lo
    trades_lo = run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_lo, t2_lo)
    m_lo = compute_metrics(trades_lo, total_bars=total_bars)
    if m_lo["exp_per_week"] <= 0:
        return lo, m_lo["exp_per_week"], 0
    t1_hi, t2_hi = BASE_T1 * hi, BASE_T2 * hi
    trades_hi = run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_hi, t2_hi)
    m_hi = compute_metrics(trades_hi, total_bars=total_bars)
    if m_hi["exp_per_week"] > 0:
        return hi, m_hi["exp_per_week"], 0
    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        mid = (lo + hi) / 2.0
        t1_mid, t2_mid = BASE_T1 * mid, BASE_T2 * mid
        trades_mid = run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_mid, t2_mid)
        m_mid = compute_metrics(trades_mid, total_bars=total_bars)
        if abs(m_mid["exp_per_week"]) < tol:
            return mid, m_mid["exp_per_week"], iterations
        if m_mid["exp_per_week"] > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0, 0.0, iterations


def main():
    parser = argparse.ArgumentParser(description="Part 2 -- Stress Model Analysis (A5)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-data", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print("  Part 2 -- Agent A5: Stress Model Analysis")
    print("  v5 (dev=2.0, tp=8, sl=5, tl=10) under multiple fee models")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat(timespec='seconds')}")
    t0 = time.time()

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
        ).decode().strip()
    except Exception:
        commit = "unknown"

    print(f"[Costs] Base fees: T1={BASE_T1*10000:.1f}bps, T2={BASE_T2*10000:.1f}bps")

    data = load_candle_cache("1h", require_data=args.require_data)
    if data is None:
        sys.exit(0)
    available_coins = set(data.keys())

    tiering = load_universe_tiering(require_data=args.require_data)
    if tiering is None:
        sys.exit(0)
    tier_coins = build_tier_coins(tiering, available_coins)

    n_t1 = len(tier_coins["tier1"])
    n_t2 = len(tier_coins["tier2"])
    n_total = n_t1 + n_t2
    print(f"[Universe] T1: {n_t1} coins, T2: {n_t2} coins, Total: {n_total}")

    if not tier_coins["tier1"] and not tier_coins["tier2"]:
        print("[SKIP] No coins in T1 or T2.")
        sys.exit(0)

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(STRESS_SCENARIOS)} scenarios + ladder + breakeven ---")
        for i, sc in enumerate(STRESS_SCENARIOS):
            t1b = BASE_T1 * sc["t1_mult"] * 10000
            t2b = BASE_T2 * sc["t2_mult"] * 10000
            print(f"  [{i}] {sc['name']:35s} T1={t1b:6.2f}bps  T2={t2b:6.2f}bps")
        print("\n  + Fee ladder: 1.0x to 2.5x in 0.1x steps")
        print("  + Binary search: exact breakeven multiplier")
        sys.exit(0)

    print("[Indicators] Precomputing base indicators...")
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f"  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s")

    print("[Indicators] Extending with VWAP fields...")
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            vwap_pct = cov["vwap_pct"]
            vwap_n = cov["vwap_available"]
            total_c = cov["total_coins"]
            print(f"  {tier_name}: VWAP {vwap_pct:.0f}% ({vwap_n}/{total_c})")

    print("[Market Context] Precomputing...")
    all_coins = list(set(c for coins in tier_coins.values() for c in coins))
    for btc in ("BTC/USD", "XBT/USD", "BTC/USDT"):
        if btc in available_coins and btc not in all_coins:
            all_coins.append(btc)
    market_context = precompute_market_context(data, all_coins)
    print("  Done.")

    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]["__coin__"] = coin

    total_bars = estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
    print(f"[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}")

    # Phase 1: Named Stress Scenarios
    sep = "=" * 70
    print(f"\n{sep}")
    print("  Phase 1: Named Stress Scenarios")
    print(sep)

    scenario_results = []
    for sc_idx, scenario in enumerate(STRESS_SCENARIOS):
        t_sc = time.time()
        t1_fee = BASE_T1 * scenario["t1_mult"]
        t2_fee = BASE_T2 * scenario["t2_mult"]
        t1_bps = t1_fee * 10000
        t2_bps = t2_fee * 10000

        trades = run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_fee, t2_fee)
        metrics = compute_metrics(trades, total_bars=total_bars)

        t1_trades = [t for t in trades if t.get("_tier") == "tier1"]
        t2_trades = [t for t in trades if t.get("_tier") == "tier2"]
        t1_pnl = sum(t["pnl"] for t in t1_trades)
        t2_pnl = sum(t["pnl"] for t in t2_trades)

        g4_pass = metrics["exp_per_week"] > 0
        elapsed_sc = time.time() - t_sc

        result = {
            "scenario_idx": sc_idx,
            "name": scenario["name"],
            "description": scenario["description"],
            "t1_mult": scenario["t1_mult"],
            "t2_mult": scenario["t2_mult"],
            "t1_bps": round(t1_bps, 2),
            "t2_bps": round(t2_bps, 2),
            "metrics": metrics,
            "tier_breakdown": {
                "tier1": {"trades": len(t1_trades), "pnl": round(t1_pnl, 2)},
                "tier2": {"trades": len(t2_trades), "pnl": round(t2_pnl, 2)},
            },
            "g4_pass": g4_pass,
            "runtime_s": round(elapsed_sc, 1),
        }
        scenario_results.append(result)

        g4_str = "PASS" if g4_pass else "FAIL"
        print(f"  [{sc_idx}] {scenario['name']:35s} "
              f"T1={t1_bps:5.1f}bps T2={t2_bps:5.1f}bps | "
              f"tr={metrics['trades']:3d} PF={metrics['pf']:.3f} "
              f"WR={metrics['wr']:.1f}% exp/w=${metrics['exp_per_week']:.2f} "
              f"DD={metrics['dd']:.1f}% | G4={g4_str} ({elapsed_sc:.1f}s)")

    # Phase 2: Fee Ladder
    print(f"\n{sep}")
    print("  Phase 2: Fee Ladder (uniform multiplier sweep)")
    print(sep)

    ladder_multipliers = [round(1.0 + i * 0.1, 1) for i in range(16)]
    ladder_results = []

    for mult in ladder_multipliers:
        t_lad = time.time()
        t1_fee = BASE_T1 * mult
        t2_fee = BASE_T2 * mult

        trades = run_v5_with_fees(data, tier_coins, tier_indicators, market_context, t1_fee, t2_fee)
        metrics = compute_metrics(trades, total_bars=total_bars)

        g4_pass = metrics["exp_per_week"] > 0
        elapsed_lad = time.time() - t_lad

        result = {
            "multiplier": mult,
            "t1_bps": round(t1_fee * 10000, 2),
            "t2_bps": round(t2_fee * 10000, 2),
            "trades": metrics["trades"],
            "pnl": metrics["pnl"],
            "pf": metrics["pf"],
            "wr": metrics["wr"],
            "exp_per_week": metrics["exp_per_week"],
            "dd": metrics["dd"],
            "g4_pass": g4_pass,
        }
        ladder_results.append(result)

        g4_str = "PASS" if g4_pass else "FAIL"
        print(f"  {mult:.1f}x  T1={t1_fee*10000:5.1f}bps T2={t2_fee*10000:5.1f}bps | "
              f"PF={metrics['pf']:.3f} exp/w=${metrics['exp_per_week']:.2f} G4={g4_str} ({elapsed_lad:.1f}s)")

    # Phase 3: Binary Search for Exact Breakeven
    print(f"\n{sep}")
    print("  Phase 3: Binary Search for Exact Breakeven Multiplier")
    print(sep)

    t_bsearch = time.time()
    be_mult, be_exp, be_iters = find_breakeven_multiplier(
        data, tier_coins, tier_indicators, market_context, total_bars,
    )
    elapsed_bsearch = time.time() - t_bsearch

    be_t1_bps = BASE_T1 * be_mult * 10000
    be_t2_bps = BASE_T2 * be_mult * 10000

    print(f"  Breakeven multiplier: {be_mult:.3f}x")
    print(f"  At breakeven: T1={be_t1_bps:.1f}bps, T2={be_t2_bps:.1f}bps")
    print(f"  Exp/week at breakeven: ${be_exp:.4f}")
    print(f"  Iterations: {be_iters} ({elapsed_bsearch:.1f}s)")

    breakeven_result = {
        "multiplier": round(be_mult, 4),
        "t1_bps_at_breakeven": round(be_t1_bps, 2),
        "t2_bps_at_breakeven": round(be_t2_bps, 2),
        "exp_per_week_at_breakeven": round(be_exp, 4),
        "iterations": be_iters,
        "search_range": [1.0, 3.0],
        "tolerance": 0.005,
        "runtime_s": round(elapsed_bsearch, 1),
    }

    elapsed = time.time() - t0

    # Summary
    print(f"\n{sep}")
    print("  Summary: G4 Gate Results")
    print(sep)

    passing = [s for s in scenario_results if s["g4_pass"]]
    failing = [s for s in scenario_results if not s["g4_pass"]]

    print(f"  PASSING ({len(passing)}/{len(scenario_results)}):")
    for s in passing:
        print(f"    + {s['name']} (exp/w=${s['metrics']['exp_per_week']:.2f})")
    print(f"  FAILING ({len(failing)}/{len(scenario_results)}):")
    for s in failing:
        print(f"    - {s['name']} (exp/w=${s['metrics']['exp_per_week']:.2f})")

    baseline_sc = scenario_results[0]
    t1_pnl_base = baseline_sc["tier_breakdown"]["tier1"]["pnl"]
    t2_pnl_base = baseline_sc["tier_breakdown"]["tier2"]["pnl"]
    print(f"\n  Edge attribution (baseline):")
    print(f"    T1 P&L: ${t1_pnl_base:.2f} ({baseline_sc['tier_breakdown']['tier1']['trades']} trades)")
    print(f"    T2 P&L: ${t2_pnl_base:.2f} ({baseline_sc['tier_breakdown']['tier2']['trades']} trades)")

    # JSON Report
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = {
        "run_header": {
            "task": "part2_stress_models",
            "agent": "A5 (Stress Modeler)",
            "date": dt_str,
            "commit": commit,
            "hypothesis": "H20_VWAP_DEVIATION v5",
            "params": V5_PARAMS,
            "cost_model": "costs_mexc_v2",
            "base_fees": {"tier1_bps": round(BASE_T1*10000, 1), "tier2_bps": round(BASE_T2*10000, 1)},
            "universe": {"tier1_coins": n_t1, "tier2_coins": n_t2, "total_coins": n_total},
            "timeframe": "1h",
            "total_bars": total_bars,
            "total_weeks": round(total_weeks, 1),
            "runtime_s": round(elapsed, 1),
        },
        "g4_gate": "exp_per_week > 0",
        "scenario_results": scenario_results,
        "fee_ladder": ladder_results,
        "breakeven": breakeven_result,
        "summary": {
            "passing_scenarios": [s["name"] for s in passing],
            "failing_scenarios": [s["name"] for s in failing],
            "breakeven_multiplier": round(be_mult, 4),
            "breakeven_t1_bps": round(be_t1_bps, 2),
            "breakeven_t2_bps": round(be_t2_bps, 2),
            "recommendation": (
                f"Strategy survives up to {be_mult:.2f}x uniform fee stress. "
                f"The current 2.0x uniform model is "
                f"{'within' if be_mult >= 2.0 else 'beyond'} the survivable range. "
                f"A tiered model (T1=1.5x, T2=2x) may be more realistic."
            ),
        },
    }

    json_path = ROOT / "reports" / "hf" / "part2_stress_models_001.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n[Report] JSON: {json_path}")

    # Markdown Report
    md = []
    md.append("# Part 2 -- Stress Model Analysis (Agent A5)")
    md.append("")
    md.append(f"**Date**: {dt_str}")
    md.append(f"**Commit**: {commit}")
    md.append(f"**Universe**: T1({n_t1}) + T2({n_t2}) = {n_total} coins")
    md.append("**Timeframe**: 1H")
    md.append("**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)")
    md.append(f"**Base Costs**: T1={BASE_T1*10000:.1f}bps, T2={BASE_T2*10000:.1f}bps (MEXC Market P50)")
    md.append(f"**Runtime**: {elapsed:.1f}s")
    md.append("")
    md.append("## Context")
    md.append("")
    md.append("The current stress test uses a uniform 2x multiplier on all fees.")
    md.append("This penalises T1 coins (tight spreads, high volume) equally with T2 coins.")
    md.append("This analysis tests whether alternative stress models produce a different G4 outcome.")
    md.append("")

    md.append("## Named Stress Scenarios")
    md.append("")
    md.append("| # | Scenario | T1 bps | T2 bps | Trades | PF | WR% | Exp/Wk | DD% | G4 |")
    md.append("|---|----------|--------|--------|--------|----|-----|--------|-----|----|")
    for s in scenario_results:
        m = s["metrics"]
        g4 = "PASS" if s["g4_pass"] else "FAIL"
        md.append(f"| {s['scenario_idx']} | {s['name']} | {s['t1_bps']:.1f} | {s['t2_bps']:.1f} "
                  f"| {m['trades']} | {m['pf']:.3f} | {m['wr']:.1f} | ${m['exp_per_week']:.2f} "
                  f"| {m['dd']:.1f} | **{g4}** |")
    md.append("")

    md.append("### Per-Tier P&L Breakdown")
    md.append("")
    md.append("| Scenario | T1 Trades | T1 P&L | T2 Trades | T2 P&L |")
    md.append("|----------|-----------|--------|-----------|--------|")
    for s in scenario_results:
        tb = s["tier_breakdown"]
        md.append(f"| {s['name']} | {tb['tier1']['trades']} | ${tb['tier1']['pnl']:.2f} "
                  f"| {tb['tier2']['trades']} | ${tb['tier2']['pnl']:.2f} |")
    md.append("")

    md.append("## Fee Ladder (Uniform Multiplier Sweep)")
    md.append("")
    md.append("| Mult | T1 bps | T2 bps | Trades | PF | WR% | Exp/Wk | DD% | G4 |")
    md.append("|------|--------|--------|--------|----|-----|--------|-----|----|")
    for lr in ladder_results:
        g4 = "PASS" if lr["g4_pass"] else "FAIL"
        md.append(f"| {lr['multiplier']:.1f}x | {lr['t1_bps']:.1f} | {lr['t2_bps']:.1f} "
                  f"| {lr['trades']} | {lr['pf']:.3f} | {lr['wr']:.1f} | ${lr['exp_per_week']:.2f} "
                  f"| {lr['dd']:.1f} | {g4} |")
    md.append("")

    md.append("## Breakeven Analysis")
    md.append("")
    md.append(f"- **Breakeven multiplier**: {be_mult:.3f}x (uniform)")
    md.append(f"- **At breakeven**: T1={be_t1_bps:.1f}bps, T2={be_t2_bps:.1f}bps")
    md.append(f"- **Exp/week at breakeven**: ${be_exp:.4f}")
    md.append(f"- **Binary search**: {be_iters} iterations, tolerance $0.005/week")
    md.append("")

    md.append("## Key Findings")
    md.append("")
    md.append(f"1. **Breakeven**: Strategy edge disappears at **{be_mult:.2f}x** uniform fee stress")
    if be_mult < 2.0:
        md.append(f"2. **Current 2x stress**: EXCEEDS breakeven by {(2.0 - be_mult):.2f}x -- strategy FAILS")
    else:
        md.append(f"2. **Current 2x stress**: WITHIN breakeven -- strategy PASSES")
    tiered_sc = scenario_results[3]
    if tiered_sc["g4_pass"]:
        md.append(f"3. **Tiered (T1=1.5x, T2=2x)**: PASSES G4 (exp/w=${tiered_sc['metrics']['exp_per_week']:.2f})")
    else:
        md.append(f"3. **Tiered (T1=1.5x, T2=2x)**: FAILS G4 (exp/w=${tiered_sc['metrics']['exp_per_week']:.2f})")
    md.append(f"4. **Edge attribution (baseline)**: "
              f"T1 ${t1_pnl_base:.0f} ({baseline_sc['tier_breakdown']['tier1']['trades']} trades), "
              f"T2 ${t2_pnl_base:.0f} ({baseline_sc['tier_breakdown']['tier2']['trades']} trades)")
    if t2_pnl_base < 0:
        md.append(f"5. **T2 is a drag**: T2 coins lose ${abs(t2_pnl_base):.0f} even at baseline fees")
    else:
        md.append(f"5. **Both tiers profitable at baseline**: T2 contributes ${t2_pnl_base:.0f}")
    md.append("")

    md.append("## Recommendation")
    md.append("")
    md.append(report["summary"]["recommendation"])
    md.append("")

    md.append("## G4 Gate Summary")
    md.append("")
    md.append(f"- **Passing**: {', '.join(s['name'] for s in passing)}")
    md.append(f"- **Failing**: {', '.join(s['name'] for s in failing)}")
    md.append("")

    md.append("---")
    md.append(f"*Generated by run_part2_stress_models.py at {dt_str}*")

    md_path = ROOT / "reports" / "hf" / "part2_stress_models_001.md"
    md_path.write_text("\n".join(md))
    print(f"[Report] MD:   {md_path}")

    print(f"\n{sep}")
    print("  COMPLETE: Stress Model Analysis")
    print(f"  Scenarios: {len(STRESS_SCENARIOS)} named + {len(ladder_multipliers)} ladder + breakeven")
    print(f"  G4 passing: {len(passing)}/{len(scenario_results)} named scenarios")
    print(f"  Breakeven: {be_mult:.3f}x uniform multiplier")
    print(f"  Runtime: {elapsed:.1f}s")
    print(sep)


if __name__ == "__main__":
    main()
