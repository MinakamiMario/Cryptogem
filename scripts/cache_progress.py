#!/usr/bin/env python3
"""
cache_progress.py — Cache build progress reporter.

Reads data/manifest.json (if present) and the unfiltered cache file
to produce a JSON + Markdown progress report under reports/.

Usage:
    python scripts/cache_progress.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
CACHE_CANDIDATES = [
    ROOT / "data" / "candle_cache_unfiltered.json",
    ROOT / "data" / "candle_cache_research_all.json",
]
REPORT_JSON = ROOT / "reports" / "cache_progress.json"
REPORT_MD = ROOT / "reports" / "cache_progress.md"

AMS = ZoneInfo("Europe/Amsterdam")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_cache_file() -> Path | None:
    """Return the first existing cache file from CACHE_CANDIDATES."""
    for p in CACHE_CANDIDATES:
        if p.exists():
            return p
    return None


def file_size_mb(path: Path) -> float:
    """Return file size in MB, rounded to 2 decimals."""
    return round(path.stat().st_size / (1024 * 1024), 2)


def count_coins_in_cache(cache: dict) -> int:
    """Count tradable coin keys (skip metadata keys starting with '_')."""
    return sum(1 for k in cache if not k.startswith("_"))


def exchange_stats_from_manifest(manifest: dict, exchange: str) -> dict:
    """Extract done/fail/pending/total for one exchange from manifest."""
    items = manifest.get(exchange, {})
    done = sum(1 for v in items.values() if v.get("status") == "done")
    fail = sum(1 for v in items.values() if v.get("status") == "fail")
    pending = sum(1 for v in items.values() if v.get("status") == "pending")
    total = len(items)
    return {"done": done, "fail": fail, "pending": pending, "total": total}


def build_report_from_manifest(manifest: dict, cache: dict | None, cache_path: Path | None) -> dict:
    """Build the full report dict when a manifest is available."""
    kraken = exchange_stats_from_manifest(manifest, "kraken")
    mexc = exchange_stats_from_manifest(manifest, "mexc")

    total_coins = count_coins_in_cache(cache) if cache else 0
    grand_total = kraken["total"] + mexc["total"]
    grand_done = kraken["done"] + mexc["done"]

    status = "COMPLETE" if grand_done == grand_total and grand_total > 0 else f"PARTIAL ({grand_done}/{grand_total})"

    report = {
        "generated": datetime.now(AMS).strftime("%Y-%m-%d %H:%M CET"),
        "kraken": kraken,
        "mexc": mexc,
        "total_coins_in_cache": total_coins,
        "cache_file": str(cache_path) if cache_path else None,
        "cache_size_mb": file_size_mb(cache_path) if cache_path else 0,
        "status": status,
    }
    return report


def build_report_from_cache_only(cache: dict, cache_path: Path) -> dict:
    """Fallback: build report when there is no manifest, just the cache."""
    total_coins = count_coins_in_cache(cache)

    # Try to extract metadata hints
    sources = cache.get("_sources", None)  # list of exchange names or dict coin->exchange
    meta_coins = cache.get("_coins", None)

    kraken_coins = 0
    mexc_coins = 0

    if isinstance(sources, dict):
        # _sources maps coin -> exchange
        for coin, src in sources.items():
            ex = src if isinstance(src, str) else str(src)
            if "kraken" in ex.lower():
                kraken_coins += 1
            elif "mexc" in ex.lower():
                mexc_coins += 1
    elif isinstance(sources, list):
        # _sources is just a list of exchange names like ['kraken', 'mexc']
        # We can't attribute individual coins — count per source in coin data if possible
        for coin_key in cache:
            if coin_key.startswith("_"):
                continue
            coin_data = cache[coin_key]
            src = None
            if isinstance(coin_data, dict):
                src = coin_data.get("source", coin_data.get("exchange", None))
            elif isinstance(coin_data, list) and coin_data:
                # List of candles — check first candle for source key
                first = coin_data[0] if coin_data else {}
                if isinstance(first, dict):
                    src = first.get("source", first.get("exchange", None))

            if isinstance(src, str) and "mexc" in src.lower():
                mexc_coins += 1
            else:
                kraken_coins += 1  # default attribution
    else:
        # No source info at all
        kraken_coins = total_coins
        mexc_coins = 0

    kraken = {"done": kraken_coins, "fail": 0, "pending": 0, "total": kraken_coins}
    mexc = {"done": mexc_coins, "fail": 0, "pending": 0, "total": mexc_coins}

    expected = meta_coins if isinstance(meta_coins, int) else total_coins
    status = "COMPLETE" if total_coins >= expected else f"PARTIAL ({total_coins}/{expected})"

    report = {
        "generated": datetime.now(AMS).strftime("%Y-%m-%d %H:%M CET"),
        "kraken": kraken,
        "mexc": mexc,
        "total_coins_in_cache": total_coins,
        "cache_file": str(cache_path),
        "cache_size_mb": file_size_mb(cache_path),
        "status": status,
        "_note": "No manifest found — stats derived from cache metadata only",
    }
    return report


def format_exchange_line(name: str, stats: dict) -> str:
    """Format a single exchange stats line for markdown/stdout."""
    return (
        f"  {name:8s}  done={stats['done']:>4d}  "
        f"fail={stats['fail']:>4d}  "
        f"pending={stats['pending']:>4d}  "
        f"total={stats['total']:>4d}"
    )


def render_markdown(report: dict) -> str:
    """Render a human-readable Markdown summary."""
    lines = [
        "# Cache Progress Report",
        "",
        f"**Generated**: {report['generated']}",
        f"**Status**: `{report['status']}`",
        "",
        "## Exchange Breakdown",
        "",
        "| Exchange | Done | Fail | Pending | Total |",
        "|----------|-----:|-----:|--------:|------:|",
    ]

    for ex in ("kraken", "mexc"):
        s = report[ex]
        lines.append(f"| {ex.capitalize()} | {s['done']} | {s['fail']} | {s['pending']} | {s['total']} |")

    lines += [
        "",
        "## Cache File",
        "",
        f"- **Coins in cache**: {report['total_coins_in_cache']}",
        f"- **File**: `{report.get('cache_file', 'N/A')}`",
        f"- **Size**: {report.get('cache_size_mb', 0)} MB",
    ]

    if "_note" in report:
        lines += ["", f"> **Note**: {report['_note']}"]

    lines.append("")
    return "\n".join(lines)


def print_summary(report: dict) -> None:
    """Print a concise summary to stdout."""
    print("=" * 60)
    print("  CACHE PROGRESS REPORT")
    print("=" * 60)
    print(f"  Generated : {report['generated']}")
    print(f"  Status    : {report['status']}")
    print()
    print(format_exchange_line("Kraken", report["kraken"]))
    print(format_exchange_line("MEXC", report["mexc"]))
    print()
    print(f"  Coins in cache : {report['total_coins_in_cache']}")
    print(f"  Cache file     : {report.get('cache_file', 'N/A')}")
    print(f"  Cache size     : {report.get('cache_size_mb', 0)} MB")
    if "_note" in report:
        print(f"\n  Note: {report['_note']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Ensure output dir exists
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)

    # Load cache file (if any)
    cache_path = find_cache_file()
    cache = None
    if cache_path:
        with open(cache_path, "r") as f:
            cache = json.load(f)

    # Load manifest (if any)
    manifest = None
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)

    # Build report
    if manifest:
        report = build_report_from_manifest(manifest, cache, cache_path)
    elif cache and cache_path:
        report = build_report_from_cache_only(cache, cache_path)
    else:
        # Nothing available
        report = {
            "generated": datetime.now(AMS).strftime("%Y-%m-%d %H:%M CET"),
            "kraken": {"done": 0, "fail": 0, "pending": 0, "total": 0},
            "mexc": {"done": 0, "fail": 0, "pending": 0, "total": 0},
            "total_coins_in_cache": 0,
            "cache_file": None,
            "cache_size_mb": 0,
            "status": "NO DATA",
            "_note": "No manifest and no cache file found",
        }

    # Write JSON report
    with open(REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2)

    # Write Markdown report
    md = render_markdown(report)
    with open(REPORT_MD, "w") as f:
        f.write(md)

    # Print to stdout
    print_summary(report)
    print(f"\n  Reports written to:")
    print(f"    {REPORT_JSON}")
    print(f"    {REPORT_MD}")


if __name__ == "__main__":
    main()
