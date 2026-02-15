#!/usr/bin/env python3
"""
LONG-HORIZON VALIDATION (max available = ~120d / 721 bars)
==========================================================
Full battery: WF(purged) + slippage ladder + 1-candle-later + jitter + MC ruin + Top1/Top3 share.
Per universe (TRADEABLE, LIVE_CURRENT) x config (C1, GRID_BEST).

Artifacts:
  reports/long_horizon_max.json
  reports/long_horizon_max.md
"""
import sys, json, time, hashlib, math, random
from pathlib import Path
from datetime import datetime
from copy import deepcopy

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)
from robustness_harness import purged_walk_forward

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

N_FOLDS = 5
EMBARGO = 2
FEE_MULTS = [1, 2, 3]
SLIPPAGE_BPS = [0, 10, 20, 35]
N_JITTER = 50
N_MC = 1000

# Decision thresholds
WF_GO = 4
WF_SOFT = 3
DD_MAX = 40.0
TOP1_MAX = 40.0


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


def slippage_ladder(indicators, coins, cfg):
    results = []
    for fm in FEE_MULTS:
        for sb in SLIPPAGE_BPS:
            eff = KRAKEN_FEE * fm + sb / 10_000
            bt = run_backtest(indicators, coins, cfg, fee_override=eff)
            results.append({
                "regime": "%dx_fees_%dbps" % (fm, sb),
                "fee_mult": fm, "slip_bps": sb,
                "eff_fee_pct": round(eff * 100, 3),
                "trades": bt["trades"], "pnl": round(bt["pnl"], 2),
                "wr": round(bt["wr"], 1), "pf": round(min(bt["pf"], 999.99), 2),
                "dd": round(bt["dd"], 1), "pass": bt["pnl"] > 0,
            })
    # 1-candle-later
    eff_1c = KRAKEN_FEE * 2 + 0.005
    bt = run_backtest(indicators, coins, cfg, fee_override=eff_1c)
    results.append({
        "regime": "1_candle_later",
        "fee_mult": 2, "slip_bps": 50,
        "eff_fee_pct": round(eff_1c * 100, 3),
        "trades": bt["trades"], "pnl": round(bt["pnl"], 2),
        "wr": round(bt["wr"], 1), "pf": round(min(bt["pf"], 999.99), 2),
        "dd": round(bt["dd"], 1), "pass": bt["pnl"] > 0,
    })
    return results


def friction_2x_20(ladder):
    r = next((x for x in ladder if x["fee_mult"] == 2 and x["slip_bps"] == 20
              and x["regime"] != "1_candle_later"), None)
    return r["pnl"] if r else 0


def candle_later_pnl(ladder):
    r = next((x for x in ladder if x["regime"] == "1_candle_later"), None)
    return r["pnl"] if r else 0


def jitter_test(indicators, coins, cfg, n=50):
    base_cfg = normalize_cfg(deepcopy(cfg))
    jitterable = {
        "tp_pct": (0.8, 1.2), "sl_pct": (0.8, 1.2),
        "vol_spike_mult": (0.85, 1.15), "rsi_max": (0.9, 1.1),
        "time_max_bars": (0.7, 1.3),
    }
    positive = 0
    rng = random.Random(42)
    for _ in range(n):
        jcfg = deepcopy(base_cfg)
        for param, (lo, hi) in jitterable.items():
            if param in jcfg:
                val = jcfg[param]
                jcfg[param] = type(val)(val * rng.uniform(lo, hi))
                if param == "rsi_max":
                    jcfg[param] = max(20, min(80, jcfg[param]))
                if param == "time_max_bars":
                    jcfg[param] = max(3, jcfg[param])
        bt = run_backtest(indicators, coins, jcfg)
        if bt["pnl"] > 0:
            positive += 1
    return round(positive / n * 100, 1)


def mc_ruin(indicators, coins, cfg, n_shuffles=1000):
    bt = run_backtest(indicators, coins, cfg)
    trade_pnls = [t["pnl"] for t in bt.get("trade_list", [])]
    if len(trade_pnls) < 5:
        return 0.0, trade_pnls
    ruin_count = 0
    rng = random.Random(42)
    for _ in range(n_shuffles):
        shuffled = list(trade_pnls)
        rng.shuffle(shuffled)
        equity = INITIAL_CAPITAL
        peak = equity
        for p in shuffled:
            equity += p
            if equity <= 0:
                ruin_count += 1
                break
            peak = max(peak, equity)
    return round(ruin_count / n_shuffles * 100, 1), trade_pnls


def top_shares(trade_pnls):
    if not trade_pnls:
        return 0.0, 0.0
    total_profit = sum(max(0, p) for p in trade_pnls)
    if total_profit <= 0:
        return 0.0, 0.0
    sorted_pnls = sorted(trade_pnls, reverse=True)
    top1 = min(1.0, max(0, sorted_pnls[0]) / total_profit) * 100 if len(sorted_pnls) >= 1 else 0
    top3_sum = sum(max(0, sorted_pnls[i]) for i in range(min(3, len(sorted_pnls))))
    top3 = min(1.0, top3_sum / total_profit) * 100
    return round(top1, 1), round(top3, 1)


def decide(wf_pass, fric_2x20, candle_pnl, dd, top1):
    if wf_pass >= WF_GO and fric_2x20 > 0 and candle_pnl > 0 and dd < DD_MAX and top1 < TOP1_MAX:
        return "GO"
    if wf_pass >= WF_SOFT and fric_2x20 > 0 and dd < DD_MAX:
        return "SOFT-GO"
    return "NO-GO"


def main():
    t_total = time.time()
    print("=" * 70)
    print("LONG-HORIZON VALIDATION (max available ~120d / 721 bars)")
    print("=" * 70)

    all_results = {}

    for uname, upath in UNIVERSES.items():
        print("\n" + "=" * 60)
        print("UNIVERSE: %s" % uname)
        print("=" * 60)

        md5 = md5_file(upath)
        expected = EXPECTED_MD5[uname]
        assert md5 == expected, "MD5 mismatch: %s != %s" % (md5, expected)
        print("  MD5: %s OK" % md5)

        data, coins = load_universe(upath)
        max_bars = max(len(data[c]) for c in coins)
        actual_days = (max_bars - START_BAR) / 6
        print("  Coins: %d, Max bars: %d, Usable: %d bars (~%.0fd)" % (
            len(coins), max_bars, max_bars - START_BAR, actual_days))

        print("  Precomputing...")
        t0 = time.time()
        indicators = precompute_all(data, coins)
        print("  Done in %.1fs" % (time.time() - t0))

        universe_results = {}

        for cname, cfg in CONFIGS.items():
            print("\n  --- %s ---" % cname)
            cfg_n = normalize_cfg(deepcopy(cfg))

            # Baseline full-run
            bt = run_backtest(indicators, coins, cfg_n)
            trades = bt["trades"]
            pnl = round(bt["pnl"], 2)
            wr = round(bt["wr"], 1)
            pf = round(min(bt["pf"], 999.99), 2)
            dd = round(bt["dd"], 1)
            trade_pnls = [t["pnl"] for t in bt.get("trade_list", [])]
            print("    Baseline: %d trades, $%.2f P&L, %.1f%% WR, PF %.2f, DD %.1f%%" % (
                trades, pnl, wr, pf, dd))

            # WF purged
            print("    Walk-Forward (purged, %d-fold, embargo=%d)..." % (N_FOLDS, EMBARGO))
            wf = purged_walk_forward(indicators, coins, cfg_n, n_folds=N_FOLDS, embargo=EMBARGO)
            wf_pass = wf["passed_folds"]
            wf_label = wf["wf_label"]
            wf_total_pnl = round(sum(f["test_pnl"] for f in wf["folds"]), 2)
            wf_folds = []
            for f in wf["folds"]:
                wf_folds.append({
                    "fold": f["fold"],
                    "test_bars": f["test_bars"],
                    "test_trades": f["test_trades"],
                    "test_pnl": round(f["test_pnl"], 2),
                    "test_wr": f["test_wr"],
                    "test_dd": f["test_dd"],
                    "pass": f["pass"],
                })
            print("    WF: %s, total test P&L: $%.2f" % (wf_label, wf_total_pnl))

            # Slippage ladder
            print("    Slippage ladder...")
            ladder = slippage_ladder(indicators, coins, cfg_n)
            fric = friction_2x_20(ladder)
            candle = candle_later_pnl(ladder)
            print("    Friction(2x+20bps): $%.2f, 1-candle: $%.2f" % (fric, candle))

            # Jitter
            print("    Jitter (%d variants)..." % N_JITTER)
            jitter_pct = jitter_test(indicators, coins, cfg_n, n=N_JITTER)
            print("    Jitter: %.1f%% positive" % jitter_pct)

            # MC ruin
            print("    MC ruin (%d shuffles)..." % N_MC)
            mc_pct, _ = mc_ruin(indicators, coins, cfg_n, n_shuffles=N_MC)
            print("    MC ruin: %.1f%%" % mc_pct)

            # Top shares
            top1, top3 = top_shares(trade_pnls)
            print("    Top1 share: %.1f%%, Top3 share: %.1f%%" % (top1, top3))

            # Decision
            verdict = decide(wf_pass, fric, candle, dd, top1)
            print("    VERDICT: %s" % verdict)

            universe_results[cname] = {
                "config": cfg,
                "actual_days": round(actual_days, 1),
                "max_bars": max_bars,
                "usable_bars": max_bars - START_BAR,
                "baseline": {
                    "trades": trades, "pnl": pnl, "wr": wr,
                    "pf": pf, "dd": dd,
                },
                "wf": {
                    "n_folds": N_FOLDS, "embargo": EMBARGO,
                    "passed": wf_pass, "label": wf_label,
                    "total_test_pnl": wf_total_pnl,
                    "folds": wf_folds,
                },
                "slippage_ladder": ladder,
                "friction_2x_20bps": fric,
                "candle_later_pnl": candle,
                "jitter_pct_positive": jitter_pct,
                "mc_ruin_pct": mc_pct,
                "top1_share": top1,
                "top3_share": top3,
                "verdict": verdict,
            }

        all_results[uname] = {
            "cache_file": str(upath),
            "md5": md5,
            "n_coins": len(coins),
            "max_bars": max_bars,
            "actual_days": round(actual_days, 1),
            "configs": universe_results,
        }

    elapsed = time.time() - t_total

    # Find best
    best = None
    best_score = -9999
    for uname, ures in all_results.items():
        for cname, cres in ures["configs"].items():
            if cres["verdict"] == "GO":
                score = cres["baseline"]["pnl"]
                if score > best_score:
                    best_score = score
                    best = (uname, cname)

    # Save JSON
    out = {
        "generated": datetime.now().isoformat(),
        "runtime_s": round(elapsed, 1),
        "target_horizon": "365d",
        "actual_horizon": "~%.0fd (max available)" % all_results[list(all_results.keys())[0]]["actual_days"],
        "results": all_results,
        "best_long_term": {
            "universe": best[0] if best else None,
            "config": best[1] if best else None,
            "verdict": "GO" if best else "NO CANDIDATE",
        },
    }

    json_path = REPORTS_DIR / "long_horizon_max.json"
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nSaved: %s" % json_path)

    # Generate MD
    md = generate_markdown(out)
    md_path = REPORTS_DIR / "long_horizon_max.md"
    with open(md_path, "w") as f:
        f.write(md)
    print("Saved: %s" % md_path)

    print("\nTotal: %.1fs" % elapsed)
    return out


def generate_markdown(out):
    lines = [
        "# Long-Horizon Validation Report",
        "",
        "**Generated**: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "**Target**: 365d | **Actual**: %s" % out["actual_horizon"],
        "**Runtime**: %.1fs" % out["runtime_s"],
        "",
    ]

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Universe | Config | Days | Trades | P&L | WR% | PF | DD% | WF | Fric2x20 | 1-candle | Jitter% | MC ruin | Top1% | Top3% | Verdict |")
    lines.append("|----------|--------|------|--------|-----|-----|-----|-----|-----|----------|---------|---------|---------|-------|-------|---------|")

    for uname, ures in out["results"].items():
        for cname, c in ures["configs"].items():
            b = c["baseline"]
            lines.append(
                "| %s | %s | %.0f | %d | $%s | %.1f | %.2f | %.1f | %s | $%s | $%s | %.0f%% | %.1f%% | %.1f%% | %.1f%% | **%s** |" % (
                    uname, cname, c["actual_days"],
                    b["trades"], "{:,.0f}".format(b["pnl"]), b["wr"], b["pf"], b["dd"],
                    c["wf"]["label"],
                    "{:,.0f}".format(c["friction_2x_20bps"]),
                    "{:,.0f}".format(c["candle_later_pnl"]),
                    c["jitter_pct_positive"], c["mc_ruin_pct"],
                    c["top1_share"], c["top3_share"],
                    c["verdict"],
                )
            )
    lines.append("")

    # Decision thresholds
    lines.append("## Decision Thresholds")
    lines.append("")
    lines.append("| Gate | Threshold |")
    lines.append("|------|-----------|")
    lines.append("| WF (GO) | >= %d/%d folds |" % (WF_GO, N_FOLDS))
    lines.append("| WF (SOFT-GO) | >= %d/%d folds |" % (WF_SOFT, N_FOLDS))
    lines.append("| Friction(2x+20bps) | > $0 |")
    lines.append("| 1-candle-later | > $0 (for GO) |")
    lines.append("| Max DD | < %.0f%% |" % DD_MAX)
    lines.append("| Top1 share | < %.0f%% |" % TOP1_MAX)
    lines.append("")

    # Per universe/config detail
    for uname, ures in out["results"].items():
        lines.append("---")
        lines.append("## Universe: %s" % uname)
        lines.append("")
        lines.append("- Cache: `%s`" % Path(ures["cache_file"]).name)
        lines.append("- MD5: `%s`" % ures["md5"])
        lines.append("- Coins: %d | Max bars: %d | ~%.0fd" % (
            ures["n_coins"], ures["max_bars"], ures["actual_days"]))
        lines.append("")

        for cname, c in ures["configs"].items():
            lines.append("### Config: %s — [%s]" % (cname, c["verdict"]))
            lines.append("```json")
            lines.append(json.dumps(c["config"], indent=2))
            lines.append("```")
            lines.append("")

            # WF folds
            lines.append("#### Walk-Forward (%s)" % c["wf"]["label"])
            lines.append("")
            lines.append("| Fold | Test Bars | Trades | P&L | WR% | DD% | Pass |")
            lines.append("|------|-----------|--------|-----|-----|-----|------|")
            for f in c["wf"]["folds"]:
                lines.append("| %d | %s | %d | $%s | %.1f | %.1f | %s |" % (
                    f["fold"], f["test_bars"], f["test_trades"],
                    "{:,.2f}".format(f["test_pnl"]), f["test_wr"], f["test_dd"],
                    "PASS" if f["pass"] else "FAIL"))
            lines.append("")

            # Slippage ladder
            lines.append("#### Slippage Ladder")
            lines.append("")
            lines.append("| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass |")
            lines.append("|--------|---------|--------|-----|-----|----|-----|------|")
            for r in c["slippage_ladder"]:
                lbl = "**1-candle-later**" if r["regime"] == "1_candle_later" else r["regime"]
                lines.append("| %s | %.3f%% | %d | $%s | %.1f | %.2f | %.1f | %s |" % (
                    lbl, r["eff_fee_pct"], r["trades"],
                    "{:,.2f}".format(r["pnl"]), r["wr"], r["pf"], r["dd"],
                    "PASS" if r["pass"] else "FAIL"))
            lines.append("")

    # Best
    b = out["best_long_term"]
    lines.append("---")
    lines.append("## Decision Line")
    lines.append("")
    if b["universe"]:
        lines.append("**BEST LONG-TERM: %s + %s → %s**" % (b["universe"], b["config"], b["verdict"]))
        best_cfg = out["results"][b["universe"]]["configs"][b["config"]]["config"]
        lines.append("")
        lines.append("```")
        lines.append("python trading_bot/paper_backfill_v4.py --hours 168 --config %s" % b["config"].lower())
        lines.append("```")
    else:
        lines.append("**NO GO CANDIDATE FOUND**")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
