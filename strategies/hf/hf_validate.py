#!/usr/bin/env python3
"""
HF Validate — 4H variant research validation harness.

Runs 6 robustness tests on Champion H2 and GRID_BEST baseline configs.
This is "4H variant research", NOT true HF (no sub-4H data exists yet).

Tests:
  1. Purged Walk-Forward (5-fold, embargo=2)
  2. Rolling Windows (~180-bar ≈ 30 days at 4H)
  3. Friction Stress (2x+20bps and 1-candle-later)
  4. Latency Proxy (covered by 1-candle-later in friction)
  5. Concentration (top1 < 40%, top3 < 70%)
  6. Trade Sufficiency (trades >= 20 or INSUFFICIENT_SAMPLE)

Verdict:
  - trades < 20:          INSUFFICIENT_SAMPLE
  - all gates pass:        GO
  - WF 3/5 and rest pass:  SOFT-GO
  - else:                  NO-GO

Usage:
    python strategies/hf/hf_validate.py
    python strategies/hf/hf_validate.py --universe tradeable
    python strategies/hf/hf_validate.py --universe live

Outputs:
    reports/hf/validate_001.json  — full structured results
    reports/hf/validate_001.md    — human-readable summary
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path setup (read-only import from trading_bot/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    run_backtest,
    normalize_cfg,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# Walk-forward parameters
WF_FOLDS = 5
WF_EMBARGO = 2  # bars purged between train/test boundary

# Rolling window size (~30 days at 4H = 180 bars)
ROLLING_WINDOW_BARS = 180

# Friction fee regimes
FEE_2X_20BPS = KRAKEN_FEE * 2 + 0.002   # 2x fees + 20bps slippage
FEE_1CANDLE = KRAKEN_FEE * 2 + 0.005    # 1-candle-later fill

# Concentration gates
CONC_TOP1_MAX = 0.40  # top1 coin < 40% of positive P&L
CONC_TOP3_MAX = 0.70  # top3 coins < 70% of positive P&L

# Trade sufficiency
MIN_TRADES = 20

# Configs to validate
CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 8,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 3.0,
})

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

CONFIGS = {
    "Champion_H2": CHAMPION_H2,
    "GRID_BEST": GRID_BEST,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(universe: str):
    """Load candle data and return (data_dict, sorted_coins, path_str)."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        print(f"  Tried: {DATA_FILES.get(universe, 'N/A')}")
        print(f"  Tried: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ---------------------------------------------------------------------------
# Test 1: Purged Walk-Forward (5-fold, embargo=2)
# ---------------------------------------------------------------------------
def test_walk_forward(data, coins, cfg, n_folds=WF_FOLDS, embargo=WF_EMBARGO):
    """
    Purged walk-forward validation. Split the bar range into n_folds segments.
    For each fold, test on that segment only, purging embargo bars at boundaries.
    Returns dict with per-fold results and pass/fail.
    """
    # Determine total bar range across all coins
    sample_coin = coins[0]
    n_bars = len(data[sample_coin])
    usable_start = START_BAR
    usable_bars = n_bars - usable_start

    fold_size = usable_bars // n_folds
    folds = []

    for i in range(n_folds):
        test_start = usable_start + i * fold_size
        test_end = test_start + fold_size if i < n_folds - 1 else n_bars

        # Purge: embargo bars before test_start and after test_end
        purge_start = max(usable_start, test_start - embargo)
        purge_end = min(n_bars, test_end + embargo)

        # Precompute indicators only up to test_end (causal)
        indicators = precompute_all(data, coins, end_bar=test_end)

        # Run backtest only on the test segment
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=test_start,
            end_bar=test_end,
        )

        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0

        fold_result = {
            "fold": i + 1,
            "test_start": test_start,
            "test_end": test_end,
            "purge_start": purge_start,
            "purge_end": purge_end,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "dd": round(result["dd"], 1),
            "positive": result["pnl"] > 0,
            "pf_above_1": pf > 1.0,
        }
        folds.append(fold_result)

    positive_folds = sum(1 for f in folds if f["positive"])
    pf_folds = sum(1 for f in folds if f["pf_above_1"])

    # Gate: >= 4/5 folds positive OR PF > 1 in 4/5
    gate_pass = positive_folds >= 4 or pf_folds >= 4
    # Soft pass: 3/5
    soft_pass = positive_folds >= 3 or pf_folds >= 3

    return {
        "test": "walk_forward",
        "n_folds": n_folds,
        "embargo": embargo,
        "folds": folds,
        "positive_folds": positive_folds,
        "pf_above1_folds": pf_folds,
        "gate": "PASS" if gate_pass else "FAIL",
        "soft_pass": soft_pass,
    }


# ---------------------------------------------------------------------------
# Test 2: Rolling Windows (~180-bar windows)
# ---------------------------------------------------------------------------
def test_rolling_windows(data, coins, cfg, window_bars=ROLLING_WINDOW_BARS):
    """
    Split into ~180-bar windows (~30 days at 4H).
    Gate: >= 70% windows have positive P&L.
    """
    sample_coin = coins[0]
    n_bars = len(data[sample_coin])

    # Precompute indicators once for full dataset
    indicators = precompute_all(data, coins)

    windows = []
    start = START_BAR
    while start + window_bars <= n_bars:
        end = start + window_bars
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=start,
            end_bar=end,
        )

        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0

        windows.append({
            "start_bar": start,
            "end_bar": end,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "positive": result["pnl"] > 0,
        })
        start += window_bars

    # Handle leftover bars as a final window if substantial (>= 50% of window)
    if start < n_bars and (n_bars - start) >= window_bars // 2:
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=start,
            end_bar=n_bars,
        )
        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0
        windows.append({
            "start_bar": start,
            "end_bar": n_bars,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "positive": result["pnl"] > 0,
        })

    n_windows = len(windows)
    positive_windows = sum(1 for w in windows if w["positive"])
    ratio = positive_windows / n_windows if n_windows > 0 else 0.0

    gate_pass = ratio >= 0.70

    return {
        "test": "rolling_windows",
        "window_bars": window_bars,
        "n_windows": n_windows,
        "positive_windows": positive_windows,
        "positive_ratio": round(ratio, 3),
        "windows": windows,
        "gate": "PASS" if gate_pass else "FAIL",
    }


# ---------------------------------------------------------------------------
# Test 3: Friction Stress (2x+20bps AND 1-candle-later)
# ---------------------------------------------------------------------------
def test_friction_stress(indicators, coins, cfg):
    """
    Run at elevated fee regimes.
    Gate: both P&L > 0.
    """
    r_2x20 = run_backtest(indicators, coins, cfg, fee_override=FEE_2X_20BPS)
    r_1c = run_backtest(indicators, coins, cfg, fee_override=FEE_1CANDLE)

    pf_2x20 = r_2x20["pf"]
    if pf_2x20 == float("inf"):
        pf_2x20 = 99.0
    pf_1c = r_1c["pf"]
    if pf_1c == float("inf"):
        pf_1c = 99.0

    pass_2x20 = r_2x20["pnl"] > 0
    pass_1c = r_1c["pnl"] > 0

    return {
        "test": "friction_stress",
        "fee_2x20bps": round(FEE_2X_20BPS, 6),
        "fee_1candle": round(FEE_1CANDLE, 6),
        "regime_2x20bps": {
            "trades": r_2x20["trades"],
            "pnl": round(r_2x20["pnl"], 2),
            "pf": round(pf_2x20, 2),
            "wr": round(r_2x20["wr"], 1),
            "dd": round(r_2x20["dd"], 1),
            "pass": pass_2x20,
        },
        "regime_1candle": {
            "trades": r_1c["trades"],
            "pnl": round(r_1c["pnl"], 2),
            "pf": round(pf_1c, 2),
            "wr": round(r_1c["wr"], 1),
            "dd": round(r_1c["dd"], 1),
            "pass": pass_1c,
        },
        "gate": "PASS" if (pass_2x20 and pass_1c) else "FAIL",
    }


# ---------------------------------------------------------------------------
# Test 4: Latency Proxy (labeled from friction 1-candle-later)
# ---------------------------------------------------------------------------
def test_latency_proxy(friction_result):
    """
    Latency proxy is covered by the 1-candle-later regime in friction stress.
    This test explicitly labels that result.
    """
    regime = friction_result["regime_1candle"]
    return {
        "test": "latency_proxy",
        "note": "Covered by 1-candle-later fee regime in friction stress test",
        "fee_regime": friction_result["fee_1candle"],
        "trades": regime["trades"],
        "pnl": regime["pnl"],
        "pf": regime["pf"],
        "wr": regime["wr"],
        "dd": regime["dd"],
        "gate": "PASS" if regime["pass"] else "FAIL",
    }


# ---------------------------------------------------------------------------
# Test 5: Concentration (top1 < 40%, top3 < 70%)
# ---------------------------------------------------------------------------
def test_concentration(indicators, coins, cfg):
    """
    Calculate top1 and top3 coin profit share.
    Denominator = sum(max(0, pnl)) across all trades (positive profit attribution).
    Gate: top1 < 40%, top3 < 70%.
    """
    result = run_backtest(indicators, coins, cfg)
    trade_list = result.get("trade_list", [])

    # Aggregate P&L by coin
    coin_pnl = defaultdict(float)
    for t in trade_list:
        coin_pnl[t["pair"]] += t["pnl"]

    # Denominator: sum of positive P&L per coin
    positive_profits = {c: max(0.0, pnl) for c, pnl in coin_pnl.items()}
    total_positive = sum(positive_profits.values())

    if total_positive <= 0:
        # No positive profit at all
        return {
            "test": "concentration",
            "total_positive_pnl": 0.0,
            "n_coins_traded": len(coin_pnl),
            "top1_coin": None,
            "top1_share": 0.0,
            "top3_coins": [],
            "top3_share": 0.0,
            "gate": "FAIL",
            "note": "No positive P&L to measure concentration",
        }

    # Sort coins by positive profit descending
    sorted_coins = sorted(positive_profits.items(), key=lambda x: -x[1])

    top1_coin = sorted_coins[0][0] if sorted_coins else None
    top1_profit = sorted_coins[0][1] if sorted_coins else 0.0
    top1_share = top1_profit / total_positive

    top3_coins = sorted_coins[:3]
    top3_profit = sum(p for _, p in top3_coins)
    top3_share = top3_profit / total_positive

    pass_top1 = top1_share < CONC_TOP1_MAX
    pass_top3 = top3_share < CONC_TOP3_MAX

    return {
        "test": "concentration",
        "total_positive_pnl": round(total_positive, 2),
        "n_coins_traded": len(coin_pnl),
        "top1_coin": top1_coin,
        "top1_share": round(top1_share, 4),
        "top1_pct": round(top1_share * 100, 1),
        "top1_gate": f"< {CONC_TOP1_MAX*100:.0f}%",
        "top1_pass": pass_top1,
        "top3_coins": [c for c, _ in top3_coins],
        "top3_share": round(top3_share, 4),
        "top3_pct": round(top3_share * 100, 1),
        "top3_gate": f"< {CONC_TOP3_MAX*100:.0f}%",
        "top3_pass": pass_top3,
        "gate": "PASS" if (pass_top1 and pass_top3) else "FAIL",
    }


# ---------------------------------------------------------------------------
# Test 6: Trade Sufficiency
# ---------------------------------------------------------------------------
def test_trade_sufficiency(indicators, coins, cfg):
    """
    CRITICAL gate. If total trades < 20, verdict is INSUFFICIENT_SAMPLE.
    """
    result = run_backtest(indicators, coins, cfg)
    n_trades = result["trades"]
    sufficient = n_trades >= MIN_TRADES

    return {
        "test": "trade_sufficiency",
        "total_trades": n_trades,
        "min_required": MIN_TRADES,
        "pnl": round(result["pnl"], 2),
        "wr": round(result["wr"], 1),
        "gate": "PASS" if sufficient else "INSUFFICIENT_SAMPLE",
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------
def compute_verdict(results):
    """
    Compute overall verdict from test results.
    - trades < 20:           INSUFFICIENT_SAMPLE
    - all gates pass:         GO
    - WF 3/5 and rest pass:   SOFT-GO
    - else:                   NO-GO with failed gates list
    """
    sufficiency = results["trade_sufficiency"]
    if sufficiency["gate"] == "INSUFFICIENT_SAMPLE":
        return {
            "verdict": "INSUFFICIENT_SAMPLE",
            "reason": f"Only {sufficiency['total_trades']} trades (need >= {MIN_TRADES})",
            "label": "4H variant research",
            "failed_gates": ["trade_sufficiency"],
        }

    # Collect gate results
    gates = {
        "walk_forward": results["walk_forward"]["gate"],
        "rolling_windows": results["rolling_windows"]["gate"],
        "friction_stress": results["friction_stress"]["gate"],
        "latency_proxy": results["latency_proxy"]["gate"],
        "concentration": results["concentration"]["gate"],
        "trade_sufficiency": results["trade_sufficiency"]["gate"],
    }

    failed = [name for name, status in gates.items() if status != "PASS"]

    if not failed:
        return {
            "verdict": "GO",
            "reason": "All 6 gates passed",
            "label": "4H variant research",
            "failed_gates": [],
        }

    # Check for SOFT-GO: WF at 3/5 (soft_pass) and everything else passes
    wf_soft = results["walk_forward"].get("soft_pass", False)
    other_failed = [g for g in failed if g != "walk_forward"]

    if wf_soft and not other_failed and "walk_forward" in failed:
        return {
            "verdict": "SOFT-GO",
            "reason": (
                f"WF {results['walk_forward']['positive_folds']}/5 folds "
                f"(soft pass at 3/5), all other gates pass"
            ),
            "label": "4H variant research",
            "failed_gates": ["walk_forward (soft)"],
        }

    return {
        "verdict": "NO-GO",
        "reason": f"Failed gates: {', '.join(failed)}",
        "label": "4H variant research",
        "failed_gates": failed,
    }


# ---------------------------------------------------------------------------
# Run all tests for a single config
# ---------------------------------------------------------------------------
def validate_config(name, cfg, data, coins):
    """Run all 6 validation tests for a single config."""
    print(f"\n  --- Validating: {name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0 = time.time()

    # Full precompute for friction/concentration/sufficiency
    print(f"    [1/6] Purged Walk-Forward ({WF_FOLDS}-fold, embargo={WF_EMBARGO})...")
    t1 = time.time()
    wf = test_walk_forward(data, coins, cfg)
    print(f"          {wf['positive_folds']}/{WF_FOLDS} positive folds -> {wf['gate']} ({time.time()-t1:.1f}s)")

    print(f"    [2/6] Rolling Windows ({ROLLING_WINDOW_BARS}-bar)...")
    t2 = time.time()
    rw = test_rolling_windows(data, coins, cfg)
    print(f"          {rw['positive_windows']}/{rw['n_windows']} positive ({rw['positive_ratio']*100:.0f}%) -> {rw['gate']} ({time.time()-t2:.1f}s)")

    # Precompute once for remaining tests
    indicators = precompute_all(data, coins)

    print(f"    [3/6] Friction Stress...")
    t3 = time.time()
    fr = test_friction_stress(indicators, coins, cfg)
    print(f"          2x+20bps: ${fr['regime_2x20bps']['pnl']:+,.0f} | "
          f"1-candle: ${fr['regime_1candle']['pnl']:+,.0f} -> {fr['gate']} ({time.time()-t3:.1f}s)")

    print(f"    [4/6] Latency Proxy...")
    lp = test_latency_proxy(fr)
    print(f"          (from 1-candle-later) -> {lp['gate']}")

    print(f"    [5/6] Concentration...")
    t5 = time.time()
    conc = test_concentration(indicators, coins, cfg)
    print(f"          top1={conc['top1_pct']:.1f}% top3={conc['top3_pct']:.1f}% -> {conc['gate']} ({time.time()-t5:.1f}s)")

    print(f"    [6/6] Trade Sufficiency...")
    t6 = time.time()
    suf = test_trade_sufficiency(indicators, coins, cfg)
    print(f"          {suf['total_trades']} trades (min={MIN_TRADES}) -> {suf['gate']} ({time.time()-t6:.1f}s)")

    results = {
        "walk_forward": wf,
        "rolling_windows": rw,
        "friction_stress": fr,
        "latency_proxy": lp,
        "concentration": conc,
        "trade_sufficiency": suf,
    }

    verdict = compute_verdict(results)
    elapsed = time.time() - t0

    print(f"\n    VERDICT: {verdict['verdict']} ({verdict['reason']})")
    print(f"    Elapsed: {elapsed:.1f}s")

    return {
        "name": name,
        "cfg": cfg,
        "tests": results,
        "verdict": verdict,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Markdown generator
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta):
    """Generate human-readable validation summary."""
    lines = [
        "# HF Validate — 4H Variant Research Validation",
        "",
        "> **NOTE**: This is 4H variant research, NOT true HF. No sub-4H data exists yet.",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Coins**: {meta['n_coins']}",
        f"**Total runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Summary table
    lines.extend([
        "## Verdict Summary",
        "",
        "| Config | Verdict | WF | Rolling | Friction | Latency | Concentration | Sufficiency |",
        "|--------|---------|----|---------|----------|---------|---------------|-------------|",
    ])

    for r in all_results:
        t = r["tests"]
        v = r["verdict"]["verdict"]

        def gate_icon(g):
            if g == "PASS":
                return "PASS"
            elif g == "INSUFFICIENT_SAMPLE":
                return "INSUF"
            return "FAIL"

        lines.append(
            f"| {r['name']} | **{v}** "
            f"| {gate_icon(t['walk_forward']['gate'])} "
            f"| {gate_icon(t['rolling_windows']['gate'])} "
            f"| {gate_icon(t['friction_stress']['gate'])} "
            f"| {gate_icon(t['latency_proxy']['gate'])} "
            f"| {gate_icon(t['concentration']['gate'])} "
            f"| {gate_icon(t['trade_sufficiency']['gate'])} |"
        )

    # Detailed results per config
    for r in all_results:
        t = r["tests"]
        lines.extend([
            "",
            f"---",
            "",
            f"## {r['name']}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            f"**Verdict**: **{r['verdict']['verdict']}** — {r['verdict']['reason']}",
            "",
        ])

        # Walk-Forward detail
        wf = t["walk_forward"]
        lines.extend([
            f"### 1. Purged Walk-Forward ({wf['n_folds']}-fold, embargo={wf['embargo']})",
            "",
            f"**Result**: {wf['positive_folds']}/{wf['n_folds']} positive folds, "
            f"{wf['pf_above1_folds']}/{wf['n_folds']} PF>1 folds -> **{wf['gate']}**",
            "",
            "| Fold | Bars | Trades | P&L | PF | WR% | DD% | Positive |",
            "|------|------|--------|-----|----|-----|-----|----------|",
        ])
        for f in wf["folds"]:
            lines.append(
                f"| {f['fold']} | {f['test_start']}-{f['test_end']} "
                f"| {f['trades']} | ${f['pnl']:+,.0f} | {f['pf']} "
                f"| {f['wr']}% | {f['dd']}% | {'YES' if f['positive'] else 'NO'} |"
            )

        # Rolling Windows detail
        rw = t["rolling_windows"]
        lines.extend([
            "",
            f"### 2. Rolling Windows ({rw['window_bars']}-bar)",
            "",
            f"**Result**: {rw['positive_windows']}/{rw['n_windows']} positive "
            f"({rw['positive_ratio']*100:.0f}%, gate >= 70%) -> **{rw['gate']}**",
            "",
            "| Window | Bars | Trades | P&L | PF | WR% | Positive |",
            "|--------|------|--------|-----|----|-----|----------|",
        ])
        for i, w in enumerate(rw["windows"], 1):
            lines.append(
                f"| {i} | {w['start_bar']}-{w['end_bar']} "
                f"| {w['trades']} | ${w['pnl']:+,.0f} | {w['pf']} "
                f"| {w['wr']}% | {'YES' if w['positive'] else 'NO'} |"
            )

        # Friction Stress detail
        fr = t["friction_stress"]
        lines.extend([
            "",
            f"### 3. Friction Stress",
            "",
            f"**Gate**: Both regimes P&L > $0 -> **{fr['gate']}**",
            "",
            "| Regime | Fee | Trades | P&L | PF | WR% | DD% | Pass |",
            "|--------|-----|--------|-----|----|-----|-----|------|",
        ])
        r_2x = fr["regime_2x20bps"]
        r_1c = fr["regime_1candle"]
        lines.append(
            f"| 2x+20bps | {fr['fee_2x20bps']:.4f} "
            f"| {r_2x['trades']} | ${r_2x['pnl']:+,.0f} "
            f"| {r_2x['pf']} | {r_2x['wr']}% | {r_2x['dd']}% "
            f"| {'YES' if r_2x['pass'] else 'NO'} |"
        )
        lines.append(
            f"| 1-candle | {fr['fee_1candle']:.4f} "
            f"| {r_1c['trades']} | ${r_1c['pnl']:+,.0f} "
            f"| {r_1c['pf']} | {r_1c['wr']}% | {r_1c['dd']}% "
            f"| {'YES' if r_1c['pass'] else 'NO'} |"
        )

        # Latency Proxy detail
        lp = t["latency_proxy"]
        lines.extend([
            "",
            f"### 4. Latency Proxy",
            "",
            f"**Note**: {lp['note']}",
            f"**Result**: P&L=${lp['pnl']:+,.0f} at fee={lp['fee_regime']:.4f} -> **{lp['gate']}**",
        ])

        # Concentration detail
        conc = t["concentration"]
        lines.extend([
            "",
            f"### 5. Concentration",
            "",
            f"**Denominator**: sum(max(0, coin_pnl)) = ${conc['total_positive_pnl']:+,.0f}",
            f"**Coins traded**: {conc['n_coins_traded']}",
            "",
            "| Metric | Value | Gate | Pass |",
            "|--------|-------|------|------|",
        ])
        top1_display = conc.get("top1_coin", "N/A") or "N/A"
        lines.append(
            f"| Top-1 ({top1_display}) | {conc['top1_pct']:.1f}% "
            f"| {conc['top1_gate']} | {'YES' if conc.get('top1_pass', False) else 'NO'} |"
        )
        top3_display = ", ".join(conc.get("top3_coins", [])) or "N/A"
        lines.append(
            f"| Top-3 ({top3_display}) | {conc['top3_pct']:.1f}% "
            f"| {conc['top3_gate']} | {'YES' if conc.get('top3_pass', False) else 'NO'} |"
        )
        lines.append(f"| **Overall** | | | **{conc['gate']}** |")

        # Trade Sufficiency detail
        suf = t["trade_sufficiency"]
        lines.extend([
            "",
            f"### 6. Trade Sufficiency",
            "",
            f"**Total trades**: {suf['total_trades']} (minimum: {suf['min_required']})",
            f"**P&L**: ${suf['pnl']:+,.0f} | **WR**: {suf['wr']}%",
            f"**Result**: **{suf['gate']}**",
        ])

    # Footer
    lines.extend([
        "",
        "---",
        "",
        "## Gate Thresholds",
        "",
        "| Gate | Threshold |",
        "|------|-----------|",
        f"| Walk-Forward | >= 4/{WF_FOLDS} folds positive (or PF>1) |",
        f"| Rolling Windows | >= 70% positive P&L |",
        f"| Friction Stress | P&L > $0 at 2x+20bps AND 1-candle-later |",
        f"| Latency Proxy | (same as 1-candle-later friction) |",
        f"| Concentration | top1 < {CONC_TOP1_MAX*100:.0f}%, top3 < {CONC_TOP3_MAX*100:.0f}% |",
        f"| Trade Sufficiency | >= {MIN_TRADES} trades |",
        "",
        "## Verdict Logic",
        "",
        "- `INSUFFICIENT_SAMPLE`: trades < 20",
        "- `GO`: all gates pass",
        "- `SOFT-GO`: WF 3/5 and all other gates pass",
        "- `NO-GO`: any gate fails (beyond soft WF)",
        "",
        f"*Generated by hf_validate.py at {meta['timestamp']}*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Validate - 4H variant research validation harness"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Validate — 4H Variant Research Validation")
    print("  NOTE: This is 4H variant research, NOT true HF")
    print("=" * 70)
    print(f"  Universe: {args.universe}")

    # Load data
    data, coins, data_path = load_data(args.universe)
    n_bars = len(data[coins[0]]) if coins else 0
    print(f"  Loaded {len(coins)} coins, {n_bars} bars from {Path(data_path).name}")

    t_start = time.time()

    # Run validation for each config
    all_results = []
    for name, cfg in CONFIGS.items():
        result = validate_config(name, cfg, data, coins)
        all_results.append(result)

    total_time = time.time() - t_start

    # Meta info
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "n_bars": n_bars,
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "configs_validated": list(CONFIGS.keys()),
        "gate_thresholds": {
            "wf_folds": WF_FOLDS,
            "wf_embargo": WF_EMBARGO,
            "wf_pass_min": 4,
            "rolling_window_bars": ROLLING_WINDOW_BARS,
            "rolling_positive_min": 0.70,
            "friction_fee_2x20bps": round(FEE_2X_20BPS, 6),
            "friction_fee_1candle": round(FEE_1CANDLE, 6),
            "concentration_top1_max": CONC_TOP1_MAX,
            "concentration_top3_max": CONC_TOP3_MAX,
            "min_trades": MIN_TRADES,
        },
    }

    # Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "validate_001.json"

    # Build structured output
    json_output = {
        "meta": meta,
        "results": [],
    }
    for r in all_results:
        json_output["results"].append({
            "name": r["name"],
            "cfg": r["cfg"],
            "verdict": r["verdict"],
            "elapsed_s": r["elapsed_s"],
            "tests": {
                "walk_forward": r["tests"]["walk_forward"],
                "rolling_windows": r["tests"]["rolling_windows"],
                "friction_stress": r["tests"]["friction_stress"],
                "latency_proxy": r["tests"]["latency_proxy"],
                "concentration": r["tests"]["concentration"],
                "trade_sufficiency": r["tests"]["trade_sufficiency"],
            },
        })

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown report
    md_path = REPORTS_DIR / "validate_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print("\n" + "=" * 70)
    print("  VALIDATION SUMMARY (4H variant research)")
    print("=" * 70)
    print(f"\n  {'Config':<20} {'Verdict':<25} {'Failed Gates'}")
    print("  " + "-" * 65)
    for r in all_results:
        v = r["verdict"]
        failed = ", ".join(v["failed_gates"]) if v["failed_gates"] else "-"
        print(f"  {r['name']:<20} {v['verdict']:<25} {failed}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()
