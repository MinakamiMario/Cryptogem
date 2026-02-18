#!/usr/bin/env python3
"""
MEXC Combined Deploy Candidate — Engine + Wrapper + Truth-Pass.

Runs the exact combined config IN ENGINE (no independence assumptions):
  - Entry: vol_mult=3.5, rsi_max=35, top-200 universe, full-range
  - Exits: rsi_rec_min_bars=5 (engine-level, other DC defaults)
  - Risk wrapper: dd_throttle(5%/0.25x) + adaptive_maxpos(2/1/1) (post-hoc)

Then runs full truth-pass battery:
  1. 5-Way Window Split (full-range divided into 5 windows)
  2. Walk-Forward (2 splits)
  3. Bootstrap Monte Carlo (1000 resamples)
  4. Determinism check (re-run exact match)

Acceptance gates:
  - PF >= 1.30
  - DD <= 20%
  - Bootstrap P5 PF >= 0.85 AND %prof >= 80%
  - Window split >= 4/5
  - Trades >= 250

Output:
  reports/4h/mexc_combined_deploy_008.json
  reports/4h/mexc_combined_deploy_008.md

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_mexc_combined_deploy.py
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
MAX_RETURN_RATIO = 1.0  # Cap per-trade return at ±100%

N_RESAMPLES = 1000
SEED = 42
N_WINDOWS = 5  # 5-way split for full-range

# Exit params: rsi_rec_min_bars=5, rest = DC defaults
EXIT_PARAMS = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 5,  # ← exit tweak from Agent 2
}

# Risk wrapper params (from Agent 1 best)
DD_THROTTLE_THRESHOLD = 0.05   # 5% drawdown
DD_THROTTLE_SCALE = 0.25       # scale to 25% size in DD
ADAPTIVE_MAXPOS_NORMAL = 2
ADAPTIVE_MAXPOS_DD10 = 1
ADAPTIVE_MAXPOS_DD20 = 1

# Acceptance gates
GATE_PF = 1.30
GATE_DD = 20.0
GATE_BOOT_P5 = 0.85
GATE_BOOT_PROF = 80.0
GATE_WINDOW = 4  # out of 5
GATE_TRADES = 250

REPORT_ID = "mexc_combined_deploy_008"


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Data loading
# ===========================================================================

def load_top200():
    """Load MEXC v2 data, filter to top-200 by median volume with >=2160 bars."""
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


# ===========================================================================
# Fixed-notional normalization
# ===========================================================================

def normalize_trades(trade_list, notional=INITIAL_CAPITAL):
    """Convert equity-proportional trades to fixed-notional $2000."""
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
    """Sort trades chronologically."""
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


# ===========================================================================
# Post-hoc wrappers (from Agent 1)
# ===========================================================================

def apply_dd_throttle(trades, dd_threshold, size_scale, initial_capital=INITIAL_CAPITAL):
    """Scale position P&L when equity is in drawdown beyond threshold."""
    sorted_t = sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital

    for t in sorted_t:
        if peak_equity > 0:
            current_dd = (peak_equity - equity) / peak_equity
        else:
            current_dd = 0.0

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
    """Reduce max concurrent positions based on DD level. Skip excess trades."""
    sorted_t = sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital
    open_positions = []

    for t in sorted_t:
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]

        # Close positions that have exited
        open_positions = [(eb, xb) for eb, xb in open_positions if xb > entry_bar]

        # Compute current DD
        if peak_equity > 0:
            current_dd = (peak_equity - equity) / peak_equity
        else:
            current_dd = 0.0

        # Adaptive max_pos
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


# ===========================================================================
# Metrics computation
# ===========================================================================

def compute_metrics(trades, initial_capital=INITIAL_CAPITAL):
    """Compute PF, DD, P&L, WR, trades/day from trade list."""
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

    # Trades per day
    if trades:
        first_bar = min(t["entry_bar"] for t in trades)
        last_bar = max(t["exit_bar"] for t in trades)
        n_bars = last_bar - first_bar + 1
        n_days = n_bars * 4 / 24
        tpd = n / n_days if n_days > 0 else 0
    else:
        tpd = 0

    return {
        "trades": n,
        "pf": round(min(pf, 99.99), 4),
        "pnl": round(total_pnl, 2),
        "dd": round(max_dd, 2),
        "wr": round(wr, 2),
        "final_equity": round(equity, 2),
        "ev_trade": round(ev, 2),
        "trades_per_day": round(tpd, 2),
    }


def exit_attribution(trades):
    """Exit reason breakdown."""
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
# Engine run + fixed-notional + wrapper pipeline
# ===========================================================================

def run_engine(data, coins, signal_fn, params, indicators, fee,
               start_bar=START_BAR, end_bar=None):
    """Run engine → fixed-notional → dd_throttle → adaptive_maxpos."""
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")

    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=fee, exit_mode="dc",
        start_bar=start_bar, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        end_bar=end_bar,
    )

    # Step 1: Fixed-notional normalization
    fixed_trades, n_capped = normalize_trades(r.trade_list)
    fixed_trades = sort_trades(fixed_trades)

    # Step 2: dd_throttle wrapper
    throttled = apply_dd_throttle(fixed_trades,
                                  dd_threshold=DD_THROTTLE_THRESHOLD,
                                  size_scale=DD_THROTTLE_SCALE)

    # Step 3: adaptive_maxpos wrapper
    wrapped = apply_adaptive_maxpos(throttled,
                                     normal_max=ADAPTIVE_MAXPOS_NORMAL,
                                     dd10_max=ADAPTIVE_MAXPOS_DD10,
                                     dd20_max=ADAPTIVE_MAXPOS_DD20)

    return {
        "raw_trades": r.trade_list,
        "fixed_trades": fixed_trades,
        "wrapped_trades": wrapped,
        "n_capped": n_capped,
        "n_raw": len(r.trade_list),
        "n_fixed": len(fixed_trades),
        "n_wrapped": len(wrapped),
        "n_skipped": len(fixed_trades) - len(wrapped),
    }


# ===========================================================================
# Truth-pass tests
# ===========================================================================

def _compute_5way_windows(max_bars):
    """Compute 5-way window split boundaries."""
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


def _run_pipeline(data, coins, signal_fn, params, indicators, fee,
                  start_bar=START_BAR, end_bar=None):
    """Single run through engine + wrappers for a time window."""
    result = run_engine(data, coins, signal_fn, params, indicators, fee,
                        start_bar=start_bar, end_bar=end_bar)
    metrics = compute_metrics(result["wrapped_trades"])
    return {
        **metrics,
        "n_raw": result["n_raw"],
        "n_fixed": result["n_fixed"],
        "n_skipped": result["n_skipped"],
        "n_capped": result["n_capped"],
        "trade_list": result["wrapped_trades"],
    }


def test_window_split_5way(data, coins, signal_fn, params, indicators, fee, windows):
    """5-Way window split. PASS if >=4/5 windows PF>=1.0."""
    results = {}
    n_profitable = 0
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = windows[name]
        bt = _run_pipeline(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=w["start"], end_bar=w["end"])
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


def test_walk_forward(data, coins, signal_fn, params, indicators, fee, windows):
    """Walk-forward: 2 splits. PASS if either split passes."""
    max_bars = windows["max_bars"]

    # Compute 3-way boundaries for WF (early/mid/late)
    usable = max_bars - START_BAR
    third = usable // 3
    early_end = START_BAR + third
    mid_end = START_BAR + 2 * third

    # Split A: cal=early, test=mid+late
    cal_a = _run_pipeline(data, coins, signal_fn, params, indicators,
                          fee=fee, start_bar=START_BAR, end_bar=early_end)
    test_a = _run_pipeline(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=early_end, end_bar=max_bars)
    split_a_pass = (cal_a["pf"] >= 1.0 and cal_a["trades"] > 0
                    and test_a["pf"] >= 0.9 and test_a["trades"] > 0)

    # Split B: cal=early+mid, test=late
    cal_b = _run_pipeline(data, coins, signal_fn, params, indicators,
                          fee=fee, start_bar=START_BAR, end_bar=mid_end)
    test_b = _run_pipeline(data, coins, signal_fn, params, indicators,
                           fee=fee, start_bar=mid_end, end_bar=max_bars)
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
    """Bootstrap. PASS if P5 PF >= GATE_BOOT_P5 AND >= GATE_BOOT_PROF% profitable."""
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


def check_determinism(data, coins, signal_fn, params, indicators, fee):
    """Rerun full-range and verify exact match."""
    r1 = _run_pipeline(data, coins, signal_fn, params, indicators, fee=fee)
    r2 = _run_pipeline(data, coins, signal_fn, params, indicators, fee=fee)
    match = (r1["trades"] == r2["trades"]
             and abs(r1["pf"] - r2["pf"]) < 1e-6
             and abs(r1["pnl"] - r2["pnl"]) < 0.01)
    return {
        "pass": match,
        "run1": {"trades": r1["trades"], "pf": r1["pf"], "pnl": r1["pnl"]},
        "run2": {"trades": r2["trades"], "pf": r2["pf"], "pnl": r2["pnl"]},
    }


def _verdict(ws_pass, wf_pass, bs_pass):
    n = sum([ws_pass, wf_pass, bs_pass])
    if n == 3:
        return "VERIFIED", 3
    elif n == 2:
        return "CONDITIONAL", 2
    else:
        return "FAILED", n


# ===========================================================================
# Gate evaluation
# ===========================================================================

def evaluate_gates(full_metrics, ws, wf, bs, det):
    """Check all acceptance gates."""
    gates = {
        "pf": {
            "gate": f"PF >= {GATE_PF}",
            "value": full_metrics["pf"],
            "pass": full_metrics["pf"] >= GATE_PF,
        },
        "dd": {
            "gate": f"DD <= {GATE_DD}%",
            "value": full_metrics["dd"],
            "pass": full_metrics["dd"] <= GATE_DD,
        },
        "bootstrap_p5": {
            "gate": f"Boot P5 PF >= {GATE_BOOT_P5}",
            "value": bs["p5_pf"],
            "pass": bs["p5_pf"] >= GATE_BOOT_P5,
        },
        "bootstrap_prof": {
            "gate": f"Boot %prof >= {GATE_BOOT_PROF}%",
            "value": bs["pct_profitable"],
            "pass": bs["pct_profitable"] >= GATE_BOOT_PROF,
        },
        "window_split": {
            "gate": f"Window >= {GATE_WINDOW}/{N_WINDOWS}",
            "value": ws["n_profitable"],
            "pass": ws["pass"],
        },
        "trades": {
            "gate": f"Trades >= {GATE_TRADES}",
            "value": full_metrics["trades"],
            "pass": full_metrics["trades"] >= GATE_TRADES,
        },
        "determinism": {
            "gate": "Determinism",
            "value": "PASS" if det["pass"] else "FAIL",
            "pass": det["pass"],
        },
    }
    n_pass = sum(1 for g in gates.values() if g["pass"])
    all_pass = n_pass == len(gates)
    return gates, n_pass, all_pass


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    git = _git_hash()

    print("\n" + "=" * 72)
    print("  MEXC COMBINED DEPLOY CANDIDATE")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print(f"  Entry: Vol Capitulation (H4S4-G05), vol_mult=3.5, rsi_max=35")
    print(f"  Exit tweak: rsi_rec_min_bars=5 (engine-level)")
    print(f"  Risk wrapper: dd_throttle(>{DD_THROTTLE_THRESHOLD*100:.0f}%, "
          f"scale={DD_THROTTLE_SCALE}) + adaptive_maxpos("
          f"{ADAPTIVE_MAXPOS_NORMAL}/{ADAPTIVE_MAXPOS_DD10}/{ADAPTIVE_MAXPOS_DD20})")
    print(f"  Universe: MEXC top-200, >=2160 bars, full-range")
    print(f"  Fee: MEXC 10bps, Sizing: fixed $2000/trade")
    print(f"  Git: {git}")

    # ------------------------------------------------------------------
    # Step 1: Load data + precompute
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

    # ------------------------------------------------------------------
    # Step 2: Resolve config + set params
    # ------------------------------------------------------------------
    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])

    # Entry overrides
    base_params["vol_mult"] = 3.5
    base_params["rsi_max"] = 35
    base_params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c

    # Exit overrides (engine-level)
    base_params.update(EXIT_PARAMS)

    print(f"\n  Signal: {cfg041['hypothesis_name']}")
    print(f"  Entry: vol_mult={base_params['vol_mult']}, rsi_max={base_params['rsi_max']}")
    print(f"  Exit: max_stop_pct={EXIT_PARAMS['max_stop_pct']}, "
          f"time_max_bars={EXIT_PARAMS['time_max_bars']}, "
          f"rsi_rec_target={EXIT_PARAMS['rsi_rec_target']}, "
          f"rsi_rec_min_bars={EXIT_PARAMS['rsi_rec_min_bars']}")

    windows = _compute_5way_windows(max_bar)
    print(f"  Max bars: {max_bar}, Days: ~{n_days:.0f}")
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = windows[name]
        print(f"  Window {name}: bars {w['start']}-{w['end']}")

    # ------------------------------------------------------------------
    # Step 3: Full-range combined run
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  [1] Full-range combined pipeline (engine + wrappers)")
    print(f"{'='*72}")
    t0 = time.time()
    full_result = run_engine(data, coins, signal_fn, base_params, indicators,
                             fee=MEXC_FEE)
    full_metrics = compute_metrics(full_result["wrapped_trades"])
    full_ea = exit_attribution(full_result["wrapped_trades"])

    # Also compute baseline (no wrappers) for comparison
    baseline_metrics = compute_metrics(full_result["fixed_trades"])
    baseline_ea = exit_attribution(full_result["fixed_trades"])

    elapsed = time.time() - t0
    print(f"\n  Baseline (engine only, rsi_rec_min_bars=5):")
    print(f"    Trades: {baseline_metrics['trades']}, PF: {baseline_metrics['pf']:.4f}, "
          f"P&L: ${baseline_metrics['pnl']:+,.2f}, DD: {baseline_metrics['dd']:.1f}%, "
          f"WR: {baseline_metrics['wr']:.1f}%")

    print(f"\n  Combined (engine + dd_throttle + adaptive_maxpos):")
    print(f"    Trades: {full_metrics['trades']}, PF: {full_metrics['pf']:.4f}, "
          f"P&L: ${full_metrics['pnl']:+,.2f}, DD: {full_metrics['dd']:.1f}%, "
          f"WR: {full_metrics['wr']:.1f}%, EV/trade: ${full_metrics['ev_trade']:.2f}")
    print(f"    Trades/day: {full_metrics['trades_per_day']:.2f}, "
          f"Capped: {full_result['n_capped']}, "
          f"Skipped by wrapper: {full_result['n_skipped']}")
    print(f"    ({elapsed:.1f}s)")

    # Exit attribution
    print(f"\n  Exit Attribution (combined):")
    for reason, stats in sorted(full_ea.items(), key=lambda x: x[1]["pnl"], reverse=True):
        print(f"    {reason}: {stats['count']}x, ${stats['pnl']:+,.0f}, "
              f"WR={stats['wr']:.0f}% ({stats['class']})")

    # ------------------------------------------------------------------
    # Step 4: 5-Way Window Split
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  [2] 5-Way Window Split")
    print(f"{'='*72}")
    t0 = time.time()
    ws = test_window_split_5way(data, coins, signal_fn, base_params, indicators,
                                 fee=MEXC_FEE, windows=windows)
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = ws[name]
        mark = "✅" if w["pf"] >= 1.0 and w["trades"] > 0 else "❌"
        print(f"    {name}: bars {w['start']}-{w['end']} | {w['trades']}tr | "
              f"PF={w['pf']:.2f} | ${w['pnl']:+,.0f} | DD={w['dd']:.1f}% {mark}")
    print(f"    → {ws['n_profitable']}/{N_WINDOWS} {'PASS' if ws['pass'] else 'FAIL'} "
          f"(gate: >={GATE_WINDOW}/{N_WINDOWS}) ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # Step 5: Walk-Forward
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  [3] Walk-Forward")
    print(f"{'='*72}")
    t0 = time.time()
    wf = test_walk_forward(data, coins, signal_fn, base_params, indicators,
                           fee=MEXC_FEE, windows=windows)
    for sname, s in [("A", wf["split_a"]), ("B", wf["split_b"])]:
        mark = "✅" if s["pass"] else "❌"
        print(f"    Split {sname}: cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
              f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f} {mark}")
    print(f"    → {'PASS' if wf['pass'] else 'FAIL'} ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # Step 6: Bootstrap
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print(f"  [4] Bootstrap ({N_RESAMPLES} resamples)")
    print(f"{'='*72}")
    t0 = time.time()
    bs = test_bootstrap(full_result["wrapped_trades"])
    print(f"    P5 PF: {bs['p5_pf']:.2f} (gate: >={GATE_BOOT_P5})")
    print(f"    Median PF: {bs['median_pf']:.2f}")
    print(f"    %Profitable: {bs['pct_profitable']:.1f}% (gate: >={GATE_BOOT_PROF}%)")
    print(f"    → {'PASS' if bs['pass'] else 'FAIL'} ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # Step 7: Determinism
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  [5] Determinism Check")
    print(f"{'='*72}")
    t0 = time.time()
    det = check_determinism(data, coins, signal_fn, base_params, indicators,
                            fee=MEXC_FEE)
    print(f"    Run1: {det['run1']['trades']}tr PF={det['run1']['pf']:.4f} "
          f"P&L=${det['run1']['pnl']:+,.2f}")
    print(f"    Run2: {det['run2']['trades']}tr PF={det['run2']['pf']:.4f} "
          f"P&L=${det['run2']['pnl']:+,.2f}")
    print(f"    → {'PASS' if det['pass'] else 'FAIL'} ({time.time()-t0:.1f}s)")

    # ------------------------------------------------------------------
    # Step 8: Gate evaluation
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  ACCEPTANCE GATES")
    print(f"{'='*72}")
    gates, n_gates_pass, all_gates_pass = evaluate_gates(
        full_metrics, ws, wf, bs, det)
    for name, g in gates.items():
        mark = "✅" if g["pass"] else "❌"
        print(f"    {mark} {g['gate']}: {g['value']}")

    verdict, n_truthpass = _verdict(ws["pass"], wf["pass"], bs["pass"])

    print(f"\n    Truth-Pass: {verdict} ({n_truthpass}/3)")
    print(f"    Gates: {n_gates_pass}/{len(gates)} passed")
    if all_gates_pass:
        print(f"\n    >>> DEPLOY CANDIDATE <<<")
    else:
        failed = [name for name, g in gates.items() if not g["pass"]]
        print(f"\n    >>> NOT DEPLOY-READY (failed: {', '.join(failed)}) <<<")

    # ------------------------------------------------------------------
    # Step 9: Reports
    # ------------------------------------------------------------------
    print(f"\n{'='*72}")
    print("  REPORTS")
    print(f"{'='*72}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "mexc_combined_deploy",
        "experiment_id": REPORT_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, >={MIN_BARS_TOP200} bars",
            "id": "mexc_4h_top200_2160_v1",
            "n_coins": n_coins,
            "bars_min": min(bars_counts),
            "bars_max": max(bars_counts),
            "bars_median": int(median(bars_counts)),
            "full_range_days": round(n_days, 1),
        },
        "fee": MEXC_FEE,
        "fee_model": "mexc_spot_10bps",
        "sizing": "fixed_notional_2000",
        "config": {
            "hypothesis_id": CONFIG_041_HYP_ID,
            "hypothesis_name": cfg041["hypothesis_name"],
            "entry": {"vol_mult": 3.5, "rsi_max": 35},
            "exit": EXIT_PARAMS,
            "wrapper": {
                "dd_throttle": {"threshold": DD_THROTTLE_THRESHOLD,
                                "scale": DD_THROTTLE_SCALE},
                "adaptive_maxpos": {"normal": ADAPTIVE_MAXPOS_NORMAL,
                                    "dd10": ADAPTIVE_MAXPOS_DD10,
                                    "dd20": ADAPTIVE_MAXPOS_DD20},
            },
        },
        "baseline_no_wrapper": {
            "trades": baseline_metrics["trades"],
            "pf": baseline_metrics["pf"],
            "pnl": baseline_metrics["pnl"],
            "dd": baseline_metrics["dd"],
            "wr": baseline_metrics["wr"],
        },
        "combined_result": {
            "trades": full_metrics["trades"],
            "pf": full_metrics["pf"],
            "pnl": full_metrics["pnl"],
            "dd": full_metrics["dd"],
            "wr": full_metrics["wr"],
            "ev_trade": full_metrics["ev_trade"],
            "trades_per_day": full_metrics["trades_per_day"],
            "n_capped": full_result["n_capped"],
            "n_skipped": full_result["n_skipped"],
        },
        "exit_attribution": full_ea,
        "window_split": {k: v for k, v in ws.items() if k != "trade_list"},
        "walk_forward": wf,
        "bootstrap": bs,
        "determinism": det,
        "gates": gates,
        "n_gates_pass": n_gates_pass,
        "all_gates_pass": all_gates_pass,
        "verdict": verdict,
        "tests_passed": n_truthpass,
    }

    json_path = REPORT_DIR / f"{REPORT_ID}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  JSON: {json_path}")

    # --- MD Report ---
    md = _build_md(report, full_metrics, baseline_metrics, full_ea,
                   baseline_ea, ws, wf, bs, det, gates,
                   n_coins, bars_counts, git, n_days,
                   all_gates_pass, n_gates_pass, verdict, n_truthpass)
    md_path = REPORT_DIR / f"{REPORT_ID}.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  MD:   {md_path}")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    elapsed = time.time() - t_total
    print(f"\n{'='*72}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*72}")
    print(f"  Config: Vol Capitulation (041) + rsi_rec_min_bars=5")
    print(f"        + dd_throttle(5%/0.25x) + adaptive_maxpos(2/1/1)")
    print(f"  Combined: PF={full_metrics['pf']:.4f}, "
          f"P&L=${full_metrics['pnl']:+,.2f}, "
          f"{full_metrics['trades']}tr, "
          f"DD={full_metrics['dd']:.1f}%")
    print(f"  Truth-Pass: {verdict} ({n_truthpass}/3)")
    print(f"  Gates: {n_gates_pass}/{len(gates)} passed")
    print(f"  Deploy: {'YES' if all_gates_pass else 'NO'}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"{'='*72}\n")


def _build_md(report, full_m, baseline_m, full_ea, baseline_ea,
              ws, wf, bs, det, gates,
              n_coins, bars_counts, git, n_days,
              all_pass, n_gates_pass, verdict, n_truthpass):
    """Build Markdown report."""
    max_bar = max(bars_counts)
    lines = [
        "# MEXC Combined Deploy Candidate — Report",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Universe**: Top {TOP_N} by volume, >={MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Full range**: ~{n_days:.0f} days, {max_bar} bars",
        f"**Fee**: MEXC 10bps",
        f"**Sizing**: Fixed $2,000/trade (no compounding)",
        "",
        "## Configuration",
        "",
        "| Layer | Parameter | Value |",
        "|-------|-----------|-------|",
        "| Entry | Signal | Vol Capitulation (H4S4-G05) |",
        "| Entry | vol_mult | 3.5 |",
        "| Entry | rsi_max | 35 |",
        f"| Exit | max_stop_pct | {EXIT_PARAMS['max_stop_pct']} |",
        f"| Exit | time_max_bars | {EXIT_PARAMS['time_max_bars']} |",
        f"| Exit | rsi_rec_target | {EXIT_PARAMS['rsi_rec_target']} |",
        f"| Exit | rsi_rec_min_bars | **{EXIT_PARAMS['rsi_rec_min_bars']}** (was 2) |",
        f"| Wrapper | dd_throttle | >{DD_THROTTLE_THRESHOLD*100:.0f}% → {DD_THROTTLE_SCALE}x |",
        f"| Wrapper | adaptive_maxpos | {ADAPTIVE_MAXPOS_NORMAL}/{ADAPTIVE_MAXPOS_DD10}/{ADAPTIVE_MAXPOS_DD20} |",
        "",
        "---",
        "",
        "## Results Summary",
        "",
        "| Metric | Baseline (no wrapper) | Combined | Delta |",
        "|--------|----------------------:|--------:|------:|",
        f"| PF | {baseline_m['pf']:.4f} | {full_m['pf']:.4f} | {full_m['pf']-baseline_m['pf']:+.4f} |",
        f"| P&L | ${baseline_m['pnl']:+,.0f} | ${full_m['pnl']:+,.0f} | ${full_m['pnl']-baseline_m['pnl']:+,.0f} |",
        f"| Trades | {baseline_m['trades']} | {full_m['trades']} | {full_m['trades']-baseline_m['trades']:+d} |",
        f"| DD | {baseline_m['dd']:.1f}% | {full_m['dd']:.1f}% | {full_m['dd']-baseline_m['dd']:+.1f}pp |",
        f"| WR | {baseline_m['wr']:.1f}% | {full_m['wr']:.1f}% | {full_m['wr']-baseline_m['wr']:+.1f}pp |",
        f"| EV/trade | | ${full_m['ev_trade']:.2f} | |",
        f"| Trades/day | | {full_m['trades_per_day']:.2f} | |",
        "",
        "## Exit Attribution (Combined)",
        "",
        "| Exit Reason | Class | Count | P&L | WR |",
        "|-------------|-------|------:|----:|---:|",
    ]
    for reason, stats in sorted(full_ea.items(), key=lambda x: x[1]["pnl"], reverse=True):
        lines.append(f"| {reason} | {stats['class']} | {stats['count']} "
                     f"| ${stats['pnl']:+,.0f} | {stats['wr']:.0f}% |")
    lines.append("")

    # Acceptance Gates
    lines.append("---")
    lines.append("")
    lines.append("## Acceptance Gates")
    lines.append("")
    lines.append("| Gate | Threshold | Value | Status |")
    lines.append("|------|-----------|------:|-------:|")
    for name, g in gates.items():
        mark = "✅ PASS" if g["pass"] else "❌ FAIL"
        lines.append(f"| {g['gate']} | | {g['value']} | {mark} |")
    lines.append("")
    lines.append(f"**Gates passed**: {n_gates_pass}/{len(gates)}")
    lines.append(f"**Deploy ready**: {'YES' if all_pass else 'NO'}")
    lines.append("")

    # Truth-Pass Detail
    lines.append("---")
    lines.append("")
    lines.append(f"## Truth-Pass: {verdict} ({n_truthpass}/3)")
    lines.append("")

    # Window Split
    lines.append(f"### {N_WINDOWS}-Way Window Split")
    lines.append("")
    lines.append("| Window | Bars | Trades | PF | P&L | DD | Status |")
    lines.append("|--------|-----:|-------:|---:|----:|---:|-------:|")
    for i in range(N_WINDOWS):
        name = f"w{i+1}"
        w = ws[name]
        mark = "✅" if w["pf"] >= 1.0 and w["trades"] > 0 else "❌"
        lines.append(f"| {name} | {w['start']}-{w['end']} | {w['trades']} "
                     f"| {w['pf']:.2f} | ${w['pnl']:+,.0f} | {w['dd']:.1f}% | {mark} |")
    lines.append(f"\n**{ws['n_profitable']}/{N_WINDOWS} "
                 f"{'PASS' if ws['pass'] else 'FAIL'}** (gate: >={GATE_WINDOW}/{N_WINDOWS})")
    lines.append("")

    # Walk-Forward
    lines.append("### Walk-Forward")
    lines.append("")
    for sname, s in [("A (cal=early, test=mid+late)", wf["split_a"]),
                     ("B (cal=early+mid, test=late)", wf["split_b"])]:
        mark = "PASS" if s["pass"] else "FAIL"
        lines.append(f"- **Split {sname}** [{mark}]: "
                     f"cal={s['cal']['trades']}tr PF={s['cal']['pf']:.2f}, "
                     f"test={s['test']['trades']}tr PF={s['test']['pf']:.2f}")
    lines.append("")

    # Bootstrap
    lines.append("### Bootstrap")
    lines.append("")
    lines.append(f"- P5 PF: {bs['p5_pf']:.2f} (gate: >={GATE_BOOT_P5})")
    lines.append(f"- Median PF: {bs['median_pf']:.2f}")
    lines.append(f"- %Profitable: {bs['pct_profitable']:.1f}% (gate: >={GATE_BOOT_PROF}%)")
    lines.append(f"- **{'PASS' if bs['pass'] else 'FAIL'}**")
    lines.append("")

    # Determinism
    lines.append(f"### Determinism: **{'PASS' if det['pass'] else 'FAIL'}**")
    lines.append("")

    # Verdict
    lines.append("---")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if all_pass:
        lines.append("### ✅ DEPLOY CANDIDATE")
        lines.append("")
        lines.append("All acceptance gates passed. This combined configuration is ready for paper trading.")
    else:
        failed = [name for name, g in gates.items() if not g["pass"]]
        lines.append(f"### ❌ NOT DEPLOY-READY")
        lines.append("")
        lines.append(f"Failed gates: {', '.join(failed)}")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
