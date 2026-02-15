#!/usr/bin/env python3
"""
Window Sweep - Temporal Stability Analysis
===========================================
Tests configs on multiple time windows to detect overfitting.
If a strategy only works in one specific period, it is likely overfit.

Windows tested:
  Fixed (from end):  last 30d, 60d, 90d, 120d
  Rolling (30d each): non-overlapping windows covering full dataset

Verdict: STABLE if >=75% windows positive AND no window >30% DD AND worst > -$500
"""
import sys
import json
import hashlib
import math
import time as _time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    START_BAR, INITIAL_CAPITAL, KRAKEN_FEE
)

# ============================================================
# CONFIG
# ============================================================
DATA_FILE = BASE_DIR.parent / "data" / "candle_cache_tradeable.json"
EXPECTED_MD5 = "f6fd2ca303b677fe67ceede4a6b8f7ba"
REPORTS_DIR = BASE_DIR.parent / "reports"

CONFIGS = {
    "C1": {
        "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
        "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15,
        "vol_confirm": True, "vol_spike_mult": 3.0,
    },
    "GRID_BEST": {
        "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
        "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12,
        "vol_confirm": True, "vol_spike_mult": 2.5,
    },
}

# Stability thresholds
STABLE_POS_PCT = 0.75
STABLE_MAX_DD = 30.0
STABLE_WORST_PNL = -500.0


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_windows(max_bars):
    windows = {}
    bars_per_day = 6

    # Fixed windows from end
    for days in [30, 60, 90, 120]:
        n_bars = days * bars_per_day
        raw_start = max_bars - n_bars
        start = max(START_BAR, raw_start)
        end = max_bars
        windows[f"fixed_{days}d"] = (start, end)

    # Rolling 30-day non-overlapping windows
    roll_size = 30 * bars_per_day  # 180 bars
    roll_start = START_BAR
    roll_idx = 1
    while roll_start < max_bars:
        roll_end = min(roll_start + roll_size, max_bars)
        windows[f"roll_{roll_idx}"] = (roll_start, roll_end)
        roll_start = roll_end
        roll_idx += 1

    return windows


def run_window(indicators, coins, cfg, start_bar, end_bar):
    bt = run_backtest(indicators, coins, cfg,
                      start_bar=start_bar, end_bar=end_bar)
    pf_val = bt["pf"]
    if pf_val == float("inf"):
        pf_val = 999.99
    return {
        "trades": bt["trades"],
        "pnl": round(bt["pnl"], 2),
        "wr": round(bt["wr"], 1),
        "pf": round(pf_val, 2),
        "dd": round(bt["dd"], 1),
        "start_bar": start_bar,
        "end_bar": end_bar,
        "n_bars": end_bar - start_bar,
    }


def calc_stability(results, config_name):
    all_windows = list(results.keys())
    rolling_windows = [w for w in all_windows if w.startswith("roll_")]

    n_total = len(all_windows)
    n_positive = sum(1 for w in all_windows if results[w]["pnl"] > 0)
    n_zero_trades = sum(1 for w in all_windows if results[w]["trades"] == 0)
    worst_pnl = min(results[w]["pnl"] for w in all_windows)
    worst_window = min(all_windows, key=lambda w: results[w]["pnl"])
    max_dd_any = max(results[w]["dd"] for w in all_windows)
    max_dd_window = max(all_windows, key=lambda w: results[w]["dd"])

    # Rolling windows CV
    roll_pnls = [results[w]["pnl"] for w in rolling_windows]
    if roll_pnls and len(roll_pnls) > 1:
        mean_pnl = sum(roll_pnls) / len(roll_pnls)
        if mean_pnl != 0:
            variance = sum((p - mean_pnl)**2 for p in roll_pnls) / (len(roll_pnls) - 1)
            std_pnl = math.sqrt(variance)
            cv = abs(std_pnl / mean_pnl)
        else:
            cv = float("inf")
    else:
        mean_pnl = roll_pnls[0] if roll_pnls else 0
        cv = float("inf")

    pos_ratio = n_positive / n_total if n_total > 0 else 0
    is_stable = (
        pos_ratio >= STABLE_POS_PCT
        and max_dd_any <= STABLE_MAX_DD
        and worst_pnl > STABLE_WORST_PNL
    )

    fail_reasons = []
    if pos_ratio < STABLE_POS_PCT:
        fail_reasons.append(f"positive ratio {pos_ratio:.0%} < {STABLE_POS_PCT:.0%}")
    if max_dd_any > STABLE_MAX_DD:
        fail_reasons.append(f"max DD {max_dd_any:.1f}% > {STABLE_MAX_DD}%")
    if worst_pnl <= STABLE_WORST_PNL:
        fail_reasons.append(f"worst P&L ${worst_pnl:.0f} <= ${STABLE_WORST_PNL:.0f}")

    cv_out = round(cv, 2) if cv != float("inf") else "inf"

    return {
        "config": config_name,
        "total_windows": n_total,
        "positive_windows": n_positive,
        "positive_ratio": round(pos_ratio, 2),
        "zero_trade_windows": n_zero_trades,
        "worst_pnl": round(worst_pnl, 2),
        "worst_window": worst_window,
        "max_dd": round(max_dd_any, 1),
        "max_dd_window": max_dd_window,
        "rolling_mean_pnl": round(mean_pnl, 2),
        "rolling_cv": cv_out,
        "verdict": "STABLE" if is_stable else "UNSTABLE",
        "fail_reasons": fail_reasons,
    }


def generate_markdown(all_results, all_stability, windows, max_bars):
    lines = []
    lines.append("# Window Sweep - Temporal Stability Report")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Dataset: candle_cache_tradeable.json | Max bars: {max_bars}")
    lines.append(f"Initial capital: ${INITIAL_CAPITAL} | Fee: {KRAKEN_FEE*100:.2f}%")
    lines.append("")
    lines.append("## Window Definitions")
    lines.append("| Window | Start Bar | End Bar | Bars | ~Days |")
    lines.append("|--------|-----------|---------|------|-------|")
    for wname in sorted(windows.keys()):
        s, e = windows[wname]
        n = e - s
        days = n / 6
        lines.append(f"| {wname} | {s} | {e} | {n} | {days:.0f}d |")

    for cfg_name in CONFIGS:
        results = all_results[cfg_name]
        stab = all_stability[cfg_name]
        lines.append("")
        lines.append(f"## Config: {cfg_name}")
        lines.append("```json")
        lines.append(json.dumps(CONFIGS[cfg_name], indent=2))
        lines.append("```")
        lines.append("")
        lines.append("### Window Results")
        lines.append("| Window | Trades | P&L | WR% | PF | DD% | Bars |")
        lines.append("|--------|--------|-----|-----|----|-----|------|")
        for wname in sorted(results.keys()):
            r = results[wname]
            if r["pnl"] >= 0:
                pnl_str = f"+${r['pnl']:.0f}"
            else:
                pnl_str = f"-${abs(r['pnl']):.0f}"
            lines.append(
                f"| {wname} | {r['trades']} | {pnl_str} | "
                f"{r['wr']:.1f} | {r['pf']:.2f} | {r['dd']:.1f} | {r['n_bars']} |"
            )

        verdict_tag = "PASS" if stab["verdict"] == "STABLE" else "FAIL"
        lines.append("")
        lines.append("### Stability Metrics")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Verdict | **{stab['verdict']}** ({verdict_tag}) |")
        lines.append(f"| Positive windows | {stab['positive_windows']}/{stab['total_windows']} ({stab['positive_ratio']:.0%}) |")
        lines.append(f"| Zero-trade windows | {stab['zero_trade_windows']} |")
        lines.append(f"| Worst P&L | ${stab['worst_pnl']:.0f} ({stab['worst_window']}) |")
        lines.append(f"| Max DD | {stab['max_dd']:.1f}% ({stab['max_dd_window']}) |")
        lines.append(f"| Rolling mean P&L | ${stab['rolling_mean_pnl']:.0f} |")
        lines.append(f"| Rolling CV | {stab['rolling_cv']} |")
        if stab["fail_reasons"]:
            lines.append(f"| Fail reasons | {'; '.join(stab['fail_reasons'])} |")

    lines.append("")
    lines.append("## Comparative Summary")
    lines.append("| Config | Verdict | Pos% | Worst P&L | Max DD | Rolling CV |")
    lines.append("|--------|---------|------|-----------|--------|------------|")
    for cfg_name in CONFIGS:
        s = all_stability[cfg_name]
        lines.append(
            f"| {cfg_name} | **{s['verdict']}** | {s['positive_ratio']:.0%} | "
            f"${s['worst_pnl']:.0f} | {s['max_dd']:.1f}% | {s['rolling_cv']} |"
        )

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("WINDOW SWEEP - Temporal Stability Analysis")
    print("=" * 60)

    # Load + verify data
    print(f"\nLoading {DATA_FILE} ...")
    file_md5 = md5_file(DATA_FILE)
    assert file_md5 == EXPECTED_MD5, f"MD5 mismatch: {file_md5} != {EXPECTED_MD5}"
    print(f"  MD5 verified: {file_md5}")

    with open(DATA_FILE) as f:
        data = json.load(f)
    # Filter out metadata keys (prefixed with _)
    coins = [k for k in data.keys() if not k.startswith("_")]
    print(f"  Coins: {len(coins)}")

    max_bars = max(len(data[c]) for c in coins)
    print(f"  Max bars: {max_bars}")

    # Precompute indicators (full dataset)
    print("\nPrecomputing indicators (full dataset)...")
    t0 = _time.time()
    indicators = precompute_all(data, coins)
    print(f"  Done in {_time.time()-t0:.1f}s")

    # Build windows
    windows = build_windows(max_bars)
    print(f"\nWindows defined: {len(windows)}")
    for wname in sorted(windows.keys()):
        s, e = windows[wname]
        print(f"  {wname:12s}: bars {s:4d}-{e:4d}  ({e-s:4d} bars, ~{(e-s)/6:.0f}d)")

    # Run backtests
    all_results = {}
    all_stability = {}

    for cfg_name, cfg in CONFIGS.items():
        cfg = normalize_cfg(dict(cfg))
        print(f"\n{'='*40}")
        print(f"Config: {cfg_name}")
        print(f"  {json.dumps(cfg, sort_keys=True)}")
        print(f"{'='*40}")

        results = {}
        for wname in sorted(windows.keys()):
            start_bar, end_bar = windows[wname]
            bt = run_window(indicators, coins, cfg, start_bar, end_bar)
            results[wname] = bt
            if bt["pnl"] >= 0:
                pnl_s = f"+${bt['pnl']:.0f}"
            else:
                pnl_s = f"-${abs(bt['pnl']):.0f}"
            print(f"  {wname:12s}: {bt['trades']:3d} trades | {pnl_s:>8s} | "
                  f"WR {bt['wr']:5.1f}% | PF {bt['pf']:6.2f} | DD {bt['dd']:5.1f}%")

        stab = calc_stability(results, cfg_name)
        all_results[cfg_name] = results
        all_stability[cfg_name] = stab

        print(f"\n  VERDICT: {stab['verdict']}")
        print(f"  Positive: {stab['positive_windows']}/{stab['total_windows']} "
              f"({stab['positive_ratio']:.0%})")
        print(f"  Worst: ${stab['worst_pnl']:.0f} ({stab['worst_window']})")
        print(f"  Max DD: {stab['max_dd']:.1f}% ({stab['max_dd_window']})")
        print(f"  Rolling CV: {stab['rolling_cv']}")
        if stab["fail_reasons"]:
            for r in stab["fail_reasons"]:
                print(f"  FAIL: {r}")

    # Save reports
    REPORTS_DIR.mkdir(exist_ok=True)

    json_out = {
        "generated": datetime.now().isoformat(),
        "dataset": str(DATA_FILE.name),
        "dataset_md5": file_md5,
        "max_bars": max_bars,
        "n_coins": len(coins),
        "configs": {k: v for k, v in CONFIGS.items()},
        "windows": {k: {"start": v[0], "end": v[1]} for k, v in windows.items()},
        "results": all_results,
        "stability": all_stability,
    }

    json_path = REPORTS_DIR / "window_sweep.json"
    with open(json_path, "w") as f:
        json.dump(json_out, f, indent=2, default=str)
    print(f"\nSaved: {json_path}")

    md_text = generate_markdown(all_results, all_stability, windows, max_bars)
    md_path = REPORTS_DIR / "window_sweep.md"
    with open(md_path, "w") as f:
        f.write(md_text)
    print(f"Saved: {md_path}")

    print("\n" + "="*60)
    print("DONE")
    print("="*60)


if __name__ == "__main__":
    main()
