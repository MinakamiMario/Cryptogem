#!/usr/bin/env python3
"""
HF Exposure Cap Rules -- Portfolio risk management via correlation-based
entry blocking across multiple timeframes.

Rules:
  At max_pos=1:  LOG-ONLY mode -- no blocking, just report correlations
  At max_pos>1:  HARD-GATE mode -- block correlated entries (rho > 0.70)

Methodology:
  1. Load candle data for the specified timeframe (4h, 1h, 15m)
  2. Pre-filter to signal-generating coins (same as hf_correlation.py)
  3. Collect ALL entry signals (max_pos=99 unconstrained)
  4. Replay with different max_pos levels (1, 2, 3):
     - At max_pos=1: LOG-ONLY (record what correlations exist, no blocking)
     - At max_pos>1: HARD-GATE (block second entry if rolling corr > 0.70)
  5. Compare P&L, trades, and correlation stats across policies
  6. Output: reports/hf/exposure_caps_{tf}_001.json + .md

Usage:
    python strategies/hf/hf_exposure_caps.py
    python strategies/hf/hf_exposure_caps.py --timeframe 4h
    python strategies/hf/hf_exposure_caps.py --timeframe 1h
    python strategies/hf/hf_exposure_caps.py --timeframe 15m

Outputs:
    reports/hf/exposure_caps_{tf}_001.json  -- full structured results
    reports/hf/exposure_caps_{tf}_001.md    -- human-readable summary
"""

import sys
import json
import math
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass

# --- Path setup ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    check_entry_at_bar,
    normalize_cfg,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
    COOLDOWN_BARS,
    COOLDOWN_AFTER_STOP,
)

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

# Timeframe-specific settings
TF_CONFIG = {
    "4h": {
        "cache_file": DATA_DIR / "candle_cache_tradeable.json",
        "bars_per_day": 6,
    },
    "1h": {
        "cache_file": DATA_DIR / "candle_cache_1h.json",
        "bars_per_day": 24,
    },
    "15m": {
        "cache_file": DATA_DIR / "candle_cache_15m.json",
        "bars_per_day": 96,
    },
}

# GRID_BEST config for signal detection
GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 10,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 2.5,
})

# Correlation parameters
CORR_WINDOW = 20   # rolling window for correlation check (bars)
CORR_THRESHOLD = 0.70  # block entry if corr > threshold

# Max-pos levels to simulate
MAX_POS_LEVELS = [1, 2, 3]


# ============================================================
# DATA LOADING
# ============================================================
def load_data(tf: str):
    """Load candle data for the given timeframe."""
    cfg = TF_CONFIG[tf]
    path = cfg["cache_file"]
    if not path.exists():
        print(f"ERROR: No data file found: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ============================================================
# SIGNAL FILTERING
# ============================================================
def find_signal_coins(data, coins, cfg):
    """
    Pre-filter to coins that produce at least 1 entry signal.
    Returns list of coin names sorted by signal count desc.
    """
    indicators = precompute_all(data, coins)
    signal_coins = []

    for coin in coins:
        ind = indicators[coin]
        n = ind["n"]
        count = 0
        for bar in range(START_BAR, n):
            ok, _ = check_entry_at_bar(ind, bar, cfg)
            if ok:
                count += 1
        if count >= 1:
            signal_coins.append((coin, count))

    signal_coins.sort(key=lambda x: x[1], reverse=True)
    return signal_coins, indicators


# ============================================================
# LOG-RETURNS AND ROLLING CORRELATION
# ============================================================
def compute_log_returns(data, coins, n_bars):
    """
    Compute log-returns per coin: log(close[i] / close[i-1]).
    Returns {coin: [return_at_bar_i, ...]}.
    """
    returns = {}
    for coin in coins:
        candles = data.get(coin, [])
        r = [0.0] * n_bars
        for i in range(1, min(n_bars, len(candles))):
            c_prev = candles[i - 1].get("close", 0)
            c_curr = candles[i].get("close", 0)
            if c_prev > 0 and c_curr > 0:
                r[i] = math.log(c_curr / c_prev)
        returns[coin] = r
    return returns


def rolling_corr(returns_a, returns_b, bar, window=CORR_WINDOW):
    """
    Compute Pearson correlation between two return series over
    [bar-window+1 .. bar]. Returns 0.0 if insufficient data.
    """
    start = max(0, bar - window + 1)
    if bar - start < 5:  # need at least 5 observations
        return 0.0
    ra = returns_a[start:bar + 1]
    rb = returns_b[start:bar + 1]
    n = len(ra)
    if n < 5:
        return 0.0

    mean_a = sum(ra) / n
    mean_b = sum(rb) / n

    cov = 0.0
    var_a = 0.0
    var_b = 0.0
    for i in range(n):
        da = ra[i] - mean_a
        db = rb[i] - mean_b
        cov += da * db
        var_a += da * da
        var_b += db * db

    denom = math.sqrt(var_a * var_b)
    if denom < 1e-12:
        return 0.0
    return cov / denom


# ============================================================
# SIMULATED POSITION
# ============================================================
@dataclass
class SimPos:
    """Simulated position for the exposure cap allocator."""
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float


# ============================================================
# EXPOSURE CAP SIMULATOR
# ============================================================
def simulate_exposure_policy(indicators, coin_list, cfg, data, n_bars,
                             returns, max_pos, mode):
    """
    Simulate trading with exposure cap policy.

    mode="log_only":  Record correlations but never block entries (max_pos=1)
    mode="hard_gate": Block correlated entries when rho > CORR_THRESHOLD

    Returns dict with trades, pnl, corr_blocks, corr_logs, etc.
    """
    cfg = normalize_cfg(dict(cfg))
    exit_type = cfg["exit_type"]

    positions = {}  # pair -> SimPos
    trades = []
    equity = float(INITIAL_CAPITAL)
    peak_eq = equity
    max_dd = 0.0
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}
    corr_blocks = 0
    corr_logs = []  # for LOG-ONLY mode: record corr values

    max_bars_avail = max(
        indicators[p]["n"] for p in coin_list
    ) if coin_list else 0
    end_bar = min(max_bars_avail, n_bars)

    for bar in range(START_BAR, end_bar):
        if equity < 0:
            break

        # --- EXIT LOGIC (mirrors engine for tp_sl) ---
        sells = []
        for pair in list(positions.keys()):
            pos = positions[pair]
            ind = indicators[pair]
            if bar >= ind["n"] or ind["rsi"][bar] is None:
                continue

            entry_price = pos.entry_price
            bars_in = bar - pos.entry_bar
            close = ind["closes"][bar]
            low = ind["lows"][bar]
            high = ind["highs"][bar]
            exit_price = None
            reason = None

            if exit_type == "tp_sl":
                tp_pct = cfg.get("tp_pct", 7.0)
                sl_pct = cfg.get("sl_pct", 15.0)
                tm_bars = cfg.get("time_max_bars", 15)
                sl_p = entry_price * (1 - sl_pct / 100)
                tp_p = entry_price * (1 + tp_pct / 100)
                if low <= sl_p:
                    exit_price, reason = sl_p, "FIXED STOP"
                elif high >= tp_p:
                    exit_price, reason = tp_p, "PROFIT TARGET"
                elif bars_in >= tm_bars:
                    exit_price, reason = close, "TIME MAX"

            if exit_price is not None:
                sells.append((pair, exit_price, reason, pos))

        # Execute sells
        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += pos.size_usd + net
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = "STOP" in reason
            trades.append({
                "pair": pair,
                "entry": pos.entry_price, "exit": exit_price,
                "pnl": net, "pnl_pct": net / pos.size_usd * 100,
                "reason": reason, "bars": bar - pos.entry_bar,
                "entry_bar": pos.entry_bar, "exit_bar": bar,
                "size": pos.size_usd, "equity_after": equity,
            })
            del positions[pair]

        # --- COLLECT ENTRY SIGNALS ---
        buys = []
        for pair in coin_list:
            if pair in positions:
                continue
            ind = indicators[pair]
            if bar >= ind["n"]:
                continue
            cd = (COOLDOWN_AFTER_STOP
                  if last_exit_was_stop.get(pair, False)
                  else COOLDOWN_BARS)
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue
            ok, vol_ratio = check_entry_at_bar(ind, bar, cfg)
            if ok:
                buys.append((pair, vol_ratio))

        if not buys or len(positions) >= max_pos:
            # DD tracking
            total_val = _total_value(positions, indicators, bar, equity)
            if total_val > peak_eq:
                peak_eq = total_val
            dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
            if dd > max_dd:
                max_dd = dd
            continue

        # Sort by vol_ratio descending (same as engine priority)
        buys.sort(key=lambda x: x[1], reverse=True)

        # --- APPLY EXPOSURE CAP ---
        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested
        slots = max_pos - len(positions)

        if slots <= 0 or available <= 10:
            total_val = _total_value(positions, indicators, bar, equity)
            if total_val > peak_eq:
                peak_eq = total_val
            dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
            if dd > max_dd:
                max_dd = dd
            continue

        size_per_pos = available / slots
        filled = 0

        for pair, vol_ratio in buys:
            if filled >= slots:
                break
            if size_per_pos < 10:
                break

            # Correlation check against open positions
            if positions:
                pair_returns = returns.get(pair, [])
                max_corr_val = 0.0
                max_corr_pair = None

                for open_pair in positions:
                    open_returns = returns.get(open_pair, [])
                    corr = rolling_corr(pair_returns, open_returns, bar)
                    if corr > max_corr_val:
                        max_corr_val = corr
                        max_corr_pair = open_pair

                if max_corr_val > CORR_THRESHOLD:
                    if mode == "hard_gate":
                        # Block entry
                        corr_blocks += 1
                        continue
                    elif mode == "log_only":
                        # Log but allow entry
                        corr_logs.append({
                            "bar": bar,
                            "new_pair": pair,
                            "open_pair": max_corr_pair,
                            "corr": round(max_corr_val, 4),
                        })

            # ENTER position
            ind = indicators[pair]
            ep = ind["closes"][bar]

            equity -= size_per_pos
            positions[pair] = SimPos(
                pair=pair, entry_price=ep, entry_bar=bar,
                size_usd=size_per_pos,
            )
            filled += 1

        # DD tracking
        total_val = _total_value(positions, indicators, bar, equity)
        if total_val > peak_eq:
            peak_eq = total_val
        dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining positions at last bar
    final_bar = end_bar - 1
    for pair in list(positions.keys()):
        pos = positions[pair]
        ind = indicators[pair]
        if final_bar < ind["n"]:
            close_price = ind["closes"][final_bar]
        else:
            close_price = pos.entry_price
        gross = (close_price - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
        net = gross - fees
        equity += pos.size_usd + net
        trades.append({
            "pair": pair,
            "entry": pos.entry_price, "exit": close_price,
            "pnl": net, "pnl_pct": net / pos.size_usd * 100,
            "reason": "END_OF_DATA", "bars": final_bar - pos.entry_bar,
            "entry_bar": pos.entry_bar, "exit_bar": final_bar,
            "size": pos.size_usd, "equity_after": equity,
        })
        del positions[pair]

    # Compute metrics
    n_trades = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = total_win / total_loss if total_loss > 0 else float("inf")

    # Unique coins traded
    coins_traded = set(t["pair"] for t in trades)

    return {
        "max_pos": max_pos,
        "mode": mode,
        "trades": n_trades,
        "pnl": round(equity - INITIAL_CAPITAL, 2),
        "pf": _safe_pf(pf),
        "wr": round(wins / n_trades * 100, 1) if n_trades else 0.0,
        "dd": round(max_dd, 1),
        "final_equity": round(equity, 2),
        "corr_blocks": corr_blocks,
        "corr_log_count": len(corr_logs),
        "corr_logs_sample": corr_logs[:20],  # first 20 for JSON
        "unique_coins": len(coins_traded),
    }


def _total_value(positions, indicators, bar, cash_equity):
    """Compute total portfolio value (cash + unrealized)."""
    total = cash_equity
    for pair, pos in positions.items():
        ind = indicators[pair]
        if bar < ind["n"]:
            cur_price = ind["closes"][bar]
            unrealized = (cur_price - pos.entry_price) / pos.entry_price * pos.size_usd
            total += pos.size_usd + unrealized
        else:
            total += pos.size_usd
    return total


def _safe_pf(pf):
    if pf == float("inf"):
        return 99.0
    return round(min(pf, 99.0), 2)


# ============================================================
# COMPARISON ANALYSIS
# ============================================================
def compare_policies(results):
    """
    Compare max_pos policies and generate analysis.
    Returns dict with comparisons and verdicts.
    """
    baseline = None
    for r in results:
        if r["max_pos"] == 1:
            baseline = r
            break

    if baseline is None:
        return {"error": "No max_pos=1 baseline found"}

    comparisons = []
    for r in results:
        if r["max_pos"] == 1:
            continue

        pnl_delta = r["pnl"] - baseline["pnl"]
        trade_mult = r["trades"] / baseline["trades"] if baseline["trades"] else 0
        dd_delta = r["dd"] - baseline["dd"]

        # Determine verdict for this policy
        if r["pnl"] > baseline["pnl"] and r["dd"] <= baseline["dd"] * 1.5:
            verdict = "BENEFICIAL"
            detail = (
                f"max_pos={r['max_pos']} ({r['mode']}): "
                f"P&L improved by ${pnl_delta:+,.0f} with acceptable DD increase."
            )
        elif r["pnl"] > baseline["pnl"]:
            verdict = "MIXED"
            detail = (
                f"max_pos={r['max_pos']} ({r['mode']}): "
                f"P&L improved by ${pnl_delta:+,.0f} but DD increased "
                f"from {baseline['dd']}% to {r['dd']}%."
            )
        elif r["pnl"] > 0:
            verdict = "NEUTRAL"
            detail = (
                f"max_pos={r['max_pos']} ({r['mode']}): "
                f"Still profitable (${r['pnl']:+,.0f}) but worse than baseline."
            )
        else:
            verdict = "HARMFUL"
            detail = (
                f"max_pos={r['max_pos']} ({r['mode']}): "
                f"P&L went negative (${r['pnl']:+,.0f}). Do not use."
            )

        comparisons.append({
            "max_pos": r["max_pos"],
            "mode": r["mode"],
            "pnl_delta": round(pnl_delta, 2),
            "trade_multiplier": round(trade_mult, 2),
            "dd_delta": round(dd_delta, 1),
            "corr_blocks": r["corr_blocks"],
            "verdict": verdict,
            "detail": detail,
        })

    return {
        "baseline": {
            "max_pos": 1,
            "trades": baseline["trades"],
            "pnl": baseline["pnl"],
            "dd": baseline["dd"],
        },
        "comparisons": comparisons,
    }


# ============================================================
# MARKDOWN REPORT
# ============================================================
def generate_markdown(tf, meta, results, analysis):
    """Generate human-readable exposure cap report."""
    bars_per_day = TF_CONFIG[tf]["bars_per_day"]

    lines = [
        f"# HF Exposure Cap Rules -- {tf.upper()} Timeframe",
        "",
        "> **Question**: How do correlation-based exposure caps affect",
        "> portfolio risk at different max_pos levels?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Timeframe**: {tf}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Signal coins**: {meta['n_signal_coins']} "
        f"(from {meta['n_coins_total']} total)",
        f"**Correlation window**: {CORR_WINDOW} bars",
        f"**Correlation threshold**: {CORR_THRESHOLD}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Exposure cap rules
    lines.extend([
        "## 1. Exposure Cap Rules",
        "",
        "| max_pos | Mode | Description |",
        "|---------|------|-------------|",
        "| 1 | LOG-ONLY | No blocking; record correlation "
        "values for monitoring |",
        "| 2 | HARD-GATE | Block entry if rolling corr > 0.70 "
        "with any open position |",
        "| 3 | HARD-GATE | Same blocking rule, 3 concurrent "
        "positions allowed |",
        "",
        "**Rationale**: At max_pos=1 there is only ever one open position,",
        "so correlation blocking is unnecessary. At max_pos>1, correlated",
        "positions amplify drawdown risk and reduce diversification benefit.",
        "",
    ])

    # Section 2: Results table
    lines.extend([
        "## 2. Simulation Results",
        "",
        "| max_pos | Mode | Trades | P&L | PF | WR% | DD% | "
        "Corr Blocks | Corr Logs | Coins |",
        "|---------|------|--------|-----|----|-----|-----|"
        "------------|-----------|-------|",
    ])
    for r in results:
        lines.append(
            f"| {r['max_pos']} | {r['mode']} | {r['trades']} "
            f"| ${r['pnl']:+,.0f} | {r['pf']} | {r['wr']}% "
            f"| {r['dd']}% | {r['corr_blocks']} "
            f"| {r['corr_log_count']} | {r['unique_coins']} |"
        )
    lines.append("")

    # Section 3: Impact analysis
    lines.extend([
        "## 3. Impact Analysis",
        "",
    ])

    if "error" not in analysis:
        baseline = analysis["baseline"]
        lines.extend([
            f"**Baseline (max_pos=1)**: {baseline['trades']} trades, "
            f"${baseline['pnl']:+,.0f}, DD={baseline['dd']}%",
            "",
            "| max_pos | Mode | P&L Delta | Trade Mult | DD Delta "
            "| Corr Blocks | Verdict |",
            "|---------|------|-----------|------------|----------"
            "|-------------|---------|",
        ])
        for c in analysis["comparisons"]:
            lines.append(
                f"| {c['max_pos']} | {c['mode']} "
                f"| ${c['pnl_delta']:+,.0f} | {c['trade_multiplier']}x "
                f"| {c['dd_delta']:+.1f}% | {c['corr_blocks']} "
                f"| **{c['verdict']}** |"
            )
        lines.append("")

        # Detailed verdicts
        for c in analysis["comparisons"]:
            lines.append(f"- {c['detail']}")
        lines.append("")
    else:
        lines.append(f"Analysis error: {analysis['error']}")
        lines.append("")

    # Section 4: Correlation log summary (from max_pos=1 LOG-ONLY)
    log_only_result = None
    for r in results:
        if r["mode"] == "log_only":
            log_only_result = r
            break

    if log_only_result and log_only_result["corr_log_count"] > 0:
        lines.extend([
            "## 4. Correlation Log (LOG-ONLY mode, max_pos=1)",
            "",
            f"**Total correlated entries logged**: "
            f"{log_only_result['corr_log_count']}",
            "",
            "These entries would have been blocked under HARD-GATE mode.",
            "",
        ])

        sample = log_only_result.get("corr_logs_sample", [])
        if sample:
            lines.extend([
                "**Sample of correlated entries**:",
                "",
                "| Bar | New Pair | Open Pair | Corr |",
                "|-----|----------|-----------|------|",
            ])
            for log in sample[:15]:
                lines.append(
                    f"| {log['bar']} | {log['new_pair']} "
                    f"| {log['open_pair']} | {log['corr']} |"
                )
            if len(sample) > 15:
                lines.append(
                    f"| ... | *{log_only_result['corr_log_count'] - 15} "
                    f"more entries* | | |"
                )
            lines.append("")
    else:
        lines.extend([
            "## 4. Correlation Log (LOG-ONLY mode, max_pos=1)",
            "",
            "No correlated entries detected during LOG-ONLY simulation.",
            "This is expected when max_pos=1 (only one position at a time).",
            "",
        ])

    # Section 5: Recommendations
    lines.extend([
        "## 5. Recommendations",
        "",
    ])

    # Determine overall recommendation
    has_beneficial = any(
        c["verdict"] == "BENEFICIAL"
        for c in analysis.get("comparisons", [])
    )
    has_harmful = any(
        c["verdict"] == "HARMFUL"
        for c in analysis.get("comparisons", [])
    )

    if has_beneficial and not has_harmful:
        lines.extend([
            "- **Increase max_pos**: At least one multi-position policy improves "
            "P&L without excessive DD increase.",
            "- **Use HARD-GATE**: Correlation blocking should be enabled at max_pos>1.",
            f"- **Threshold**: rho > {CORR_THRESHOLD} is effective for blocking "
            "redundant entries.",
        ])
    elif has_harmful:
        lines.extend([
            "- **Keep max_pos=1**: Some multi-position policies caused negative P&L.",
            "- **Monitor correlations**: Use LOG-ONLY mode to track correlation "
            "patterns over time.",
            "- **Review before increasing**: More data or different thresholds "
            "may be needed.",
        ])
    else:
        lines.extend([
            "- **max_pos=1 remains optimal**: Multi-position policies did not "
            "clearly improve returns.",
            "- **LOG-ONLY monitoring**: Continue tracking correlations for future "
            "reference.",
            "- **Re-evaluate periodically**: Market regime changes may affect "
            "correlation structure.",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by hf_exposure_caps.py -- {tf.upper()} timeframe*",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="HF Exposure Cap Rules -- correlation-based entry blocking"
    )
    parser.add_argument(
        "--timeframe", "-tf",
        choices=["4h", "1h", "15m"],
        default="4h",
        help="Timeframe to analyze (default: 4h)",
    )
    args = parser.parse_args()

    tf = args.timeframe
    tf_cfg = TF_CONFIG[tf]
    bars_per_day = tf_cfg["bars_per_day"]

    print("=" * 70)
    print(f"  HF Exposure Cap Rules -- {tf.upper()} Timeframe")
    print("  Question: How do correlation caps affect portfolio risk?")
    print("=" * 70)

    # 1. Load data
    data, all_coins, data_path = load_data(tf)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from "
          f"{Path(data_path).name}")

    t_start = time.time()

    # 2. Find signal-generating coins
    print("\n  Finding signal-generating coins (GRID_BEST config)...")
    t0 = time.time()
    signal_coins, indicators = find_signal_coins(data, all_coins, GRID_BEST)
    t_signal = time.time() - t0
    sig_coin_names = [c for c, _ in signal_coins]
    print(f"  Found {len(signal_coins)} signal-generating coins ({t_signal:.1f}s)")

    if len(sig_coin_names) < 1:
        print("  ERROR: No signal-generating coins found.")
        sys.exit(1)

    # 3. Precompute indicators for signal coins only
    print("\n  Precomputing indicators for signal coins...")
    t0 = time.time()
    sig_indicators = precompute_all(data, sig_coin_names)
    t_ind = time.time() - t0
    print(f"  Indicators computed ({t_ind:.1f}s)")

    # 4. Compute log-returns for correlation checks
    print("  Computing log-returns...")
    t0 = time.time()
    returns = compute_log_returns(data, sig_coin_names, n_bars)
    t_ret = time.time() - t0
    print(f"  Log-returns computed ({t_ret:.1f}s)")

    # 5. Simulate each max_pos policy
    results = []
    policies = [
        (1, "log_only"),
        (2, "hard_gate"),
        (3, "hard_gate"),
    ]

    for max_pos, mode in policies:
        print(f"\n  Simulating max_pos={max_pos}, mode={mode}...")
        t0 = time.time()
        result = simulate_exposure_policy(
            sig_indicators, sig_coin_names, GRID_BEST, data, n_bars,
            returns, max_pos, mode,
        )
        elapsed = time.time() - t0
        results.append(result)

        print(f"    Trades={result['trades']}, P&L=${result['pnl']:+,.0f}, "
              f"PF={result['pf']}, DD={result['dd']}%")
        if mode == "hard_gate":
            print(f"    Corr blocks: {result['corr_blocks']}")
        elif mode == "log_only":
            print(f"    Corr logs: {result['corr_log_count']}")
        print(f"    ({elapsed:.1f}s)")

    # 6. Compare policies
    print("\n  Comparing policies...")
    analysis = compare_policies(results)

    total_time = time.time() - t_start

    # 7. Build output
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timeframe": tf,
        "data_file": data_path,
        "n_coins_total": len(all_coins),
        "n_signal_coins": len(signal_coins),
        "n_bars": n_bars,
        "bars_per_day": bars_per_day,
        "corr_window": CORR_WINDOW,
        "corr_threshold": CORR_THRESHOLD,
        "config_used": "GRID_BEST",
        "max_pos_levels": MAX_POS_LEVELS,
        "total_time_s": round(total_time, 2),
    }

    json_output = {
        "meta": meta,
        "signal_coins": [
            {"coin": c, "signals": n} for c, n in signal_coins
        ],
        "results": results,
        "analysis": analysis,
    }

    # Write JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"exposure_caps_{tf}_001.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown
    md_path = REPORTS_DIR / f"exposure_caps_{tf}_001.md"
    md = generate_markdown(tf, meta, results, analysis)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print(f"\n{'='*70}")
    print(f"  EXPOSURE CAP ANALYSIS COMPLETE ({tf.upper()})")
    print(f"  Signal coins: {len(signal_coins)}")
    print(f"  Policies tested: {len(results)}")
    for r in results:
        status = "LOG" if r["mode"] == "log_only" else "GATE"
        blocks = r["corr_blocks"] if r["mode"] == "hard_gate" else r["corr_log_count"]
        block_label = "blocks" if r["mode"] == "hard_gate" else "logs"
        print(f"    mp={r['max_pos']} ({status}): {r['trades']} trades, "
              f"${r['pnl']:+,.0f}, DD={r['dd']}%, "
              f"{blocks} corr {block_label}")
    print(f"  Runtime: {total_time:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
