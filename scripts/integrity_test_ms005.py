#!/usr/bin/env python3
"""
ADR-LAB-001 Integrity Test — ms_005 (FVG Fill / Scalp FVG)

Four tests per research integrity principles:
  1. Blind run on full universe (no coin pre-selection)
  2. Per-coin P&L distribution (concentration, Herfindahl, persistence)
  3. Walk-forward persistence (5-fold rolling + coin persistence)
  4. Cross-exchange sanity check (Kraken vs MEXC)

Pass criteria:
  T1: PF >= 1.0 on full blind universe
  T2: Herfindahl < 0.10 AND top-1 coin < 15% P&L AND top-5 coins < 50% P&L
  T3: >= 4/5 WF folds PF >= 0.9 AND coin-persistence rank correlation > 0
  T4: Cross-exchange PF >= 0.8 AND same direction (profitable)

Usage:
    python3 scripts/integrity_test_ms005.py
    python3 scripts/integrity_test_ms005.py --config ms_018_mse_shallow
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import importlib
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

# ---------------------------------------------------------------------------
# Path setup (repo root FIRST to avoid trading_bot/strategies shadowing)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))  # must be first — strategies.4h lives here

_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")

resolve_dataset = _data_resolver.resolve_dataset
run_backtest = _sprint3_engine.run_backtest
precompute_ms_indicators = _ms_indicators.precompute_ms_indicators
build_sweep_configs = _ms_hypotheses.build_sweep_configs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KRAKEN_DATASET = "4h_default"  # ohlcv_4h_kraken_spot_usd_526
MEXC_DATASET = "ohlcv_4h_mexc_spot_usdt_v2"  # 444 coins
MIN_BARS = 360
START_BAR = 50
DEFAULT_CONFIG = "ms_005_msb_base"
N_BOOTSTRAP = 1000
SEED = 42

# Pass thresholds
HHI_MAX = 0.10             # Herfindahl index
TOP1_PNL_MAX_PCT = 15.0    # Top-1 coin max % of total P&L
TOP5_PNL_MAX_PCT = 50.0    # Top-5 coins max % of total P&L
WF_MIN_FOLDS = 4           # out of 5
WF_MIN_PF = 0.9
CROSS_MIN_PF = 0.8
COIN_PERSIST_MIN_CORR = 0.0  # Spearman rank correlation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_pf(trades):
    gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def _calc_wr(trades):
    if not trades:
        return 0.0
    return 100 * sum(1 for t in trades if t["pnl"] > 0) / len(trades)


def _load_and_prepare(dataset_id):
    """Load dataset and return (data, coins, path)."""
    path = resolve_dataset(dataset_id)
    with open(path) as f:
        data = json.load(f)
    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    return data, coins, path


def _run_bt(data, coins, signal_fn, params, indicators,
            start_bar=START_BAR, end_bar=None, fee=None):
    """Run a single backtest, return BacktestResult."""
    kwargs = dict(
        data=data, coins=coins, signal_fn=signal_fn, params=params,
        indicators=indicators, exit_mode="dc",
        start_bar=start_bar,
    )
    if end_bar is not None:
        kwargs["end_bar"] = end_bar
    if fee is not None:
        kwargs["fee"] = fee
    return run_backtest(**kwargs)


# ---------------------------------------------------------------------------
# TEST 1: Blind Universe Run
# ---------------------------------------------------------------------------

def test_blind_universe(data, coins, signal_fn, params, indicators, label="Kraken"):
    """Run on full universe without any coin pre-selection."""
    print(f"\n{'=' * 72}")
    print(f"  TEST 1: BLIND UNIVERSE RUN ({label})")
    print(f"{'=' * 72}")

    bt = _run_bt(data, coins, signal_fn, params, indicators)
    n_coins_traded = len(set(t["pair"] for t in bt.trade_list))

    print(f"\n  Universe: {len(coins)} coins")
    print(f"  Coins traded: {n_coins_traded}")
    print(f"  Trades: {bt.trades}")
    print(f"  PF: {bt.pf:.2f}")
    print(f"  WR: {bt.wr:.1f}%")
    print(f"  P&L: ${bt.pnl:+,.0f}")
    print(f"  DD: {bt.dd:.1f}%")

    passed = bt.pf >= 1.0 and bt.trades >= 80
    print(f"\n  Verdict: {'PASS' if passed else 'FAIL'} (PF={bt.pf:.2f} {'≥' if bt.pf >= 1.0 else '<'} 1.0, "
          f"trades={bt.trades} {'≥' if bt.trades >= 80 else '<'} 80)")

    return {
        "label": label,
        "n_coins": len(coins),
        "n_coins_traded": n_coins_traded,
        "trades": bt.trades,
        "pf": round(bt.pf, 4),
        "wr": round(bt.wr, 2),
        "pnl": round(bt.pnl, 2),
        "dd": round(bt.dd, 2),
        "pass": passed,
        "trade_list": bt.trade_list,
    }


# ---------------------------------------------------------------------------
# TEST 2: Per-Coin P&L Distribution
# ---------------------------------------------------------------------------

def test_coin_distribution(trade_list, label=""):
    """Analyze per-coin concentration and distribution."""
    print(f"\n{'=' * 72}")
    print(f"  TEST 2: PER-COIN P&L DISTRIBUTIE")
    print(f"{'=' * 72}")

    # Group by coin
    coin_stats = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trade_list:
        pair = t["pair"]
        coin_stats[pair]["trades"] += 1
        coin_stats[pair]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            coin_stats[pair]["wins"] += 1

    n_coins = len(coin_stats)
    total_pnl = sum(s["pnl"] for s in coin_stats.values())
    total_trades = sum(s["trades"] for s in coin_stats.values())

    # Positive P&L coins only for concentration
    positive_coins = {k: v for k, v in coin_stats.items() if v["pnl"] > 0}
    total_positive_pnl = sum(v["pnl"] for v in positive_coins.values())

    # Sort by P&L descending
    sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)

    # --- Herfindahl Index (on trade share) ---
    trade_shares = [(s["trades"] / total_trades) ** 2 for s in coin_stats.values()]
    hhi = sum(trade_shares)

    # --- P&L concentration ---
    if total_positive_pnl > 0:
        top1_pnl_pct = sorted_coins[0][1]["pnl"] / total_positive_pnl * 100
        top5_pnl = sum(s[1]["pnl"] for s in sorted_coins[:5])
        top5_pnl_pct = top5_pnl / total_positive_pnl * 100
        top10_pnl = sum(s[1]["pnl"] for s in sorted_coins[:10])
        top10_pnl_pct = top10_pnl / total_positive_pnl * 100
    else:
        top1_pnl_pct = top5_pnl_pct = top10_pnl_pct = 0.0

    # --- Per-coin PF distribution ---
    coin_pfs = []
    for pair, stats in sorted_coins:
        gp = stats["pnl"] if stats["pnl"] > 0 else 0
        gl = abs(stats["pnl"]) if stats["pnl"] < 0 else 0
        # Per-coin PF approximation
        wins_pnl = sum(t["pnl"] for t in trade_list if t["pair"] == pair and t["pnl"] > 0)
        losses_pnl = abs(sum(t["pnl"] for t in trade_list if t["pair"] == pair and t["pnl"] < 0))
        pf = wins_pnl / losses_pnl if losses_pnl > 0 else (float("inf") if wins_pnl > 0 else 0.0)
        coin_pfs.append((pair, pf, stats["trades"], stats["pnl"]))

    # Coins with PF > 1.0
    profitable_coins = sum(1 for _, pf, tr, _ in coin_pfs if pf > 1.0 and tr >= 3)
    total_with_min_trades = sum(1 for _, _, tr, _ in coin_pfs if tr >= 3)
    pct_profitable = profitable_coins / total_with_min_trades * 100 if total_with_min_trades > 0 else 0

    # Print results
    print(f"\n  Coins traded: {n_coins}")
    print(f"  Total trades: {total_trades}")
    print(f"  Total P&L: ${total_pnl:+,.0f}")

    print(f"\n  --- Concentration Metrics ---")
    print(f"  Herfindahl Index (HHI): {hhi:.4f} (threshold: < {HHI_MAX})")
    print(f"  Top-1 coin P&L share: {top1_pnl_pct:.1f}% (threshold: < {TOP1_PNL_MAX_PCT}%)")
    print(f"  Top-5 coins P&L share: {top5_pnl_pct:.1f}% (threshold: < {TOP5_PNL_MAX_PCT}%)")
    print(f"  Top-10 coins P&L share: {top10_pnl_pct:.1f}%")
    print(f"  Profitable coins (≥3 trades, PF>1): {profitable_coins}/{total_with_min_trades} ({pct_profitable:.0f}%)")

    print(f"\n  --- Top 10 Coins (by P&L) ---")
    print(f"  {'Pair':<16} {'Trades':>7} {'PF':>7} {'P&L':>10} {'WR%':>6}")
    print(f"  {'-'*16} {'-'*7} {'-'*7} {'-'*10} {'-'*6}")
    for pair, pf, tr, pnl in coin_pfs[:10]:
        wr = coin_stats[pair]["wins"] / coin_stats[pair]["trades"] * 100
        pf_str = f"{min(pf, 99.9):.2f}"
        print(f"  {pair:<16} {tr:>7} {pf_str:>7} {pnl:>+10.0f} {wr:>5.1f}%")

    print(f"\n  --- Bottom 5 Coins (by P&L) ---")
    for pair, pf, tr, pnl in coin_pfs[-5:]:
        wr = coin_stats[pair]["wins"] / coin_stats[pair]["trades"] * 100
        pf_str = f"{min(pf, 99.9):.2f}"
        print(f"  {pair:<16} {tr:>7} {pf_str:>7} {pnl:>+10.0f} {wr:>5.1f}%")

    # Verdict
    hhi_pass = hhi < HHI_MAX
    top1_pass = top1_pnl_pct < TOP1_PNL_MAX_PCT
    top5_pass = top5_pnl_pct < TOP5_PNL_MAX_PCT

    passed = hhi_pass and top1_pass and top5_pass
    print(f"\n  HHI < {HHI_MAX}: {'PASS' if hhi_pass else 'FAIL'} ({hhi:.4f})")
    print(f"  Top-1 < {TOP1_PNL_MAX_PCT}%: {'PASS' if top1_pass else 'FAIL'} ({top1_pnl_pct:.1f}%)")
    print(f"  Top-5 < {TOP5_PNL_MAX_PCT}%: {'PASS' if top5_pass else 'FAIL'} ({top5_pnl_pct:.1f}%)")
    print(f"  Verdict: {'PASS' if passed else 'FAIL'}")

    return {
        "n_coins_traded": n_coins,
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "hhi": round(hhi, 6),
        "top1_pnl_pct": round(top1_pnl_pct, 2),
        "top5_pnl_pct": round(top5_pnl_pct, 2),
        "top10_pnl_pct": round(top10_pnl_pct, 2),
        "profitable_coins_pct": round(pct_profitable, 1),
        "profitable_coins": profitable_coins,
        "total_coins_min3_trades": total_with_min_trades,
        "hhi_pass": hhi_pass,
        "top1_pass": top1_pass,
        "top5_pass": top5_pass,
        "pass": passed,
        "top10": [
            {"pair": pair, "pf": round(min(pf, 99.99), 4), "trades": tr, "pnl": round(pnl, 2)}
            for pair, pf, tr, pnl in coin_pfs[:10]
        ],
        "bottom5": [
            {"pair": pair, "pf": round(min(pf, 99.99), 4), "trades": tr, "pnl": round(pnl, 2)}
            for pair, pf, tr, pnl in coin_pfs[-5:]
        ],
    }


# ---------------------------------------------------------------------------
# TEST 3: Walk-Forward Persistence (5-fold) + Coin Persistence
# ---------------------------------------------------------------------------

def test_walk_forward_5fold(data, coins, signal_fn, params, indicators):
    """5-fold rolling walk-forward + coin-level persistence."""
    print(f"\n{'=' * 72}")
    print(f"  TEST 3: 5-FOLD WALK-FORWARD + COIN PERSISTENCE")
    print(f"{'=' * 72}")

    max_bars = max(ind["n"] for ind in indicators.values())
    usable = max_bars - START_BAR
    fold_size = usable // 5

    folds = []
    for i in range(5):
        start = START_BAR + i * fold_size
        end = START_BAR + (i + 1) * fold_size if i < 4 else max_bars
        folds.append({"start_bar": start, "end_bar": end, "label": f"F{i+1}"})

    # Run each fold
    print(f"\n  5 temporal folds ({fold_size} bars each):\n")
    print(f"  {'Fold':<6} {'Bars':<14} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10}")
    print(f"  {'-'*6} {'-'*14} {'-'*7} {'-'*7} {'-'*7} {'-'*10}")

    fold_results = []
    fold_trade_lists = []
    for fold in folds:
        bt = _run_bt(data, coins, signal_fn, params, indicators,
                     start_bar=fold["start_bar"], end_bar=fold["end_bar"])
        pf = bt.pf
        wr = bt.wr
        pnl = bt.pnl
        marker = "✅" if pf >= WF_MIN_PF else "❌"
        print(f"  {fold['label']:<6} {fold['start_bar']:>4}-{fold['end_bar']:<8} {bt.trades:>7} "
              f"{pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {marker}")

        fold_results.append({
            "label": fold["label"],
            "start_bar": fold["start_bar"],
            "end_bar": fold["end_bar"],
            "trades": bt.trades,
            "pf": round(pf, 4),
            "wr": round(wr, 2),
            "pnl": round(pnl, 2),
            "dd": round(bt.dd, 2),
            "pass": pf >= WF_MIN_PF and bt.trades > 0,
        })
        fold_trade_lists.append(bt.trade_list)

    n_pass = sum(1 for fr in fold_results if fr["pass"])
    wf_pass = n_pass >= WF_MIN_FOLDS
    print(f"\n  Folds passing (PF ≥ {WF_MIN_PF}): {n_pass}/5 (need ≥ {WF_MIN_FOLDS})")
    print(f"  Walk-forward: {'PASS' if wf_pass else 'FAIL'}")

    # --- Coin Persistence ---
    # Compare coin P&L ranking in first half vs second half
    print(f"\n  --- Coin Persistence (rank correlation) ---")

    half1_trades = []
    half2_trades = []
    for i, tl in enumerate(fold_trade_lists):
        if i < 2:  # F1, F2
            half1_trades.extend(tl)
        else:  # F3, F4, F5
            half2_trades.extend(tl)

    def _coin_pnl_map(trades):
        m = defaultdict(float)
        for t in trades:
            m[t["pair"]] += t["pnl"]
        return m

    h1_pnl = _coin_pnl_map(half1_trades)
    h2_pnl = _coin_pnl_map(half2_trades)

    # Coins present in both halves
    common_coins = sorted(set(h1_pnl.keys()) & set(h2_pnl.keys()))
    print(f"  Coins in both halves: {len(common_coins)}")

    if len(common_coins) >= 10:
        # Spearman rank correlation
        h1_vals = np.array([h1_pnl[c] for c in common_coins])
        h2_vals = np.array([h2_pnl[c] for c in common_coins])

        # Rank-based correlation
        h1_ranks = np.argsort(np.argsort(-h1_vals)).astype(float)  # desc rank
        h2_ranks = np.argsort(np.argsort(-h2_vals)).astype(float)
        n = len(common_coins)
        d_sq = np.sum((h1_ranks - h2_ranks) ** 2)
        spearman = 1 - (6 * d_sq) / (n * (n**2 - 1))

        # Top-20 overlap
        h1_top20 = set(sorted(common_coins, key=lambda c: h1_pnl[c], reverse=True)[:20])
        h2_top20 = set(sorted(common_coins, key=lambda c: h2_pnl[c], reverse=True)[:20])
        overlap = len(h1_top20 & h2_top20)

        persist_pass = spearman > COIN_PERSIST_MIN_CORR
        print(f"  Spearman rank correlation: {spearman:.3f} (threshold: > {COIN_PERSIST_MIN_CORR})")
        print(f"  Top-20 coin overlap: {overlap}/20 ({overlap/20*100:.0f}%)")
        print(f"  Coin persistence: {'PASS' if persist_pass else 'FAIL'}")
    else:
        spearman = 0.0
        overlap = 0
        persist_pass = False
        print(f"  Insufficient common coins for persistence test")

    passed = wf_pass and persist_pass
    print(f"\n  Verdict: {'PASS' if passed else 'FAIL'}")

    return {
        "folds": fold_results,
        "n_folds_pass": n_pass,
        "wf_pass": wf_pass,
        "common_coins": len(common_coins),
        "spearman_rho": round(spearman, 4),
        "top20_overlap": overlap,
        "persist_pass": persist_pass,
        "pass": passed,
    }


# ---------------------------------------------------------------------------
# TEST 4: Cross-Exchange Sanity Check
# ---------------------------------------------------------------------------

def _align_mexc_to_kraken_window(mexc_data, mexc_coins, kraken_data, kraken_coins):
    """Trim MEXC candle data to match Kraken's time window.

    Returns trimmed data dict where each coin only has candles within
    the Kraken time range. This ensures apples-to-apples comparison.
    """
    # Determine Kraken time window
    kr_times = []
    for pair in kraken_coins[:50]:
        candles = kraken_data[pair]
        if candles:
            kr_times.append(candles[0]["time"])
            kr_times.append(candles[-1]["time"])
    kr_start = min(kr_times)
    kr_end = max(kr_times)

    from datetime import datetime, timezone
    print(f"  Kraken window: {datetime.fromtimestamp(kr_start, tz=timezone.utc):%Y-%m-%d} "
          f"to {datetime.fromtimestamp(kr_end, tz=timezone.utc):%Y-%m-%d}")

    # Trim MEXC data to this window
    trimmed = {}
    trimmed_coins = []
    for pair in mexc_coins:
        candles = mexc_data[pair]
        aligned = [c for c in candles if kr_start <= c["time"] <= kr_end]
        if len(aligned) >= MIN_BARS:
            trimmed[pair] = aligned
            trimmed_coins.append(pair)

    # Copy metadata keys
    for k in mexc_data:
        if k.startswith("_"):
            trimmed[k] = mexc_data[k]

    print(f"  MEXC coins after alignment (≥{MIN_BARS} bars): {len(trimmed_coins)}")
    if trimmed_coins:
        lens = [len(trimmed[p]) for p in trimmed_coins]
        print(f"  MEXC aligned bar range: {min(lens)}-{max(lens)}")

    return trimmed, trimmed_coins


def test_cross_exchange(signal_fn, params, kraken_result, kraken_data=None,
                        kraken_coins=None, mexc_fee=0.001):
    """Run on MEXC 4H data (time-aligned to Kraken window) and compare."""
    print(f"\n{'=' * 72}")
    print(f"  TEST 4: CROSS-EXCHANGE SANITY CHECK (Kraken vs MEXC)")
    print(f"{'=' * 72}")

    # Load MEXC data
    print(f"\n  Loading MEXC dataset...")
    t0 = time.time()
    mexc_data, mexc_coins, mexc_path = _load_and_prepare(MEXC_DATASET)
    print(f"  MEXC raw: {len(mexc_coins)} coins ({time.time() - t0:.1f}s)")

    # Align time windows
    if kraken_data is not None and kraken_coins is not None:
        print(f"  Aligning MEXC to Kraken time window...")
        mexc_data, mexc_coins = _align_mexc_to_kraken_window(
            mexc_data, mexc_coins, kraken_data, kraken_coins)

    print(f"  Precomputing MEXC indicators...")
    t1 = time.time()
    mexc_indicators = precompute_ms_indicators(mexc_data, mexc_coins)
    print(f"  Done ({time.time() - t1:.1f}s)")

    # Run on MEXC with MEXC fee structure (0.1% taker = 10bps)
    print(f"  Running backtest (fee={mexc_fee*100:.1f}bps per side)...")
    bt = _run_bt(mexc_data, mexc_coins, signal_fn, params, mexc_indicators,
                 fee=mexc_fee)

    n_coins_traded = len(set(t["pair"] for t in bt.trade_list))

    # Overlapping coins
    kraken_coins_traded = set(t["pair"] for t in kraken_result["trade_list"])
    mexc_coins_traded = set(t["pair"] for t in bt.trade_list)
    overlap = len(kraken_coins_traded & mexc_coins_traded)

    print(f"\n  {'Metric':<20} {'Kraken':>12} {'MEXC':>12}")
    print(f"  {'-'*20} {'-'*12} {'-'*12}")
    print(f"  {'Coins universe':<20} {kraken_result['n_coins']:>12} {len(mexc_coins):>12}")
    print(f"  {'Coins traded':<20} {kraken_result['n_coins_traded']:>12} {n_coins_traded:>12}")
    print(f"  {'Coin overlap':<20} {'':>12} {overlap:>12}")
    print(f"  {'Trades':<20} {kraken_result['trades']:>12} {bt.trades:>12}")
    print(f"  {'PF':<20} {kraken_result['pf']:>12.2f} {bt.pf:>12.2f}")
    print(f"  {'WR':<20} {kraken_result['wr']:>11.1f}% {bt.wr:>11.1f}%")
    print(f"  {'P&L':<20} ${kraken_result['pnl']:>+10,.0f} ${bt.pnl:>+10,.0f}")
    print(f"  {'DD':<20} {kraken_result['dd']:>11.1f}% {bt.dd:>11.1f}%")
    print(f"  {'Fee':<20} {'26bps':>12} {f'{mexc_fee*10000:.0f}bps':>12}")

    pf_pass = bt.pf >= CROSS_MIN_PF
    profitable = bt.pnl > 0
    passed = pf_pass and profitable

    print(f"\n  MEXC PF ≥ {CROSS_MIN_PF}: {'PASS' if pf_pass else 'FAIL'} ({bt.pf:.2f})")
    print(f"  MEXC profitable: {'PASS' if profitable else 'FAIL'} (${bt.pnl:+,.0f})")
    print(f"  Verdict: {'PASS' if passed else 'FAIL'}")

    return {
        "mexc_coins": len(mexc_coins),
        "mexc_coins_traded": n_coins_traded,
        "coin_overlap": overlap,
        "mexc_trades": bt.trades,
        "mexc_pf": round(bt.pf, 4),
        "mexc_wr": round(bt.wr, 2),
        "mexc_pnl": round(bt.pnl, 2),
        "mexc_dd": round(bt.dd, 2),
        "mexc_fee_bps": mexc_fee * 10000,
        "pf_pass": pf_pass,
        "profitable": profitable,
        "pass": passed,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ADR-LAB-001 Integrity Test for MS strategies"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"Config ID to test (default: {DEFAULT_CONFIG})")
    parser.add_argument("--mexc-fee", type=float, default=0.001,
                        help="MEXC fee per side (default: 0.001 = 10bps)")
    args = parser.parse_args()

    config_id = args.config

    print(f"\n{'=' * 72}")
    print(f"  ADR-LAB-001 INTEGRITY TEST")
    print(f"  Config: {config_id}")
    print(f"{'=' * 72}")

    # Resolve config
    all_configs = build_sweep_configs()
    cfg = None
    for c in all_configs:
        if c["id"] == config_id:
            cfg = c
            break
    if cfg is None:
        # Try partial match
        for c in all_configs:
            if config_id in c["id"]:
                cfg = c
                break
    if cfg is None:
        print(f"  ERROR: Config '{config_id}' not found.")
        print(f"  Available: {[c['id'] for c in all_configs]}")
        sys.exit(1)

    signal_fn = cfg["signal_fn"]
    params = cfg["params"]
    print(f"  Family: {cfg['family']}")
    print(f"  Description: {cfg['description']}")

    # Load primary (Kraken) data
    print(f"\n  Loading Kraken dataset ({KRAKEN_DATASET})...")
    t0 = time.time()
    data, coins, data_path = _load_and_prepare(KRAKEN_DATASET)
    print(f"  Kraken: {len(coins)} coins ({time.time() - t0:.1f}s)")

    print(f"  Precomputing indicators...")
    t1 = time.time()
    indicators = precompute_ms_indicators(data, coins)
    print(f"  Done ({time.time() - t1:.1f}s)")

    # ═══════════════════════════════════════════════════════════════════
    # TEST 1: Blind Universe Run
    # ═══════════════════════════════════════════════════════════════════
    t1_result = test_blind_universe(data, coins, signal_fn, params, indicators, label="Kraken")

    # ═══════════════════════════════════════════════════════════════════
    # TEST 2: Per-Coin Distribution
    # ═══════════════════════════════════════════════════════════════════
    t2_result = test_coin_distribution(t1_result["trade_list"])

    # ═══════════════════════════════════════════════════════════════════
    # TEST 3: Walk-Forward + Coin Persistence
    # ═══════════════════════════════════════════════════════════════════
    t3_result = test_walk_forward_5fold(data, coins, signal_fn, params, indicators)

    # ═══════════════════════════════════════════════════════════════════
    # TEST 4: Cross-Exchange
    # ═══════════════════════════════════════════════════════════════════
    t4_result = test_cross_exchange(signal_fn, params, t1_result,
                                    kraken_data=data, kraken_coins=coins,
                                    mexc_fee=args.mexc_fee)

    # ═══════════════════════════════════════════════════════════════════
    # FINAL VERDICT
    # ═══════════════════════════════════════════════════════════════════
    tests = [
        ("T1: Blind Universe", t1_result["pass"]),
        ("T2: Coin Distribution", t2_result["pass"]),
        ("T3: Walk-Forward + Persistence", t3_result["pass"]),
        ("T4: Cross-Exchange", t4_result["pass"]),
    ]

    n_pass = sum(1 for _, p in tests if p)

    print(f"\n{'=' * 72}")
    print(f"  ADR-LAB-001 INTEGRITY TEST — EINDOORDEEL")
    print(f"{'=' * 72}")
    print(f"\n  {'Test':<35} {'Verdict':>10}")
    print(f"  {'-'*35} {'-'*10}")
    for name, passed in tests:
        print(f"  {name:<35} {'✅ PASS' if passed else '❌ FAIL':>10}")

    if n_pass == 4:
        verdict = "VERIFIED"
    elif n_pass >= 3:
        verdict = "CONDITIONAL"
    else:
        verdict = "FAILED"

    icon = "✅" if verdict == "VERIFIED" else ("⚠️" if verdict == "CONDITIONAL" else "❌")
    print(f"\n  {icon} {config_id}: {verdict} ({n_pass}/4 tests)")

    # Save results
    output = {
        "config_id": config_id,
        "family": cfg["family"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "tests_passed": n_pass,
        "test1_blind_universe": {k: v for k, v in t1_result.items() if k != "trade_list"},
        "test2_coin_distribution": t2_result,
        "test3_walk_forward": t3_result,
        "test4_cross_exchange": t4_result,
    }

    out_dir = REPO_ROOT / "reports" / "ms"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"integrity_test_{config_id}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Opgeslagen: {out_path}")


if __name__ == "__main__":
    main()
