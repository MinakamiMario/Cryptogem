#!/usr/bin/env python3
"""
MEXC Risk Wrapper Sweep — Position sizing & DD reduction for Sprint4_041.

Post-hoc risk wrapper sweep on the MEXC top-200 full-range baseline.
Goal: find wrappers that reduce DD while preserving PF >= 1.15.

Baseline: Sprint4_041 (Vol Capitulation, H4S4-G05) with vol_mult=3.5, rsi_max=35
on MEXC top-200 by median volume, >=2160 bars, MEXC 10bps fee, full range (~2853 bars).

Wrapper strategies:
  A. DD Throttle       -- reduce position size when equity is in drawdown
  B. Vol Scaling       -- scale size inversely with recent ATR
  C. Adaptive MaxPos   -- reduce concurrent positions based on DD level
  D. Cooldown Extension -- longer cooldown after stop-loss exits
  E. Combined          -- best of each category combined

All metrics use FIXED-NOTIONAL normalization ($2000/trade).
Per-trade returns capped at +/-100% (data anomaly filter).

Output:
  reports/4h/mexc_risk_wrappers_006.json
  reports/4h/mexc_risk_wrappers_006.md

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_mexc_risk_wrappers.py
"""
from __future__ import annotations

import sys
import json
import time
import copy
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median
from itertools import product

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_ROOT = Path.home() / "CryptogemData"
V2_DATA_FILE = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h" / "candle_cache_4h_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
MIN_BARS_TOP200 = 2160
TOP_N = 200

# Fixed-notional cap
MAX_RETURN_RATIO = 1.0  # Cap at +/-100%
NOTIONAL = 2000

# Baseline reference (from truthpass report)
BASELINE_PF = 1.36
BASELINE_DD = 52.6
BASELINE_TRADES = 330

STOP_REASONS = {"FIXED STOP", "HARD STOP"}


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Data loading (same as run_mexc_top200_truthpass.py)
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

def normalize_trades(trade_list, notional=NOTIONAL):
    """Convert equity-proportional trades to fixed-notional.

    Each trade's return = pnl / size, then fixed_pnl = return * notional.
    Cap returns at +/-MAX_RETURN_RATIO (data anomaly filter).
    """
    fixed = []
    n_capped = 0
    for t in trade_list:
        size = t.get("size", notional)
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


# ===========================================================================
# Metrics computation
# ===========================================================================

def compute_metrics(trades, initial_capital=INITIAL_CAPITAL):
    """Compute PF, DD, P&L, trade count from fixed-notional trade list."""
    if not trades:
        return {"trades": 0, "pf": 0.0, "pnl": 0.0, "dd": 0.0,
                "wr": 0.0, "final_equity": initial_capital, "ev_trade": 0.0,
                "trades_per_day": 0.0}

    equity = initial_capital
    peak_equity = initial_capital
    max_dd = 0.0
    wins_sum = 0.0
    losses_sum = 0.0
    n_wins = 0

    for t in trades:
        pnl = t["pnl"]
        equity += pnl
        if pnl > 0:
            wins_sum += pnl
            n_wins += 1
        else:
            losses_sum += abs(pnl)
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            dd_pct = (peak_equity - equity) / peak_equity * 100
            if dd_pct > max_dd:
                max_dd = dd_pct

    n = len(trades)
    pf = wins_sum / losses_sum if losses_sum > 0 else (99.99 if wins_sum > 0 else 0.0)
    total_pnl = equity - initial_capital
    wr = n_wins / n * 100 if n > 0 else 0.0
    ev_trade = total_pnl / n if n > 0 else 0.0

    # Trades per day (approximate: full range ~467 days)
    if trades:
        first_bar = min(t["entry_bar"] for t in trades)
        last_bar = max(t["exit_bar"] for t in trades)
        n_bars = last_bar - first_bar + 1
        n_days = n_bars * 4 / 24  # 4H bars
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
        "ev_trade": round(ev_trade, 2),
        "trades_per_day": round(tpd, 2),
    }


def sort_trades(trades):
    """Sort trades chronologically by entry_bar, then exit_bar."""
    return sorted(trades, key=lambda t: (t["entry_bar"], t["exit_bar"]))


# ===========================================================================
# Scoring function
# ===========================================================================

def score_wrapper(pf, dd, trades, baseline_pf=BASELINE_PF,
                  baseline_dd=BASELINE_DD, baseline_trades=BASELINE_TRADES):
    """Higher = better. Rewards DD reduction, penalizes PF loss."""
    dd_improvement = max(0, baseline_dd - dd) / baseline_dd  # 0-1 scale
    pf_retention = min(pf / baseline_pf, 1.2)  # cap at 120% of baseline
    trade_retention = min(trades / baseline_trades, 1.0)  # penalize losing >50% trades
    if pf < 1.0:
        return 0.0  # hard gate
    return round(dd_improvement * 0.5 + pf_retention * 0.3 + trade_retention * 0.2, 6)


# ===========================================================================
# Wrapper A: DD Throttle
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
        new_t["size"] = round(t["size"] * scale, 2)
        new_t["_scale"] = scale
        result.append(new_t)

        equity += new_t["pnl"]
        if equity > peak_equity:
            peak_equity = equity

    return result


# ===========================================================================
# Wrapper B: Vol Scaling
# ===========================================================================

def apply_vol_scaling(trades, atr_by_pair, target_percentile, atr_lookback,
                      initial_capital=INITIAL_CAPITAL):
    """Scale position size inversely with recent ATR.

    For each trade, lookup ATR at entry_bar. Compute percentile across all
    trade entry ATRs. Scale = target_pctl_value / current_atr. Clamp [0.25, 2.0].
    """
    # Collect ATR at entry for all trades
    atr_at_entries = []
    for t in trades:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])
        if bar < len(atr_arr) and atr_arr[bar] is not None and atr_arr[bar] > 0:
            atr_at_entries.append(atr_arr[bar])

    if not atr_at_entries:
        return list(trades)

    atr_sorted = sorted(atr_at_entries)
    idx = max(0, int(len(atr_sorted) * target_percentile / 100) - 1)
    target_atr = atr_sorted[idx]
    if target_atr <= 0:
        return list(trades)

    sorted_t = sort_trades(trades)
    result = []
    for t in sorted_t:
        pair = t["pair"]
        bar = t["entry_bar"]
        atr_arr = atr_by_pair.get(pair, [])

        if bar < len(atr_arr) and atr_arr[bar] is not None and atr_arr[bar] > 0:
            current_atr = atr_arr[bar]
            scale = target_atr / current_atr
            scale = max(0.25, min(2.0, scale))
        else:
            scale = 1.0

        new_t = dict(t)
        new_t["pnl"] = round(t["pnl"] * scale, 2)
        new_t["size"] = round(t["size"] * scale, 2)
        new_t["_scale"] = scale
        result.append(new_t)

    return result


# ===========================================================================
# Wrapper C: Adaptive MaxPos
# ===========================================================================

def apply_adaptive_maxpos(trades, normal_max, dd10_max, dd20_max,
                          initial_capital=INITIAL_CAPITAL):
    """Reduce max concurrent positions based on DD level.

    DD < 10%:  max_pos = normal_max
    DD 10-20%: max_pos = dd10_max
    DD > 20%:  max_pos = dd20_max

    Walks chronologically, tracks open positions, skips excess.
    """
    sorted_t = sort_trades(trades)
    result = []
    equity = initial_capital
    peak_equity = initial_capital
    open_positions = []  # list of (entry_bar, exit_bar)

    for t in sorted_t:
        entry_bar = t["entry_bar"]
        exit_bar = t["exit_bar"]

        # Close positions that have exited by this entry_bar
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

        # Check capacity
        if len(open_positions) >= max_pos:
            continue  # skip this trade

        # Accept trade
        open_positions.append((entry_bar, exit_bar))
        result.append(dict(t))

        # Update equity
        equity += t["pnl"]
        if equity > peak_equity:
            peak_equity = equity

    return result


# ===========================================================================
# Wrapper D: Cooldown Extension
# ===========================================================================

def apply_cooldown_ext(trades, cooldown_bars, initial_capital=INITIAL_CAPITAL):
    """Extend cooldown after stop-loss exits.

    Skip trades where entry_bar - prev_exit_bar < cooldown_bars
    for same coin after a FIXED STOP exit.
    """
    sorted_t = sort_trades(trades)
    result = []
    last_stop_bar = {}  # pair -> exit_bar

    for t in sorted_t:
        pair = t["pair"]
        entry_bar = t["entry_bar"]

        # Check cooldown
        if pair in last_stop_bar:
            bars_since_stop = entry_bar - last_stop_bar[pair]
            if bars_since_stop < cooldown_bars:
                continue

        result.append(dict(t))

        # Track if this was a stop
        if t.get("reason", "") in STOP_REASONS:
            last_stop_bar[pair] = t["exit_bar"]

    return result


# ===========================================================================
# Wrapper grids
# ===========================================================================

DD_THROTTLE_GRID = [
    {"dd_threshold": dt, "size_scale": ss}
    for dt in [0.05, 0.10, 0.15, 0.20, 0.25]
    for ss in [0.25, 0.50, 0.75]
]  # 15 combos

VOL_SCALE_GRID = [
    {"atr_lookback": al, "target_percentile": tp}
    for al in [7, 14, 21]
    for tp in [25, 50, 75]
]  # 9 combos

ADAPTIVE_MAXPOS_GRID = [
    {"normal_max": 3, "dd10_max": 2, "dd20_max": 1},
    {"normal_max": 3, "dd10_max": 3, "dd20_max": 1},
    {"normal_max": 2, "dd10_max": 2, "dd20_max": 1},
    {"normal_max": 2, "dd10_max": 1, "dd20_max": 1},
]  # 4 combos

COOLDOWN_EXT_GRID = [
    {"cooldown_bars": cb}
    for cb in [8, 12, 16, 20, 24]
]  # 5 combos


# ===========================================================================
# Main execution
# ===========================================================================

def main():
    t_total = time.time()
    git_hash = _git_hash()

    print("\n" + "=" * 72)
    print("  MEXC RISK WRAPPER SWEEP")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print(f"  Config: Sprint4_041 (H4S4-G05) vol_mult=3.5, rsi_max=35")
    print(f"  Dataset: MEXC v2, top-200, >=2160 bars, full range")
    print(f"  Fee: MEXC 10bps ({MEXC_FEE})")
    print(f"  Sizing: Fixed notional ${NOTIONAL}/trade")
    print(f"  Git: {git_hash}")

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

    print("\n  Precomputing indicators...")
    t0 = time.time()
    indicators = _s2_ind.precompute_all(data, coins)
    market_context = _s2_ctx.precompute_sprint2_context(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s")

    # ------------------------------------------------------------------
    # Step 2: Find config 041, set up params
    # ------------------------------------------------------------------
    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])

    # Override to vol_mult=3.5, rsi_max=35 (primary config from truthpass)
    base_params["vol_mult"] = 3.5
    base_params["rsi_max"] = 35
    base_params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c

    print(f"\n  Signal: {cfg041['hypothesis_name']}")
    print(f"  vol_mult={base_params['vol_mult']}, rsi_max={base_params['rsi_max']}")
    print(f"  max_stop_pct={base_params.get('max_stop_pct')}, "
          f"time_max_bars={base_params.get('time_max_bars')}")

    # ------------------------------------------------------------------
    # Step 3: Run baseline backtest
    # ------------------------------------------------------------------
    print("\n  Running baseline backtest (full range)...")
    _engine = importlib.import_module("strategies.4h.sprint3.engine")
    t0 = time.time()
    result = _engine.run_backtest(
        data, coins, signal_fn, base_params, indicators,
        fee=MEXC_FEE, exit_mode="dc",
        start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
    )
    bt_time = time.time() - t0
    print(f"  Backtest done in {bt_time:.1f}s")
    print(f"  Raw trades: {result.trades}, PF: {result.pf:.4f}, "
          f"P&L: ${result.pnl:+,.2f}, DD: {result.dd:.1f}%")

    # ------------------------------------------------------------------
    # Step 4: Normalize to fixed-notional
    # ------------------------------------------------------------------
    raw_trades = result.trade_list
    fixed_trades, n_capped = normalize_trades(raw_trades, NOTIONAL)
    fixed_trades = sort_trades(fixed_trades)
    baseline = compute_metrics(fixed_trades)

    print(f"\n  Fixed-notional baseline:")
    print(f"  Trades: {baseline['trades']}, PF: {baseline['pf']:.4f}, "
          f"P&L: ${baseline['pnl']:+,.2f}, DD: {baseline['dd']:.1f}%, "
          f"WR: {baseline['wr']:.1f}%, EV/trade: ${baseline['ev_trade']:.2f}")
    print(f"  Trades/day: {baseline['trades_per_day']:.2f}, Capped: {n_capped}")

    # Update baseline reference with actual values
    actual_baseline_pf = baseline["pf"]
    actual_baseline_dd = baseline["dd"]
    actual_baseline_trades = baseline["trades"]

    # ------------------------------------------------------------------
    # Step 5: Extract ATR arrays for vol_scaling
    # ------------------------------------------------------------------
    print("\n  Extracting ATR arrays for vol_scaling...")
    atr_by_pair = {}
    for pair in coins:
        ind = indicators.get(pair)
        if ind and "atr" in ind:
            atr_by_pair[pair] = ind["atr"]
    print(f"  ATR data for {len(atr_by_pair)} pairs")

    # ------------------------------------------------------------------
    # Step 6: Run all individual wrappers
    # ------------------------------------------------------------------
    all_results = []
    category_best = {}  # category -> (score, result_dict)

    def run_and_record(category, label, wrapper_fn, *args, **kwargs):
        """Apply wrapper, compute metrics, record result."""
        wrapped_trades = wrapper_fn(fixed_trades, *args, **kwargs)
        m = compute_metrics(wrapped_trades)
        sc = score_wrapper(m["pf"], m["dd"], m["trades"],
                           actual_baseline_pf, actual_baseline_dd, actual_baseline_trades)

        entry = {
            "category": category,
            "label": label,
            "trades": m["trades"],
            "pf": m["pf"],
            "pnl": m["pnl"],
            "dd": m["dd"],
            "wr": m["wr"],
            "ev_trade": m["ev_trade"],
            "score": sc,
            "dd_reduction_pct": round((actual_baseline_dd - m["dd"]) / actual_baseline_dd * 100, 2) if actual_baseline_dd > 0 else 0,
            "pf_change_pct": round((m["pf"] - actual_baseline_pf) / actual_baseline_pf * 100, 2) if actual_baseline_pf > 0 else 0,
            "trade_loss_pct": round((actual_baseline_trades - m["trades"]) / actual_baseline_trades * 100, 2) if actual_baseline_trades > 0 else 0,
        }
        all_results.append(entry)

        # Track category best
        if category not in category_best or sc > category_best[category][0]:
            category_best[category] = (sc, entry)

        # Print
        pf_mark = "+" if m["pf"] >= actual_baseline_pf else ""
        dd_mark = "v" if m["dd"] < actual_baseline_dd else "^"
        gate = "PASS" if m["pf"] >= 1.15 and m["dd"] < 35 and m["trades"] > 200 else "----"
        print(f"    [{gate}] {label:<50s} | Tr {m['trades']:>3d} | PF {m['pf']:.2f} | "
              f"DD {m['dd']:>5.1f}% {dd_mark} | P&L ${m['pnl']:>+9.2f} | Score {sc:.4f}")

        return entry

    # --- A. DD Throttle ---
    print(f"\n  === A. DD Throttle ({len(DD_THROTTLE_GRID)} combos) ===")
    for p in DD_THROTTLE_GRID:
        label = f"dd_throttle(dd>{p['dd_threshold']*100:.0f}%,scale={p['size_scale']})"
        run_and_record("dd_throttle", label,
                       apply_dd_throttle,
                       dd_threshold=p["dd_threshold"],
                       size_scale=p["size_scale"])

    # --- B. Vol Scaling ---
    print(f"\n  === B. Vol Scaling ({len(VOL_SCALE_GRID)} combos) ===")
    for p in VOL_SCALE_GRID:
        label = f"vol_scale(atr{p['atr_lookback']},pctl={p['target_percentile']})"
        run_and_record("vol_scale", label,
                       apply_vol_scaling,
                       atr_by_pair=atr_by_pair,
                       target_percentile=p["target_percentile"],
                       atr_lookback=p["atr_lookback"])

    # --- C. Adaptive MaxPos ---
    print(f"\n  === C. Adaptive MaxPos ({len(ADAPTIVE_MAXPOS_GRID)} combos) ===")
    for p in ADAPTIVE_MAXPOS_GRID:
        label = f"adaptive_maxpos({p['normal_max']}/{p['dd10_max']}/{p['dd20_max']})"
        run_and_record("adaptive_maxpos", label,
                       apply_adaptive_maxpos,
                       normal_max=p["normal_max"],
                       dd10_max=p["dd10_max"],
                       dd20_max=p["dd20_max"])

    # --- D. Cooldown Extension ---
    print(f"\n  === D. Cooldown Extension ({len(COOLDOWN_EXT_GRID)} combos) ===")
    for p in COOLDOWN_EXT_GRID:
        label = f"cooldown_ext(cd={p['cooldown_bars']}bars)"
        run_and_record("cooldown_ext", label,
                       apply_cooldown_ext,
                       cooldown_bars=p["cooldown_bars"])

    # ------------------------------------------------------------------
    # Step 7: Combined wrappers (top-2 from each category)
    # ------------------------------------------------------------------
    print(f"\n  === E. Combined Wrappers ===")

    # Get top-2 from each individual category
    per_cat = {}
    for r in all_results:
        cat = r["category"]
        if cat not in per_cat:
            per_cat[cat] = []
        per_cat[cat].append(r)

    top2_per_cat = {}
    for cat, results in per_cat.items():
        sorted_r = sorted(results, key=lambda x: x["score"], reverse=True)
        top2_per_cat[cat] = sorted_r[:2]

    # Build combined combos: best dd_throttle x best vol_scale, etc.
    # Pick top-1 from each size-based (dd_throttle, vol_scale) and
    # top-1 from each trade-skipping (adaptive_maxpos, cooldown_ext)
    size_cats = ["dd_throttle", "vol_scale"]
    skip_cats = ["adaptive_maxpos", "cooldown_ext"]

    combined_count = 0

    # Combined: size-based + skip-based (top-2 each)
    for size_cat in size_cats:
        for skip_cat in skip_cats:
            size_top = top2_per_cat.get(size_cat, [])[:2]
            skip_top = top2_per_cat.get(skip_cat, [])[:2]
            for s_entry in size_top:
                for k_entry in skip_top:
                    combined_count += 1
                    combo_label = f"COMBO({s_entry['label']} + {k_entry['label']})"

                    # Apply size-based first, then skip-based
                    # Re-extract params from label to apply
                    # Size-based wrapper
                    if size_cat == "dd_throttle":
                        # Parse params from the grid by matching label
                        for p in DD_THROTTLE_GRID:
                            lbl = f"dd_throttle(dd>{p['dd_threshold']*100:.0f}%,scale={p['size_scale']})"
                            if lbl == s_entry["label"]:
                                step1 = apply_dd_throttle(
                                    fixed_trades,
                                    dd_threshold=p["dd_threshold"],
                                    size_scale=p["size_scale"],
                                )
                                break
                        else:
                            continue
                    else:  # vol_scale
                        for p in VOL_SCALE_GRID:
                            lbl = f"vol_scale(atr{p['atr_lookback']},pctl={p['target_percentile']})"
                            if lbl == s_entry["label"]:
                                step1 = apply_vol_scaling(
                                    fixed_trades,
                                    atr_by_pair=atr_by_pair,
                                    target_percentile=p["target_percentile"],
                                    atr_lookback=p["atr_lookback"],
                                )
                                break
                        else:
                            continue

                    # Skip-based wrapper on step1 output
                    if skip_cat == "adaptive_maxpos":
                        for p in ADAPTIVE_MAXPOS_GRID:
                            lbl = f"adaptive_maxpos({p['normal_max']}/{p['dd10_max']}/{p['dd20_max']})"
                            if lbl == k_entry["label"]:
                                step2 = apply_adaptive_maxpos(
                                    step1,
                                    normal_max=p["normal_max"],
                                    dd10_max=p["dd10_max"],
                                    dd20_max=p["dd20_max"],
                                )
                                break
                        else:
                            continue
                    else:  # cooldown_ext
                        for p in COOLDOWN_EXT_GRID:
                            lbl = f"cooldown_ext(cd={p['cooldown_bars']}bars)"
                            if lbl == k_entry["label"]:
                                step2 = apply_cooldown_ext(
                                    step1,
                                    cooldown_bars=p["cooldown_bars"],
                                )
                                break
                        else:
                            continue

                    # Compute metrics for combined
                    m = compute_metrics(step2)
                    sc = score_wrapper(m["pf"], m["dd"], m["trades"],
                                       actual_baseline_pf, actual_baseline_dd,
                                       actual_baseline_trades)

                    entry = {
                        "category": "combined",
                        "label": combo_label,
                        "trades": m["trades"],
                        "pf": m["pf"],
                        "pnl": m["pnl"],
                        "dd": m["dd"],
                        "wr": m["wr"],
                        "ev_trade": m["ev_trade"],
                        "score": sc,
                        "dd_reduction_pct": round((actual_baseline_dd - m["dd"]) / actual_baseline_dd * 100, 2) if actual_baseline_dd > 0 else 0,
                        "pf_change_pct": round((m["pf"] - actual_baseline_pf) / actual_baseline_pf * 100, 2) if actual_baseline_pf > 0 else 0,
                        "trade_loss_pct": round((actual_baseline_trades - m["trades"]) / actual_baseline_trades * 100, 2) if actual_baseline_trades > 0 else 0,
                    }
                    all_results.append(entry)

                    gate = "PASS" if m["pf"] >= 1.15 and m["dd"] < 35 and m["trades"] > 200 else "----"
                    dd_mark = "v" if m["dd"] < actual_baseline_dd else "^"
                    print(f"    [{gate}] {combo_label[:70]:<70s}")
                    print(f"           Tr {m['trades']:>3d} | PF {m['pf']:.2f} | "
                          f"DD {m['dd']:>5.1f}% {dd_mark} | P&L ${m['pnl']:>+9.2f} | Score {sc:.4f}")

    print(f"\n  Combined combos: {combined_count}")

    # ------------------------------------------------------------------
    # Step 8: Sort by score, build leaderboard
    # ------------------------------------------------------------------
    all_results.sort(key=lambda x: x["score"], reverse=True)
    top10 = all_results[:10]

    print(f"\n{'='*72}")
    print(f"  TOP-10 LEADERBOARD (by score)")
    print(f"{'='*72}")
    print(f"  {'#':>2s}  {'Score':>6s}  {'PF':>5s}  {'DD%':>6s}  {'Tr':>4s}  "
          f"{'P&L':>10s}  {'WR%':>5s}  {'DD red':>7s}  Label")
    print(f"  {'--':>2s}  {'-----':>6s}  {'----':>5s}  {'---':>6s}  {'--':>4s}  "
          f"{'---':>10s}  {'---':>5s}  {'------':>7s}  -----")
    for i, r in enumerate(top10, 1):
        deploy = "*" if r["pf"] >= 1.15 and r["dd"] < 35 and r["trades"] > 200 else " "
        print(f"  {i:>2d}{deploy} {r['score']:>6.4f}  {r['pf']:>5.2f}  {r['dd']:>5.1f}%  "
              f"{r['trades']:>4d}  ${r['pnl']:>+9.2f}  {r['wr']:>5.1f}  "
              f"{r['dd_reduction_pct']:>+6.1f}%  {r['label'][:60]}")

    # ------------------------------------------------------------------
    # Step 9: Category best
    # ------------------------------------------------------------------
    print(f"\n  PER-CATEGORY BEST:")
    for cat in ["dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext", "combined"]:
        cat_results = [r for r in all_results if r["category"] == cat]
        if cat_results:
            best = cat_results[0]  # already sorted by score
            print(f"    {cat:<20s}: Score {best['score']:.4f} | PF {best['pf']:.2f} | "
                  f"DD {best['dd']:.1f}% | Tr {best['trades']} | {best['label'][:50]}")

    # ------------------------------------------------------------------
    # Step 10: Deploy candidate check
    # ------------------------------------------------------------------
    deploy_candidates = [r for r in all_results
                         if r["pf"] >= 1.15 and r["dd"] < 35 and r["trades"] > 200]

    print(f"\n  DEPLOY CANDIDATES (PF>=1.15, DD<35%, Trades>200): {len(deploy_candidates)}")
    for r in deploy_candidates[:5]:
        print(f"    {r['label'][:60]}")
        print(f"      PF={r['pf']:.2f}, DD={r['dd']:.1f}%, Tr={r['trades']}, "
              f"P&L=${r['pnl']:+,.2f}, Score={r['score']:.4f}")

    # ------------------------------------------------------------------
    # Step 11: Write reports
    # ------------------------------------------------------------------
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "experiment": "mexc_risk_wrappers",
        "experiment_id": "mexc_risk_wrappers_006",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git_hash,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, >={MIN_BARS_TOP200} bars",
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
            "vol_mult": 3.5,
            "rsi_max": 35,
        },
        "baseline": {
            "trades": baseline["trades"],
            "pf": baseline["pf"],
            "pnl": baseline["pnl"],
            "dd": baseline["dd"],
            "wr": baseline["wr"],
            "ev_trade": baseline["ev_trade"],
            "trades_per_day": baseline["trades_per_day"],
            "n_capped": n_capped,
        },
        "wrapper_grids": {
            "dd_throttle": len(DD_THROTTLE_GRID),
            "vol_scale": len(VOL_SCALE_GRID),
            "adaptive_maxpos": len(ADAPTIVE_MAXPOS_GRID),
            "cooldown_ext": len(COOLDOWN_EXT_GRID),
            "combined": combined_count,
            "total": len(all_results),
        },
        "deploy_candidates": len(deploy_candidates),
        "top10": top10,
        "all_results": all_results,
    }

    json_path = REPORT_DIR / "mexc_risk_wrappers_006.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  JSON: {json_path}")

    # --- MD Report ---
    md = []
    md.append("# MEXC Risk Wrapper Sweep — Sprint4_041 DD Reduction")
    md.append("")
    md.append(f"**Date**: {report['timestamp'][:10]}")
    md.append(f"**Git**: `{git_hash}`")
    md.append(f"**Config**: Sprint4_041 (H4S4-G05) vol_mult=3.5, rsi_max=35")
    md.append(f"**Universe**: Top {TOP_N} by volume, >={MIN_BARS_TOP200} bars ({n_coins} coins)")
    md.append(f"**Full range**: ~{n_days:.0f} days, {max_bar} bars")
    md.append(f"**Fee**: MEXC 10bps")
    md.append(f"**Sizing**: Fixed $2,000/trade (no compounding)")
    md.append("")

    md.append("## Baseline")
    md.append("")
    md.append(f"| Metric | Value |")
    md.append(f"|--------|------:|")
    md.append(f"| Trades | {baseline['trades']} |")
    md.append(f"| PF | {baseline['pf']:.4f} |")
    md.append(f"| P&L | ${baseline['pnl']:+,.2f} |")
    md.append(f"| DD | {baseline['dd']:.1f}% |")
    md.append(f"| WR | {baseline['wr']:.1f}% |")
    md.append(f"| EV/trade | ${baseline['ev_trade']:.2f} |")
    md.append(f"| Trades/day | {baseline['trades_per_day']:.2f} |")
    md.append(f"| Capped returns | {n_capped} |")
    md.append("")

    md.append("## Methodology")
    md.append("")
    md.append("Post-hoc risk wrappers applied to fixed-notional ($2000/trade) trade list.")
    md.append("Entry and exit logic UNCHANGED. Only sizing or trade admission modified.")
    md.append("")
    md.append("### Wrapper Strategies")
    md.append("1. **DD Throttle** (15 combos): Scale position size when DD > threshold")
    md.append("2. **Vol Scaling** (9 combos): Size inversely proportional to ATR (capped 0.25x-2.0x)")
    md.append("3. **Adaptive MaxPos** (4 combos): Reduce max concurrent positions by DD level")
    md.append("4. **Cooldown Extension** (5 combos): Extend post-stop cooldown beyond default 8 bars")
    md.append("5. **Combined** (top-2 x top-2 cross-category): Size-based + skip-based")
    md.append("")
    md.append(f"**Total combos**: {len(all_results)}")
    md.append("")

    md.append("### Scoring Function")
    md.append("```")
    md.append("score = dd_improvement * 0.5 + pf_retention * 0.3 + trade_retention * 0.2")
    md.append("Hard gate: PF < 1.0 => score = 0")
    md.append("```")
    md.append("")

    # Top-10
    md.append("## Top-10 Leaderboard")
    md.append("")
    md.append("| # | Score | PF | DD% | Trades | P&L | WR% | DD Reduction | Category | Label |")
    md.append("|---|------:|---:|----:|-------:|----:|----:|------------:|----------|-------|")
    for i, r in enumerate(top10, 1):
        deploy = " **DEPLOY**" if r["pf"] >= 1.15 and r["dd"] < 35 and r["trades"] > 200 else ""
        md.append(f"| {i} | {r['score']:.4f} | {r['pf']:.2f} | {r['dd']:.1f}% "
                  f"| {r['trades']} | ${r['pnl']:+,.0f} | {r['wr']:.1f}% "
                  f"| {r['dd_reduction_pct']:+.1f}% | {r['category']} | {r['label'][:50]}{deploy} |")
    md.append("")

    # Per-category best
    md.append("## Per-Category Best")
    md.append("")
    md.append("| Category | Score | PF | DD% | Trades | P&L | Label |")
    md.append("|----------|------:|---:|----:|-------:|----:|-------|")
    for cat in ["dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext", "combined"]:
        cat_results = [r for r in all_results if r["category"] == cat]
        if cat_results:
            best = cat_results[0]
            md.append(f"| {cat} | {best['score']:.4f} | {best['pf']:.2f} | {best['dd']:.1f}% "
                      f"| {best['trades']} | ${best['pnl']:+,.0f} | {best['label'][:45]} |")
    md.append("")

    # Deploy candidates
    md.append("## Deploy Candidates (PF>=1.15, DD<35%, Trades>200)")
    md.append("")
    if deploy_candidates:
        md.append("| # | Category | PF | DD% | Trades | P&L | Score | Label |")
        md.append("|---|----------|---:|----:|-------:|----:|------:|-------|")
        for i, r in enumerate(deploy_candidates, 1):
            md.append(f"| {i} | {r['category']} | {r['pf']:.2f} | {r['dd']:.1f}% "
                      f"| {r['trades']} | ${r['pnl']:+,.0f} | {r['score']:.4f} "
                      f"| {r['label'][:50]} |")
    else:
        md.append("**No deploy candidates found.** No wrapper meets all three gates simultaneously.")
    md.append("")

    # All individual results by category
    md.append("## All Results by Category")
    md.append("")
    for cat in ["dd_throttle", "vol_scale", "adaptive_maxpos", "cooldown_ext", "combined"]:
        cat_results = [r for r in all_results if r["category"] == cat]
        if not cat_results:
            continue
        md.append(f"### {cat.replace('_', ' ').title()} ({len(cat_results)} combos)")
        md.append("")
        md.append("| # | Score | PF | DD% | Trades | P&L | DD red | Label |")
        md.append("|---|------:|---:|----:|-------:|----:|-------:|-------|")
        for i, r in enumerate(cat_results, 1):
            md.append(f"| {i} | {r['score']:.4f} | {r['pf']:.2f} | {r['dd']:.1f}% "
                      f"| {r['trades']} | ${r['pnl']:+,.0f} "
                      f"| {r['dd_reduction_pct']:+.1f}% | {r['label'][:45]} |")
        md.append("")

    # Recommendation
    md.append("## Recommendation")
    md.append("")
    if deploy_candidates:
        best_dc = deploy_candidates[0]
        md.append(f"**Recommended deploy candidate**: {best_dc['label']}")
        md.append(f"- PF: {best_dc['pf']:.2f} (baseline: {actual_baseline_pf:.2f})")
        md.append(f"- DD: {best_dc['dd']:.1f}% (baseline: {actual_baseline_dd:.1f}%)")
        md.append(f"- Trades: {best_dc['trades']} (baseline: {actual_baseline_trades})")
        md.append(f"- P&L: ${best_dc['pnl']:+,.2f} (baseline: ${baseline['pnl']:+,.2f})")
        md.append(f"- Score: {best_dc['score']:.4f}")
    else:
        md.append("No wrapper combination meets the deploy gate (PF>=1.15 AND DD<35% AND trades>200).")
        md.append("")
        md.append("Best options by different criteria:")
        # Best DD reduction with PF >= 1.15
        pf_ok = [r for r in all_results if r["pf"] >= 1.15]
        if pf_ok:
            best_dd = max(pf_ok, key=lambda x: x["dd_reduction_pct"])
            md.append(f"- **Best DD reduction (PF>=1.15)**: {best_dd['label'][:50]}")
            md.append(f"  DD: {best_dd['dd']:.1f}% ({best_dd['dd_reduction_pct']:+.1f}%), "
                      f"PF: {best_dd['pf']:.2f}, Trades: {best_dd['trades']}")
        # Best PF retention with DD < 35%
        dd_ok = [r for r in all_results if r["dd"] < 35]
        if dd_ok:
            best_pf = max(dd_ok, key=lambda x: x["pf"])
            md.append(f"- **Best PF (DD<35%)**: {best_pf['label'][:50]}")
            md.append(f"  PF: {best_pf['pf']:.2f}, DD: {best_pf['dd']:.1f}%, "
                      f"Trades: {best_pf['trades']}")
        # Overall best score
        if all_results:
            best_score = all_results[0]
            md.append(f"- **Best score overall**: {best_score['label'][:50]}")
            md.append(f"  Score: {best_score['score']:.4f}, PF: {best_score['pf']:.2f}, "
                      f"DD: {best_score['dd']:.1f}%, Trades: {best_score['trades']}")
    md.append("")

    md_path = REPORT_DIR / "mexc_risk_wrappers_006.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"  MD:   {md_path}")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    elapsed = time.time() - t_total
    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")
    print(f"  Total combos: {len(all_results)}")
    print(f"  Deploy candidates: {len(deploy_candidates)}")
    print(f"  Best score: {all_results[0]['score']:.4f} ({all_results[0]['label'][:50]})")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
