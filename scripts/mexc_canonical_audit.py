#!/usr/bin/env python3
"""
MEXC Canonical Audit — Where is the MEXC edge (if any)?

MEXC is the deployment venue. Kraken results are discovery signals only.
This script answers: is ms_018 / ms_005 deployment-worthy on MEXC?

Tests:
  A1. Halal whitelist classification — overlap vs MEXC-only vs Kraken-only
  A2. MEXC full-universe per-coin edge map (ms_018 + ms_005)
  A3. MEXC profitable subset extraction — is there ANY MEXC subset with PF > 1.0?
  A4. Halal whitelist backtest on MEXC data — what does the live universe actually produce?
  A5. Verdict — deployment-worthy or NO-GO
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── repo setup ──────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "trading_bot"))
sys.path.insert(0, str(REPO))  # must be first — strategies.ms lives here

import importlib  # noqa: E402
_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_hyp = importlib.import_module("strategies.ms.hypotheses")
_ms_ind = importlib.import_module("strategies.ms.indicators")

_data_resolver = importlib.import_module("strategies.4h.data_resolver")

run_backtest = _engine.run_backtest
KRAKEN_FEE = _engine.KRAKEN_FEE
START_BAR = _engine.START_BAR
build_sweep_configs = _ms_hyp.build_sweep_configs
precompute_ms_indicators = _ms_ind.precompute_ms_indicators
resolve_dataset = _data_resolver.resolve_dataset

# ── data identifiers ────────────────────────────────────────────
KRAKEN_DATASET = "4h_default"
MEXC_DATASET = "ohlcv_4h_mexc_spot_usdt_v2"
HALAL_FILE = REPO / "trading_bot" / "halal_coins.txt"
REPORT_DIR = REPO / "reports" / "ms"

MEXC_FEE = 0.001  # 10 bps/side


def load_candle_data(dataset_id: str) -> dict:
    path = resolve_dataset(dataset_id)
    with open(path) as f:
        return json.load(f)


def load_halal_coins() -> list[str]:
    coins = []
    with open(HALAL_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            coins.append(line)
    return coins


def get_config(config_id: str) -> tuple:
    """Return (signal_fn, params) for a config."""
    all_configs = build_sweep_configs()
    for cfg in all_configs:
        if cfg["id"] == config_id:
            return cfg["signal_fn"], cfg["params"]
    raise ValueError(f"Config {config_id} not found")


def coins_from_data(data: dict, min_bars: int = 360) -> list[str]:
    out = []
    for pair, candles in data.items():
        if not isinstance(candles, list):
            continue
        if len(candles) >= min_bars:
            out.append(pair)
    return sorted(out)


def align_mexc_to_kraken_window(mexc_data: dict, kraken_data: dict) -> dict:
    """Trim MEXC candles to match Kraken's time window."""
    # Find Kraken's time bounds
    kr_min_ts, kr_max_ts = float("inf"), 0
    for pair, candles in kraken_data.items():
        if not isinstance(candles, list) or len(candles) < 10:
            continue
        for c in candles:
            ts = c.get("timestamp", c.get("t", 0))
            if ts > 0:
                kr_min_ts = min(kr_min_ts, ts)
                kr_max_ts = max(kr_max_ts, ts)
    if kr_min_ts == float("inf"):
        return mexc_data

    aligned = {}
    for pair, candles in mexc_data.items():
        if not isinstance(candles, list):
            continue
        trimmed = [c for c in candles
                    if kr_min_ts <= c.get("timestamp", c.get("t", 0)) <= kr_max_ts]
        if len(trimmed) >= 50:
            aligned[pair] = trimmed
    return aligned


def run_on_universe(data: dict, coins: list[str], signal_fn, params: dict,
                    fee: float, label: str) -> dict:
    """Run backtest and return per-coin results + aggregate."""
    indicators = precompute_ms_indicators(data, coins)
    result = run_backtest(
        data, coins, signal_fn, params, indicators,
        exit_mode="dc", fee=fee, start_bar=START_BAR,
    )

    # Per-coin breakdown
    coin_stats = {}
    for t in result.trade_list:
        pair = t["pair"]
        if pair not in coin_stats:
            coin_stats[pair] = {"trades": 0, "gross_win": 0.0, "gross_loss": 0.0,
                                "pnl": 0.0, "wins": 0}
        coin_stats[pair]["trades"] += 1
        coin_stats[pair]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            coin_stats[pair]["gross_win"] += t["pnl"]
            coin_stats[pair]["wins"] += 1
        else:
            coin_stats[pair]["gross_loss"] += abs(t["pnl"])

    for pair, s in coin_stats.items():
        s["pf"] = (s["gross_win"] / s["gross_loss"]
                   if s["gross_loss"] > 0
                   else (99.99 if s["gross_win"] > 0 else 0.0))
        s["wr"] = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0.0

    return {
        "label": label,
        "n_coins": len(coins),
        "n_coins_traded": len(coin_stats),
        "trades": result.trades,
        "pf": round(result.pf, 4),
        "wr": round(result.wr, 2),
        "pnl": round(result.pnl, 2),
        "dd": round(result.dd, 2),
        "coin_stats": coin_stats,
    }


def find_profitable_subsets(coin_stats: dict, min_trades: int = 3) -> dict:
    """Analyze if any natural subset of coins produces PF > 1.0."""
    # Filter coins with enough trades
    eligible = {p: s for p, s in coin_stats.items() if s["trades"] >= min_trades}

    # Sort by PF descending
    ranked = sorted(eligible.items(), key=lambda x: x[1]["pf"], reverse=True)

    # Progressive subset: add coins one-by-one from best to worst
    cumulative = []
    cum_win, cum_loss, cum_pnl = 0.0, 0.0, 0.0
    cum_trades = 0
    for pair, s in ranked:
        cum_win += s["gross_win"]
        cum_loss += s["gross_loss"]
        cum_pnl += s["pnl"]
        cum_trades += s["trades"]
        cum_pf = cum_win / cum_loss if cum_loss > 0 else 99.99
        cumulative.append({
            "n_coins": len(cumulative) + 1,
            "added": pair,
            "cum_pf": round(cum_pf, 4),
            "cum_pnl": round(cum_pnl, 2),
            "cum_trades": cum_trades,
        })

    # Find largest subset with PF >= 1.0
    best_pf_subset_size = 0
    best_pf_subset_pf = 0.0
    best_pf_subset_trades = 0
    for c in cumulative:
        if c["cum_pf"] >= 1.0:
            best_pf_subset_size = c["n_coins"]
            best_pf_subset_pf = c["cum_pf"]
            best_pf_subset_trades = c["cum_trades"]

    # Profitable coins
    profitable = [(p, s) for p, s in eligible.items() if s["pnl"] > 0]
    unprofitable = [(p, s) for p, s in eligible.items() if s["pnl"] <= 0]

    # Profitable-only aggregate
    prof_win = sum(s["gross_win"] for _, s in profitable)
    prof_loss = sum(s["gross_loss"] for _, s in profitable)
    prof_pnl = sum(s["pnl"] for _, s in profitable)
    prof_trades = sum(s["trades"] for _, s in profitable)
    prof_pf = prof_win / prof_loss if prof_loss > 0 else 99.99

    return {
        "eligible_coins": len(eligible),
        "profitable_coins": len(profitable),
        "unprofitable_coins": len(unprofitable),
        "profitable_only_pf": round(prof_pf, 4),
        "profitable_only_pnl": round(prof_pnl, 2),
        "profitable_only_trades": prof_trades,
        "best_pf_subset_size": best_pf_subset_size,
        "best_pf_subset_pf": round(best_pf_subset_pf, 4),
        "best_pf_subset_trades": best_pf_subset_trades,
        "cumulative_curve": cumulative[:20],  # top 20 for readability
        "top10_coins": [
            {"pair": p, "pf": round(s["pf"], 2), "trades": s["trades"],
             "pnl": round(s["pnl"], 2)}
            for p, s in sorted(eligible.items(), key=lambda x: x[1]["pnl"], reverse=True)[:10]
        ],
        "bottom10_coins": [
            {"pair": p, "pf": round(s["pf"], 2), "trades": s["trades"],
             "pnl": round(s["pnl"], 2)}
            for p, s in sorted(eligible.items(), key=lambda x: x[1]["pnl"])[:10]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="MEXC Canonical Audit")
    parser.add_argument("--config", default="ms_018_mse_shallow",
                        help="Config ID (default: ms_018_mse_shallow)")
    parser.add_argument("--also", default="ms_005_msb_base",
                        help="Secondary config (default: ms_005_msb_base)")
    args = parser.parse_args()

    print(f"\n{'=' * 72}")
    print(f"  MEXC CANONICAL AUDIT — {args.config}")
    print(f"  Secondary: {args.also}")
    print(f"  MEXC is deployment venue. Kraken = discovery only.")
    print(f"{'=' * 72}\n")

    # ── Load data ─────────────────────────────────────────────
    print("[1/6] Loading datasets...")
    kraken_data = load_candle_data(KRAKEN_DATASET)
    mexc_data_raw = load_candle_data(MEXC_DATASET)

    kraken_coins = coins_from_data(kraken_data, min_bars=360)
    mexc_coins_raw = coins_from_data(mexc_data_raw, min_bars=360)

    # Align MEXC to Kraken time window
    mexc_data = align_mexc_to_kraken_window(mexc_data_raw, kraken_data)
    mexc_coins = coins_from_data(mexc_data, min_bars=50)

    print(f"  Kraken: {len(kraken_coins)} coins")
    print(f"  MEXC (aligned): {len(mexc_coins)} coins")

    # ── A1: Halal whitelist classification ────────────────────
    print("\n[2/6] A1: Halal whitelist classification...")
    halal_raw = load_halal_coins()

    # Normalize pairs for comparison
    kraken_bases = set()
    for p in kraken_coins:
        base = p.replace("/USD", "").replace("/USDT", "")
        kraken_bases.add(base)

    mexc_bases = set()
    for p in mexc_coins:
        base = p.replace("/USD", "").replace("/USDT", "")
        mexc_bases.add(base)

    halal_classification = []
    for coin_raw in halal_raw:
        base = coin_raw.replace("/USDT", "").replace("/USD", "")
        on_kraken = base in kraken_bases
        on_mexc = base in mexc_bases
        if on_kraken and on_mexc:
            cls = "overlap"
        elif on_mexc and not on_kraken:
            cls = "mexc_only"
        elif on_kraken and not on_mexc:
            cls = "kraken_only"
        else:
            cls = "neither"
        halal_classification.append({
            "coin": coin_raw, "base": base,
            "on_kraken": on_kraken, "on_mexc": on_mexc,
            "class": cls,
        })

    n_overlap = sum(1 for h in halal_classification if h["class"] == "overlap")
    n_mexc_only = sum(1 for h in halal_classification if h["class"] == "mexc_only")
    n_kraken_only = sum(1 for h in halal_classification if h["class"] == "kraken_only")
    n_neither = sum(1 for h in halal_classification if h["class"] == "neither")

    print(f"  Halal coins: {len(halal_raw)}")
    print(f"  Overlap (both exchanges): {n_overlap}")
    print(f"  MEXC-only: {n_mexc_only}")
    print(f"  Kraken-only: {n_kraken_only}")
    print(f"  Neither: {n_neither}")
    print(f"\n  Classification:")
    for h in halal_classification:
        mark = {"overlap": "BOTH", "mexc_only": "MEXC", "kraken_only": "KRKN", "neither": "NONE"}
        print(f"    [{mark[h['class']]:4s}] {h['coin']}")

    a1_result = {
        "total": len(halal_raw),
        "overlap": n_overlap,
        "mexc_only": n_mexc_only,
        "kraken_only": n_kraken_only,
        "neither": n_neither,
        "coins": halal_classification,
    }

    # ── A2 + A3: MEXC full-universe per-coin edge map ─────────
    results = {}
    for config_id in [args.config, args.also]:
        print(f"\n[3/6] A2: MEXC full-universe backtest — {config_id}...")
        signal_fn, params = get_config(config_id)

        # Run on full MEXC universe
        mexc_result = run_on_universe(
            mexc_data, mexc_coins, signal_fn, params,
            fee=MEXC_FEE, label=f"MEXC_full_{config_id}",
        )
        print(f"  MEXC full: {mexc_result['trades']} trades, "
              f"PF={mexc_result['pf']}, P&L=${mexc_result['pnl']}, "
              f"DD={mexc_result['dd']}%")

        # A3: Profitable subset analysis
        print(f"\n[4/6] A3: Profitable subset extraction — {config_id}...")
        subset_analysis = find_profitable_subsets(mexc_result["coin_stats"])
        print(f"  Eligible coins (>=3 trades): {subset_analysis['eligible_coins']}")
        print(f"  Profitable coins: {subset_analysis['profitable_coins']}")
        print(f"  Profitable-only PF: {subset_analysis['profitable_only_pf']}")
        print(f"  Profitable-only trades: {subset_analysis['profitable_only_trades']}")
        print(f"  Largest PF>=1.0 subset: {subset_analysis['best_pf_subset_size']} coins "
              f"(PF={subset_analysis['best_pf_subset_pf']}, "
              f"{subset_analysis['best_pf_subset_trades']} trades)")

        print(f"\n  Top-10 coins by P&L:")
        for c in subset_analysis["top10_coins"]:
            print(f"    {c['pair']:20s} PF={c['pf']:6.2f}  trades={c['trades']:3d}  "
                  f"P&L=${c['pnl']:+.2f}")

        print(f"\n  Bottom-10 coins by P&L:")
        for c in subset_analysis["bottom10_coins"]:
            print(f"    {c['pair']:20s} PF={c['pf']:6.2f}  trades={c['trades']:3d}  "
                  f"P&L=${c['pnl']:+.2f}")

        # Cumulative curve (first 20)
        print(f"\n  Cumulative PF curve (adding coins best→worst):")
        for c in subset_analysis["cumulative_curve"]:
            marker = " <<<" if c["cum_pf"] >= 1.0 and (
                len(subset_analysis["cumulative_curve"]) <= 1
                or c["n_coins"] == subset_analysis["best_pf_subset_size"]
            ) else ""
            print(f"    n={c['n_coins']:3d}  PF={c['cum_pf']:6.4f}  "
                  f"P&L=${c['cum_pnl']:+.2f}  trades={c['cum_trades']}{marker}")

        # A4: Halal whitelist on MEXC
        print(f"\n[5/6] A4: Halal whitelist backtest on MEXC — {config_id}...")
        halal_mexc_pairs = []
        for h in halal_classification:
            if h["on_mexc"]:
                mexc_pair = f"{h['base']}/USDT"
                if mexc_pair in mexc_data and len(mexc_data.get(mexc_pair, [])) >= 50:
                    halal_mexc_pairs.append(mexc_pair)

        if halal_mexc_pairs:
            halal_result = run_on_universe(
                mexc_data, halal_mexc_pairs, signal_fn, params,
                fee=MEXC_FEE, label=f"MEXC_halal_{config_id}",
            )
            print(f"  Halal on MEXC ({len(halal_mexc_pairs)} coins): "
                  f"{halal_result['trades']} trades, PF={halal_result['pf']}, "
                  f"P&L=${halal_result['pnl']}, DD={halal_result['dd']}%")

            # Per-coin halal breakdown
            print(f"\n  Per-coin halal results:")
            for pair in sorted(halal_mexc_pairs):
                cs = halal_result["coin_stats"].get(pair)
                if cs:
                    print(f"    {pair:20s} PF={cs['pf']:6.2f}  trades={cs['trades']:3d}  "
                          f"P&L=${cs['pnl']:+.2f}  WR={cs['wr']:.0f}%")
                else:
                    print(f"    {pair:20s} — no trades")
        else:
            halal_result = {"trades": 0, "pf": 0, "pnl": 0, "dd": 0}
            print(f"  No halal coins available on MEXC with sufficient data")

        results[config_id] = {
            "mexc_full": {k: v for k, v in mexc_result.items() if k != "coin_stats"},
            "mexc_coin_count_profitable": subset_analysis["profitable_coins"],
            "mexc_coin_count_unprofitable": subset_analysis["unprofitable_coins"],
            "subset_analysis": {k: v for k, v in subset_analysis.items()
                                if k not in ("cumulative_curve",)},
            "cumulative_top20": subset_analysis["cumulative_curve"],
            "halal_mexc": {k: v for k, v in halal_result.items() if k != "coin_stats"},
            "halal_per_coin": {
                pair: {
                    "pf": round(s["pf"], 4),
                    "trades": s["trades"],
                    "pnl": round(s["pnl"], 2),
                    "wr": round(s["wr"], 1),
                }
                for pair, s in halal_result.get("coin_stats", {}).items()
            } if isinstance(halal_result, dict) and "coin_stats" in halal_result else {},
        }

    # ── A5: Verdict ───────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  A5: MEXC CANONICAL VERDICT")
    print(f"{'=' * 72}")

    for config_id, r in results.items():
        mexc_pf = r["mexc_full"]["pf"]
        mexc_pnl = r["mexc_full"]["pnl"]
        halal_pf = r["halal_mexc"].get("pf", 0)
        halal_pnl = r["halal_mexc"].get("pnl", 0)
        halal_trades = r["halal_mexc"].get("trades", 0)
        best_subset = r["subset_analysis"]["best_pf_subset_size"]
        best_subset_pf = r["subset_analysis"]["best_pf_subset_pf"]
        best_subset_trades = r["subset_analysis"]["best_pf_subset_trades"]
        prof_coins = r["mexc_coin_count_profitable"]
        total_eligible = r["subset_analysis"]["eligible_coins"]

        # Deployment verdict
        if halal_pf >= 1.0 and halal_trades >= 20:
            verdict = "CONDITIONAL_GO"
            reason = f"Halal PF={halal_pf} on {halal_trades} trades"
        elif mexc_pf >= 1.0:
            verdict = "CONDITIONAL_GO"
            reason = f"MEXC full PF={mexc_pf}"
        elif best_subset_pf >= 1.0 and best_subset_trades >= 30:
            verdict = "INVESTIGATE"
            reason = (f"Profitable subset exists: {best_subset} coins, "
                      f"PF={best_subset_pf}, {best_subset_trades} trades")
        else:
            verdict = "NO-GO"
            reason = (f"MEXC full PF={mexc_pf}, halal PF={halal_pf}, "
                      f"no viable subset found")

        print(f"\n  {config_id}:")
        print(f"    MEXC full:     PF={mexc_pf}, P&L=${mexc_pnl}, "
              f"{prof_coins}/{total_eligible} coins profitable")
        print(f"    Halal subset:  PF={halal_pf}, P&L=${halal_pnl}, "
              f"{halal_trades} trades")
        print(f"    Best subset:   {best_subset} coins, PF={best_subset_pf}, "
              f"{best_subset_trades} trades")
        print(f"    VERDICT:       {verdict}")
        print(f"    Reason:        {reason}")

    print(f"\n{'=' * 72}\n")

    # ── Save report ───────────────────────────────────────────
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "canonical_venue": "MEXC",
        "configs_tested": list(results.keys()),
        "a1_halal_classification": a1_result,
        "results": results,
    }
    out_path = REPORT_DIR / "mexc_canonical_audit.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report saved: {out_path}")


if __name__ == "__main__":
    main()
