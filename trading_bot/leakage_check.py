#!/usr/bin/env python3
"""
LEAKAGE / PURGE SANITY CHECK
=============================
Compares purged walk-forward (embargo=2) vs no-purge control (embargo=0)
side-by-side for multiple configs and universes.

If removing the purge materially improves results (>20% delta),
it indicates look-ahead leakage in the backtest engine.

Artifacts:
  - reports/leakage_check.json  (full data)
  - reports/leakage_check.md    (side-by-side markdown table)
"""
import sys
import json
import time
import hashlib
from pathlib import Path
from copy import deepcopy
from datetime import datetime

BASE_DIR = Path(__file__).parent
PROJECT_DIR = BASE_DIR.parent
REPORTS_DIR = PROJECT_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)
from robustness_harness import purged_walk_forward

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

UNIVERSES = {
    "LIVE_CURRENT": BASE_DIR / "candle_cache_532.json",
    "TRADEABLE": PROJECT_DIR / "data" / "candle_cache_tradeable.json",
}

EXPECTED_MD5 = {
    "LIVE_CURRENT": "3b1dba2eeb4d95ac68d0874b50de3d4d",
    "TRADEABLE": "f6fd2ca303b677fe67ceede4a6b8f7ba",
}

N_FOLDS = 5
EMBARGO_PURGED = 2
EMBARGO_NOPURGE = 0
LEAKAGE_THRESHOLD_PCT = 20.0


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_universe(path):
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins


def run_wf_pair(indicators, coins, cfg, n_folds=5):
    cfg = normalize_cfg(deepcopy(cfg))

    t0 = time.time()
    purged = purged_walk_forward(indicators, coins, cfg,
                                 n_folds=n_folds, embargo=EMBARGO_PURGED)
    t_purged = time.time() - t0

    t0 = time.time()
    nopurge = purged_walk_forward(indicators, coins, cfg,
                                  n_folds=n_folds, embargo=EMBARGO_NOPURGE)
    t_nopurge = time.time() - t0

    purged_total_pnl = sum(f["test_pnl"] for f in purged["folds"])
    nopurge_total_pnl = sum(f["test_pnl"] for f in nopurge["folds"])

    if abs(purged_total_pnl) > 0.01:
        leakage_delta_pct = ((nopurge_total_pnl - purged_total_pnl)
                             / abs(purged_total_pnl) * 100)
    else:
        leakage_delta_pct = 0.0

    verdict = ("LEAKAGE WARNING" if leakage_delta_pct > LEAKAGE_THRESHOLD_PCT
               else "CLEAN")

    return {
        "purged": {
            "embargo": EMBARGO_PURGED,
            "passed_folds": purged["passed_folds"],
            "wf_label": purged["wf_label"],
            "total_test_pnl": round(purged_total_pnl, 2),
            "max_test_dd": purged["max_test_dd"],
            "folds": purged["folds"],
            "time_s": round(t_purged, 2),
        },
        "nopurge": {
            "embargo": EMBARGO_NOPURGE,
            "passed_folds": nopurge["passed_folds"],
            "wf_label": nopurge["wf_label"],
            "total_test_pnl": round(nopurge_total_pnl, 2),
            "max_test_dd": nopurge["max_test_dd"],
            "folds": nopurge["folds"],
            "time_s": round(t_nopurge, 2),
        },
        "leakage_delta_pct": round(leakage_delta_pct, 2),
        "verdict": verdict,
    }


def format_fold_comparison(purged_folds, nopurge_folds):
    out = []
    out.append("| Fold | Purged Test P&L | NoPurge Test P&L | Delta | Purged WR | NoPurge WR |")
    out.append("|------|-----------------|------------------|-------|-----------|------------|")
    for pf, nf in zip(purged_folds, nopurge_folds):
        delta = nf["test_pnl"] - pf["test_pnl"]
        sign = "+" if delta >= 0 else ""
        out.append(
            "| {} | ${:,.2f} | ${:,.2f} | {}${:,.2f} | {}% | {}% |".format(
                pf["fold"], pf["test_pnl"], nf["test_pnl"],
                sign, delta, pf["test_wr"], nf["test_wr"]
            )
        )
    return chr(10).join(out)


def main():
    print("=" * 70)
    print("LEAKAGE / PURGE SANITY CHECK")
    print("Timestamp: {}".format(datetime.now().isoformat()))
    print("=" * 70)

    # ---- MD5 verification ----
    print("\n--- MD5 Verification ---")
    md5_ok = True
    md5_results = {}
    for uname, upath in UNIVERSES.items():
        digest = md5_file(upath)
        expected = EXPECTED_MD5[uname]
        match = digest == expected
        status = "OK" if match else "MISMATCH"
        md5_results[uname] = {"computed": digest, "expected": expected, "match": match}
        print("  {}: {} {} {}  [{}]".format(uname, digest, "==" if match else "!=", expected, status))
        if not match:
            md5_ok = False

    if not md5_ok:
        print("\nWARNING: MD5 mismatch detected. Proceeding anyway.")

    # ---- Run tests ----
    all_results = {}
    md_sections = []

    for uname, upath in UNIVERSES.items():
        print("\n" + "=" * 60)
        print("UNIVERSE: {}".format(uname))
        print("  Path: {}".format(upath))
        print("=" * 60)

        data, coins = load_universe(upath)
        print("  Coins: {}".format(len(coins)))

        t0 = time.time()
        indicators = precompute_all(data, coins)
        t_pre = time.time() - t0
        print("  Precompute: {:.1f}s".format(t_pre))

        universe_results = {}

        for cname, cfg in CONFIGS.items():
            print("\n  --- Config: {} ---".format(cname))
            print("  {}".format(json.dumps(cfg, sort_keys=True)))

            result = run_wf_pair(indicators, coins, cfg, n_folds=N_FOLDS)
            universe_results[cname] = result

            p = result["purged"]
            n = result["nopurge"]

            print("  PURGED   (emb={}): {} passed | Total test P&L: ${:,.2f} | Max DD: {}% | {}s".format(
                EMBARGO_PURGED, p["wf_label"], p["total_test_pnl"], p["max_test_dd"], p["time_s"]))
            print("  NOPURGE  (emb={}): {} passed | Total test P&L: ${:,.2f} | Max DD: {}% | {}s".format(
                EMBARGO_NOPURGE, n["wf_label"], n["total_test_pnl"], n["max_test_dd"], n["time_s"]))
            print("  LEAKAGE DELTA: {:+.2f}%  ->  {}".format(result["leakage_delta_pct"], result["verdict"]))

            print("\n  Fold-by-fold comparison:")
            for pf, nf in zip(p["folds"], n["folds"]):
                delta = nf["test_pnl"] - pf["test_pnl"]
                sign = "+" if delta >= 0 else ""
                print("    Fold {}: Purged ${:>8,.2f} ({}tr, {}%WR) | NoPurge ${:>8,.2f} ({}tr, {}%WR) | Delta {}${:,.2f}".format(
                    pf["fold"], pf["test_pnl"], pf["test_trades"], pf["test_wr"],
                    nf["test_pnl"], nf["test_trades"], nf["test_wr"], sign, delta))

            md_sections.append("### {} / {}\n".format(uname, cname))
            md_sections.append("Config: `{}`\n".format(json.dumps(cfg, sort_keys=True)))
            md_sections.append("")
            md_sections.append("| Metric | Purged (emb=2) | NoPurge (emb=0) |")
            md_sections.append("|--------|----------------|-----------------|")
            md_sections.append("| Passed Folds | {} | {} |".format(p["wf_label"], n["wf_label"]))
            md_sections.append("| Total Test P&L | ${:,.2f} | ${:,.2f} |".format(p["total_test_pnl"], n["total_test_pnl"]))
            md_sections.append("| Max Test DD | {}% | {}% |".format(p["max_test_dd"], n["max_test_dd"]))
            md_sections.append("| Runtime | {}s | {}s |".format(p["time_s"], n["time_s"]))
            md_sections.append("| **Leakage Delta** | | **{:+.2f}%** |".format(result["leakage_delta_pct"]))
            md_sections.append("| **Verdict** | | **{}** |".format(result["verdict"]))
            md_sections.append("")
            md_sections.append(format_fold_comparison(p["folds"], n["folds"]))
            md_sections.append("")

        all_results[uname] = universe_results

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    any_leak = False
    summary_lines = []
    summary_lines.append("| Universe | Config | Purged P&L | NoPurge P&L | Delta% | Verdict |")
    summary_lines.append("|----------|--------|------------|-------------|--------|---------|")

    for uname, uresults in all_results.items():
        for cname, result in uresults.items():
            p = result["purged"]
            n = result["nopurge"]
            d = result["leakage_delta_pct"]
            v = result["verdict"]
            if v == "LEAKAGE WARNING":
                any_leak = True
            summary_lines.append(
                "| {} | {} | ${:,.2f} | ${:,.2f} | {:+.2f}% | {} |".format(
                    uname, cname, p["total_test_pnl"], n["total_test_pnl"], d, v))
            print("  {:15s} / {:10s}: Purged ${:>8,.2f} vs NoPurge ${:>8,.2f} | Delta {:+.2f}% -> {}".format(
                uname, cname, p["total_test_pnl"], n["total_test_pnl"], d, v))

    overall = "LEAKAGE DETECTED" if any_leak else "ALL CLEAN -- NO LEAKAGE"
    print("\n  OVERALL: {}".format(overall))

    # ---- Save JSON ----
    report_json = {
        "timestamp": datetime.now().isoformat(),
        "n_folds": N_FOLDS,
        "embargo_purged": EMBARGO_PURGED,
        "embargo_nopurge": EMBARGO_NOPURGE,
        "leakage_threshold_pct": LEAKAGE_THRESHOLD_PCT,
        "md5": md5_results,
        "configs": {k: v for k, v in CONFIGS.items()},
        "results": all_results,
        "overall_verdict": overall,
    }

    json_path = REPORTS_DIR / "leakage_check.json"
    with open(json_path, "w") as f:
        json.dump(report_json, f, indent=2, default=str)
    print("\n  Saved: {}".format(json_path))

    # ---- Save Markdown ----
    md_lines = [
        "# Leakage / Purge Sanity Check Report",
        "",
        "**Generated**: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M")),
        "**Method**: Purged Walk-Forward (embargo=2) vs No-Purge (embargo=0), {}-fold".format(N_FOLDS),
        "**Leakage Threshold**: >{}% delta triggers warning".format(LEAKAGE_THRESHOLD_PCT),
        "",
        "## MD5 Verification",
        "",
        "| Universe | MD5 | Expected | Match |",
        "|----------|-----|----------|-------|",
    ]
    for uname, md5info in md5_results.items():
        md_lines.append(
            "| {} | `{}...` | `{}...` | {} |".format(
                uname, md5info["computed"][:12], md5info["expected"][:12],
                "OK" if md5info["match"] else "MISMATCH"))
    md_lines.append("")
    md_lines.append("## Summary")
    md_lines.append("")
    md_lines.extend(summary_lines)
    md_lines.append("")
    md_lines.append("### Overall Verdict: **{}**".format(overall))
    md_lines.append("")
    md_lines.append("## Detailed Results")
    md_lines.append("")
    md_lines.extend(md_sections)

    md_path = REPORTS_DIR / "leakage_check.md"
    with open(md_path, "w") as f:
        f.write(chr(10).join(md_lines))
    print("  Saved: {}".format(md_path))

    # ---- Print MD report ----
    print("\n" + "=" * 70)
    print("MARKDOWN REPORT:")
    print("=" * 70)
    print(chr(10).join(md_lines))


if __name__ == "__main__":
    main()
