#!/usr/bin/env python3
"""
MEXC Trades-Gate Sweep — adaptive_maxpos variants to reach trades >= 250.

ADR-4H-014: Hold the trades >= 250 gate. Test 2 wrapper relaxations:
  - relaxed_A: adaptive_maxpos 2/2/1 (allow 2 slots at DD 10-20%)
  - relaxed_B: adaptive_maxpos 3/2/1 (allow 3 slots when healthy)

Same engine config as combined deploy (report 008):
  - Entry: vol_mult=3.5, rsi_max=35, top-200 universe, full-range
  - Exit: rsi_rec_min_bars=5
  - dd_throttle: 5%/0.25x (unchanged)
  - Fee: MEXC 10bps
  - Sizing: fixed $2000/trade

Full truth-pass battery per variant + acceptance gates evaluation.

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_mexc_trades_gate_sweep.py
"""
from __future__ import annotations

import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

DATA_ROOT = Path.home() / "CryptogemData"
V2_DATA_FILE = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h" / "candle_cache_4h_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

# ---------------------------------------------------------------------------
# Constants (same as combined deploy)
# ---------------------------------------------------------------------------
CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

MIN_BARS_TOP200 = 2160
TOP_N = 200
MAX_RETURN_RATIO = 1.0

N_RESAMPLES = 1000
SEED = 42
N_WINDOWS = 5

EXIT_PARAMS = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 5,
}

DD_THROTTLE_THRESHOLD = 0.05
DD_THROTTLE_SCALE = 0.25

# Acceptance gates
GATE_PF = 1.30
GATE_DD = 20.0
GATE_BOOT_P5 = 0.85
GATE_BOOT_PROF = 80.0
GATE_WINDOW = 4
GATE_TRADES = 250

# ---------------------------------------------------------------------------
# Sweep variants
# ---------------------------------------------------------------------------
VARIANTS = [
    {
        "name": "baseline_2_1_1",
        "label": "Baseline (2/1/1) — from report 008",
        "maxpos_normal": 2,
        "maxpos_dd10": 1,
        "maxpos_dd20": 1,
    },
    {
        "name": "relaxed_A_2_2_1",
        "label": "Relaxed A (2/2/1) — allow 2 at DD 10-20%",
        "maxpos_normal": 2,
        "maxpos_dd10": 2,
        "maxpos_dd20": 1,
    },
    {
        "name": "relaxed_B_3_2_1",
        "label": "Relaxed B (3/2/1) — allow 3 when healthy",
        "maxpos_normal": 3,
        "maxpos_dd10": 2,
        "maxpos_dd20": 1,
    },
]

REPORT_ID = "mexc_trades_gate_sweep_009"


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Reused functions from combined deploy
# ===========================================================================

def load_top200():
    print("\n  Loading top-200 universe...")
    with open(V2_DATA_FILE) as f:
        raw_data = json.load(f)
    coins_all = [k for k in raw_data if not k.startswith("_")]
    eligible = []
    for pair in coins_all:
        candles = raw_data[pair]
        n = len(candles)
        if n < MIN_BARS_TOP200:
            continue
        vols = [c.get("volume", 0) or 0 for c in candles[-720:]]
        eligible.append((pair, n, median(vols)))
    eligible.sort(key=lambda x: x[2], reverse=True)
    top200 = eligible[:TOP_N]
    coins = sorted([t[0] for t in top200])
    data = {c: raw_data[c] for c in coins}
    bars_counts = [len(data[c]) for c in coins]
    print(f"  Coins: {len(coins)}, Bars: {min(bars_counts)}-{max(bars_counts)}, "
          f"median: {int(median(bars_counts))}")
    return data, coins, bars_counts


def normalize_trades(trade_list, notional=INITIAL_CAPITAL):
    fixed = []
    n_capped = 0
    for t in trade_list:
        size = t.get("size", t.get("size_usd", notional))
        if size <= 0:
            size = notional
        ret = t["pnl"] / size
        if abs(ret) > MAX_RETURN_RATIO:
            ret = MAX_RETURN_RATIO if ret > 0 else -MAX_RETURN_RATIO
            n_capped += 1
        ft = dict(t)
        ft["pnl"] = round(ret * notional, 2)
        ft["size"] = notional
        ft["_orig_pnl"] = round(t["pnl"], 2)
        ft["_orig_size"] = round(size, 2)
        fixed.append(ft)
    return fixed, n_capped


def sort_trades(trades):
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


def apply_dd_throttle(trades, dd_threshold, size_scale, initial_capital=INITIAL_CAPITAL):
    sorted_t = sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital
    for t in sorted_t:
        current_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        scale = size_scale if current_dd >= dd_threshold else 1.0
        new_t = dict(t)
        new_t["pnl"] = round(t["pnl"] * scale, 2)
        new_t["size"] = round(t.get("size", INITIAL_CAPITAL) * scale, 2)
        new_t["_dd_scale"] = scale
        result.append(new_t)
        equity += new_t["pnl"]
        if equity > peak_equity:
            peak_equity = equity
    return result


def apply_adaptive_maxpos(trades, normal_max, dd10_max, dd20_max,
                          initial_capital=INITIAL_CAPITAL):
    sorted_t = sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital
    open_positions = []
    for t in sorted_t:
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]
        open_positions = [(eb, xb) for eb, xb in open_positions if xb > entry_bar]
        current_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        if current_dd < 0.10:
            max_pos = normal_max
        elif current_dd < 0.20:
            max_pos = dd10_max
        else:
            max_pos = dd20_max
        if len(open_positions) >= max_pos:
            continue
        open_positions.append((entry_bar, exit_bar))
        result.append(dict(t))
        equity += t["pnl"]
        if equity > peak_equity:
            peak_equity = equity
    return result


def compute_metrics(trades, initial_capital=INITIAL_CAPITAL):
    if not trades:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0, "dd": 0.0, "wr": 0.0,
                "final_equity": initial_capital, "ev_trade": 0.0, "trades_per_day": 0.0}
    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    gp = gl = 0.0
    n_wins = 0
    for t in trades:
        pnl = t["pnl"]
        equity += pnl
        if pnl > 0:
            gp += pnl
            n_wins += 1
        else:
            gl += abs(pnl)
        if equity > peak:
            peak = equity
        if peak > 0:
            dd_pct = (peak - equity) / peak * 100
            if dd_pct > max_dd:
                max_dd = dd_pct
    n = len(trades)
    pf = gp / gl if gl > 0 else (99.99 if gp > 0 else 0.0)
    total_pnl = equity - initial_capital
    wr = n_wins / n * 100 if n > 0 else 0.0
    ev = total_pnl / n if n > 0 else 0.0
    if trades:
        first_bar = min(t["entry_bar"] for t in trades)
        last_bar = max(t["exit_bar"] for t in trades)
        n_bars = last_bar - first_bar + 1
        n_days = n_bars * 4 / 24
        tpd = n / n_days if n_days > 0 else 0
    else:
        tpd = 0
    return {
        "trades": n, "pf": round(min(pf, 99.99), 4),
        "pnl": round(total_pnl, 2), "dd": round(max_dd, 2),
        "wr": round(wr, 2), "final_equity": round(equity, 2),
        "ev_trade": round(ev, 2), "trades_per_day": round(tpd, 2),
    }


def exit_attribution(trades):
    CLASS_A = {"RSI RECOVERY", "DC TARGET", "BB TARGET", "PROFIT TARGET"}
    by_reason = {}
    for t in trades:
        reason = t.get("reason", "UNKNOWN")
        if reason not in by_reason:
            by_reason[reason] = {"class": "A" if reason in CLASS_A else "B",
                                 "count": 0, "pnl": 0.0, "wins": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_reason[reason]["wins"] += 1
    for r in by_reason.values():
        r["wr"] = round(100 * r["wins"] / r["count"], 1) if r["count"] > 0 else 0
        r["pnl"] = round(r["pnl"], 2)
    return by_reason


# ===========================================================================
# Engine run — produces raw + fixed trades (shared across variants)
# ===========================================================================

def run_engine_base(data, coins, signal_fn, params, indicators, fee,
                    start_bar=START_BAR, end_bar=None):
    """Run engine + fixed-notional ONLY (no wrappers yet)."""
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")
    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=fee, exit_mode="dc",
        start_bar=start_bar, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=end_bar,
    )
    fixed_trades, n_capped = normalize_trades(r.trade_list)
    fixed_trades = sort_trades(fixed_trades)
    return fixed_trades, n_capped, len(r.trade_list)


def apply_wrappers(fixed_trades, variant):
    """Apply dd_throttle + adaptive_maxpos for a specific variant."""
    throttled = apply_dd_throttle(fixed_trades,
                                  dd_threshold=DD_THROTTLE_THRESHOLD,
                                  size_scale=DD_THROTTLE_SCALE)
    wrapped = apply_adaptive_maxpos(throttled,
                                     normal_max=variant["maxpos_normal"],
                                     dd10_max=variant["maxpos_dd10"],
                                     dd20_max=variant["maxpos_dd20"])
    return wrapped


# ===========================================================================
# Truth-pass tests
# ===========================================================================

def compute_5way_windows(max_bars):
    usable = max_bars - START_BAR
    fifth = usable // N_WINDOWS
    windows = {}
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        start = START_BAR + i * fifth
        end = START_BAR + (i + 1) * fifth if i < N_WINDOWS - 1 else max_bars
        windows[name] = {"start": start, "end": end}
    windows["max_bars"] = max_bars
    return windows


def run_variant_pipeline(data, coins, signal_fn, params, indicators, fee,
                         variant, start_bar=START_BAR, end_bar=None):
    """Engine → fixed-notional → variant wrappers → metrics."""
    fixed_trades, n_capped, n_raw = run_engine_base(
        data, coins, signal_fn, params, indicators, fee,
        start_bar=start_bar, end_bar=end_bar)
    wrapped = apply_wrappers(fixed_trades, variant)
    metrics = compute_metrics(wrapped)
    return {
        **metrics,
        "n_raw": n_raw,
        "n_fixed": len(fixed_trades),
        "n_wrapped": len(wrapped),
        "n_skipped": len(fixed_trades) - len(wrapped),
        "n_capped": n_capped,
        "trade_list": wrapped,
    }


def test_window_split(data, coins, signal_fn, params, indicators, fee,
                      windows, variant):
    results = {}
    n_profitable = 0
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = windows[name]
        bt = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                                  fee=fee, variant=variant,
                                  start_bar=w["start"], end_bar=w["end"])
        results[name] = {
            "start": w["start"], "end": w["end"],
            "trades": bt["trades"], "pf": bt["pf"],
            "pnl": bt["pnl"], "wr": bt["wr"], "dd": bt["dd"],
        }
        if bt["pf"] >= 1.0 and bt["trades"] > 0:
            n_profitable += 1
    results["n_profitable"] = n_profitable
    results["pass"] = n_profitable >= GATE_WINDOW
    return results


def test_walk_forward(data, coins, signal_fn, params, indicators, fee,
                      windows, variant):
    max_bars = windows["max_bars"]
    usable = max_bars - START_BAR
    third = usable // 3
    early_end = START_BAR + third
    mid_end = START_BAR + 2 * third

    cal_a = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                                 fee=fee, variant=variant,
                                 start_bar=START_BAR, end_bar=early_end)
    test_a = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                                  fee=fee, variant=variant,
                                  start_bar=early_end, end_bar=max_bars)
    split_a_pass = (cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
                    and test_a["pf"] >= 0.9 and test_a["trades"] > 0)

    cal_b = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                                 fee=fee, variant=variant,
                                 start_bar=START_BAR, end_bar=mid_end)
    test_b = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                                  fee=fee, variant=variant,
                                  start_bar=mid_end, end_bar=max_bars)
    split_b_pass = (cal_b["pf"] >= 1.0 and cal_b["trades"] > 0
                    and test_b["pf"] >= 0.9 and test_b["trades"] > 0)

    return {
        "split_a": {
            "cal": {"bars": f"{START_BAR}-{early_end}", "trades": cal_a["trades"],
                    "pf": cal_a["pf"], "pnl": cal_a["pnl"]},
            "test": {"bars": f"{early_end}-{max_bars}", "trades": test_a["trades"],
                     "pf": test_a["pf"], "pnl": test_a["pnl"]},
            "pass": split_a_pass,
        },
        "split_b": {
            "cal": {"bars": f"{START_BAR}-{mid_end}", "trades": cal_b["trades"],
                    "pf": cal_b["pf"], "pnl": cal_b["pnl"]},
            "test": {"bars": f"{mid_end}-{max_bars}", "trades": test_b["trades"],
                     "pf": test_b["pf"], "pnl": test_b["pnl"]},
            "pass": split_b_pass,
        },
        "pass": split_a_pass or split_b_pass,
    }


def test_bootstrap(trade_list, n_resamples=N_RESAMPLES):
    if len(trade_list) < 10:
        return {"pass": False, "n_trades": len(trade_list)}
    rng = np.random.default_rng(SEED)
    pnls = np.array([t["pnl"] for t in trade_list])
    n = len(pnls)
    pfs, final_pnls = [], []
    for _ in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        gp = np.sum(sample[sample > 0])
        gl = np.abs(np.sum(sample[sample < 0]))
        pf = gp / gl if gl > 0 else (99.99 if gp > 0 else 0)
        pfs.append(pf)
        final_pnls.append(np.sum(sample))
    pfs = np.array(pfs)
    final_pnls = np.array(final_pnls)
    return {
        "n_resamples": n_resamples, "n_trades": n,
        "median_pf": round(float(np.median(pfs)), 4),
        "p5_pf": round(float(np.percentile(pfs, 5)), 4),
        "p95_pf": round(float(np.percentile(pfs, 95)), 4),
        "median_pnl": round(float(np.median(final_pnls)), 2),
        "p5_pnl": round(float(np.percentile(final_pnls, 5)), 2),
        "pct_profitable": round(float(np.mean(final_pnls > 0) * 100), 1),
        "pass": bool(
            np.percentile(pfs, 5) >= GATE_BOOT_P5
            and np.mean(final_pnls > 0) * 100 >= GATE_BOOT_PROF
        ),
    }


def check_determinism(data, coins, signal_fn, params, indicators, fee, variant):
    r1 = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                              fee=fee, variant=variant)
    r2 = run_variant_pipeline(data, coins, signal_fn, params, indicators,
                              fee=fee, variant=variant)
    match = (r1["trades"] == r2["trades"]
             and abs(r1["pf"] - r2["pf"]) < 1e-6
             and abs(r1["pnl"] - r2["pnl"]) < 0.01)
    return {
        "pass": match,
        "run1": {"trades": r1["trades"], "pf": r1["pf"], "pnl": r1["pnl"]},
        "run2": {"trades": r2["trades"], "pf": r2["pf"], "pnl": r2["pnl"]},
    }


def evaluate_gates(full_metrics, ws, wf, bs, det):
    gates = {
        "pf": {"gate": f"PF >= {GATE_PF}", "value": full_metrics["pf"],
               "pass": full_metrics["pf"] >= GATE_PF},
        "dd": {"gate": f"DD <= {GATE_DD}%", "value": full_metrics["dd"],
               "pass": full_metrics["dd"] <= GATE_DD},
        "bootstrap_p5": {"gate": f"Boot P5 PF >= {GATE_BOOT_P5}", "value": bs["p5_pf"],
                         "pass": bs["p5_pf"] >= GATE_BOOT_P5},
        "bootstrap_prof": {"gate": f"Boot %prof >= {GATE_BOOT_PROF}%", "value": bs["pct_profitable"],
                           "pass": bs["pct_profitable"] >= GATE_BOOT_PROF},
        "window_split": {"gate": f"Window >= {GATE_WINDOW}/{N_WINDOWS}", "value": ws["n_profitable"],
                         "pass": ws["pass"]},
        "trades": {"gate": f"Trades >= {GATE_TRADES}", "value": full_metrics["trades"],
                   "pass": full_metrics["trades"] >= GATE_TRADES},
        "determinism": {"gate": "Determinism", "value": "PASS" if det["pass"] else "FAIL",
                        "pass": det["pass"]},
    }
    n_pass = sum(1 for g in gates.values() if g["pass"])
    all_pass = n_pass == len(gates)
    return gates, n_pass, all_pass


def _verdict(ws_pass, wf_pass, bs_pass):
    n = sum([ws_pass, wf_pass, bs_pass])
    if n == 3:
        return "VERIFIED", 3
    elif n == 2:
        return "CONDITIONAL", 2
    else:
        return "FAILED", n


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    git = _git_hash()

    print("\n" + "=" * 72)
    print("  MEXC TRADES-GATE SWEEP — adaptive_maxpos variants")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  ADR: 4H-014")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Load data + precompute (shared across all variants)
    # ------------------------------------------------------------------
    data, coins, bars_counts = load_top200()
    n_coins = len(coins)
    max_bar = max(bars_counts)
    n_days = (max_bar - START_BAR) * 4 / 24

    import importlib
    _s2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _s2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
    _hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = _s2_ind.precompute_all(data, coins)
    market_context = _s2_ctx.precompute_sprint2_context(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s")

    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])
    base_params["vol_mult"] = 3.5
    base_params["rsi_max"] = 35
    base_params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c
    base_params.update(EXIT_PARAMS)

    windows = compute_5way_windows(max_bar)

    print(f"\n  Signal: {cfg041['hypothesis_name']}")
    print(f"  Max bars: {max_bar}, Days: ~{n_days:.0f}")
    print(f"  Variants: {len(VARIANTS)}")

    # ------------------------------------------------------------------
    # Run all variants
    # ------------------------------------------------------------------
    all_results = {}

    for vi, variant in enumerate(VARIANTS):
        vname = variant["name"]
        maxpos_str = f"{variant['maxpos_normal']}/{variant['maxpos_dd10']}/{variant['maxpos_dd20']}"

        print(f"\n{'='*72}")
        print(f"  VARIANT {vi+1}/{len(VARIANTS)}: {variant['label']}")
        print(f"  adaptive_maxpos: {maxpos_str}")
        print(f"{'='*72}")

        # Full-range run
        t0 = time.time()
        full = run_variant_pipeline(data, coins, signal_fn, base_params,
                                    indicators, fee=MEXC_FEE, variant=variant)
        full_ea = exit_attribution(full["trade_list"])
        print(f"\n  Full: {full['trades']}tr, PF={full['pf']:.4f}, "
              f"P&L=${full['pnl']:+,.0f}, DD={full['dd']:.1f}%, "
              f"WR={full['wr']:.1f}%, trades/day={full['trades_per_day']:.2f}")
        print(f"  Skipped: {full['n_skipped']}, Capped: {full['n_capped']}")

        # Window split
        print(f"\n  5-Way Window Split:")
        ws = test_window_split(data, coins, signal_fn, base_params,
                               indicators, fee=MEXC_FEE, windows=windows,
                               variant=variant)
        for i in range(N_WINDOWS):
            name = f"w{i+1}"
            w = ws[name]
            mark = "✅" if w["pf"] >= 1.0 and w["trades"] > 0 else "❌"
            print(f"    {name}: {w['trades']}tr PF={w['pf']:.2f} ${w['pnl']:+,.0f} {mark}")
        print(f"    → {ws['n_profitable']}/{N_WINDOWS} "
              f"{'PASS' if ws['pass'] else 'FAIL'}")

        # Walk-forward
        wf = test_walk_forward(data, coins, signal_fn, base_params,
                               indicators, fee=MEXC_FEE, windows=windows,
                               variant=variant)
        for sname, s in [("A", wf["split_a"]), ("B", wf["split_b"])]:
            mark = "✅" if s["pass"] else "❌"
            print(f"  WF Split {sname}: cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                  f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f} {mark}")

        # Bootstrap
        bs = test_bootstrap(full["trade_list"])
        print(f"  Bootstrap: P5={bs['p5_pf']:.2f}, median={bs['median_pf']:.2f}, "
              f"%prof={bs['pct_profitable']:.1f}%")

        # Determinism
        det = check_determinism(data, coins, signal_fn, base_params,
                                indicators, fee=MEXC_FEE, variant=variant)
        print(f"  Determinism: {'PASS' if det['pass'] else 'FAIL'}")

        # Gates
        gates, n_gates, all_gates = evaluate_gates(full, ws, wf, bs, det)
        verdict, n_tp = _verdict(ws["pass"], wf["pass"], bs["pass"])

        print(f"\n  GATES: {n_gates}/7")
        for gname, g in gates.items():
            mark = "✅" if g["pass"] else "❌"
            print(f"    {mark} {g['gate']}: {g['value']}")
        print(f"  Truth-Pass: {verdict} ({n_tp}/3)")
        deploy = "YES ✅" if all_gates else "NO ❌"
        print(f"  Deploy: {deploy}")
        print(f"  ({time.time()-t0:.1f}s)")

        all_results[vname] = {
            "variant": variant,
            "full_metrics": {k: v for k, v in full.items() if k != "trade_list"},
            "exit_attribution": full_ea,
            "window_split": {k: v for k, v in ws.items()},
            "walk_forward": wf,
            "bootstrap": bs,
            "determinism": det,
            "gates": gates,
            "n_gates_pass": n_gates,
            "all_gates_pass": all_gates,
            "verdict": verdict,
            "tests_passed": n_tp,
        }

    # ------------------------------------------------------------------
    # Scoreboard
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  SCOREBOARD")
    print(f"{'='*72}")
    print(f"  {'Variant':<20} {'maxpos':<10} {'Trades':>6} {'PF':>7} "
          f"{'P&L':>10} {'DD':>6} {'Win':>4} {'Boot':>5} "
          f"{'Gates':>5} {'Deploy':>6}")
    print(f"  {'-'*20} {'-'*10} {'-'*6} {'-'*7} {'-'*10} {'-'*6} "
          f"{'-'*4} {'-'*5} {'-'*5} {'-'*6}")

    best_variant = None
    for vname, vr in all_results.items():
        v = vr["variant"]
        m = vr["full_metrics"]
        maxpos_str = f"{v['maxpos_normal']}/{v['maxpos_dd10']}/{v['maxpos_dd20']}"
        ws_str = f"{vr['window_split']['n_profitable']}/5"
        bs_str = f"{vr['bootstrap']['p5_pf']:.2f}"
        g_str = f"{vr['n_gates_pass']}/7"
        d_str = "YES" if vr["all_gates_pass"] else "NO"
        d_mark = "✅" if vr["all_gates_pass"] else "❌"
        print(f"  {vname:<20} {maxpos_str:<10} {m['trades']:>6} {m['pf']:>7.4f} "
              f"${m['pnl']:>+9,.0f} {m['dd']:>5.1f}% {ws_str:>4} {bs_str:>5} "
              f"{g_str:>5} {d_str:>4} {d_mark}")
        if vr["all_gates_pass"]:
            if best_variant is None or m["pf"] > all_results[best_variant]["full_metrics"]["pf"]:
                best_variant = vname

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  REPORTS")
    print(f"{'='*72}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "mexc_trades_gate_sweep",
        "experiment_id": REPORT_ID,
        "adr": "4H-014",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, >={MIN_BARS_TOP200} bars",
            "n_coins": n_coins,
        },
        "fee": MEXC_FEE,
        "fee_model": "mexc_spot_10bps",
        "sizing": "fixed_notional_2000",
        "config": {
            "hypothesis_id": CONFIG_041_HYP_ID,
            "entry": {"vol_mult": 3.5, "rsi_max": 35},
            "exit": EXIT_PARAMS,
            "dd_throttle": {"threshold": DD_THROTTLE_THRESHOLD, "scale": DD_THROTTLE_SCALE},
        },
        "variants": {vn: {k: v for k, v in vr.items() if k != "trade_list"}
                     for vn, vr in all_results.items()},
        "best_variant": best_variant,
        "scoreboard": {
            vn: {
                "maxpos": f"{vr['variant']['maxpos_normal']}/{vr['variant']['maxpos_dd10']}/{vr['variant']['maxpos_dd20']}",
                "trades": vr["full_metrics"]["trades"],
                "pf": vr["full_metrics"]["pf"],
                "pnl": vr["full_metrics"]["pnl"],
                "dd": vr["full_metrics"]["dd"],
                "windows": vr["window_split"]["n_profitable"],
                "boot_p5": vr["bootstrap"]["p5_pf"],
                "gates": vr["n_gates_pass"],
                "deploy": vr["all_gates_pass"],
                "verdict": vr["verdict"],
            }
            for vn, vr in all_results.items()
        },
    }

    json_path = REPORT_DIR / f"{REPORT_ID}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  JSON: {json_path}")

    # --- MD ---
    md_lines = [
        "# MEXC Trades-Gate Sweep — Report",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**ADR**: 4H-014",
        f"**Universe**: Top {TOP_N}, >={MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Fee**: MEXC 10bps | **Sizing**: Fixed $2,000/trade",
        "",
        "## Purpose",
        "",
        "ADR-4H-014: Hold trades ≥ 250 gate. Test adaptive_maxpos relaxations",
        "to recover trades while keeping DD ≤ 20% and all other gates green.",
        "",
        "## Scoreboard",
        "",
        "| Variant | maxpos | Trades | PF | P&L | DD | Win | Boot P5 | Gates | Deploy |",
        "|---------|:------:|-------:|---:|----:|---:|:---:|--------:|:-----:|:------:|",
    ]
    for vn, vr in all_results.items():
        v = vr["variant"]
        m = vr["full_metrics"]
        mp = f"{v['maxpos_normal']}/{v['maxpos_dd10']}/{v['maxpos_dd20']}"
        ws_s = f"{vr['window_split']['n_profitable']}/5"
        d_mark = "✅" if vr["all_gates_pass"] else "❌"
        md_lines.append(
            f"| {vn} | {mp} | {m['trades']} | {m['pf']:.2f} "
            f"| ${m['pnl']:+,.0f} | {m['dd']:.1f}% | {ws_s} "
            f"| {vr['bootstrap']['p5_pf']:.2f} | {vr['n_gates_pass']}/7 | {d_mark} |"
        )
    md_lines.append("")

    # Per-variant detail
    for vn, vr in all_results.items():
        v = vr["variant"]
        m = vr["full_metrics"]
        mp = f"{v['maxpos_normal']}/{v['maxpos_dd10']}/{v['maxpos_dd20']}"
        md_lines.extend([
            f"## {v['label']}",
            "",
            f"**adaptive_maxpos**: {mp}",
            "",
            f"| Metric | Value |",
            f"|--------|------:|",
            f"| Trades | {m['trades']} |",
            f"| PF | {m['pf']:.4f} |",
            f"| P&L | ${m['pnl']:+,.0f} |",
            f"| DD | {m['dd']:.1f}% |",
            f"| WR | {m['wr']:.1f}% |",
            f"| EV/trade | ${m['ev_trade']:.2f} |",
            f"| Trades/day | {m['trades_per_day']:.2f} |",
            "",
        ])

        # Gates
        md_lines.append("**Gates**:")
        md_lines.append("")
        md_lines.append("| Gate | Value | Status |")
        md_lines.append("|------|------:|-------:|")
        for gn, g in vr["gates"].items():
            mark = "✅" if g["pass"] else "❌"
            md_lines.append(f"| {g['gate']} | {g['value']} | {mark} |")
        md_lines.append("")
        md_lines.append(f"**Truth-Pass**: {vr['verdict']} ({vr['tests_passed']}/3)")
        md_lines.append(f"**Gates**: {vr['n_gates_pass']}/7")
        deploy_str = "YES ✅" if vr["all_gates_pass"] else "NO ❌"
        md_lines.append(f"**Deploy**: {deploy_str}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    # Conclusion
    md_lines.append("## Conclusion")
    md_lines.append("")
    if best_variant:
        bv = all_results[best_variant]
        bm = bv["full_metrics"]
        md_lines.append(f"**Winner: {best_variant}** — {bm['trades']} trades, "
                        f"PF={bm['pf']:.2f}, DD={bm['dd']:.1f}%, 7/7 gates ✅")
    else:
        md_lines.append("**No variant passes all 7 gates.** Further investigation needed.")
    md_lines.append("")

    md_path = REPORT_DIR / f"{REPORT_ID}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"  MD:   {md_path}")

    # ------------------------------------------------------------------
    # Final
    # ------------------------------------------------------------------
    elapsed = time.time() - t_total
    print(f"\n{'='*72}")
    print(f"  DONE in {elapsed:.1f}s")
    if best_variant:
        bm = all_results[best_variant]["full_metrics"]
        print(f"  WINNER: {best_variant} — {bm['trades']}tr, PF={bm['pf']:.4f}, "
              f"DD={bm['dd']:.1f}%, 7/7 gates")
    else:
        print(f"  NO WINNER — no variant passes all 7 gates")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
