#!/usr/bin/env python3
"""
MEXC DD Micro-Sweep — tune dd_throttle to get DD < 20% with trades >= 250.

ADR-4H-014 addendum: adaptive_maxpos=3/2/1 is fixed. Sweep dd_throttle
threshold (5-7%) × scale (0.20-0.25) to find combo that passes ALL 7 gates.

Phase 1: Quick gate-check on 6 combos (full-range metrics + DD + trades only)
Phase 2: Full truth-pass on best combo (if any passes quick gates)

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_mexc_dd_microsweep.py
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
# Constants
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

# Fixed: adaptive_maxpos 3/2/1
MAXPOS_NORMAL = 3
MAXPOS_DD10 = 2
MAXPOS_DD20 = 1

# Gates
GATE_PF = 1.30
GATE_DD = 20.0
GATE_BOOT_P5 = 0.85
GATE_BOOT_PROF = 80.0
GATE_WINDOW = 4
GATE_TRADES = 250

# Micro-sweep grid
THROTTLE_GRID = [
    {"threshold": 0.05, "scale": 0.25, "label": "5%/0.25x (baseline)"},
    {"threshold": 0.05, "scale": 0.22, "label": "5%/0.22x"},
    {"threshold": 0.05, "scale": 0.20, "label": "5%/0.20x"},
    {"threshold": 0.06, "scale": 0.25, "label": "6%/0.25x"},
    {"threshold": 0.06, "scale": 0.22, "label": "6%/0.22x"},
    {"threshold": 0.07, "scale": 0.25, "label": "7%/0.25x"},
]

REPORT_ID = "mexc_dd_microsweep_010"


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Reused functions
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
    print(f"  Coins: {len(coins)}, Bars: {min(bars_counts)}-{max(bars_counts)}")
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
        fixed.append(ft)
    return fixed, n_capped


def sort_trades(trades):
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


def apply_dd_throttle(trades, dd_threshold, size_scale):
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


def apply_adaptive_maxpos(trades):
    sorted_t = sort_trades(trades)
    result = []
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    open_positions = []
    for t in sorted_t:
        entry_bar = t["entry_bar"]
        open_positions = [(eb, xb) for eb, xb in open_positions if xb > entry_bar]
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd < 0.10:
            max_pos = MAXPOS_NORMAL
        elif dd < 0.20:
            max_pos = MAXPOS_DD10
        else:
            max_pos = MAXPOS_DD20
        if len(open_positions) >= max_pos:
            continue
        open_positions.append((entry_bar, t["exit_bar"]))
        result.append(dict(t))
        equity += t["pnl"]
        if equity > peak:
            peak = equity
    return result


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
# Engine
# ===========================================================================

def run_engine_raw(data, coins, signal_fn, params, indicators, fee,
                   start_bar=START_BAR, end_bar=None):
    """Engine → fixed-notional (no wrappers)."""
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")
    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=fee, exit_mode="dc",
        start_bar=start_bar, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=end_bar,
    )
    fixed, n_capped = normalize_trades(r.trade_list)
    fixed = sort_trades(fixed)
    return fixed, n_capped


def apply_full_wrapper(fixed_trades, throttle_cfg):
    """dd_throttle(cfg) → adaptive_maxpos(3/2/1)."""
    throttled = apply_dd_throttle(fixed_trades,
                                  dd_threshold=throttle_cfg["threshold"],
                                  size_scale=throttle_cfg["scale"])
    wrapped = apply_adaptive_maxpos(throttled)
    return wrapped


# ===========================================================================
# Truth-pass suite
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


def run_pipeline(data, coins, signal_fn, params, indicators, fee,
                 throttle_cfg, start_bar=START_BAR, end_bar=None):
    """Full pipeline for a window."""
    fixed, n_capped = run_engine_raw(data, coins, signal_fn, params, indicators,
                                     fee, start_bar=start_bar, end_bar=end_bar)
    wrapped = apply_full_wrapper(fixed, throttle_cfg)
    m = compute_metrics(wrapped)
    return {**m, "trade_list": wrapped, "n_fixed": len(fixed),
            "n_wrapped": len(wrapped), "n_skipped": len(fixed) - len(wrapped),
            "n_capped": n_capped}


def test_window_split(data, coins, signal_fn, params, indicators, fee,
                      windows, throttle_cfg):
    results = {}
    n_prof = 0
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = windows[name]
        bt = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                          throttle_cfg, start_bar=w["start"], end_bar=w["end"])
        results[name] = {"start": w["start"], "end": w["end"],
                         "trades": bt["trades"], "pf": bt["pf"],
                         "pnl": bt["pnl"], "dd": bt["dd"]}
        if bt["pf"] >= 1.0 and bt["trades"] > 0:
            n_prof += 1
    results["n_profitable"] = n_prof
    results["pass"] = n_prof >= GATE_WINDOW
    return results


def test_walk_forward(data, coins, signal_fn, params, indicators, fee,
                      windows, throttle_cfg):
    max_bars = windows["max_bars"]
    usable = max_bars - START_BAR
    third = usable // 3
    early_end = START_BAR + third
    mid_end = START_BAR + 2 * third

    cal_a = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                         throttle_cfg, start_bar=START_BAR, end_bar=early_end)
    test_a = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                          throttle_cfg, start_bar=early_end, end_bar=max_bars)
    sp_a = (cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
            and test_a["pf"] >= 0.9 and test_a["trades"] > 0)

    cal_b = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                         throttle_cfg, start_bar=START_BAR, end_bar=mid_end)
    test_b = run_pipeline(data, coins, signal_fn, params, indicators, fee,
                          throttle_cfg, start_bar=mid_end, end_bar=max_bars)
    sp_b = (cal_b["pf"] >= 1.0 and cal_b["trades"] > 0
            and test_b["pf"] >= 0.9 and test_b["trades"] > 0)

    return {
        "split_a": {"cal": {"trades": cal_a["trades"], "pf": cal_a["pf"]},
                    "test": {"trades": test_a["trades"], "pf": test_a["pf"]},
                    "pass": sp_a},
        "split_b": {"cal": {"trades": cal_b["trades"], "pf": cal_b["pf"]},
                    "test": {"trades": test_b["trades"], "pf": test_b["pf"]},
                    "pass": sp_b},
        "pass": sp_a or sp_b,
    }


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


def check_determinism(data, coins, signal_fn, params, indicators, fee, throttle_cfg):
    r1 = run_pipeline(data, coins, signal_fn, params, indicators, fee, throttle_cfg)
    r2 = run_pipeline(data, coins, signal_fn, params, indicators, fee, throttle_cfg)
    match = (r1["trades"] == r2["trades"]
             and abs(r1["pf"] - r2["pf"]) < 1e-6
             and abs(r1["pnl"] - r2["pnl"]) < 0.01)
    return {"pass": match}


def evaluate_gates(m, ws, wf, bs, det):
    gates = {
        "pf": {"gate": f"PF >= {GATE_PF}", "value": m["pf"],
               "pass": m["pf"] >= GATE_PF},
        "dd": {"gate": f"DD <= {GATE_DD}%", "value": m["dd"],
               "pass": m["dd"] <= GATE_DD},
        "boot_p5": {"gate": f"Boot P5 >= {GATE_BOOT_P5}", "value": bs["p5_pf"],
                    "pass": bs["p5_pf"] >= GATE_BOOT_P5},
        "boot_prof": {"gate": f"Boot %prof >= {GATE_BOOT_PROF}%", "value": bs["pct_profitable"],
                      "pass": bs["pct_profitable"] >= GATE_BOOT_PROF},
        "windows": {"gate": f"Win >= {GATE_WINDOW}/{N_WINDOWS}", "value": ws["n_profitable"],
                    "pass": ws["pass"]},
        "trades": {"gate": f"Trades >= {GATE_TRADES}", "value": m["trades"],
                   "pass": m["trades"] >= GATE_TRADES},
        "determinism": {"gate": "Determinism", "value": "PASS" if det["pass"] else "FAIL",
                        "pass": det["pass"]},
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
    print("  MEXC DD MICRO-SWEEP — dd_throttle tuning")
    print(f"  adaptive_maxpos: {MAXPOS_NORMAL}/{MAXPOS_DD10}/{MAXPOS_DD20} (fixed)")
    print(f"  Grid: {len(THROTTLE_GRID)} combos")
    print(f"  ADR: 4H-014 addendum")
    print("=" * 72)

    # Load + precompute (shared)
    data, coins, bars_counts = load_top200()
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
    params = dict(cfg041["params"])
    params["vol_mult"] = 3.5
    params["rsi_max"] = 35
    params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c
    params.update(EXIT_PARAMS)

    windows = compute_5way_windows(max_bar)

    # ==================================================================
    # Phase 1: Quick full-range scan (all combos)
    # ==================================================================
    print(f"\n{'='*72}")
    print("  PHASE 1: Quick gate-check (full-range)")
    print(f"{'='*72}")

    # Run engine ONCE — fixed trades are shared across all throttle combos
    print("  Running engine (shared across combos)...")
    t0 = time.time()
    fixed_trades, n_capped = run_engine_raw(data, coins, signal_fn, params,
                                            indicators, MEXC_FEE)
    print(f"  Engine: {len(fixed_trades)} fixed trades, {n_capped} capped ({time.time()-t0:.1f}s)")

    phase1 = []
    for i, tc in enumerate(THROTTLE_GRID):
        wrapped = apply_full_wrapper(fixed_trades, tc)
        m = compute_metrics(wrapped)
        quick_pass = m["pf"] >= GATE_PF and m["dd"] <= GATE_DD and m["trades"] >= GATE_TRADES
        mark = "✅" if quick_pass else "❌"
        print(f"  [{i+1}] {tc['label']:<20} → {m['trades']}tr  PF={m['pf']:.4f}  "
              f"DD={m['dd']:.1f}%  ${m['pnl']:+,.0f}  {mark}")
        phase1.append({
            "throttle": tc,
            "metrics": m,
            "wrapped_trades": wrapped,
            "quick_pass": quick_pass,
        })

    # Select candidates: pass quick gates
    candidates = [p for p in phase1 if p["quick_pass"]]
    print(f"\n  Quick-pass candidates: {len(candidates)}/{len(THROTTLE_GRID)}")

    if not candidates:
        print("\n  ⚠️  No combo passes quick gates (PF+DD+trades). Trying best DD combo...")
        # Fallback: pick combo closest to passing all 3
        phase1.sort(key=lambda p: (p["metrics"]["dd"] <= GATE_DD,
                                    p["metrics"]["trades"] >= GATE_TRADES,
                                    -p["metrics"]["dd"]))
        candidates = [phase1[0]]
        print(f"  Fallback: {candidates[0]['throttle']['label']}")

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
        label = tc["label"]
        m = cand["metrics"]
        trades = cand["wrapped_trades"]

        print(f"\n  --- Candidate {ci+1}: {label} ---")
        print(f"  Quick: {m['trades']}tr, PF={m['pf']:.4f}, DD={m['dd']:.1f}%")

        t0 = time.time()

        # Window split
        ws = test_window_split(data, coins, signal_fn, params, indicators,
                               MEXC_FEE, windows, tc)
        print(f"  Windows: {ws['n_profitable']}/{N_WINDOWS} "
              f"{'PASS' if ws['pass'] else 'FAIL'}")
        for i in range(N_WINDOWS):
            name = f"w{i+1}"
            w = ws[name]
            wm = "✅" if w["pf"] >= 1.0 and w["trades"] > 0 else "❌"
            print(f"    {name}: {w['trades']}tr PF={w['pf']:.2f} ${w['pnl']:+,.0f} {wm}")

        # Walk-forward
        wf = test_walk_forward(data, coins, signal_fn, params, indicators,
                               MEXC_FEE, windows, tc)
        for sn, s in [("A", wf["split_a"]), ("B", wf["split_b"])]:
            sm = "✅" if s["pass"] else "❌"
            print(f"  WF {sn}: cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                  f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f} {sm}")

        # Bootstrap
        bs = test_bootstrap(trades)
        print(f"  Boot: P5={bs['p5_pf']:.2f}, %prof={bs['pct_profitable']:.1f}%")

        # Determinism
        det = check_determinism(data, coins, signal_fn, params, indicators,
                                MEXC_FEE, tc)
        print(f"  Det: {'PASS' if det['pass'] else 'FAIL'}")

        # Gates
        gates, n_gates, all_pass = evaluate_gates(m, ws, wf, bs, det)

        # Verdict
        tp_n = sum([ws["pass"], wf["pass"], bs["pass"]])
        if tp_n == 3:
            verdict = "VERIFIED"
        elif tp_n == 2:
            verdict = "CONDITIONAL"
        else:
            verdict = "FAILED"

        print(f"\n  GATES: {n_gates}/7  Truth-Pass: {verdict} ({tp_n}/3)")
        for gn, g in gates.items():
            gm = "✅" if g["pass"] else "❌"
            print(f"    {gm} {g['gate']}: {g['value']}")

        deploy = "YES ✅" if all_pass else "NO ❌"
        print(f"  Deploy: {deploy} ({time.time()-t0:.1f}s)")

        ea = exit_attribution(trades)

        result = {
            "throttle": tc,
            "metrics": m,
            "exit_attribution": ea,
            "window_split": {k: v for k, v in ws.items()},
            "walk_forward": wf,
            "bootstrap": bs,
            "determinism": det,
            "gates": gates,
            "n_gates": n_gates,
            "all_gates": all_pass,
            "verdict": verdict,
            "tp_n": tp_n,
        }
        all_results[label] = result

        if all_pass and (best is None or m["pf"] > all_results[best]["metrics"]["pf"]):
            best = label

    # ==================================================================
    # Scoreboard
    # ==================================================================
    print(f"\n{'='*72}")
    print("  SCOREBOARD — All Phase 1 combos + Phase 2 detail")
    print(f"{'='*72}")
    print(f"  {'Label':<22} {'Trades':>6} {'PF':>7} {'P&L':>10} {'DD':>6} "
          f"{'Win':>4} {'BtP5':>5} {'Gts':>4} {'Deploy':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*7} {'-'*10} {'-'*6} {'-'*4} {'-'*5} {'-'*4} {'-'*6}")

    for p in phase1:
        tc = p["throttle"]
        m = p["metrics"]
        label = tc["label"]
        # Check if we ran full truth-pass
        if label in all_results:
            r = all_results[label]
            ws_s = f"{r['window_split']['n_profitable']}/5"
            bp5 = f"{r['bootstrap']['p5_pf']:.2f}"
            gts = f"{r['n_gates']}/7"
            dep = "YES" if r["all_gates"] else "NO"
            dm = "✅" if r["all_gates"] else "❌"
        else:
            ws_s = " — "
            bp5 = " — "
            gts = " — "
            dep = " — "
            dm = "⏭️"  # skipped
        print(f"  {label:<22} {m['trades']:>6} {m['pf']:>7.4f} "
              f"${m['pnl']:>+9,.0f} {m['dd']:>5.1f}% {ws_s:>4} {bp5:>5} "
              f"{gts:>4} {dep:>4} {dm}")

    # ==================================================================
    # Reports
    # ==================================================================
    print(f"\n{'='*72}")
    print("  REPORTS")
    print(f"{'='*72}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "mexc_dd_microsweep",
        "experiment_id": REPORT_ID,
        "adr": "4H-014 addendum",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {"filter": f"top {TOP_N}, >={MIN_BARS_TOP200} bars",
                     "n_coins": len(coins)},
        "fee": MEXC_FEE,
        "sizing": "fixed_notional_2000",
        "fixed_params": {
            "adaptive_maxpos": f"{MAXPOS_NORMAL}/{MAXPOS_DD10}/{MAXPOS_DD20}",
            "entry": {"vol_mult": 3.5, "rsi_max": 35},
            "exit": EXIT_PARAMS,
        },
        "phase1_grid": [
            {"label": p["throttle"]["label"],
             "threshold": p["throttle"]["threshold"],
             "scale": p["throttle"]["scale"],
             "trades": p["metrics"]["trades"],
             "pf": p["metrics"]["pf"],
             "pnl": p["metrics"]["pnl"],
             "dd": p["metrics"]["dd"],
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
    md = ["# MEXC DD Micro-Sweep — Report", "",
          f"**Date**: {report['timestamp'][:10]}",
          f"**Git**: `{git}`",
          f"**ADR**: 4H-014 addendum",
          f"**Fixed**: adaptive_maxpos {MAXPOS_NORMAL}/{MAXPOS_DD10}/{MAXPOS_DD20}",
          "", "## Phase 1: Quick Gate-Check", "",
          "| # | Label | Trades | PF | P&L | DD | Quick |",
          "|---|-------|-------:|---:|----:|---:|:-----:|"]
    for i, p in enumerate(phase1):
        m = p["metrics"]
        qm = "✅" if p["quick_pass"] else "❌"
        md.append(f"| {i+1} | {p['throttle']['label']} | {m['trades']} | "
                  f"{m['pf']:.4f} | ${m['pnl']:+,.0f} | {m['dd']:.1f}% | {qm} |")
    md.append("")

    if all_results:
        md.extend(["## Phase 2: Full Truth-Pass", ""])
        for label, r in all_results.items():
            m = r["metrics"]
            dm = "✅ 7/7 GO" if r["all_gates"] else f"❌ {r['n_gates']}/7"
            md.extend([
                f"### {label}", "",
                f"| Metric | Value |", f"|--------|------:|",
                f"| Trades | {m['trades']} |",
                f"| PF | {m['pf']:.4f} |",
                f"| P&L | ${m['pnl']:+,.0f} |",
                f"| DD | {m['dd']:.1f}% |",
                f"| Windows | {r['window_split']['n_profitable']}/5 |",
                f"| Boot P5 | {r['bootstrap']['p5_pf']:.2f} |",
                f"| Boot %prof | {r['bootstrap']['pct_profitable']:.1f}% |",
                f"| Truth-Pass | {r['verdict']} ({r['tp_n']}/3) |",
                f"| Gates | {dm} |", "",
            ])
            # Gates detail
            md.append("| Gate | Value | Status |")
            md.append("|------|------:|-------:|")
            for gn, g in r["gates"].items():
                gm = "✅" if g["pass"] else "❌"
                md.append(f"| {g['gate']} | {g['value']} | {gm} |")
            md.extend(["", "---", ""])

    md.extend(["## Conclusion", ""])
    if best:
        bm = all_results[best]["metrics"]
        md.append(f"**WINNER: {best}** — {bm['trades']} trades, "
                  f"PF={bm['pf']:.4f}, DD={bm['dd']:.1f}%, 7/7 gates ✅")
        md.append("")
        md.append("This config is ready for **GO — PAPERTRADE**.")
    else:
        md.append("**No combo passes all 7 gates.**")
    md.append("")

    md_path = REPORT_DIR / f"{REPORT_ID}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md))
    print(f"  MD:   {md_path}")

    elapsed = time.time() - t_total
    print(f"\n{'='*72}")
    if best:
        bm = all_results[best]["metrics"]
        print(f"  🏆 WINNER: {best}")
        print(f"     {bm['trades']}tr, PF={bm['pf']:.4f}, DD={bm['dd']:.1f}%, 7/7 gates")
    else:
        print(f"  ❌ NO WINNER")
    print(f"  Done in {elapsed:.1f}s")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
