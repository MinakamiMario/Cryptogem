#!/usr/bin/env python3
"""
Universe Split - Run robustness harness on 4 different coin universes.

Universes:
  1. LIVE_CURRENT  (523c) - trading_bot/candle_cache_532.json as-is
  2. KRAKEN_ONLY   (~522c) - coins from research_all also in 532 cache
  3. MEXC_ONLY     (~1568c) - coins from research_all NOT in 532 cache
  4. MEXC_TOP      (200c) - top 200 MEXC coins by median volume

Output: reports/universe_split.json + reports/universe_split.md
"""
import sys
import json
import subprocess
import statistics
import traceback
import time
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo("Europe/Amsterdam")

ROOT = Path(__file__).parent.parent
HARNESS = ROOT / "trading_bot" / "robustness_harness.py"
CACHE_532 = ROOT / "trading_bot" / "candle_cache_532.json"
CACHE_RESEARCH = ROOT / "data" / "candle_cache_research_all.json"
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"

CONFIG = "C1_TPSL_RSI45"

UNIVERSES = [
    {"id": "LIVE_CURRENT", "label": "Live Current (Kraken 532 cache)",
     "cache_path": None, "temp_cache": None},
    {"id": "KRAKEN_ONLY", "label": "Kraken-only coins (from research_all)",
     "cache_path": None, "temp_cache": str(DATA_DIR / "temp_kraken_only.json")},
    {"id": "MEXC_ONLY", "label": "MEXC-exclusive coins (not on Kraken)",
     "cache_path": None, "temp_cache": str(DATA_DIR / "temp_mexc_only.json")},
    {"id": "MEXC_TOP", "label": "MEXC top 200 by median volume",
     "cache_path": None, "temp_cache": str(DATA_DIR / "temp_mexc_top200.json")},
]


def load_caches():
    print("  Loading candle_cache_532.json...", flush=True)
    with open(CACHE_532) as f:
        d532 = json.load(f)
    print("  Loading candle_cache_research_all.json...", flush=True)
    with open(CACHE_RESEARCH) as f:
        dall = json.load(f)
    return d532, dall


def get_coin_sets(d532, dall):
    coins_532 = set(k for k in d532.keys() if not k.startswith("_"))
    coins_all = set(k for k in dall.keys() if not k.startswith("_"))
    kraken_coins = coins_532 & coins_all
    mexc_coins = coins_all - coins_532
    print(f"  532 cache: {len(coins_532)} coins")
    print(f"  Research cache: {len(coins_all)} coins")
    print(f"  Kraken overlap: {len(kraken_coins)} coins")
    print(f"  MEXC exclusive: {len(mexc_coins)} coins")
    return coins_532, kraken_coins, mexc_coins


def median_volume(candles):
    vols = [c.get("volume", 0) for c in candles if isinstance(c, dict)]
    if not vols:
        return 0.0
    return statistics.median(vols)


def write_filtered_cache(dall, coin_set, output_path, label):
    filtered = {}
    for k in dall:
        if k.startswith("_"):
            filtered[k] = dall[k]
    filtered["_universe"] = label
    filtered["_coins"] = len(coin_set)
    count = 0
    for coin in sorted(coin_set):
        if coin in dall:
            filtered[coin] = dall[coin]
            count += 1
    print(f"  Writing {output_path} ({count} coins)...", flush=True)
    with open(output_path, "w") as f:
        json.dump(filtered, f)
    fsize = Path(output_path).stat().st_size / 1e6
    print(f"  Done ({fsize:.1f} MB)")
    return count


def build_temp_caches(d532, dall, kraken_coins, mexc_coins):
    results = {}
    print("  [KRAKEN_ONLY] Building temp cache...")
    n = write_filtered_cache(dall, kraken_coins, UNIVERSES[1]["temp_cache"], "kraken_only")
    results["KRAKEN_ONLY"] = n

    print("  [MEXC_ONLY] Building temp cache...")
    n = write_filtered_cache(dall, mexc_coins, UNIVERSES[2]["temp_cache"], "mexc_only")
    results["MEXC_ONLY"] = n

    print("  [MEXC_TOP] Computing median volumes...")
    vol_ranking = []
    for coin in mexc_coins:
        if coin in dall and isinstance(dall[coin], list):
            mv = median_volume(dall[coin])
            vol_ranking.append((coin, mv))
    vol_ranking.sort(key=lambda x: x[1], reverse=True)
    top200 = set(c for c, _ in vol_ranking[:200])
    if len(vol_ranking) >= 200:
        print(f"  Volume range: {vol_ranking[0][1]:.0f} (top) to {vol_ranking[-1][1]:.2f} (bottom)")
        print(f"  Top200 cutoff volume: {vol_ranking[199][1]:.2f}")

    print("  [MEXC_TOP] Building temp cache...")
    n = write_filtered_cache(dall, top200, UNIVERSES[3]["temp_cache"], "mexc_top200")
    results["MEXC_TOP"] = n
    return results


def run_harness(cache_path, universe_id, output_dir):
    cmd = [
        sys.executable, str(HARNESS),
        "--universe", "all",
        "--candle-cache", str(cache_path),
        "--output-dir", str(output_dir),
        "--config", CONFIG,
    ]
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  Running harness: {universe_id}")
    print(f"  Cache: {Path(cache_path).name}")
    print(f"  Output: {output_dir}")
    print(f"  Config: {CONFIG}")
    print(f"{sep}")

    t0 = time.time()
    try:
        result = subprocess.run(cmd, timeout=600, capture_output=True, text=True)
        elapsed = round(time.time() - t0, 1)
        print(result.stdout)
        if result.stderr:
            print(f"  STDERR: {result.stderr[-500:]}")
        if result.returncode != 0:
            print(f"  Harness FAILED (exit code {result.returncode})")
            return {"error": f"Harness exit code {result.returncode}",
                    "stderr": result.stderr[-500:] if result.stderr else "",
                    "elapsed_s": elapsed}
        return _load_reports(output_dir, elapsed)
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - t0, 1)
        print(f"  Harness TIMEOUT after {elapsed}s")
        return {"error": "Timeout (600s)", "elapsed_s": elapsed}
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        print(f"  Harness EXCEPTION: {e}")
        traceback.print_exc()
        return {"error": str(e), "elapsed_s": elapsed}


def _load_reports(report_dir, elapsed):
    reports = {"elapsed_s": elapsed}
    rd = Path(report_dir)
    for name in ["wf_report", "friction_report", "mc_report", "jitter_report", "universe_report"]:
        path = rd / f"{name}.json"
        if path.exists():
            with open(path) as f:
                reports[name] = json.load(f)
    gonogo = rd / "go_nogo.md"
    if gonogo.exists():
        with open(gonogo) as f:
            reports["go_nogo_md"] = f.read()
    return reports


def _parse_gonogo_baseline(md_text, config):
    """Parse baseline metrics from go_nogo.md markdown table (fallback for killed configs)."""
    for line in md_text.split("\n"):
        if config not in line or "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 5:
            try:
                trades = int(cells[1].strip())
                pnl_str = cells[2].strip().lstrip("$").replace(",", "")
                pnl = float(pnl_str)
                wr = float(cells[3].replace("%", "").strip())
                dd = float(cells[4].replace("%", "").strip())
                return {"trades": trades, "pnl": pnl, "wr": wr, "dd": dd}
            except (ValueError, IndexError):
                pass
    return None


def extract_metrics(reports, universe_id, n_coins):
    if "error" in reports:
        return {
            "universe": universe_id, "coins": n_coins, "trades": 0,
            "pnl": 0.0, "wr": 0.0, "dd": 0.0, "pf": 0.0,
            "wf_score": "?", "friction_2x20": 0.0, "mc_ruin": 100.0,
            "jitter_pct": 0.0, "univ_shift": "?", "top1_pct": 0.0,
            "verdict": "ERROR", "error": reports["error"],
            "elapsed_s": reports.get("elapsed_s", 0),
        }

    metrics = {"universe": universe_id, "coins": n_coins, "elapsed_s": reports.get("elapsed_s", 0)}

    # WF
    wf = reports.get("wf_report", {})
    cfg_wf = wf.get("results", {}).get(CONFIG, {})
    metrics["wf_score"] = cfg_wf.get("wf_label", "?")

    # Friction
    fric = reports.get("friction_report", {})
    cfg_fric = fric.get("results", {}).get(CONFIG, {})
    fric_matrix = cfg_fric.get("matrix", {})
    fric_2x20 = fric_matrix.get("2.0x_fee+20bps", {})
    metrics["friction_2x20"] = fric_2x20.get("pnl", 0.0)

    # MC
    mc = reports.get("mc_report", {})
    cfg_mc = mc.get("results", {}).get(CONFIG, {})
    metrics["mc_ruin"] = cfg_mc.get("ruin_prob_pct", 100.0)

    # Jitter
    jit = reports.get("jitter_report", {})
    cfg_jit = jit.get("results", {}).get(CONFIG, {})
    metrics["jitter_pct"] = cfg_jit.get("positive_pct", 0.0)

    # Universe
    univ = reports.get("universe_report", {})
    cfg_univ = univ.get("results", {}).get(CONFIG, {})
    conc = cfg_univ.get("concentration", {})
    metrics["top1_pct"] = round(conc.get("top1_share", 0) * 100, 1)
    metrics["univ_shift"] = f"{cfg_univ.get('n_positive_subsets', 0)}/4"

    # Baseline from friction 1x fee (closest to raw baseline)
    baseline = fric_matrix.get("1.0x_fee+0bps", {})
    if not baseline:
        # fallback: search other reports
        for rname in ["wf_report", "mc_report", "jitter_report", "universe_report"]:
            r = reports.get(rname, {})
            res = r.get("results", {}).get(CONFIG, {})
            if "baseline" in res:
                baseline = res["baseline"]
                break

    # Final fallback: parse from go_nogo.md (for killed configs with <15 trades)
    if not baseline:
        gonogo_md = reports.get("go_nogo_md", "")
        parsed = _parse_gonogo_baseline(gonogo_md, CONFIG)
        if parsed:
            baseline = parsed

    metrics["trades"] = baseline.get("trades", 0)
    metrics["pnl"] = round(baseline.get("pnl", 0), 2)
    metrics["wr"] = round(baseline.get("wr", 0), 1)
    metrics["dd"] = round(baseline.get("dd", 0), 1)
    pf = baseline.get("pf", 0)
    metrics["pf"] = pf if isinstance(pf, str) else round(pf, 2)

    # Verdict from go_nogo.md
    gonogo_md = reports.get("go_nogo_md", "")
    metrics["verdict"] = "?"
    for line in gonogo_md.split("\n"):
        if CONFIG in line:
            if "NO-GO" in line:
                metrics["verdict"] = "NO-GO"
            elif "SOFT-GO" in line:
                metrics["verdict"] = "SOFT-GO"
            elif "GO" in line:
                metrics["verdict"] = "GO"
            break

    return metrics


def write_report_json(all_metrics, output_path):
    report = {
        "timestamp": datetime.now(AMS).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "config": CONFIG,
        "universes": all_metrics,
    }
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Written: {output_path}")


def write_report_md(all_metrics, output_path):
    now = datetime.now(AMS).strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"# Universe Split Report",
        f"**Date**: {now}",
        f"**Config**: `{CONFIG}`",
        f"**Harness**: robustness_harness.py v2 (5 tests: WF, Friction, MC, Jitter, Universe)",
        "",
        "## Universe Overview",
        "",
        "| Universe | Coins | Description |",
        "|----------|------:|-------------|",
    ]
    descs = {
        "LIVE_CURRENT": "Live Kraken 532 cache (production set)",
        "KRAKEN_ONLY": "Kraken coins extracted from research_all cache",
        "MEXC_ONLY": "MEXC-exclusive coins (not available on Kraken)",
        "MEXC_TOP": "Top 200 MEXC coins by median volume",
    }
    for m in all_metrics:
        lines.append(f"| {m['universe']} | {m['coins']} | {descs.get(m['universe'], m['universe'])} |")

    lines.extend(["", "## Results Comparison", ""])
    lines.append("| Metric | " + " | ".join(m["universe"] for m in all_metrics) + " |")
    lines.append("|--------|" + "|".join("-" * max(len(m["universe"]), 12) + ":" for m in all_metrics) + "|")

    def fmt_pnl(m):
        return f"${m['pnl']:,.0f}" if m["trades"] > 0 else "-"
    def fmt_wr(m):
        return f"{m['wr']:.1f}%" if m["trades"] > 0 else "-"
    def fmt_dd(m):
        return f"{m['dd']:.1f}%" if m["trades"] > 0 else "-"
    def fmt_pf(m):
        return str(m["pf"]) if m["trades"] > 0 else "-"
    def fmt_fric(m):
        return f"${m['friction_2x20']:,.0f}" if m["trades"] > 0 else "-"
    def fmt_mcr(m):
        return f"{m['mc_ruin']:.1f}%" if m["trades"] > 0 else "-"
    def fmt_jit(m):
        return f"{m['jitter_pct']:.0f}%" if m["trades"] > 0 else "-"
    def fmt_top1(m):
        return f"{m['top1_pct']:.1f}%" if m["trades"] > 0 else "-"

    rows = [
        ("Coins", lambda m: str(m["coins"])),
        ("Trades", lambda m: str(m["trades"])),
        ("P&L ($)", fmt_pnl),
        ("Win Rate (%)", fmt_wr),
        ("Max DD (%)", fmt_dd),
        ("Profit Factor", fmt_pf),
        ("Walk-Forward", lambda m: m["wf_score"]),
        ("Friction 2x+20bps ($)", fmt_fric),
        ("MC Ruin (%)", fmt_mcr),
        ("Jitter pos (%)", fmt_jit),
        ("Universe Shift", lambda m: m["univ_shift"]),
        ("Top1 (%)", fmt_top1),
        ("**Verdict**", lambda m: f"**{m['verdict']}**"),
        ("Runtime (s)", lambda m: f"{m['elapsed_s']:.0f}"),
    ]

    for label, fn in rows:
        cells = " | ".join(fn(m) for m in all_metrics)
        lines.append(f"| {label} | {cells} |")

    errors = [(m["universe"], m.get("error", "")) for m in all_metrics if m.get("error")]
    if errors:
        lines.extend(["", "## Errors", ""])
        for uid, err in errors:
            lines.append(f"- **{uid}**: {err}")

    lines.extend(["", "## Analysis", ""])
    go_u = [m for m in all_metrics if m["verdict"] == "GO"]
    nogo_u = [m for m in all_metrics if m["verdict"] == "NO-GO"]
    softgo_u = [m for m in all_metrics if m["verdict"] == "SOFT-GO"]

    if go_u:
        lines.append(f"**GO universes ({len(go_u)})**: " + ", ".join(m["universe"] for m in go_u))
    if softgo_u:
        lines.append(f"**SOFT-GO universes ({len(softgo_u)})**: " + ", ".join(m["universe"] for m in softgo_u))
    if nogo_u:
        lines.append(f"**NO-GO universes ({len(nogo_u)})**: " + ", ".join(m["universe"] for m in nogo_u))
    lines.append("")

    pnl_values = [m["pnl"] for m in all_metrics if m["trades"] > 0]
    if len(pnl_values) >= 2:
        all_positive = all(p > 0 for p in pnl_values)
        lines.append(f"- P&L sign consistency: {'All positive' if all_positive else 'MIXED (some negative)'}")
        lines.append(f"- P&L range: ${min(pnl_values):,.0f} to ${max(pnl_values):,.0f}")

    wr_values = [m["wr"] for m in all_metrics if m["trades"] > 0]
    if len(wr_values) >= 2:
        lines.append(f"- Win rate range: {min(wr_values):.1f}% to {max(wr_values):.1f}%")

    trade_values = [m["trades"] for m in all_metrics if m["trades"] > 0]
    if trade_values:
        lines.append(f"- Trade count range: {min(trade_values)} to {max(trade_values)}")

    lines.extend(["", "## Conclusion", ""])
    n_go = len(go_u) + len(softgo_u)
    n_total = len(all_metrics)
    if n_go == n_total:
        lines.append(f"Strategy passes GO/NO-GO on ALL {n_total} universes. Strong cross-universe robustness.")
    elif n_go >= n_total * 0.75:
        lines.append(f"Strategy passes on {n_go}/{n_total} universes. Reasonable robustness but check failures.")
    elif n_go >= n_total * 0.5:
        lines.append(f"Strategy passes on {n_go}/{n_total} universes. Mixed results -- universe-dependent performance.")
    else:
        lines.append(f"Strategy passes on only {n_go}/{n_total} universes. Poor cross-universe robustness.")
    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Written: {output_path}")


def main():
    t_start = time.time()
    print("=" * 65)
    print("  UNIVERSE SPLIT -- Cross-Universe Robustness Test")
    print(f"  {datetime.now(AMS).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Config: {CONFIG}")
    print("=" * 65)

    print("\n[1/4] Loading caches...")
    d532, dall = load_caches()

    print("\n[2/4] Determining coin sets...")
    coins_532, kraken_coins, mexc_coins = get_coin_sets(d532, dall)

    print("\n[3/4] Building temporary caches...")
    build_temp_caches(d532, dall, kraken_coins, mexc_coins)
    del d532, dall

    print("\n[4/4] Running harness on 4 universes...")
    UNIVERSES[0]["cache_path"] = str(CACHE_532)
    UNIVERSES[1]["cache_path"] = UNIVERSES[1]["temp_cache"]
    UNIVERSES[2]["cache_path"] = UNIVERSES[2]["temp_cache"]
    UNIVERSES[3]["cache_path"] = UNIVERSES[3]["temp_cache"]

    coin_counts = {
        "LIVE_CURRENT": len(coins_532),
        "KRAKEN_ONLY": len(kraken_coins),
        "MEXC_ONLY": len(mexc_coins),
        "MEXC_TOP": 200,
    }

    all_metrics = []
    for univ in UNIVERSES:
        uid = univ["id"]
        cache = univ["cache_path"]
        output_dir = str(REPORT_DIR / "universe_split" / uid.lower())
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        reports = run_harness(cache, uid, output_dir)
        n_coins = coin_counts.get(uid, 0)
        metrics = extract_metrics(reports, uid, n_coins)
        all_metrics.append(metrics)

    print("\n" + "=" * 65)
    print("  Writing combined reports...")
    print("=" * 65)

    json_path = REPORT_DIR / "universe_split.json"
    md_path = REPORT_DIR / "universe_split.md"
    write_report_json(all_metrics, json_path)
    write_report_md(all_metrics, md_path)

    print("\n" + "=" * 100)
    print("  UNIVERSE SPLIT SUMMARY")
    print("=" * 100)
    hdr = f"{'Universe':<16} {'Coins':>5} {'Tr':>3} {'P&L':>8} {'WR':>6} {'DD':>6} {'WF':>5} {'Fric':>8} {'MCr%':>6} {'Jit%':>5} {'Top1%':>6} {'Verdict':>8}"
    print(hdr)
    print("-" * 100)
    for m in all_metrics:
        if m.get("error"):
            print(f"{m['universe']:<16} {m['coins']:>5} {'ERROR':>60} {m.get('error','')[:30]}")
        else:
            print(f"{m['universe']:<16} {m['coins']:>5} {m['trades']:>3} ${m['pnl']:>7,.0f} {m['wr']:>5.1f}% {m['dd']:>5.1f}% {m['wf_score']:>5} ${m['friction_2x20']:>7,.0f} {m['mc_ruin']:>5.1f}% {m['jitter_pct']:>4.0f}% {m['top1_pct']:>5.1f}% {m['verdict']:>8}")
    print("-" * 100)

    print("\n  Cleaning up temp caches...")
    for univ in UNIVERSES:
        tc = univ.get("temp_cache")
        if tc and Path(tc).exists():
            Path(tc).unlink()
            print(f"    Deleted: {tc}")

    total = round(time.time() - t_start, 1)
    print(f"\n  Total runtime: {total}s ({total/60:.1f} min)")
    print(f"  Reports: {json_path}")
    print(f"           {md_path}")


if __name__ == "__main__":
    main()
