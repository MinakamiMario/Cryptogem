#!/usr/bin/env python3
"""
Tier 1 Imperfection Hypothesis Tests — ms_018
==============================================
H1: Weekend filter (dag-van-de-week)
H2: Time-of-day entry kwaliteit (4H candle starttijd)
H3: Liquiditeits-quintiel amplificatie (volume stratificatie)
H4: Vol_scale wrapper (ATR-based position sizing)

Één backtest run, vier analyses. Per ADR-LAB-001: goedkoopste test eerst.
"""

import sys, json, importlib, statistics
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))  # must be first — strategies.4h lives here, not in trading_bot/

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
FEE_BPS = 26  # Kraken

# ── Helpers ──────────────────────────────────────────────────────

def calc_pf(trades):
    """Profit factor from trade list."""
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss

def calc_wr(trades):
    """Win rate %."""
    if not trades:
        return 0.0
    return 100 * sum(1 for t in trades if t["pnl"] > 0) / len(trades)

def calc_pnl(trades):
    """Total P&L."""
    return sum(t["pnl"] for t in trades)

def calc_dd(trades, initial_equity=2000):
    """Max drawdown % from equity curve."""
    equity = initial_equity
    peak = equity
    max_dd = 0
    for t in sorted(trades, key=lambda x: x["entry_bar"]):
        equity += t["pnl"]
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    return max_dd * 100

def print_group_stats(label, groups, baseline_pf=None):
    """Print stats per group."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'Group':<25} {'Trades':>7} {'PF':>7} {'WR%':>7} {'P&L':>10} {'EV/tr':>8} {'DD%':>7}")
    print(f"  {'-'*25} {'-'*7} {'-'*7} {'-'*7} {'-'*10} {'-'*8} {'-'*7}")

    results = []
    for name, trades in sorted(groups.items()):
        if not trades:
            continue
        pf = calc_pf(trades)
        wr = calc_wr(trades)
        pnl = calc_pnl(trades)
        ev = pnl / len(trades) if trades else 0
        dd = calc_dd(trades)
        results.append((name, len(trades), pf, wr, pnl, ev, dd))
        marker = ""
        if baseline_pf and pf > baseline_pf * 1.1:
            marker = " ✅ (+10%)"
        elif baseline_pf and pf < baseline_pf * 0.9:
            marker = " ❌ (-10%)"
        print(f"  {name:<25} {len(trades):>7} {pf:>7.2f} {wr:>6.1f}% {pnl:>+10.0f} {ev:>+8.1f} {dd:>6.1f}%{marker}")

    return results

def enrich_trades_with_time(trades, data):
    """Add datetime info to each trade."""
    for t in trades:
        pair = t["pair"]
        candles = data[pair]
        if t["entry_bar"] < len(candles):
            ts = candles[t["entry_bar"]]["time"]
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            t["_entry_dt"] = dt
            t["_weekday"] = dt.weekday()  # 0=Mon, 6=Sun
            t["_hour"] = dt.hour
            t["_day_name"] = dt.strftime("%a")
        else:
            t["_entry_dt"] = None
            t["_weekday"] = -1
            t["_hour"] = -1
            t["_day_name"] = "?"

def calc_avg_daily_volume(data, pair, n_bars=100):
    """Approximate average daily volume from last n_bars of 4H candles."""
    candles = data[pair]
    recent = candles[-n_bars:] if len(candles) >= n_bars else candles
    # 4H = 6 bars per day
    total_vol = sum(c.get("volume", 0) for c in recent)
    n_days = len(recent) / 6.0
    return total_vol / n_days if n_days > 0 else 0

# ── Main ─────────────────────────────────────────────────────────

def main():
    print("Loading data...")
    path = _data_resolver.resolve_dataset(DATASET_ID)
    with open(path) as f:
        data = json.load(f)

    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    print(f"Universe: {len(coins)} coins (>= {MIN_BARS} bars)")

    print("Precomputing indicators (~30s)...")
    indicators = _ms_indicators.precompute_ms_indicators(data, coins)

    # Get ms_018 config
    configs = _ms_hypotheses.build_sweep_configs()
    ms_018 = [c for c in configs if "018" in c["id"]][0]
    print(f"Config: {ms_018['id']} ({ms_018['label']})")

    # Run baseline backtest
    print("Running baseline backtest...")
    bt = _sprint3_engine.run_backtest(
        data=data, coins=coins,
        signal_fn=ms_018["signal_fn"], params=ms_018["params"],
        indicators=indicators, exit_mode="dc", start_bar=START_BAR,
    )

    trades = bt.trade_list
    print(f"\n  BASELINE: {bt.trades} trades | PF={bt.pf:.2f} | WR={bt.wr:.1f}% "
          f"| P&L=${bt.pnl:+,.0f} | DD={bt.dd:.1f}%")
    baseline_pf = bt.pf

    # Enrich trades with timestamps
    enrich_trades_with_time(trades, data)

    # ═══════════════════════════════════════════════════════════════
    # H1: WEEKEND FILTER
    # Falsificatie: PF-weekend ≤ PF-doordeweeks → verwerpen
    # ═══════════════════════════════════════════════════════════════

    weekend_groups = {"Weekend (Fri-Sun)": [], "Weekday (Mon-Thu)": []}
    for t in trades:
        if t["_weekday"] in (4, 5, 6):  # Fri, Sat, Sun
            weekend_groups["Weekend (Fri-Sun)"].append(t)
        else:
            weekend_groups["Weekday (Mon-Thu)"].append(t)

    h1_results = print_group_stats("H1: WEEKEND vs WEEKDAY", weekend_groups, baseline_pf)

    # Also per individual day
    day_groups = defaultdict(list)
    for t in trades:
        day_groups[f"{t['_weekday']}_{t['_day_name']}"].append(t)
    print_group_stats("H1 detail: per dag", day_groups, baseline_pf)

    # H1 verdict
    wk_end = [t for t in trades if t["_weekday"] in (4, 5, 6)]
    wk_day = [t for t in trades if t["_weekday"] in (0, 1, 2, 3)]
    pf_weekend = calc_pf(wk_end)
    pf_weekday = calc_pf(wk_day)
    h1_pass = pf_weekend > pf_weekday
    print(f"\n  H1 VERDICT: PF weekend={pf_weekend:.2f} vs weekday={pf_weekday:.2f}")
    print(f"  → {'OVERLEEFT — weekend entries zijn beter' if h1_pass else 'VERWORPEN — geen weekend edge'}")

    # ═══════════════════════════════════════════════════════════════
    # H2: TIME-OF-DAY ENTRY KWALITEIT
    # Falsificatie: PF vlak over alle 4H vensters → verwerpen
    # ═══════════════════════════════════════════════════════════════

    tod_groups = defaultdict(list)
    for t in trades:
        tod_groups[f"{t['_hour']:02d}:00 UTC"].append(t)

    h2_results = print_group_stats("H2: TIME-OF-DAY (4H entry window)", tod_groups, baseline_pf)

    # H2 verdict: is er significante variatie?
    pfs_by_hour = {}
    for name, trs in tod_groups.items():
        if len(trs) >= 10:  # minimum sample
            pfs_by_hour[name] = calc_pf(trs)

    if len(pfs_by_hour) >= 3:
        pf_vals = list(pfs_by_hour.values())
        pf_range = max(pf_vals) - min(pf_vals)
        pf_cv = statistics.stdev(pf_vals) / statistics.mean(pf_vals) if statistics.mean(pf_vals) > 0 else 0
        best_hour = max(pfs_by_hour, key=pfs_by_hour.get)
        worst_hour = min(pfs_by_hour, key=pfs_by_hour.get)
        h2_pass = pf_range > 0.5  # PF verschil >0.5 is materieel
        print(f"\n  H2 VERDICT: PF range={pf_range:.2f} (CV={pf_cv:.2f})")
        print(f"  Beste: {best_hour} PF={pfs_by_hour[best_hour]:.2f} | Slechtste: {worst_hour} PF={pfs_by_hour[worst_hour]:.2f}")
        print(f"  → {'OVERLEEFT — time-of-day maakt uit' if h2_pass else 'VERWORPEN — PF vlak over alle vensters'}")
    else:
        print(f"\n  H2 VERDICT: Onvoldoende data (< 3 vensters met ≥10 trades)")
        h2_pass = False

    # ═══════════════════════════════════════════════════════════════
    # H3: LIQUIDITEITS-QUINTIEL AMPLIFICATIE
    # Falsificatie: PF vlak over volume-quintielen → verwerpen
    # ═══════════════════════════════════════════════════════════════

    # Calculate average daily volume per coin
    coin_volumes = {}
    for pair in coins:
        coin_volumes[pair] = calc_avg_daily_volume(data, pair)

    # Assign quintile per coin
    sorted_coins = sorted(coins, key=lambda p: coin_volumes[p])
    n = len(sorted_coins)
    quintile_map = {}
    for i, pair in enumerate(sorted_coins):
        q = min(4, i * 5 // n)  # 0-4
        quintile_map[pair] = q

    vol_groups = defaultdict(list)
    quintile_labels = {0: "Q1 (laagst volume)", 1: "Q2", 2: "Q3", 3: "Q4", 4: "Q5 (hoogst volume)"}
    for t in trades:
        q = quintile_map.get(t["pair"], -1)
        if q >= 0:
            vol_groups[quintile_labels[q]].append(t)

    h3_results = print_group_stats("H3: LIQUIDITEITS-QUINTIELEN", vol_groups, baseline_pf)

    # H3 verdict: monotoon dalend van Q1 naar Q5?
    q_pfs = {}
    for q in range(5):
        label = quintile_labels[q]
        trs = vol_groups.get(label, [])
        if len(trs) >= 10:
            q_pfs[q] = calc_pf(trs)

    if len(q_pfs) >= 4:
        # Check if low-volume has higher PF than high-volume
        q_vals = [q_pfs[q] for q in sorted(q_pfs.keys())]
        monotone_score = sum(1 for i in range(len(q_vals)-1) if q_vals[i] > q_vals[i+1])
        total_pairs = len(q_vals) - 1
        ratio_low_high = q_pfs.get(0, 0) / q_pfs.get(4, 1) if q_pfs.get(4, 1) > 0 else float("inf")
        h3_pass = ratio_low_high > 1.3  # Q1 PF > 130% van Q5 PF
        print(f"\n  H3 VERDICT: Q1/Q5 ratio={ratio_low_high:.2f} | Monotoon: {monotone_score}/{total_pairs}")
        print(f"  → {'OVERLEEFT — lage-liquiditeit versterkt edge' if h3_pass else 'VERWORPEN — geen liquiditeitseffect'}")
    else:
        print(f"\n  H3 VERDICT: Onvoldoende data (< 4 quintielen met ≥10 trades)")
        h3_pass = False

    # ═══════════════════════════════════════════════════════════════
    # H4: VOL_SCALE WRAPPER (post-hoc equity simulatie)
    # Falsificatie: DD niet lager OF PF daalt >20% → verwerpen
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  H4: VOL_SCALE WRAPPER (ATR-based position sizing)")
    print(f"{'='*70}")

    # Compute ATR14 percentile per coin per bar for position sizing
    # Simple vol_scale: scale = min(1.0, pctl_25 / current_atr14)
    # If current ATR is higher than usual → smaller position

    def get_atr14_at_bar(pair, bar, data_dict):
        """Get ATR14 at a given bar from raw candle data."""
        candles = data_dict[pair]
        if bar < 14:
            return None
        trs = []
        for i in range(bar - 13, bar + 1):
            h = candles[i]["high"]
            l = candles[i]["low"]
            c_prev = candles[i-1]["close"] if i > 0 else candles[i]["open"]
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            trs.append(tr)
        return sum(trs) / 14

    # Build ATR14 history per coin for percentile calculation
    print("  Computing ATR14 percentiles per coin...")
    coin_atr_histories = {}
    for pair in coins:
        candles = data[pair]
        atrs = []
        for bar in range(14, len(candles)):
            atr = get_atr14_at_bar(pair, bar, data)
            if atr and atr > 0:
                atrs.append(atr)
        if atrs:
            atrs_sorted = sorted(atrs)
            pctl_25 = atrs_sorted[len(atrs_sorted) // 4]  # 25th percentile
            coin_atr_histories[pair] = {"atrs": atrs, "pctl_25": pctl_25}

    # Simulate vol_scale on trades
    base_size = 2000  # $2000 per trade
    initial_equity = 2000

    # Baseline equity curve (no vol_scale)
    trades_sorted = sorted(trades, key=lambda x: x["entry_bar"])

    baseline_equity = initial_equity
    baseline_peak = baseline_equity
    baseline_max_dd = 0
    for t in trades_sorted:
        baseline_equity += t["pnl"]
        baseline_peak = max(baseline_peak, baseline_equity)
        dd = (baseline_peak - baseline_equity) / baseline_peak if baseline_peak > 0 else 0
        baseline_max_dd = max(baseline_max_dd, dd)

    # Vol_scale equity curve
    vol_equity = initial_equity
    vol_peak = vol_equity
    vol_max_dd = 0
    vol_pnl_total = 0
    vol_gross_profit = 0
    vol_gross_loss = 0
    vol_scales_used = []

    for t in trades_sorted:
        pair = t["pair"]
        bar = t["entry_bar"]

        # Compute scale factor
        atr_now = get_atr14_at_bar(pair, bar, data)
        atr_info = coin_atr_histories.get(pair)

        if atr_now and atr_info and atr_now > 0:
            scale = min(1.0, atr_info["pctl_25"] / atr_now)
        else:
            scale = 1.0

        vol_scales_used.append(scale)

        # Scale the P&L proportionally
        scaled_pnl = t["pnl"] * scale
        vol_pnl_total += scaled_pnl

        if scaled_pnl > 0:
            vol_gross_profit += scaled_pnl
        else:
            vol_gross_loss += abs(scaled_pnl)

        vol_equity += scaled_pnl
        vol_peak = max(vol_peak, vol_equity)
        dd = (vol_peak - vol_equity) / vol_peak if vol_peak > 0 else 0
        vol_max_dd = max(vol_max_dd, dd)

    vol_pf = vol_gross_profit / vol_gross_loss if vol_gross_loss > 0 else float("inf")

    print(f"\n  {'Metric':<25} {'Baseline':>12} {'Vol_Scale':>12} {'Delta':>12}")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12}")
    print(f"  {'PF':<25} {bt.pf:>12.2f} {vol_pf:>12.2f} {vol_pf - bt.pf:>+12.2f}")
    print(f"  {'P&L':<25} {'$'+f'{bt.pnl:+,.0f}':>12} {'$'+f'{vol_pnl_total:+,.0f}':>12} {'$'+f'{vol_pnl_total - bt.pnl:+,.0f}':>12}")
    print(f"  {'Max DD %':<25} {baseline_max_dd*100:>11.1f}% {vol_max_dd*100:>11.1f}% {(vol_max_dd - baseline_max_dd)*100:>+11.1f}%")

    if vol_scales_used:
        avg_scale = statistics.mean(vol_scales_used)
        med_scale = statistics.median(vol_scales_used)
        print(f"\n  Scale stats: mean={avg_scale:.3f}, median={med_scale:.3f}, "
              f"min={min(vol_scales_used):.3f}, max={max(vol_scales_used):.3f}")

    pf_drop_pct = (bt.pf - vol_pf) / bt.pf * 100 if bt.pf > 0 else 0
    dd_reduction = baseline_max_dd - vol_max_dd
    h4_pass = dd_reduction > 0.02 and pf_drop_pct < 20  # DD lager EN PF niet >20% gedaald

    print(f"\n  H4 VERDICT: DD reductie={dd_reduction*100:+.1f}pp | PF verandering={-pf_drop_pct:+.1f}%")
    print(f"  → {'OVERLEEFT — DD lager zonder grote PF-daling' if h4_pass else 'VERWORPEN — DD niet lager of PF te veel gedaald'}")

    # ═══════════════════════════════════════════════════════════════
    # SAMENVATTING
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'='*70}")
    print(f"  TIER 1 SAMENVATTING")
    print(f"{'='*70}")
    verdicts = [
        ("H1: Weekend filter", h1_pass),
        ("H2: Time-of-day", h2_pass),
        ("H3: Liquiditeits-quintiel", h3_pass),
        ("H4: Vol_scale wrapper", h4_pass),
    ]
    for name, passed in verdicts:
        status = "✅ OVERLEEFT" if passed else "❌ VERWORPEN"
        print(f"  {status}  {name}")

    survivors = sum(1 for _, p in verdicts if p)
    print(f"\n  {survivors}/4 hypotheses overleven eerste falsificatie-test")
    if survivors > 0:
        print(f"  → Volgende stap: combinatie-test van overlevende hypotheses")
    else:
        print(f"  → Geen Tier 1 hypotheses overleven. Door naar Tier 2.")

    # Save results
    output_path = Path(__file__).parent.parent / "reports" / "tier1_hypotheses_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = {
        "baseline": {"trades": bt.trades, "pf": bt.pf, "wr": bt.wr, "pnl": bt.pnl, "dd": bt.dd},
        "h1_weekend": {
            "pf_weekend": pf_weekend, "pf_weekday": pf_weekday,
            "trades_weekend": len(wk_end), "trades_weekday": len(wk_day),
            "verdict": "PASS" if h1_pass else "FAIL",
        },
        "h2_time_of_day": {
            "pfs_by_hour": {k: round(v, 3) for k, v in pfs_by_hour.items()},
            "verdict": "PASS" if h2_pass else "FAIL",
        },
        "h3_liquidity": {
            "pfs_by_quintile": {f"Q{q+1}": round(q_pfs.get(q, 0), 3) for q in range(5)},
            "verdict": "PASS" if h3_pass else "FAIL",
        },
        "h4_vol_scale": {
            "baseline_pf": round(bt.pf, 3), "vol_pf": round(vol_pf, 3),
            "baseline_dd": round(baseline_max_dd * 100, 1),
            "vol_dd": round(vol_max_dd * 100, 1),
            "pf_drop_pct": round(pf_drop_pct, 1),
            "dd_reduction_pp": round(dd_reduction * 100, 1),
            "verdict": "PASS" if h4_pass else "FAIL",
        },
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Resultaten opgeslagen: {output_path}")


if __name__ == "__main__":
    main()
