#!/usr/bin/env python3
"""
MS max_pos sensitivity — ms_018 with max_pos=1,2,3,5,8
=========================================================
Quick comparison to find optimal position sizing.
"""
import sys, time, json
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

import importlib

_engine = importlib.import_module('strategies.4h.sprint3.engine')
_hyps = importlib.import_module('strategies.ms.hypotheses')
_ind = importlib.import_module('strategies.ms.indicators')
_resolver = importlib.import_module('strategies.4h.data_resolver')

DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 60
MAX_POS_VALUES = [1, 2, 3, 5, 8]


def main():
    # Load data
    print(f"\n{'='*72}")
    print("  MS max_pos SENSITIVITY — ms_018 (shift_pb shallow)")
    print(f"{'='*72}\n")

    print("  Loading data...")
    path = _resolver.resolve_dataset(DATASET_ID)
    with open(path, "r") as f:
        data = json.load(f)
    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    print(f"  {len(coins)} coins loaded")

    print("  Computing MS indicators...")
    t0 = time.time()
    indicators = _ind.precompute_ms_indicators(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s\n")

    # Get ms_018 config
    all_configs = _hyps.build_sweep_configs()
    ms_018 = None
    for c in all_configs:
        if c["id"] == "ms_018_mse_shallow":
            ms_018 = c
            break
    if ms_018 is None:
        print("  ERROR: ms_018 not found!")
        return

    signal_fn = ms_018["signal_fn"]
    base_params = dict(ms_018["params"])

    # Run for each max_pos
    print(f"  {'max_pos':>8} | {'Trades':>7} | {'PF':>6} | {'P&L':>10} | {'DD%':>6} | {'WR%':>5} | {'Avg bars':>9} | {'Max open':>9}")
    print(f"  {'─'*80}")

    results = []
    for mp in MAX_POS_VALUES:
        params = dict(base_params)
        params["max_pos"] = mp

        bt = _engine.run_backtest(
            data=data,
            coins=coins,
            signal_fn=signal_fn,
            params=params,
            indicators=indicators,
            exit_mode="dc",
            start_bar=START_BAR,
        )

        trades = bt.trades
        pf = bt.pf
        pnl = bt.pnl
        dd = bt.dd
        wr = bt.wr * 100

        # Avg holding period from trade_list
        avg_bars = 0
        if bt.trade_list:
            bars_list = [t.get('bars_held', t.get('actual_bars', 0)) for t in bt.trade_list]
            avg_bars = sum(bars_list) / len(bars_list) if bars_list else 0

        row = {
            "max_pos": mp,
            "trades": trades,
            "pf": round(pf, 2),
            "pnl": round(pnl, 2),
            "dd_pct": round(dd, 1),
            "wr_pct": round(wr, 1),
            "avg_bars": round(avg_bars, 1),
        }
        results.append(row)

        print(f"  {mp:>8} | {trades:>7} | {pf:>6.2f} | ${pnl:>9,.0f} | {dd:>5.1f} | {wr:>5.1f} | {avg_bars:>9.1f} |")

    # Summary
    print(f"\n  {'='*72}")
    print("  ANALYSIS")
    print(f"  {'='*72}\n")

    best_pf = max(results, key=lambda r: r["pf"])
    best_pnl = max(results, key=lambda r: r["pnl"])
    best_dd = min(results, key=lambda r: r["dd_pct"])

    print(f"  Best PF:  max_pos={best_pf['max_pos']} → PF={best_pf['pf']}")
    print(f"  Best P&L: max_pos={best_pnl['max_pos']} → ${best_pnl['pnl']:,.0f}")
    print(f"  Best DD:  max_pos={best_dd['max_pos']} → {best_dd['dd_pct']}%")

    # Risk-adjusted: PF / DD
    print(f"\n  Risk-adjusted (PF / DD%):")
    for r in results:
        ratio = r["pf"] / r["dd_pct"] * 100 if r["dd_pct"] > 0 else 0
        print(f"    max_pos={r['max_pos']}: {ratio:.2f}")

    # Save
    out = {
        "date": datetime.now(timezone.utc).isoformat(),
        "config": "ms_018_mse_shallow",
        "dataset": DATASET_ID,
        "results": results,
    }
    out_path = REPO_ROOT / "reports" / "ms" / "maxpos_sensitivity.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    main()
