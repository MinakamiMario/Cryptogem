#!/usr/bin/env python3
"""
HF Allocator Experiment — 4H variant research.

Stap 1 throughput improvement: simulate max_pos=1/2/3 with tier quotas
and correlation guardrails under friction v2 per-tier fees.

Approach:
  The backtest engine supports max_pos natively, but it has no concept of
  tier quotas or correlation limits. This script uses two methods:

  Method A — "Native max_pos": Run the engine with max_pos=1/2/3 on the
  full T1+T2 universe with per-tier fees (split by tier, aggregate).
  This shows raw throughput improvement from more slots.

  Method B — "Quota-aware replay": Collect ALL entry signals from the
  engine (max_pos=99, so nothing is crowded out), then replay with a
  custom allocator that enforces:
    - max_pos cap (1/2/3)
    - tier quota (e.g., "at least 1 slot reserved for T1")
    - correlation guard (block entry if rolling corr with any open
      position > threshold)
    - per-tier fee deduction

  Output metrics per policy:
    - Total trades, trades/week
    - P&L, PF, DD
    - Tier mix (% T1 vs T2 trades)
    - Zero-trade-day %
    - Correlation stats

Usage:
    python strategies/hf/hf_allocator.py
    python strategies/hf/hf_allocator.py --universe tradeable

Outputs:
    reports/hf/allocator_001.json  — full structured results
    reports/hf/allocator_001.md    — human-readable summary
"""

import sys
import json
import time
import argparse
import math
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from dataclasses import dataclass, field

# --- Path setup ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    run_backtest,
    normalize_cfg,
    check_entry_at_bar,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
    COOLDOWN_BARS,
    COOLDOWN_AFTER_STOP,
)

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"
TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# Per-tier fees (from UNIVERSE_POLICY.md / hf_friction_v2.py)
TIER_FEES = {
    "1": round(KRAKEN_FEE + 0.0005, 4),   # 31 bps
    "2": round(KRAKEN_FEE + 0.0030, 4),   # 56 bps
}
TIER_LABELS = {"1": "Tier 1 (Liquid)", "2": "Tier 2 (Mid)"}

CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8,
    "time_max_bars": 15, "tp_pct": 12, "vol_confirm": True, "vol_spike_mult": 3.0,
})
GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10,
    "time_max_bars": 15, "tp_pct": 12, "vol_confirm": True, "vol_spike_mult": 2.5,
})

CONFIGS = {"GRID_BEST": GRID_BEST, "Champion_H2": CHAMPION_H2}

# Allocator policies to test
MAX_POS_LEVELS = [1, 2, 3]

# Correlation guardrail threshold (rolling 20-bar return correlation)
CORR_WINDOW = 20
CORR_THRESHOLD = 0.70  # block entry if corr > 0.70 with any open position

# Tier quota policies (for Method B)
# Format: {name: {max_pos, t1_min_slots, t2_max_slots, corr_guard}}
QUOTA_POLICIES = {
    "baseline_mp1": {"max_pos": 1, "t1_min": 0, "t2_max": 1, "corr_guard": False},
    "mp2_no_quota": {"max_pos": 2, "t1_min": 0, "t2_max": 2, "corr_guard": False},
    "mp2_t1_reserve": {"max_pos": 2, "t1_min": 1, "t2_max": 1, "corr_guard": False},
    "mp2_corr_guard": {"max_pos": 2, "t1_min": 0, "t2_max": 2, "corr_guard": True},
    "mp2_full": {"max_pos": 2, "t1_min": 1, "t2_max": 1, "corr_guard": True},
    "mp3_no_quota": {"max_pos": 3, "t1_min": 0, "t2_max": 3, "corr_guard": False},
    "mp3_t1_reserve": {"max_pos": 3, "t1_min": 1, "t2_max": 2, "corr_guard": False},
    "mp3_corr_guard": {"max_pos": 3, "t1_min": 0, "t2_max": 3, "corr_guard": True},
    "mp3_full": {"max_pos": 3, "t1_min": 1, "t2_max": 2, "corr_guard": True},
}


# ============================================================
# DATA LOADING
# ============================================================
def load_data(universe: str):
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def load_tiers():
    """Load tier assignments → {coin: tier_id_str}."""
    if not TIERING_PATH.exists():
        print(f"ERROR: {TIERING_PATH} not found. Run hf_universe_tiering.py first.")
        sys.exit(1)
    with open(TIERING_PATH) as f:
        d = json.load(f)
    tier_map = {}
    for tier_id, tier_info in d["tier_breakdown"].items():
        coins_list = tier_info.get("coins", [])
        for c in coins_list:
            if isinstance(c, str):
                tier_map[c] = tier_id
            elif isinstance(c, dict):
                tier_map[c.get("coin", c.get("symbol", ""))] = tier_id
    return tier_map


def build_bar_date_map(data, coins, n_bars):
    """Build bar_idx → {date, week, ts}."""
    bar_map = {}
    ref_coin = coins[0]
    candles = data[ref_coin]
    for i in range(min(n_bars, len(candles))):
        ts = candles[i].get("time", 0)
        if ts:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            bar_map[i] = {
                "date": dt.strftime("%Y-%m-%d"),
                "week": dt.strftime("%Y-W%W"),
                "ts": ts,
            }
    return bar_map


# ============================================================
# METHOD A: Native max_pos via engine
# ============================================================
def run_native_max_pos(data, tier_map, indicators_by_tier, tiers_coins,
                       cfg_base, max_pos_val):
    """
    Run per-tier backtests with cfg.max_pos = max_pos_val, then aggregate.
    Returns (composite_result, per_tier_results).
    """
    cfg = dict(cfg_base)
    cfg["max_pos"] = max_pos_val
    cfg = normalize_cfg(cfg)

    all_trades = []
    per_tier = {}

    for tier_id in ("1", "2"):
        tier_coins = tiers_coins.get(tier_id, [])
        fee = TIER_FEES[tier_id]
        if not tier_coins:
            per_tier[tier_id] = {"trades": 0, "pnl": 0.0, "pf": 0.0,
                                 "wr": 0.0, "dd": 0.0}
            continue

        indicators = indicators_by_tier[tier_id]
        result = run_backtest(indicators, tier_coins, cfg, fee_override=fee)
        trade_list = result.get("trade_list", [])

        for t in trade_list:
            t["_tier"] = tier_id

        all_trades.extend(trade_list)
        per_tier[tier_id] = {
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": _safe_pf(result["pf"]),
            "wr": round(result["wr"], 1),
            "dd": round(result["dd"], 1),
            "n_coins": len(tier_coins),
        }

    composite = _replay_equity(all_trades, INITIAL_CAPITAL)
    return composite, per_tier


# ============================================================
# METHOD B: Quota-aware replay allocator
# ============================================================
@dataclass
class SimPos:
    """Simulated position for the custom allocator."""
    pair: str
    tier: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float
    highest_price: float = 0.0


def compute_rolling_returns(data, coins, n_bars, window=CORR_WINDOW):
    """
    Precompute rolling log-returns per coin for correlation checks.
    Returns {coin: [return_at_bar_i, ...]} where return = ln(close_i / close_{i-1}).
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


def run_quota_allocator(indicators, coin_list, cfg_base, tier_map, data,
                        n_bars, returns, policy):
    """
    Custom allocator that replays the bar loop with tier quotas and
    correlation guardrails.

    Steps per bar:
      1. Check exits for open positions (same logic as engine)
      2. Collect all entry signals (across all coins)
      3. Apply allocation policy:
         a. Tier quota filter
         b. Correlation guard filter
         c. Fill up to max_pos slots, prioritizing by vol_ratio
      4. Update equity and track metrics
    """
    cfg = normalize_cfg(dict(cfg_base))
    # Override max_pos to not constrain signal collection
    exit_type = cfg["exit_type"]
    max_pos = policy["max_pos"]
    t1_min = policy["t1_min"]
    t2_max = policy["t2_max"]
    use_corr = policy["corr_guard"]

    positions = {}  # pair -> SimPos
    trades = []
    equity = float(INITIAL_CAPITAL)
    peak_eq = equity
    max_dd = 0.0
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}
    corr_blocks = 0
    quota_blocks = 0

    max_bars_avail = max(indicators[p]["n"] for p in coin_list) if coin_list else 0
    end_bar = min(max_bars_avail, n_bars)

    for bar in range(START_BAR, end_bar):
        if equity < 0:
            break

        # --- 1. EXIT LOGIC (mirrors engine exactly for tp_sl) ---
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
            fee = TIER_FEES.get(pos.tier, TIER_FEES["2"])
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
            net = gross - fees
            equity += pos.size_usd + net
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = "STOP" in reason
            trades.append({
                "pair": pair, "tier": pos.tier,
                "entry": pos.entry_price, "exit": exit_price,
                "pnl": net, "pnl_pct": net / pos.size_usd * 100,
                "reason": reason, "bars": bar - pos.entry_bar,
                "entry_bar": pos.entry_bar, "exit_bar": bar,
                "size": pos.size_usd, "equity_after": equity,
                "fee_applied": fee,
            })
            del positions[pair]

        # --- 2. COLLECT ALL ENTRY SIGNALS ---
        buys = []
        for pair in coin_list:
            if pair in positions:
                continue
            ind = indicators[pair]
            if bar >= ind["n"]:
                continue
            cd = COOLDOWN_AFTER_STOP if last_exit_was_stop.get(pair, False) else COOLDOWN_BARS
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue
            ok, vol_ratio = check_entry_at_bar(ind, bar, cfg)
            if ok:
                tier = tier_map.get(pair, "2")
                buys.append((pair, vol_ratio, tier))

        if not buys or len(positions) >= max_pos:
            # Update DD tracking
            _update_dd(positions, indicators, bar, equity, peak_eq)
            total_val = _total_value(positions, indicators, bar, equity)
            if total_val > peak_eq:
                peak_eq = total_val
            dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
            if dd > max_dd:
                max_dd = dd
            continue

        # Sort by vol_ratio descending (same as engine)
        buys.sort(key=lambda x: x[1], reverse=True)

        # --- 3. APPLY ALLOCATION POLICY ---
        # Count current positions by tier
        open_t1 = sum(1 for p in positions.values() if p.tier == "1")
        open_t2 = sum(1 for p in positions.values() if p.tier == "2")

        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested
        slots = max_pos - len(positions)

        if slots <= 0 or available <= 10:
            _update_dd_inline(positions, indicators, bar, equity, peak_eq, max_dd)
            total_val = _total_value(positions, indicators, bar, equity)
            if total_val > peak_eq:
                peak_eq = total_val
            dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
            if dd > max_dd:
                max_dd = dd
            continue

        size_per_pos = available / slots
        filled = 0

        for pair, vol_ratio, tier in buys:
            if filled >= slots:
                break
            if size_per_pos < 10:
                break

            # Tier quota check
            if tier == "2" and open_t2 >= t2_max:
                quota_blocks += 1
                continue
            # T1 reserve: if we have slots and no T1 open, save a slot for T1
            if tier == "2" and t1_min > 0 and open_t1 < t1_min:
                remaining_slots = slots - filled
                if remaining_slots <= t1_min - open_t1:
                    # Must save remaining slots for T1
                    quota_blocks += 1
                    continue

            # Correlation guard
            if use_corr and positions:
                blocked = False
                pair_returns = returns.get(pair, [])
                for open_pair, open_pos in positions.items():
                    open_returns = returns.get(open_pair, [])
                    corr = rolling_corr(pair_returns, open_returns, bar)
                    if corr > CORR_THRESHOLD:
                        blocked = True
                        corr_blocks += 1
                        break
                if blocked:
                    continue

            # ENTER position
            ind = indicators[pair]
            ep = ind["closes"][bar]
            sl_pct = cfg.get("sl_pct", cfg.get("max_stop_pct", 15.0))
            stop = ep * (1 - sl_pct / 100)

            equity -= size_per_pos
            positions[pair] = SimPos(
                pair=pair, tier=tier, entry_price=ep, entry_bar=bar,
                size_usd=size_per_pos, stop_price=stop, highest_price=ep,
            )
            if tier == "1":
                open_t1 += 1
            else:
                open_t2 += 1
            filled += 1

        # --- 4. DD TRACKING ---
        total_val = _total_value(positions, indicators, bar, equity)
        if total_val > peak_eq:
            peak_eq = total_val
        dd = (peak_eq - total_val) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close any remaining positions at last bar
    final_bar = end_bar - 1
    for pair in list(positions.keys()):
        pos = positions[pair]
        ind = indicators[pair]
        if final_bar < ind["n"]:
            close_price = ind["closes"][final_bar]
        else:
            close_price = pos.entry_price  # fallback
        fee = TIER_FEES.get(pos.tier, TIER_FEES["2"])
        gross = (close_price - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
        net = gross - fees
        equity += pos.size_usd + net
        trades.append({
            "pair": pair, "tier": pos.tier,
            "entry": pos.entry_price, "exit": close_price,
            "pnl": net, "pnl_pct": net / pos.size_usd * 100,
            "reason": "END_OF_DATA", "bars": final_bar - pos.entry_bar,
            "entry_bar": pos.entry_bar, "exit_bar": final_bar,
            "size": pos.size_usd, "equity_after": equity,
            "fee_applied": fee,
        })
        del positions[pair]

    # Compute metrics
    n_trades = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = total_win / total_loss if total_loss > 0 else float("inf")

    return {
        "trades": n_trades,
        "pnl": round(equity - INITIAL_CAPITAL, 2),
        "pf": _safe_pf(pf),
        "wr": round(wins / n_trades * 100, 1) if n_trades else 0.0,
        "dd": round(max_dd, 1),
        "final_equity": round(equity, 2),
        "corr_blocks": corr_blocks,
        "quota_blocks": quota_blocks,
        "trade_list": trades,
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


def _update_dd(positions, indicators, bar, equity, peak_eq):
    """Placeholder for inline DD — handled in main loop."""
    pass


def _update_dd_inline(positions, indicators, bar, equity, peak_eq, max_dd):
    """Placeholder — DD tracked inline."""
    pass


def _safe_pf(pf):
    if pf == float("inf"):
        return 99.0
    return round(min(pf, 99.0), 2)


def _replay_equity(trade_list, initial_capital):
    """Replay equity curve from merged trades."""
    if not trade_list:
        return {"pnl": 0.0, "pf": 0.0, "dd": 0.0, "trades": 0,
                "wr": 0.0, "final_equity": initial_capital}

    sorted_trades = sorted(trade_list, key=lambda t: (t["entry_bar"], t.get("exit_bar", 0)))
    equity = float(initial_capital)
    peak_eq = equity
    max_dd = 0.0
    total_win = 0.0
    total_loss = 0.0
    n_wins = 0

    for t in sorted_trades:
        pnl = t["pnl"]
        equity += pnl
        if pnl > 0:
            total_win += pnl
            n_wins += 1
        else:
            total_loss += pnl
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    n_trades = len(sorted_trades)
    wr = n_wins / n_trades * 100 if n_trades else 0.0
    abs_loss = abs(total_loss)
    pf = total_win / abs_loss if abs_loss > 0 else float("inf")

    return {
        "pnl": round(equity - initial_capital, 2),
        "pf": _safe_pf(pf),
        "dd": round(max_dd, 1),
        "trades": n_trades,
        "wr": round(wr, 1),
        "final_equity": round(equity, 2),
    }


# ============================================================
# TRADE ANALYSIS HELPERS
# ============================================================
def analyze_trade_list(trade_list, bar_date_map, n_bars):
    """Compute throughput metrics from a trade list."""
    if not trade_list:
        return {
            "total_trades": 0, "trades_per_week": 0.0,
            "pct_zero_days": 100.0, "pct_zero_weeks": 100.0,
            "tier_mix": {}, "unique_coins": 0,
        }

    # Tier mix
    tier_counts = defaultdict(int)
    tier_pnl = defaultdict(float)
    coins_seen = set()
    for t in trade_list:
        tier = t.get("tier", t.get("_tier", "?"))
        tier_counts[tier] += 1
        tier_pnl[tier] += t["pnl"]
        coins_seen.add(t["pair"])

    total = len(trade_list)
    tier_mix = {}
    for tier in sorted(tier_counts.keys()):
        tier_mix[tier] = {
            "trades": tier_counts[tier],
            "pct": round(tier_counts[tier] / total * 100, 1),
            "pnl": round(tier_pnl[tier], 2),
        }

    # Per-day / per-week
    day_trades = defaultdict(int)
    week_trades = defaultdict(int)
    for t in trade_list:
        bar_info = bar_date_map.get(t["entry_bar"])
        if bar_info:
            day_trades[bar_info["date"]] += 1
            week_trades[bar_info["week"]] += 1

    all_dates = sorted(set(
        bar_date_map[b]["date"] for b in bar_date_map if START_BAR <= b < n_bars
    ))
    all_weeks = sorted(set(
        bar_date_map[b]["week"] for b in bar_date_map if START_BAR <= b < n_bars
    ))

    total_days = len(all_dates)
    zero_days = sum(1 for d in all_dates if day_trades.get(d, 0) == 0)
    total_weeks = len(all_weeks)
    zero_weeks = sum(1 for w in all_weeks if week_trades.get(w, 0) == 0)
    mean_tpw = round(total / total_weeks, 2) if total_weeks else 0
    tpw_vals = [week_trades.get(w, 0) for w in all_weeks]
    median_tpw = sorted(tpw_vals)[len(tpw_vals) // 2] if tpw_vals else 0

    return {
        "total_trades": total,
        "trades_per_week_mean": mean_tpw,
        "trades_per_week_median": median_tpw,
        "pct_zero_days": round(zero_days / total_days * 100, 1) if total_days else 100,
        "pct_zero_weeks": round(zero_weeks / total_weeks * 100, 1) if total_weeks else 100,
        "tier_mix": tier_mix,
        "unique_coins": len(coins_seen),
    }


# ============================================================
# MARKDOWN REPORT
# ============================================================
def generate_markdown(results, meta):
    lines = [
        "# HF Allocator Experiment — 4H Variant Research",
        "",
        "> **Question**: Can max_pos>1 + tier quotas + correlation guardrails",
        "> increase throughput without destroying risk-adjusted returns?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']} (T1+T2 only, {meta['n_coins_live']} coins)",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Bars**: {meta['n_bars']} (4H, ~{meta['n_bars'] * 4 // 24} days)",
        f"**Correlation window**: {CORR_WINDOW} bars, threshold={CORR_THRESHOLD}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    for cfg_name, cfg_results in results.items():
        lines.extend([
            "---",
            "",
            f"## {cfg_name}",
            "",
        ])

        # Method A table
        lines.extend([
            "### Method A: Native max_pos (per-tier fees, no quotas/corr)",
            "",
            "| max_pos | Trades | P&L | PF | WR% | DD% | Trades/wk | 0-day% |",
            "|---------|--------|-----|----|-----|-----|-----------|--------|",
        ])
        for mp_result in cfg_results.get("method_a", []):
            mp = mp_result["max_pos"]
            c = mp_result["composite"]
            a = mp_result["analysis"]
            lines.append(
                f"| {mp} | {c['trades']} | ${c['pnl']:+,.0f} | {c['pf']} "
                f"| {c['wr']}% | {c['dd']}% | {a['trades_per_week_mean']} "
                f"| {a['pct_zero_days']}% |"
            )
        lines.append("")

        # Method A tier breakdown
        lines.extend([
            "**Tier breakdown (Method A)**:",
            "",
            "| max_pos | T1 trades | T1 P&L | T2 trades | T2 P&L |",
            "|---------|-----------|--------|-----------|--------|",
        ])
        for mp_result in cfg_results.get("method_a", []):
            mp = mp_result["max_pos"]
            pt = mp_result["per_tier"]
            t1 = pt.get("1", {"trades": 0, "pnl": 0.0})
            t2 = pt.get("2", {"trades": 0, "pnl": 0.0})
            lines.append(
                f"| {mp} | {t1['trades']} | ${t1['pnl']:+,.0f} "
                f"| {t2['trades']} | ${t2['pnl']:+,.0f} |"
            )
        lines.append("")

        # Method B table
        lines.extend([
            "### Method B: Quota-Aware Allocator (per-tier fees + quotas + corr guard)",
            "",
            "| Policy | max_pos | T1 min | T2 max | Corr | Trades | P&L | PF | DD% | Tr/wk | 0-day% | CorrBlk | QuotaBlk |",
            "|--------|---------|--------|--------|------|--------|-----|----|-----|-------|--------|---------|----------|",
        ])
        for pol_result in cfg_results.get("method_b", []):
            pol = pol_result["policy"]
            r = pol_result["result"]
            a = pol_result["analysis"]
            p = QUOTA_POLICIES[pol]
            lines.append(
                f"| {pol} | {p['max_pos']} | {p['t1_min']} | {p['t2_max']} "
                f"| {'Y' if p['corr_guard'] else 'N'} "
                f"| {r['trades']} | ${r['pnl']:+,.0f} | {r['pf']} "
                f"| {r['dd']}% | {a['trades_per_week_mean']} "
                f"| {a['pct_zero_days']}% | {r['corr_blocks']} | {r['quota_blocks']} |"
            )
        lines.append("")

        # Method B tier mix
        lines.extend([
            "**Tier mix (Method B)**:",
            "",
            "| Policy | T1 trades (%) | T1 P&L | T2 trades (%) | T2 P&L |",
            "|--------|---------------|--------|---------------|--------|",
        ])
        for pol_result in cfg_results.get("method_b", []):
            pol = pol_result["policy"]
            a = pol_result["analysis"]
            t1 = a["tier_mix"].get("1", {"trades": 0, "pct": 0, "pnl": 0})
            t2 = a["tier_mix"].get("2", {"trades": 0, "pct": 0, "pnl": 0})
            lines.append(
                f"| {pol} | {t1['trades']} ({t1['pct']}%) | ${t1['pnl']:+,.0f} "
                f"| {t2['trades']} ({t2['pct']}%) | ${t2['pnl']:+,.0f} |"
            )
        lines.append("")

    # Summary / key findings
    lines.extend([
        "---",
        "",
        "## Key Findings",
        "",
    ])

    # Auto-generate comparison
    for cfg_name, cfg_results in results.items():
        baseline = None
        best_method_a = None
        best_method_b = None

        for mp_r in cfg_results.get("method_a", []):
            if mp_r["max_pos"] == 1:
                baseline = mp_r
            if best_method_a is None or mp_r["composite"]["pnl"] > best_method_a["composite"]["pnl"]:
                best_method_a = mp_r

        for pol_r in cfg_results.get("method_b", []):
            if best_method_b is None or pol_r["result"]["pnl"] > best_method_b["result"]["pnl"]:
                best_method_b = pol_r

        if baseline:
            base_trades = baseline["composite"]["trades"]
            base_pnl = baseline["composite"]["pnl"]
            lines.append(f"**{cfg_name}**:")
            lines.append(f"- Baseline (mp=1): {base_trades} trades, ${base_pnl:+,.0f}")

            if best_method_a and best_method_a["max_pos"] > 1:
                bm = best_method_a
                trade_mult = bm["composite"]["trades"] / base_trades if base_trades else 0
                lines.append(
                    f"- Best native mp={bm['max_pos']}: "
                    f"{bm['composite']['trades']} trades ({trade_mult:.1f}x), "
                    f"${bm['composite']['pnl']:+,.0f}, DD={bm['composite']['dd']}%"
                )

            if best_method_b:
                bm = best_method_b
                trade_mult = bm["result"]["trades"] / base_trades if base_trades else 0
                lines.append(
                    f"- Best quota policy ({bm['policy']}): "
                    f"{bm['result']['trades']} trades ({trade_mult:.1f}x), "
                    f"${bm['result']['pnl']:+,.0f}, DD={bm['result']['dd']}%"
                )
            lines.append("")

    lines.extend([
        "---",
        "*Generated by hf_allocator.py — 4H variant research*",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="HF Allocator Experiment — 4H variant research"
    )
    parser.add_argument("--universe", choices=["tradeable", "live"],
                        default="tradeable")
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Allocator Experiment — 4H Variant Research")
    print("  Question: Can max_pos>1 + quotas + corr guard boost throughput?")
    print("=" * 70)

    # Load data
    data, all_coins, data_path = load_data(args.universe)
    n_bars = len(data[all_coins[0]])
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars")

    # Load tiers
    tier_map = load_tiers()
    print(f"  Tier map: {len(tier_map)} coins")

    # Filter to T1+T2 only (live universe per UNIVERSE_POLICY.md)
    live_coins = [c for c in all_coins if tier_map.get(c) in ("1", "2")]
    tiers_coins = {
        "1": [c for c in live_coins if tier_map.get(c) == "1"],
        "2": [c for c in live_coins if tier_map.get(c) == "2"],
    }
    print(f"  Live universe: {len(live_coins)} coins "
          f"(T1={len(tiers_coins['1'])}, T2={len(tiers_coins['2'])})")

    # Build bar-date map
    bar_date_map = build_bar_date_map(data, all_coins, n_bars)

    # Precompute indicators per tier (for Method A)
    print("  Precomputing indicators per tier...")
    t0 = time.time()
    indicators_by_tier = {}
    for tier_id in ("1", "2"):
        tc = tiers_coins[tier_id]
        if tc:
            indicators_by_tier[tier_id] = precompute_all(data, tc)
        else:
            indicators_by_tier[tier_id] = {}
    print(f"  Per-tier precompute: {time.time() - t0:.1f}s")

    # Precompute indicators for full live universe (for Method B)
    print("  Precomputing indicators for live universe...")
    t0 = time.time()
    indicators_live = precompute_all(data, live_coins)
    print(f"  Live precompute: {time.time() - t0:.1f}s")

    # Precompute rolling returns (for correlation guard)
    print("  Computing rolling returns for correlation guard...")
    t0 = time.time()
    returns = compute_rolling_returns(data, live_coins, n_bars)
    print(f"  Returns computed: {time.time() - t0:.1f}s")

    t_start = time.time()
    all_results = {}

    for cfg_name, cfg_base in CONFIGS.items():
        print(f"\n{'='*60}")
        print(f"  Config: {cfg_name}")
        print(f"  {json.dumps(cfg_base, sort_keys=True)}")
        print(f"{'='*60}")

        cfg_results = {"method_a": [], "method_b": []}

        # --- METHOD A: Native max_pos ---
        print("\n  === Method A: Native max_pos ===")
        for mp in MAX_POS_LEVELS:
            print(f"\n  max_pos={mp}...")
            t0 = time.time()
            composite, per_tier = run_native_max_pos(
                data, tier_map, indicators_by_tier, tiers_coins, cfg_base, mp
            )
            elapsed = time.time() - t0

            # Collect trade_list from per-tier runs for analysis
            # Re-run to get trade_lists (they're not returned from composite)
            cfg_mp = normalize_cfg({**cfg_base, "max_pos": mp})
            all_trades_mp = []
            for tier_id in ("1", "2"):
                tc = tiers_coins[tier_id]
                fee = TIER_FEES[tier_id]
                if tc:
                    r = run_backtest(indicators_by_tier[tier_id], tc, cfg_mp,
                                     fee_override=fee)
                    for t in r.get("trade_list", []):
                        t["tier"] = tier_id
                        t["_tier"] = tier_id
                    all_trades_mp.extend(r.get("trade_list", []))

            analysis = analyze_trade_list(all_trades_mp, bar_date_map, n_bars)

            print(f"    Trades={composite['trades']}, P&L=${composite['pnl']:+,.0f}, "
                  f"PF={composite['pf']}, DD={composite['dd']}%, "
                  f"Tr/wk={analysis['trades_per_week_mean']} ({elapsed:.1f}s)")

            cfg_results["method_a"].append({
                "max_pos": mp,
                "composite": composite,
                "per_tier": per_tier,
                "analysis": analysis,
            })

        # --- METHOD B: Quota-aware allocator ---
        print("\n  === Method B: Quota-Aware Allocator ===")
        for pol_name, policy in QUOTA_POLICIES.items():
            print(f"\n  Policy: {pol_name} "
                  f"(mp={policy['max_pos']}, t1_min={policy['t1_min']}, "
                  f"t2_max={policy['t2_max']}, corr={policy['corr_guard']})...")
            t0 = time.time()
            result = run_quota_allocator(
                indicators_live, live_coins, cfg_base, tier_map, data,
                n_bars, returns, policy
            )
            elapsed = time.time() - t0

            trade_list = result.pop("trade_list", [])
            analysis = analyze_trade_list(trade_list, bar_date_map, n_bars)

            print(f"    Trades={result['trades']}, P&L=${result['pnl']:+,.0f}, "
                  f"PF={result['pf']}, DD={result['dd']}%, "
                  f"Tr/wk={analysis['trades_per_week_mean']}, "
                  f"CorrBlk={result['corr_blocks']}, QuotaBlk={result['quota_blocks']} "
                  f"({elapsed:.1f}s)")

            cfg_results["method_b"].append({
                "policy": pol_name,
                "result": result,
                "analysis": analysis,
            })

        all_results[cfg_name] = cfg_results

    total_time = time.time() - t_start

    # Meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins_total": len(all_coins),
        "n_coins_live": len(live_coins),
        "n_bars": n_bars,
        "tier_counts": {k: len(v) for k, v in tiers_coins.items()},
        "corr_window": CORR_WINDOW,
        "corr_threshold": CORR_THRESHOLD,
        "tier_fees": {k: v for k, v in TIER_FEES.items()},
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "max_pos_levels": MAX_POS_LEVELS,
        "quota_policies": QUOTA_POLICIES,
    }

    # Write JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "allocator_001.json"
    with open(json_path, "w") as f:
        json.dump({"meta": meta, "results": all_results}, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown
    md_path = REPORTS_DIR / "allocator_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print(f"\n{'='*70}")
    print(f"  ALLOCATOR EXPERIMENT COMPLETE")
    print(f"  Runtime: {total_time:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
