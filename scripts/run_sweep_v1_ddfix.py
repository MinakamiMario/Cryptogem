#!/usr/bin/env python3
"""
Sweep v1 DD-Fix — Risk wrappers for drawdown reduction on A06.

Config A06 (sweep_v1_006_sv1a06_rsi45_p8_atr2.0):
  VERIFIED (3/3 truth-pass), PF=1.52, 347 trades, DD=63.1%, P&L=+$3,425
  Goal: reduce DD to <= 20-25% without destroying PF (keep PF >= 1.15)

Architecture (cloned from MEXC DD microsweep):
  Phase 0: Load data, precompute sweep_v1 indicators + RSI rank, build universe
  Phase 1: Run engine ONCE (shared trades), apply dd_throttle × adaptive_maxpos
           grid (9 × 3 = 27 combos), quick gate-check
  Phase 2: Full truth-pass on best combo(s) — 3-way window + bootstrap

Wrappers:
  - dd_throttle: reduce position size when equity DD exceeds threshold
  - adaptive_maxpos: reduce max concurrent positions based on DD level

Output: reports/4h/sweep_v1/ddfix/

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_sweep_v1_ddfix.py
"""
from __future__ import annotations

import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

REPORT_DIR = REPO_ROOT / "reports" / "4h" / "sweep_v1" / "ddfix"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
KRAKEN_FEE = 0.0026
INITIAL_CAPITAL = 2000
MIN_BARS = 360
START_BAR = 50
MAX_RETURN_RATIO = 1.0

# A06 config params
A06_PARAMS = {
    "rsi_max": 45,
    "pivot_window": 8,
    "max_atr_dist": 2.0,
    "vol_floor": 0.8,
    "max_pos": 3,
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45,
    "rsi_rec_min_bars": 2,
}

# Truth-pass constants
N_RESAMPLES = 1000
SEED = 42
N_WINDOWS = 3  # 3-way window split (early/mid/late)

# Gates
GATE_PF = 1.15      # keep PF healthy after wrapping
GATE_DD = 25.0       # target DD reduction
GATE_BOOT_P5 = 0.85
GATE_BOOT_PROF = 80.0
GATE_WINDOW = 2      # 2/3 windows profitable
GATE_TRADES = 200     # A06 has 347; wrappers may skip some

# ---------------------------------------------------------------------------
# DD Throttle grid: (threshold, scale)
# ---------------------------------------------------------------------------
DD_THROTTLE_GRID = [
    {"threshold": 0.05, "scale": 0.30, "label": "5%/0.30x"},
    {"threshold": 0.05, "scale": 0.25, "label": "5%/0.25x"},
    {"threshold": 0.05, "scale": 0.22, "label": "5%/0.22x"},
    {"threshold": 0.05, "scale": 0.20, "label": "5%/0.20x"},
    {"threshold": 0.08, "scale": 0.30, "label": "8%/0.30x"},
    {"threshold": 0.08, "scale": 0.25, "label": "8%/0.25x"},
    {"threshold": 0.08, "scale": 0.22, "label": "8%/0.22x"},
    {"threshold": 0.10, "scale": 0.30, "label": "10%/0.30x"},
    {"threshold": 0.10, "scale": 0.25, "label": "10%/0.25x"},
]

# Adaptive maxpos grid: [calm, medium, stressed]
# A06 default max_pos=3
ADAPTIVE_MAXPOS_GRID = [
    {"levels": [3, 2, 1], "label": "3/2/1"},
    {"levels": [2, 1, 1], "label": "2/1/1"},
    {"levels": [3, 2, 0], "label": "3/2/0"},
]

REPORT_ID = "sweep_v1_ddfix_a06_001"


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Trade normalization + metrics (from MEXC microsweep pattern)
# ===========================================================================

def normalize_trades(trade_list, notional=INITIAL_CAPITAL):
    """Normalize trades to fixed notional. Cap extreme returns."""
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
        fixed.append(ft)
    return fixed, n_capped


def sort_trades(trades):
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


def compute_metrics(trades):
    if not trades:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0, "dd": 0.0, "wr": 0.0,
                "ev_trade": 0.0, "trades_per_day": 0.0}
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
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
    total_pnl = equity - INITIAL_CAPITAL
    wr = n_wins / n * 100 if n > 0 else 0.0
    ev = total_pnl / n if n > 0 else 0.0
    first_bar = min(t["entry_bar"] for t in trades)
    last_bar = max(t["exit_bar"] for t in trades)
    n_bars = last_bar - first_bar + 1
    n_days = n_bars * 4 / 24
    tpd = n / n_days if n_days > 0 else 0
    return {
        "trades": n, "pf": round(min(pf, 99.99), 4),
        "pnl": round(total_pnl, 2), "dd": round(max_dd, 2),
        "wr": round(wr, 2), "ev_trade": round(ev, 2),
        "trades_per_day": round(tpd, 2),
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
# Wrappers (dd_throttle + adaptive_maxpos)
# ===========================================================================

def apply_dd_throttle(trades, dd_threshold, size_scale):
    """Scale position size (and P&L proportionally) when in drawdown."""
    sorted_t = sort_trades(trades)
    result = []
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    for t in sorted_t:
        dd = (peak - equity) / peak if peak > 0 else 0.0
        scale = size_scale if dd >= dd_threshold else 1.0
        new_t = dict(t)
        new_t["pnl"] = round(t["pnl"] * scale, 2)
        new_t["size"] = round(t.get("size", INITIAL_CAPITAL) * scale, 2)
        new_t["_dd_scale"] = scale
        result.append(new_t)
        equity += new_t["pnl"]
        if equity > peak:
            peak = equity
    return result


def apply_adaptive_maxpos(trades, levels):
    """Reduce max concurrent positions based on current drawdown.

    levels = [calm_max, medium_max, stressed_max]
    DD < 10%:   calm_max
    DD 10-20%:  medium_max
    DD >= 20%:  stressed_max (0 = skip all trades)
    """
    sorted_t = sort_trades(trades)
    result = []
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    open_positions = []

    calm, medium, stressed = levels

    for t in sorted_t:
        entry_bar = t["entry_bar"]
        open_positions = [(eb, xb) for eb, xb in open_positions if xb > entry_bar]
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd < 0.10:
            max_pos = calm
        elif dd < 0.20:
            max_pos = medium
        else:
            max_pos = stressed
        if len(open_positions) >= max_pos:
            continue
        open_positions.append((entry_bar, t["exit_bar"]))
        result.append(dict(t))
        equity += t["pnl"]
        if equity > peak:
            peak = equity
    return result


def apply_full_wrapper(fixed_trades, throttle_cfg, maxpos_cfg):
    """dd_throttle(cfg) -> adaptive_maxpos(levels)."""
    throttled = apply_dd_throttle(fixed_trades,
                                  dd_threshold=throttle_cfg["threshold"],
                                  size_scale=throttle_cfg["scale"])
    wrapped = apply_adaptive_maxpos(throttled, levels=maxpos_cfg["levels"])
    return wrapped


# ===========================================================================
# Engine
# ===========================================================================

def run_engine_raw(data, coins, signal_fn, params, indicators, fee,
                   start_bar=START_BAR, end_bar=None):
    """Engine -> fixed-notional (no wrappers)."""
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")
    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=fee, exit_mode="dc",
        start_bar=start_bar, initial_capital=INITIAL_CAPITAL,
        end_bar=end_bar,
    )
    fixed, n_capped = normalize_trades(r.trade_list)
    fixed = sort_trades(fixed)
    return fixed, n_capped


# ===========================================================================
# Truth-pass suite
# ===========================================================================

def compute_3way_windows(max_bars):
    usable = max_bars - START_BAR
    third = usable // 3
    return {
        "early":  {"start": START_BAR, "end": START_BAR + third},
        "mid":    {"start": START_BAR + third, "end": START_BAR + 2 * third},
        "late":   {"start": START_BAR + 2 * third, "end": max_bars},
        "max_bars": max_bars,
    }


def run_pipeline(data, coins, signal_fn, params, indicators, fee,
                 throttle_cfg, maxpos_cfg, start_bar=START_BAR, end_bar=None):
    """Full pipeline for a window."""
    fixed, n_capped = run_engine_raw(data, coins, signal_fn, params, indicators,
                                     fee, start_bar=start_bar, end_bar=end_bar)
    wrapped = apply_full_wrapper(fixed, throttle_cfg, maxpos_cfg)
    m = compute_metrics(wrapped)
    return {**m, "trade_list": wrapped, "n_fixed": len(fixed),
            "n_wrapped": len(wrapped), "n_skipped": len(fixed) - len(wrapped),
            "n_capped": n_capped}


def test_window_split(data, coins, signal_fn, params, indicators, fee,
                      windows, throttle_cfg, maxpos_cfg):
    results = {}
    n_prof = 0
    for name in ["early", "mid", "late"]:
        w = windows[name]
        bt = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                          throttle_cfg, maxpos_cfg,
                          start_bar=w["start"], end_bar=w["end"])
        results[name] = {"start": w["start"], "end": w["end"],
                         "trades": bt["trades"], "pf": bt["pf"],
                         "pnl": bt["pnl"], "dd": bt["dd"]}
        if bt["pf"] >= 1.0 and bt["trades"] > 0:
            n_prof += 1
    results["n_profitable"] = n_prof
    results["pass"] = n_prof >= GATE_WINDOW
    return results


def test_bootstrap(trade_list):
    if len(trade_list) < 10:
        return {"pass": False, "n_trades": len(trade_list)}
    rng = np.random.default_rng(SEED)
    pnls = np.array([t["pnl"] for t in trade_list])
    n = len(pnls)
    pfs, finals = [], []
    for _ in range(N_RESAMPLES):
        sample = rng.choice(pnls, size=n, replace=True)
        gp = np.sum(sample[sample > 0])
        gl = np.abs(np.sum(sample[sample < 0]))
        pf = gp / gl if gl > 0 else (99.99 if gp > 0 else 0)
        pfs.append(pf)
        finals.append(np.sum(sample))
    pfs = np.array(pfs)
    finals = np.array(finals)
    return {
        "n_resamples": N_RESAMPLES, "n_trades": n,
        "median_pf": round(float(np.median(pfs)), 4),
        "p5_pf": round(float(np.percentile(pfs, 5)), 4),
        "pct_profitable": round(float(np.mean(finals > 0) * 100), 1),
        "pass": bool(np.percentile(pfs, 5) >= GATE_BOOT_P5
                     and np.mean(finals > 0) * 100 >= GATE_BOOT_PROF),
    }


def evaluate_gates(m, ws, bs):
    gates = {
        "pf": {"gate": f"PF >= {GATE_PF}", "value": m["pf"],
               "pass": m["pf"] >= GATE_PF},
        "dd": {"gate": f"DD <= {GATE_DD}%", "value": m["dd"],
               "pass": m["dd"] <= GATE_DD},
        "boot_p5": {"gate": f"Boot P5 >= {GATE_BOOT_P5}", "value": bs.get("p5_pf", 0),
                    "pass": bs.get("p5_pf", 0) >= GATE_BOOT_P5},
        "boot_prof": {"gate": f"Boot %prof >= {GATE_BOOT_PROF}%",
                      "value": bs.get("pct_profitable", 0),
                      "pass": bs.get("pct_profitable", 0) >= GATE_BOOT_PROF},
        "windows": {"gate": f"Win >= {GATE_WINDOW}/{N_WINDOWS}",
                    "value": ws["n_profitable"],
                    "pass": ws["pass"]},
        "trades": {"gate": f"Trades >= {GATE_TRADES}", "value": m["trades"],
                   "pass": m["trades"] >= GATE_TRADES},
    }
    n_pass = sum(1 for g in gates.values() if g["pass"])
    return gates, n_pass, n_pass == len(gates)


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    git = _git_hash()

    print("\n" + "=" * 72)
    print("  SWEEP V1 DD-FIX — A06 drawdown reduction sweep")
    print(f"  Config: sweep_v1_006_sv1a06_rsi45_p8_atr2.0")
    print(f"  Original: PF=1.52, 347 trades, DD=63.1%")
    print(f"  Target: DD <= {GATE_DD}%, PF >= {GATE_PF}")
    print(f"  Grid: {len(DD_THROTTLE_GRID)} throttle x {len(ADAPTIVE_MAXPOS_GRID)} maxpos"
          f" = {len(DD_THROTTLE_GRID) * len(ADAPTIVE_MAXPOS_GRID)} combos")
    print("=" * 72)

    # ==================================================================
    # Phase 0: Load data + precompute (same as sweep_v1 runner)
    # ==================================================================
    print(f"\n{'='*72}")
    print("  PHASE 0: Data Loading & Indicator Precompute")
    print(f"{'='*72}")

    import importlib
    _data_resolver = importlib.import_module("strategies.4h.data_resolver")
    _sweep_v1_ind = importlib.import_module("strategies.4h.sweep_v1.indicators")
    _sweep_v1_hyp = importlib.import_module("strategies.4h.sweep_v1.hypotheses")
    _sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")

    resolve_dataset = _data_resolver.resolve_dataset
    precompute_all = _sweep_v1_ind.precompute_all
    precompute_rsi_rank = _sweep_v1_ind.precompute_rsi_rank
    precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
    signal_fn = _sweep_v1_hyp.signal_swing_fractal_bounce

    # Load dataset
    dataset_path = resolve_dataset(DEFAULT_DATASET)
    print(f"  Dataset: {dataset_path}")

    t0 = time.time()
    with open(dataset_path) as f:
        data = json.load(f)

    all_coins = sorted([k for k in data if not k.startswith("_")])
    coins = [c for c in all_coins if len(data.get(c, [])) >= MIN_BARS]
    print(f"  All coins: {len(all_coins)}, universe (>={MIN_BARS} bars): {len(coins)}")
    print(f"  Data loaded: {time.time() - t0:.1f}s")

    # Precompute Sweep v1 indicators
    print(f"  Precomputing Sweep v1 indicators...")
    t1 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Indicators: {time.time() - t1:.1f}s")

    # RSI rank (cross-sectional)
    n_bars = max(ind["n"] for ind in indicators.values()) if indicators else 0
    max_bar = n_bars  # for window computation
    print(f"  Precomputing RSI rank ({n_bars} bars)...")
    t_rsi = time.time()
    rsi_rank = precompute_rsi_rank(indicators, coins, n_bars)
    print(f"  RSI rank: {time.time() - t_rsi:.1f}s")

    # Inject RSI rank into per-coin indicators
    for coin in coins:
        ind = indicators.get(coin)
        if ind is None:
            continue
        ind["__rsi_percentile__"] = rsi_rank["rsi_percentile"].get(coin, [None] * n_bars)
        ind["__rsi_median__"] = rsi_rank["rsi_median"]

    # Market context
    print(f"  Precomputing market context...")
    t2 = time.time()
    market_ctx = precompute_sprint2_context(data, coins)
    print(f"  Market context: {time.time() - t2:.1f}s")

    # Build params with market context
    params = dict(A06_PARAMS)
    params["__market__"] = market_ctx

    # Inject per-coin identity into indicators
    for c in coins:
        indicators[c]["__coin__"] = c

    windows = compute_3way_windows(max_bar)
    n_days = (max_bar - START_BAR) * 4 / 24
    print(f"  Phase 0 complete: {len(coins)} coins, {max_bar} max bars, {n_days:.0f} days")

    # ==================================================================
    # Phase 1: Quick gate-check (all 27 combos)
    # ==================================================================
    print(f"\n{'='*72}")
    print(f"  PHASE 1: Quick gate-check ({len(DD_THROTTLE_GRID) * len(ADAPTIVE_MAXPOS_GRID)} combos)")
    print(f"{'='*72}")

    # Run engine ONCE — shared across all wrapper combos
    print("  Running engine (shared across combos)...")
    t0 = time.time()
    fixed_trades, n_capped = run_engine_raw(data, coins, signal_fn, params,
                                            indicators, KRAKEN_FEE)
    print(f"  Engine: {len(fixed_trades)} fixed trades, {n_capped} capped ({time.time()-t0:.1f}s)")

    # Compute original (unwrapped) metrics for reference
    orig_m = compute_metrics(fixed_trades)
    print(f"\n  ORIGINAL (no wrappers):")
    print(f"    Trades: {orig_m['trades']}, PF: {orig_m['pf']:.4f}, "
          f"DD: {orig_m['dd']:.1f}%, P&L: ${orig_m['pnl']:+,.0f}, "
          f"WR: {orig_m['wr']:.1f}%, EV: ${orig_m['ev_trade']:+.2f}/trade")

    print(f"\n  {'Label':<25} {'Trades':>6} {'PF':>7} {'P&L':>10} {'DD':>6} "
          f"{'WR':>6} {'EV/t':>7} {'Quick':>5}")
    print(f"  {'-'*25} {'-'*6} {'-'*7} {'-'*10} {'-'*6} {'-'*6} {'-'*7} {'-'*5}")

    phase1 = []
    for tc in DD_THROTTLE_GRID:
        for mc in ADAPTIVE_MAXPOS_GRID:
            label = f"{tc['label']}+{mc['label']}"
            wrapped = apply_full_wrapper(fixed_trades, tc, mc)
            m = compute_metrics(wrapped)

            quick_pass = (m["pf"] >= GATE_PF
                         and m["dd"] <= GATE_DD
                         and m["trades"] >= GATE_TRADES)
            mark = "PASS" if quick_pass else "FAIL"
            print(f"  {label:<25} {m['trades']:>6} {m['pf']:>7.4f} "
                  f"${m['pnl']:>+9,.0f} {m['dd']:>5.1f}% "
                  f"{m['wr']:>5.1f}% ${m['ev_trade']:>+6.2f} {mark:>5}")
            phase1.append({
                "throttle": tc,
                "maxpos": mc,
                "label": label,
                "metrics": m,
                "wrapped_trades": wrapped,
                "quick_pass": quick_pass,
            })

    # Select candidates
    candidates = [p for p in phase1 if p["quick_pass"]]
    print(f"\n  Quick-pass candidates: {len(candidates)}/{len(phase1)}")

    if not candidates:
        print("\n  No combo passes quick gates. Selecting best DD combo with PF >= 1.10...")
        viable = [p for p in phase1 if p["metrics"]["pf"] >= 1.10]
        if viable:
            viable.sort(key=lambda p: p["metrics"]["dd"])
            candidates = viable[:3]  # top 3 by DD
        else:
            # Absolute fallback: best PF
            phase1.sort(key=lambda p: -p["metrics"]["pf"])
            candidates = phase1[:1]
        for c in candidates:
            print(f"    Fallback: {c['label']} (PF={c['metrics']['pf']:.4f}, DD={c['metrics']['dd']:.1f}%)")

    # ==================================================================
    # Phase 2: Full truth-pass on candidates
    # ==================================================================
    print(f"\n{'='*72}")
    print(f"  PHASE 2: Full truth-pass ({len(candidates)} candidate(s))")
    print(f"{'='*72}")

    best = None
    all_results = {}

    for ci, cand in enumerate(candidates):
        tc = cand["throttle"]
        mc = cand["maxpos"]
        label = cand["label"]
        m = cand["metrics"]
        trades = cand["wrapped_trades"]

        print(f"\n  --- Candidate {ci+1}: {label} ---")
        print(f"  Quick: {m['trades']}tr, PF={m['pf']:.4f}, DD={m['dd']:.1f}%, "
              f"P&L=${m['pnl']:+,.0f}")

        t0 = time.time()

        # Window split (re-run engine per window with wrappers)
        ws = test_window_split(data, coins, signal_fn, params, indicators,
                               KRAKEN_FEE, windows, tc, mc)
        print(f"  Windows: {ws['n_profitable']}/{N_WINDOWS} "
              f"{'PASS' if ws['pass'] else 'FAIL'}")
        for name in ["early", "mid", "late"]:
            w = ws[name]
            wm = "PASS" if w["pf"] >= 1.0 and w["trades"] > 0 else "FAIL"
            print(f"    {name}: {w['trades']}tr PF={w['pf']:.2f} ${w['pnl']:+,.0f} DD={w['dd']:.1f}% {wm}")

        # Bootstrap
        bs = test_bootstrap(trades)
        print(f"  Boot: P5={bs['p5_pf']:.2f}, %prof={bs['pct_profitable']:.1f}%"
              f" {'PASS' if bs['pass'] else 'FAIL'}")

        # Gates
        gates, n_gates, all_pass = evaluate_gates(m, ws, bs)

        # Truth-pass verdict
        tp_tests = [ws["pass"], bs["pass"]]
        tp_n = sum(tp_tests)
        if tp_n == 2:
            verdict = "VERIFIED"
        elif tp_n == 1:
            verdict = "CONDITIONAL"
        else:
            verdict = "FAILED"

        print(f"\n  GATES: {n_gates}/{len(gates)}  Truth-Pass: {verdict} ({tp_n}/2)")
        for gn, g in gates.items():
            gm = "PASS" if g["pass"] else "FAIL"
            print(f"    [{gm:4s}] {g['gate']}: {g['value']}")

        deploy = f"YES ({n_gates}/{len(gates)} gates)" if all_pass else f"NO ({n_gates}/{len(gates)} gates)"
        print(f"  Deploy: {deploy} ({time.time()-t0:.1f}s)")

        ea = exit_attribution(trades)

        # DD reduction stats
        dd_reduction_pct = (orig_m["dd"] - m["dd"]) / orig_m["dd"] * 100 if orig_m["dd"] > 0 else 0
        pf_change_pct = (m["pf"] - orig_m["pf"]) / orig_m["pf"] * 100 if orig_m["pf"] > 0 else 0

        result = {
            "throttle": tc,
            "maxpos": mc,
            "label": label,
            "metrics": m,
            "exit_attribution": ea,
            "window_split": {k: v for k, v in ws.items()},
            "bootstrap": bs,
            "gates": gates,
            "n_gates": n_gates,
            "all_gates": all_pass,
            "verdict": verdict,
            "tp_n": tp_n,
            "dd_reduction_pct": round(dd_reduction_pct, 2),
            "pf_change_pct": round(pf_change_pct, 2),
        }
        all_results[label] = result

        if all_pass and (best is None or m["pf"] > all_results.get(best, {}).get("metrics", {}).get("pf", 0)):
            best = label

    # ==================================================================
    # Scoreboard
    # ==================================================================
    print(f"\n{'='*72}")
    print("  SCOREBOARD — All Phase 1 combos + Phase 2 detail")
    print(f"{'='*72}")
    print(f"  {'Label':<25} {'Trades':>6} {'PF':>7} {'P&L':>10} {'DD':>6} "
          f"{'DD_red':>7} {'Win':>4} {'BtP5':>5} {'Gts':>4} {'Deploy':>6}")
    print(f"  {'-'*25} {'-'*6} {'-'*7} {'-'*10} {'-'*6} {'-'*7} "
          f"{'-'*4} {'-'*5} {'-'*4} {'-'*6}")

    # Sort: all_pass first, then by DD ascending
    phase1_sorted = sorted(phase1, key=lambda p: (
        not (p["label"] in all_results and all_results[p["label"]].get("all_gates", False)),
        p["metrics"]["dd"],
    ))

    for p in phase1_sorted:
        m = p["metrics"]
        label = p["label"]
        dd_red = (orig_m["dd"] - m["dd"]) / orig_m["dd"] * 100 if orig_m["dd"] > 0 else 0
        if label in all_results:
            r = all_results[label]
            ws_s = f"{r['window_split']['n_profitable']}/{N_WINDOWS}"
            bp5 = f"{r['bootstrap']['p5_pf']:.2f}"
            gts = f"{r['n_gates']}/{len(r['gates'])}"
            dep = "YES" if r["all_gates"] else "NO"
        else:
            ws_s = " -- "
            bp5 = " -- "
            gts = " -- "
            dep = " -- "
        print(f"  {label:<25} {m['trades']:>6} {m['pf']:>7.4f} "
              f"${m['pnl']:>+9,.0f} {m['dd']:>5.1f}% {dd_red:>+6.1f}% "
              f"{ws_s:>4} {bp5:>5} {gts:>4} {dep:>6}")

    # ==================================================================
    # Reports
    # ==================================================================
    print(f"\n{'='*72}")
    print("  REPORTS")
    print(f"{'='*72}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "sweep_v1_ddfix",
        "experiment_id": REPORT_ID,
        "config": "sweep_v1_006_sv1a06_rsi45_p8_atr2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": DEFAULT_DATASET,
        "universe": {"filter": f">={MIN_BARS} bars", "n_coins": len(coins)},
        "fee": KRAKEN_FEE,
        "sizing": "fixed_notional_2000",
        "original": {
            "trades": orig_m["trades"],
            "pf": orig_m["pf"],
            "pnl": orig_m["pnl"],
            "dd": orig_m["dd"],
            "wr": orig_m["wr"],
        },
        "a06_params": {k: v for k, v in A06_PARAMS.items()},
        "gates": {
            "pf": GATE_PF, "dd": GATE_DD, "boot_p5": GATE_BOOT_P5,
            "boot_prof": GATE_BOOT_PROF, "window": GATE_WINDOW,
            "trades": GATE_TRADES,
        },
        "phase1_grid": [
            {"label": p["label"],
             "throttle": p["throttle"]["label"],
             "maxpos": p["maxpos"]["label"],
             "trades": p["metrics"]["trades"],
             "pf": p["metrics"]["pf"],
             "pnl": p["metrics"]["pnl"],
             "dd": p["metrics"]["dd"],
             "wr": p["metrics"]["wr"],
             "quick_pass": p["quick_pass"]}
            for p in phase1
        ],
        "phase2_results": {
            label: {k: v for k, v in r.items() if k != "wrapped_trades"}
            for label, r in all_results.items()
        },
        "best": best,
    }

    json_path = REPORT_DIR / f"{REPORT_ID}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  JSON: {json_path}")

    # MD report
    md = [
        "# Sweep v1 DD-Fix — A06 Drawdown Reduction", "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Config**: sweep_v1_006_sv1a06_rsi45_p8_atr2.0",
        f"**Original**: {orig_m['trades']}tr, PF={orig_m['pf']:.4f}, "
        f"DD={orig_m['dd']:.1f}%, P&L=${orig_m['pnl']:+,.0f}",
        "",
        "## Methodology",
        "",
        "Post-hoc equity simulation applying risk wrappers to existing trade lists.",
        "Entry and exit logic are UNCHANGED. Only sizing and trade admission modified.",
        "",
        "### Wrappers",
        "1. **DD Throttle**: Scale position size by factor when DD > threshold",
        "2. **Adaptive MaxPos**: Reduce max concurrent positions (calm/medium/stressed) by DD level",
        "",
        f"### Grid: {len(DD_THROTTLE_GRID)} throttle x {len(ADAPTIVE_MAXPOS_GRID)} maxpos"
        f" = {len(DD_THROTTLE_GRID) * len(ADAPTIVE_MAXPOS_GRID)} combos",
        "",
        "### Gates",
        f"- PF >= {GATE_PF}",
        f"- DD <= {GATE_DD}%",
        f"- Trades >= {GATE_TRADES}",
        f"- Boot P5 >= {GATE_BOOT_P5}",
        f"- Boot %prof >= {GATE_BOOT_PROF}%",
        f"- Windows >= {GATE_WINDOW}/{N_WINDOWS}",
        "",
        "## Phase 1: Quick Gate-Check (all combos)", "",
        "| # | Label | Trades | PF | P&L | DD | DD_red | Quick |",
        "|---|-------|-------:|---:|----:|---:|-------:|:-----:|",
    ]
    for i, p in enumerate(phase1):
        m = p["metrics"]
        dd_red = (orig_m["dd"] - m["dd"]) / orig_m["dd"] * 100 if orig_m["dd"] > 0 else 0
        qm = "PASS" if p["quick_pass"] else "FAIL"
        md.append(f"| {i+1} | {p['label']} | {m['trades']} | "
                  f"{m['pf']:.4f} | ${m['pnl']:+,.0f} | {m['dd']:.1f}% | "
                  f"{dd_red:+.1f}% | {qm} |")
    md.append("")

    if all_results:
        md.extend(["## Phase 2: Full Truth-Pass", ""])
        for label, r in all_results.items():
            m = r["metrics"]
            dm = f"{r['n_gates']}/{len(r['gates'])} gates"
            if r["all_gates"]:
                dm += " -- GO"
            md.extend([
                f"### {label}", "",
                f"| Metric | Value |", f"|--------|------:|",
                f"| Trades | {m['trades']} |",
                f"| PF | {m['pf']:.4f} |",
                f"| P&L | ${m['pnl']:+,.0f} |",
                f"| DD | {m['dd']:.1f}% |",
                f"| DD reduction | {r['dd_reduction_pct']:+.1f}% |",
                f"| PF change | {r['pf_change_pct']:+.1f}% |",
                f"| Windows | {r['window_split']['n_profitable']}/{N_WINDOWS} |",
                f"| Boot P5 | {r['bootstrap']['p5_pf']:.2f} |",
                f"| Boot %prof | {r['bootstrap']['pct_profitable']:.1f}% |",
                f"| Truth-Pass | {r['verdict']} ({r['tp_n']}/2) |",
                f"| Gates | {dm} |", "",
            ])
            # Gates detail
            md.append("| Gate | Value | Status |")
            md.append("|------|------:|-------:|")
            for gn, g in r["gates"].items():
                gm = "PASS" if g["pass"] else "FAIL"
                md.append(f"| {g['gate']} | {g['value']} | {gm} |")
            md.extend([""])

            # Exit attribution
            ea = r.get("exit_attribution", {})
            if ea:
                md.append("**Exit Attribution:**")
                md.append("| Reason | Class | Count | P&L | WR |")
                md.append("|--------|:-----:|------:|----:|---:|")
                for reason, stats in sorted(ea.items(), key=lambda x: -x[1]["pnl"]):
                    md.append(f"| {reason} | {stats['class']} | {stats['count']} | "
                              f"${stats['pnl']:+,.0f} | {stats['wr']:.1f}% |")
                md.append("")
            md.append("---")
            md.append("")

    md.extend(["## Conclusion", ""])
    if best:
        bm = all_results[best]["metrics"]
        br = all_results[best]
        md.append(f"**WINNER: {best}** -- {bm['trades']} trades, "
                  f"PF={bm['pf']:.4f}, DD={bm['dd']:.1f}%, "
                  f"DD reduction {br['dd_reduction_pct']:+.1f}%, "
                  f"{br['n_gates']}/{len(br['gates'])} gates")
        md.append("")
        md.append(f"Original A06: PF={orig_m['pf']:.4f}, DD={orig_m['dd']:.1f}%")
        md.append(f"Wrapped:      PF={bm['pf']:.4f}, DD={bm['dd']:.1f}%")
    else:
        any_close = [p for p in phase1 if p["metrics"]["dd"] <= 30.0 and p["metrics"]["pf"] >= 1.10]
        if any_close:
            md.append("**No combo passes all gates.** Best near-pass:")
            for c in sorted(any_close, key=lambda x: x["metrics"]["dd"])[:3]:
                m = c["metrics"]
                md.append(f"- {c['label']}: PF={m['pf']:.4f}, DD={m['dd']:.1f}%, {m['trades']}tr")
        else:
            md.append("**No combo achieves DD <= 25% with PF >= 1.15.**")
            md.append("A06 DD=63.1% may require engine-level changes (not just post-hoc wrappers).")
    md.append("")

    md_path = REPORT_DIR / f"{REPORT_ID}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md))
    print(f"  MD:   {md_path}")

    # ==================================================================
    # Summary
    # ==================================================================
    elapsed = time.time() - t_total
    print(f"\n{'='*72}")
    if best:
        bm = all_results[best]["metrics"]
        br = all_results[best]
        print(f"  WINNER: {best}")
        print(f"    {bm['trades']}tr, PF={bm['pf']:.4f}, DD={bm['dd']:.1f}%, "
              f"P&L=${bm['pnl']:+,.0f}")
        print(f"    DD reduction: {br['dd_reduction_pct']:+.1f}%, "
              f"PF change: {br['pf_change_pct']:+.1f}%")
        print(f"    Gates: {br['n_gates']}/{len(br['gates'])}, "
              f"Truth-Pass: {br['verdict']}")
    else:
        print(f"  NO WINNER (no combo passes all {len(gates)} gates)")
        # Show best candidate
        best_cand = min(phase1, key=lambda p: p["metrics"]["dd"])
        m = best_cand["metrics"]
        print(f"  Best DD: {best_cand['label']} -- DD={m['dd']:.1f}%, PF={m['pf']:.4f}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
