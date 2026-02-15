#!/usr/bin/env python3
"""
ROLLING REGIME SWEEP - Long-term stability across rolling windows
=================================================================
Full horizon split into rolling windows (6x~20d on 721 bars).
Per window: trades, P&L, WR, PF, DD.
Also runs each window under 2x+20bps friction and 1-candle-later.

Stability: >=70% windows positive = STABLE, else UNSTABLE.

Artifacts:
  reports/rolling_regime_sweep.json
  reports/rolling_regime_sweep.md
"""
import sys, json, time, hashlib, math
from pathlib import Path
from datetime import datetime
from copy import deepcopy

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)

REPORTS_DIR = BASE_DIR.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

UNIVERSES = {
    "TRADEABLE": BASE_DIR.parent / "data" / "candle_cache_tradeable.json",
    "LIVE_CURRENT": BASE_DIR / "candle_cache_532.json",
}
EXPECTED_MD5 = {
    "TRADEABLE": "f6fd2ca303b677fe67ceede4a6b8f7ba",
    "LIVE_CURRENT": "3b1dba2eeb4d95ac68d0874b50de3d4d",
}

CONFIGS = {
    "C1": {
        "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
        "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15,
        "vol_confirm": True, "vol_spike_mult": 3.0,
    },
    "GRID_BEST": {
        "exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
        "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12,
        "vol_confirm": True, "vol_spike_mult": 2.5,
    },
}

# Fee regimes to test per window
FEE_REGIMES = {
    "baseline": KRAKEN_FEE,
    "2x_20bps": KRAKEN_FEE * 2 + 0.002,
    "1_candle_later": KRAKEN_FEE * 2 + 0.005,
}

STABLE_POS_PCT = 0.70


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_universe(path):
    with open(path) as f:
        data = json.load(f)
    coins = sorted(k for k in data if not k.startswith("_"))
    return data, coins


def build_rolling_windows(max_bars, n_windows=6):
    usable = max_bars - START_BAR
    window_size = usable // n_windows
    windows = []
    for i in range(n_windows):
        start = START_BAR + i * window_size
        end = START_BAR + (i + 1) * window_size if i < n_windows - 1 else max_bars
        days = (end - start) / 6
        windows.append({
            "window": "W%d" % (i + 1),
            "start": start, "end": end,
            "bars": end - start,
            "approx_days": round(days, 1),
        })
    return windows


def run_window_regimes(indicators, coins, cfg, start, end):
    results = {}
    for regime_name, fee in FEE_REGIMES.items():
        bt = run_backtest(indicators, coins, cfg,
                          start_bar=start, end_bar=end, fee_override=fee)
        results[regime_name] = {
            "trades": bt["trades"],
            "pnl": round(bt["pnl"], 2),
            "wr": round(bt["wr"], 1),
            "pf": round(min(bt["pf"], 999.99), 2),
            "dd": round(bt["dd"], 1),
        }
    return results


def calc_stability(window_results, regime="baseline"):
    pnls = [w["regimes"][regime]["pnl"] for w in window_results]
    trades = [w["regimes"][regime]["trades"] for w in window_results]
    dds = [w["regimes"][regime]["dd"] for w in window_results]

    n = len(pnls)
    n_pos = sum(1 for p in pnls if p > 0)
    pos_pct = round(n_pos / n * 100, 1) if n > 0 else 0
    worst_pnl = min(pnls) if pnls else 0
    worst_idx = pnls.index(worst_pnl) if pnls else -1
    max_dd = max(dds) if dds else 0
    mean_pnl = sum(pnls) / n if n > 0 else 0

    if n > 1 and mean_pnl != 0:
        var = sum((p - mean_pnl) ** 2 for p in pnls) / (n - 1)
        cv = round(abs(math.sqrt(var) / mean_pnl), 2)
    else:
        cv = float("inf")

    is_stable = (n_pos / n) >= STABLE_POS_PCT if n > 0 else False

    return {
        "regime": regime,
        "n_windows": n,
        "n_positive": n_pos,
        "positive_pct": pos_pct,
        "worst_pnl": round(worst_pnl, 2),
        "worst_window": "W%d" % (worst_idx + 1) if worst_idx >= 0 else "N/A",
        "max_dd": round(max_dd, 1),
        "mean_pnl": round(mean_pnl, 2),
        "cv": cv if cv != float("inf") else "inf",
        "total_trades": sum(trades),
        "min_trades": min(trades) if trades else 0,
        "max_trades": max(trades) if trades else 0,
        "stable": is_stable,
    }


def main():
    t_total = time.time()
    print("=" * 70)
    print("ROLLING REGIME SWEEP")
    print("=" * 70)

    all_results = {}

    for uname, upath in UNIVERSES.items():
        print("\n" + "=" * 60)
        print("UNIVERSE: %s" % uname)
        print("=" * 60)

        md5 = md5_file(upath)
        assert md5 == EXPECTED_MD5[uname], "MD5 mismatch"
        print("  MD5: %s OK" % md5)

        data, coins = load_universe(upath)
        max_bars = max(len(data[c]) for c in coins)
        print("  Coins: %d, Max bars: %d" % (len(coins), max_bars))

        print("  Precomputing...")
        t0 = time.time()
        indicators = precompute_all(data, coins)
        print("  Done in %.1fs" % (time.time() - t0))

        windows = build_rolling_windows(max_bars, n_windows=6)
        print("  Rolling windows: %d" % len(windows))
        for w in windows:
            print("    %s: bars [%d, %d) = %d bars (~%.0fd)" % (
                w["window"], w["start"], w["end"], w["bars"], w["approx_days"]))

        universe_results = {}

        for cname, cfg in CONFIGS.items():
            print("\n  --- %s ---" % cname)
            cfg_n = normalize_cfg(deepcopy(cfg))

            window_data = []
            for w in windows:
                regimes = run_window_regimes(indicators, coins, cfg_n, w["start"], w["end"])
                entry = {
                    "window": w["window"],
                    "start": w["start"], "end": w["end"],
                    "bars": w["bars"], "approx_days": w["approx_days"],
                    "regimes": regimes,
                }
                window_data.append(entry)

                bl = regimes["baseline"]
                fr = regimes["2x_20bps"]
                cl = regimes["1_candle_later"]
                print("    %s: %dtr $%7.0f WR%.0f%% DD%.0f%% | fric $%7.0f | 1c $%7.0f" % (
                    w["window"], bl["trades"], bl["pnl"], bl["wr"], bl["dd"],
                    fr["pnl"], cl["pnl"]))

            # Stability per regime
            stability = {}
            for regime in FEE_REGIMES:
                stability[regime] = calc_stability(window_data, regime)

            s = stability["baseline"]
            print("    Stability: %d/%d positive (%.0f%%), CV=%.2f, worst=$%.0f (%s)" % (
                s["n_positive"], s["n_windows"], s["positive_pct"],
                s["cv"] if isinstance(s["cv"], float) else 999,
                s["worst_pnl"], s["worst_window"]))
            print("    Verdict: %s" % ("STABLE" if s["stable"] else "UNSTABLE"))

            universe_results[cname] = {
                "config": cfg,
                "windows": window_data,
                "stability": stability,
            }

        all_results[uname] = {
            "cache_file": str(upath),
            "md5": md5,
            "n_coins": len(coins),
            "max_bars": max_bars,
            "n_windows": len(windows),
            "configs": universe_results,
        }

    elapsed = time.time() - t_total

    out = {
        "generated": datetime.now().isoformat(),
        "runtime_s": round(elapsed, 1),
        "fee_regimes": {k: round(v * 100, 3) for k, v in FEE_REGIMES.items()},
        "stable_threshold": STABLE_POS_PCT,
        "results": all_results,
    }

    json_path = REPORTS_DIR / "rolling_regime_sweep.json"
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved: %s" % json_path)

    md = generate_markdown(out)
    md_path = REPORTS_DIR / "rolling_regime_sweep.md"
    with open(md_path, "w") as f:
        f.write(md)
    print("Saved: %s" % md_path)

    print("\nTotal: %.1fs" % elapsed)


def generate_markdown(out):
    lines = [
        "# Rolling Regime Sweep Report",
        "",
        "**Generated**: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "**Runtime**: %.1fs" % out["runtime_s"],
        "**Fee Regimes**: baseline=%.3f%%, 2x+20bps=%.3f%%, 1-candle-later=%.3f%%" % (
            out["fee_regimes"]["baseline"],
            out["fee_regimes"]["2x_20bps"],
            out["fee_regimes"]["1_candle_later"]),
        "**Stable Threshold**: >= %.0f%% windows positive" % (out["stable_threshold"] * 100),
        "",
    ]

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Universe | Config | Windows | Pos% (base) | Pos% (fric) | Pos% (1c) | CV | Worst P&L | Max DD | Total Tr | Verdict |")
    lines.append("|----------|--------|---------|-------------|-------------|-----------|-----|-----------|--------|----------|---------|")

    for uname, ures in out["results"].items():
        for cname, cres in ures["configs"].items():
            sb = cres["stability"]["baseline"]
            sf = cres["stability"]["2x_20bps"]
            sc = cres["stability"]["1_candle_later"]
            verdict = "STABLE" if sb["stable"] else "UNSTABLE"
            lines.append(
                "| %s | %s | %d | %.0f%% | %.0f%% | %.0f%% | %s | $%s | %.1f%% | %d | **%s** |" % (
                    uname, cname, sb["n_windows"],
                    sb["positive_pct"], sf["positive_pct"], sc["positive_pct"],
                    sb["cv"],
                    "{:,.0f}".format(sb["worst_pnl"]),
                    sb["max_dd"], sb["total_trades"], verdict,
                )
            )
    lines.append("")

    # Detail per universe/config
    for uname, ures in out["results"].items():
        lines.append("---")
        lines.append("## Universe: %s" % uname)
        lines.append("")
        lines.append("- Cache: `%s`" % Path(ures["cache_file"]).name)
        lines.append("- MD5: `%s`" % ures["md5"])
        lines.append("- Coins: %d | Max bars: %d" % (ures["n_coins"], ures["max_bars"]))
        lines.append("")

        for cname, cres in ures["configs"].items():
            lines.append("### Config: %s" % cname)
            lines.append("")

            # Window table
            lines.append("| Window | Bars | ~Days | Tr(base) | P&L(base) | WR% | DD% | Tr(fric) | P&L(fric) | Tr(1c) | P&L(1c) |")
            lines.append("|--------|------|-------|----------|-----------|-----|-----|----------|-----------|--------|---------|")
            for w in cres["windows"]:
                bl = w["regimes"]["baseline"]
                fr = w["regimes"]["2x_20bps"]
                cl = w["regimes"]["1_candle_later"]
                lines.append(
                    "| %s | %d-%d | %.0f | %d | $%s | %.1f | %.1f | %d | $%s | %d | $%s |" % (
                        w["window"], w["start"], w["end"], w["approx_days"],
                        bl["trades"], "{:,.0f}".format(bl["pnl"]),
                        bl["wr"], bl["dd"],
                        fr["trades"], "{:,.0f}".format(fr["pnl"]),
                        cl["trades"], "{:,.0f}".format(cl["pnl"]),
                    )
                )
            lines.append("")

            # Stability
            lines.append("#### Stability")
            lines.append("")
            lines.append("| Regime | Pos% | Worst | Mean P&L | CV | Max DD | Trades(min/max) | Stable |")
            lines.append("|--------|------|-------|----------|-----|--------|-----------------|--------|")
            for regime in ["baseline", "2x_20bps", "1_candle_later"]:
                s = cres["stability"][regime]
                lines.append(
                    "| %s | %.0f%% | $%s (%s) | $%s | %s | %.1f%% | %d/%d | %s |" % (
                        regime, s["positive_pct"],
                        "{:,.0f}".format(s["worst_pnl"]), s["worst_window"],
                        "{:,.0f}".format(s["mean_pnl"]),
                        s["cv"], s["max_dd"],
                        s["min_trades"], s["max_trades"],
                        "YES" if s["stable"] else "NO",
                    )
                )
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
