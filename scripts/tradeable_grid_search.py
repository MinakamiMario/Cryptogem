#!/usr/bin/env python3
"""Mini Grid Search on TRADEABLE universe — coordinate descent + combos."""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "trading_bot"))
from agent_team_v3 import precompute_all, run_backtest, normalize_cfg, KRAKEN_FEE, INITIAL_CAPITAL, START_BAR
from robustness_harness import purged_walk_forward

CACHE_PATH = Path(__file__).parent.parent / "data" / "candle_cache_tradeable.json"
BASELINE = {"exit_type": "tp_sl", "rsi_max": 45, "vol_spike_mult": 3.0, "vol_confirm": True, "tp_pct": 15, "sl_pct": 15, "time_max_bars": 15, "max_pos": 1}
PARAM_GRID = {"tp_pct": [10, 12, 15, 20], "sl_pct": [10, 12, 15, 20], "time_max_bars": [6, 10, 15, 20], "rsi_max": [40, 42, 45], "vol_spike_mult": [2.0, 2.5, 3.0]}

def quick_wf(indicators, coins, cfg, n_folds=3, embargo=2):
    max_bars = max(indicators[p]["n"] for p in coins if p in indicators)
    usable = max_bars - START_BAR
    fold_size = usable // n_folds
    folds_pass = 0
    for i in range(n_folds):
        test_start = START_BAR + i * fold_size
        test_end = test_start + fold_size if i < n_folds - 1 else max_bars
        bt = run_backtest(indicators, coins, cfg, start_bar=test_start, end_bar=test_end)
        if bt["pnl"] > 0:
            folds_pass += 1
    return folds_pass, n_folds

def quick_friction(indicators, coins, cfg):
    eff_fee = KRAKEN_FEE * 2.0 + 0.002
    bt = run_backtest(indicators, coins, cfg, fee_override=eff_fee)
    return bt["pnl"]

def eval_config(indicators, coins, cfg, label=""):
    cfg = normalize_cfg(dict(cfg))
    bt = run_backtest(indicators, coins, cfg)
    if bt["trades"] < 10:
        print(f"  {label:<40} SKIP (<10 trades)")
        return None
    wf_pass, wf_total = quick_wf(indicators, coins, cfg)
    fric_pnl = quick_friction(indicators, coins, cfg)
    score = wf_pass * 30 + (20 if fric_pnl > 0 else 0) + min(30, bt["pnl"] / 100) + min(10, bt["trades"] * 0.5)
    r = {"label": label, "cfg": dict(cfg), "trades": bt["trades"], "pnl": round(bt["pnl"], 2), "wr": round(bt["wr"], 1), "dd": round(bt["dd"], 1), "pf": round(bt["pf"], 2) if bt["pf"] < 999 else "INF", "wf": f"{wf_pass}/{wf_total}", "wf_pass": wf_pass, "fric_pnl": round(fric_pnl, 2), "score": score}
    status = "PASS" if wf_pass >= 2 and fric_pnl > 0 else "FAIL"
    print(f"  {label:<40} {bt['trades']:>3}tr ${bt['pnl']:>7.0f} WR{bt['wr']:>4.0f}% DD{bt['dd']:>4.0f}% WF{wf_pass}/{wf_total} Fric${fric_pnl:>7.0f} [{status}]")
    return r

def main():
    print("=" * 70)
    print("  MINI GRID SEARCH - TRADEABLE UNIVERSE")
    print("=" * 70)
    t0 = time.time()
    with open(CACHE_PATH) as f:
        data = json.load(f)
    coins = sorted(k for k, v in data.items() if isinstance(v, list) and len(v) > 50)
    print(f"  {len(coins)} coins ({time.time()-t0:.1f}s)")
    print("Precomputing indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Done ({time.time()-t1:.1f}s)")

    print("\n--- PHASE 1: Coordinate Descent ---")
    results = []
    base_r = eval_config(indicators, coins, BASELINE, "BASELINE")
    if base_r:
        results.append(base_r)

    for param, values in PARAM_GRID.items():
        for val in values:
            if val == BASELINE.get(param):
                continue
            cfg = dict(BASELINE)
            cfg[param] = val
            r = eval_config(indicators, coins, cfg, f"{param}={val}")
            if r:
                results.append(r)

    base_score = base_r["score"] if base_r else 0
    best_per_param = {}
    for r in results:
        if r["label"] == "BASELINE":
            continue
        param = r["label"].split("=")[0]
        if param not in best_per_param or r["score"] > best_per_param[param]["score"]:
            best_per_param[param] = r

    improvements = [(p, r) for p, r in best_per_param.items() if r["score"] > base_score]
    improvements.sort(key=lambda x: x[1]["score"], reverse=True)
    print(f"\n  {len(improvements)} improving params:")
    for p, r in improvements:
        print(f"    {r['label']}: score={r['score']:.1f} vs baseline={base_score:.1f}")

    print("\n--- PHASE 2: Top Combinations ---")
    if len(improvements) >= 2:
        for i in range(len(improvements)):
            for j in range(i+1, len(improvements)):
                p1, r1 = improvements[i]
                p2, r2 = improvements[j]
                cfg = dict(BASELINE)
                cfg[p1] = r1["cfg"][p1]
                cfg[p2] = r2["cfg"][p2]
                lbl = f"{r1['label']}+{r2['label']}"
                r = eval_config(indicators, coins, cfg, lbl)
                if r:
                    results.append(r)

    if len(improvements) >= 3:
        print("\n--- PHASE 2b: Triple Combinations ---")
        for i in range(min(3, len(improvements))):
            for j in range(i+1, min(4, len(improvements))):
                for k in range(j+1, min(5, len(improvements))):
                    p1, r1 = improvements[i]
                    p2, r2 = improvements[j]
                    p3, r3 = improvements[k]
                    cfg = dict(BASELINE)
                    cfg[p1] = r1["cfg"][p1]
                    cfg[p2] = r2["cfg"][p2]
                    cfg[p3] = r3["cfg"][p3]
                    lbl = f"{r1['label']}+{r2['label']}+{r3['label']}"
                    r = eval_config(indicators, coins, cfg, lbl)
                    if r:
                        results.append(r)

    results.sort(key=lambda x: x["score"], reverse=True)
    passing = [r for r in results if r["wf_pass"] >= 2 and r["fric_pnl"] > 0]

    print(f"\n{'='*70}")
    print(f"  TOP 10 (of {len(results)} tested)")
    print(f"{'='*70}")
    print(f"{'#':>2} {'Config':<45} {'Tr':>3} {'P&L':>7} {'WR':>5} {'DD':>5} {'WF':>4} {'Fric':>7} {'Scr':>5}")
    print("-" * 90)
    for i, r in enumerate(results[:10]):
        print(f"{i+1:>2} {r['label']:<45} {r['trades']:>3} {r['pnl']:>7.0f} {r['wr']:>5.1f} {r['dd']:>5.1f} {r['wf']:>4} {r['fric_pnl']:>7.0f} {r['score']:>5.1f}")

    out_path = Path(__file__).parent.parent / "reports" / "tradeable_harness" / "grid_search.json"
    output = {"cache": str(CACHE_PATH), "n_coins": len(coins), "baseline": base_r, "n_tested": len(results), "n_passing": len(passing), "top_10": results[:10], "passing": passing[:5], "best": passing[0] if passing else None}

    if passing:
        best = passing[0]
        print(f"\n  BEST PASSING: {best['label']}")
        print(f"  Config: {json.dumps(best['cfg'], sort_keys=True)}")
        print(f"\n--- FULL 5-FOLD WF on best ---")
        wf5 = purged_walk_forward(indicators, coins, normalize_cfg(dict(best["cfg"])))
        for f in wf5["folds"]:
            sym = "PASS" if f["pass"] else "FAIL"
            print(f"  F{f['fold']}: {f['test_bars']} {f['test_trades']}tr ${f['test_pnl']} DD{f['test_dd']}% [{sym}]")
        print(f"  Result: {wf5['wf_label']} go={wf5['go']} soft={wf5['soft_go']}")
        output["best_wf5"] = wf5
    else:
        print("\n  NO PASSING CONFIGS")

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    print(f"Total: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
