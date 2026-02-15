#!/usr/bin/env python3
"""
HF Correlation Analysis -- Rolling pairwise Pearson correlation for
signal-generating coins across multiple timeframes.

Methodology:
  1. Load candle data for the specified timeframe (4h, 1h, 15m)
  2. Pre-filter to signal-generating coins only (~50 coins that
     actually produce entry signals under GRID_BEST config)
  3. Compute rolling pairwise Pearson correlation on log-returns
     - Window = bars_per_day * 10 (10 days of data)
     - bars_per_day: 4h=6, 1h=24, 15m=96
  4. Identify clusters: groups of coins with avg pairwise rho > 0.70
  5. Output: reports/hf/correlation_{tf}_001.json + .md

Usage:
    python strategies/hf/hf_correlation.py
    python strategies/hf/hf_correlation.py --timeframe 4h
    python strategies/hf/hf_correlation.py --timeframe 1h
    python strategies/hf/hf_correlation.py --timeframe 15m

Outputs:
    reports/hf/correlation_{tf}_001.json  -- full structured results
    reports/hf/correlation_{tf}_001.md    -- human-readable summary
"""

import sys
import json
import math
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# --- Path setup ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    check_entry_at_bar,
    normalize_cfg,
    KRAKEN_FEE,
    START_BAR,
)

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

# Timeframe-specific settings
TF_CONFIG = {
    "4h": {
        "cache_file": DATA_DIR / "candle_cache_tradeable.json",
        "bars_per_day": 6,
    },
    "1h": {
        "cache_file": DATA_DIR / "candle_cache_1h.json",
        "bars_per_day": 24,
    },
    "15m": {
        "cache_file": DATA_DIR / "candle_cache_15m.json",
        "bars_per_day": 96,
    },
}

# GRID_BEST config for signal detection
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

# Correlation thresholds
CORR_THRESHOLD = 0.70   # high correlation cutoff
MIN_OBSERVATIONS = 10   # minimum data points for valid correlation


# ============================================================
# DATA LOADING
# ============================================================
def load_data(tf: str):
    """Load candle data for the given timeframe."""
    cfg = TF_CONFIG[tf]
    path = cfg["cache_file"]
    if not path.exists():
        print(f"ERROR: No data file found: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ============================================================
# SIGNAL FILTERING
# ============================================================
def find_signal_coins(data, coins, cfg):
    """
    Pre-filter to coins that produce at least 1 entry signal.
    Runs check_entry_at_bar on all bars for each coin.

    Returns list of (coin, signal_count) sorted by signal_count desc.
    """
    indicators = precompute_all(data, coins)
    signal_coins = []

    for coin in coins:
        ind = indicators[coin]
        n = ind["n"]
        count = 0
        for bar in range(START_BAR, n):
            ok, _ = check_entry_at_bar(ind, bar, cfg)
            if ok:
                count += 1
        if count >= 1:
            signal_coins.append((coin, count))

    signal_coins.sort(key=lambda x: x[1], reverse=True)
    return signal_coins, indicators


# ============================================================
# LOG-RETURNS
# ============================================================
def compute_log_returns(data, coins, n_bars):
    """
    Compute log-returns per coin: log(close[i] / close[i-1]).
    Returns {coin: [return_at_bar_i, ...]}.
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


# ============================================================
# ROLLING CORRELATION
# ============================================================
def rolling_corr(returns_a, returns_b, window):
    """
    Compute rolling Pearson correlation between two return series.

    For each position from window onwards, compute correlation of
    the last `window` returns. Returns list of (bar, rho) tuples
    for positions where correlation is valid.
    """
    n = min(len(returns_a), len(returns_b))
    results = []

    for end in range(window, n):
        start = end - window
        ra = returns_a[start:end]
        rb = returns_b[start:end]

        w = len(ra)
        if w < MIN_OBSERVATIONS:
            continue

        mean_a = sum(ra) / w
        mean_b = sum(rb) / w

        cov = 0.0
        var_a = 0.0
        var_b = 0.0
        for i in range(w):
            da = ra[i] - mean_a
            db = rb[i] - mean_b
            cov += da * db
            var_a += da * da
            var_b += db * db

        denom = math.sqrt(var_a * var_b)
        if denom < 1e-12:
            continue

        rho = cov / denom
        results.append((end, rho))

    return results


def compute_mean_corr(returns_a, returns_b, window):
    """Compute the mean rolling correlation between two series."""
    pairs = rolling_corr(returns_a, returns_b, window)
    if not pairs:
        return 0.0
    return sum(rho for _, rho in pairs) / len(pairs)


def compute_pairwise_corr_matrix(returns, coins, window):
    """
    Compute mean rolling pairwise correlation for all coin pairs.

    Returns:
        corr_matrix: dict of (coin_a, coin_b) -> mean_rho
        high_pairs: list of (coin_a, coin_b, mean_rho) with rho > CORR_THRESHOLD
    """
    n = len(coins)
    corr_matrix = {}
    high_pairs = []

    total_pairs = n * (n - 1) // 2
    computed = 0

    for i in range(n):
        for j in range(i + 1, n):
            coin_a = coins[i]
            coin_b = coins[j]
            mean_rho = compute_mean_corr(
                returns[coin_a], returns[coin_b], window
            )
            corr_matrix[(coin_a, coin_b)] = mean_rho
            corr_matrix[(coin_b, coin_a)] = mean_rho

            if mean_rho > CORR_THRESHOLD:
                high_pairs.append((coin_a, coin_b, round(mean_rho, 4)))

            computed += 1
            if computed % 200 == 0 or computed == total_pairs:
                print(f"    Computed {computed}/{total_pairs} pairs...")

    high_pairs.sort(key=lambda x: x[2], reverse=True)
    return corr_matrix, high_pairs


# ============================================================
# CLUSTER DETECTION
# ============================================================
def find_clusters(corr_matrix, coins, threshold=0.70):
    """
    Find groups of coins with avg pairwise correlation > threshold.

    Uses greedy agglomerative approach:
      1. Build adjacency list of high-correlation pairs
      2. For each unvisited coin, grow cluster by adding neighbors
         whose average correlation with existing cluster > threshold
      3. Return list of clusters (each is a list of coins)
    """
    # Build adjacency with high-corr pairs
    adj = defaultdict(set)
    for i, coin_a in enumerate(coins):
        for j in range(i + 1, len(coins)):
            coin_b = coins[j]
            rho = corr_matrix.get((coin_a, coin_b), 0.0)
            if rho > threshold:
                adj[coin_a].add(coin_b)
                adj[coin_b].add(coin_a)

    visited = set()
    clusters = []

    # Sort by number of high-corr neighbors (desc) to find dense clusters first
    sorted_coins = sorted(coins, key=lambda c: len(adj.get(c, set())), reverse=True)

    for seed in sorted_coins:
        if seed in visited:
            continue
        if not adj.get(seed):
            continue

        cluster = [seed]
        visited.add(seed)

        candidates = sorted(adj[seed] - visited,
                            key=lambda c: corr_matrix.get((seed, c), 0.0),
                            reverse=True)

        for candidate in candidates:
            if candidate in visited:
                continue

            # Check average correlation with all current cluster members
            avg_corr_with_cluster = sum(
                corr_matrix.get((candidate, member), 0.0)
                for member in cluster
            ) / len(cluster)

            if avg_corr_with_cluster > threshold:
                cluster.append(candidate)
                visited.add(candidate)

        if len(cluster) >= 2:
            # Compute cluster's internal avg correlation
            n_c = len(cluster)
            pair_corrs = []
            for ii in range(n_c):
                for jj in range(ii + 1, n_c):
                    pair_corrs.append(
                        corr_matrix.get((cluster[ii], cluster[jj]), 0.0)
                    )
            avg_internal = sum(pair_corrs) / len(pair_corrs) if pair_corrs else 0.0

            clusters.append({
                "coins": cluster,
                "size": n_c,
                "avg_internal_corr": round(avg_internal, 4),
                "n_pairs": len(pair_corrs),
            })

    clusters.sort(key=lambda c: c["avg_internal_corr"], reverse=True)
    return clusters


# ============================================================
# CORRELATION STATISTICS
# ============================================================
def compute_corr_stats(corr_matrix, coins):
    """Compute summary statistics of the pairwise correlation matrix."""
    all_rhos = []
    n = len(coins)
    for i in range(n):
        for j in range(i + 1, n):
            rho = corr_matrix.get((coins[i], coins[j]), 0.0)
            all_rhos.append(rho)

    if not all_rhos:
        return {
            "n_pairs": 0, "mean": 0.0, "median": 0.0,
            "std": 0.0, "min": 0.0, "max": 0.0,
            "pct_above_050": 0.0, "pct_above_070": 0.0,
        }

    all_rhos.sort()
    n_rhos = len(all_rhos)
    mean_rho = sum(all_rhos) / n_rhos
    median_rho = all_rhos[n_rhos // 2]
    variance = sum((r - mean_rho) ** 2 for r in all_rhos) / n_rhos
    std_rho = math.sqrt(variance)

    above_050 = sum(1 for r in all_rhos if r > 0.50)
    above_070 = sum(1 for r in all_rhos if r > 0.70)

    return {
        "n_pairs": n_rhos,
        "mean": round(mean_rho, 4),
        "median": round(median_rho, 4),
        "std": round(std_rho, 4),
        "min": round(all_rhos[0], 4),
        "max": round(all_rhos[-1], 4),
        "pct_above_050": round(above_050 / n_rhos * 100, 1),
        "pct_above_070": round(above_070 / n_rhos * 100, 1),
    }


# ============================================================
# PER-COIN CORRELATION PROFILE
# ============================================================
def compute_per_coin_profile(corr_matrix, coins):
    """For each coin, compute mean and max correlation with others."""
    profiles = {}
    for coin in coins:
        corrs = []
        for other in coins:
            if other == coin:
                continue
            rho = corr_matrix.get((coin, other), 0.0)
            corrs.append((other, rho))
        corrs.sort(key=lambda x: x[1], reverse=True)
        mean_corr = sum(r for _, r in corrs) / len(corrs) if corrs else 0.0
        max_corr_pair = corrs[0] if corrs else (None, 0.0)

        profiles[coin] = {
            "mean_corr": round(mean_corr, 4),
            "max_corr": round(max_corr_pair[1], 4),
            "max_corr_with": max_corr_pair[0],
            "n_high_corr": sum(1 for _, r in corrs if r > CORR_THRESHOLD),
        }
    return profiles


# ============================================================
# MARKDOWN REPORT
# ============================================================
def generate_markdown(tf, meta, signal_coins, corr_stats,
                      high_pairs, clusters, profiles):
    """Generate human-readable correlation report."""
    bars_per_day = TF_CONFIG[tf]["bars_per_day"]
    window = bars_per_day * 10

    lines = [
        f"# HF Correlation Analysis -- {tf.upper()} Timeframe",
        "",
        "> **Question**: Which signal-generating coins are highly correlated,",
        "> and should we apply diversification constraints?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Timeframe**: {tf}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins in universe**: {meta['n_coins_total']}",
        f"**Signal-generating coins**: {meta['n_signal_coins']}",
        f"**Rolling window**: {window} bars ({window // bars_per_day} days)",
        f"**Correlation threshold**: {CORR_THRESHOLD}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Signal coin summary
    lines.extend([
        "## 1. Signal-Generating Coins",
        "",
        f"Out of {meta['n_coins_total']} coins, **{meta['n_signal_coins']}** "
        f"produced at least 1 entry signal under GRID_BEST config.",
        "",
        "**Top 20 by signal count**:",
        "",
        "| Coin | Signals |",
        "|------|---------|",
    ])
    for coin, count in signal_coins[:20]:
        lines.append(f"| {coin} | {count} |")
    lines.append("")

    # Section 2: Correlation distribution
    lines.extend([
        "## 2. Correlation Distribution",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total pairs | {corr_stats['n_pairs']} |",
        f"| Mean rho | {corr_stats['mean']} |",
        f"| Median rho | {corr_stats['median']} |",
        f"| Std dev | {corr_stats['std']} |",
        f"| Min rho | {corr_stats['min']} |",
        f"| Max rho | {corr_stats['max']} |",
        f"| % pairs rho > 0.50 | {corr_stats['pct_above_050']}% |",
        f"| % pairs rho > 0.70 | {corr_stats['pct_above_070']}% |",
        "",
    ])

    # Section 3: High-correlation pairs
    lines.extend([
        "## 3. High-Correlation Pairs (rho > 0.70)",
        "",
        f"**Total high-correlation pairs**: {len(high_pairs)}",
        "",
    ])

    if high_pairs:
        lines.extend([
            "| Rank | Coin A | Coin B | Mean Rho |",
            "|------|--------|--------|----------|",
        ])
        for idx, (a, b, rho) in enumerate(high_pairs[:30], 1):
            lines.append(f"| {idx} | {a} | {b} | {rho} |")
        if len(high_pairs) > 30:
            lines.append(f"| ... | *{len(high_pairs) - 30} more pairs omitted* | | |")
        lines.append("")
    else:
        lines.extend([
            "No pairs with mean rolling correlation > 0.70 found.",
            "",
        ])

    # Section 4: Clusters
    lines.extend([
        "## 4. Correlation Clusters",
        "",
        f"**Clusters found**: {len(clusters)}",
        "",
    ])

    if clusters:
        for idx, cluster in enumerate(clusters, 1):
            lines.extend([
                f"### Cluster {idx} (size={cluster['size']}, "
                f"avg rho={cluster['avg_internal_corr']})",
                "",
                f"Coins: {', '.join(cluster['coins'])}",
                "",
            ])
    else:
        lines.extend([
            "No clusters with avg pairwise rho > 0.70 detected.",
            "",
        ])

    # Section 5: Per-coin profile (top 15 most correlated)
    sorted_profiles = sorted(profiles.items(),
                             key=lambda x: x[1]["mean_corr"], reverse=True)
    lines.extend([
        "## 5. Per-Coin Correlation Profile (Top 15 Most Correlated)",
        "",
        "| Coin | Mean Rho | Max Rho | Max Corr With | # High Pairs |",
        "|------|----------|---------|---------------|-------------|",
    ])
    for coin, prof in sorted_profiles[:15]:
        lines.append(
            f"| {coin} | {prof['mean_corr']} | {prof['max_corr']} "
            f"| {prof['max_corr_with']} | {prof['n_high_corr']} |"
        )
    lines.append("")

    # Section 6: Heatmap summary (textual)
    lines.extend([
        "## 6. Heatmap Summary",
        "",
        "Correlation density by range:",
        "",
        "| Range | Count | % of Total |",
        "|-------|-------|------------|",
    ])

    # Build histogram
    all_rhos_for_hist = []
    sig_coins_list = [c for c, _ in signal_coins]
    n_sig = len(sig_coins_list)
    for i in range(n_sig):
        for j in range(i + 1, n_sig):
            key = (sig_coins_list[i], sig_coins_list[j])
            if key in meta.get("_corr_matrix_keys", set()):
                pass
            # We don't have access to full matrix here, use stats
    # Use corr_stats for the summary
    n_pairs = corr_stats["n_pairs"]
    if n_pairs > 0:
        # Estimate distribution from stats
        pct_070 = corr_stats["pct_above_070"]
        pct_050 = corr_stats["pct_above_050"]
        n_above_070 = int(n_pairs * pct_070 / 100)
        n_050_070 = int(n_pairs * (pct_050 - pct_070) / 100)
        n_below_050 = n_pairs - n_above_070 - n_050_070

        lines.extend([
            f"| rho < 0.50 | {n_below_050} | {round(n_below_050 / n_pairs * 100, 1)}% |",
            f"| 0.50 <= rho < 0.70 | {n_050_070} | {round(n_050_070 / n_pairs * 100, 1)}% |",
            f"| rho >= 0.70 | {n_above_070} | {pct_070}% |",
        ])
    lines.append("")

    # Section 7: Implications
    lines.extend([
        "## 7. Implications for Portfolio Construction",
        "",
    ])

    if len(high_pairs) == 0:
        lines.extend([
            "- **Low concentration risk**: No signal-generating coin pairs exceed the "
            "0.70 correlation threshold.",
            "- **Diversification benefit**: Signal coins appear well-diversified.",
            "- **At max_pos=1**: No correlation risk (only one position at a time).",
            "- **At max_pos>1**: Correlation guard is unlikely to block entries.",
        ])
    elif len(high_pairs) <= 10:
        lines.extend([
            f"- **Moderate concentration risk**: {len(high_pairs)} pairs exceed rho > 0.70.",
            "- **At max_pos=1**: No action needed (single position).",
            "- **At max_pos>1**: Correlation guard should block concurrent entries "
            "in highly correlated pairs.",
            f"- **Clusters found**: {len(clusters)} -- review for position sizing.",
        ])
    else:
        lines.extend([
            f"- **HIGH concentration risk**: {len(high_pairs)} pairs exceed rho > 0.70.",
            "- **At max_pos=1**: LOG-ONLY mode recommended for monitoring.",
            "- **At max_pos>1**: HARD-GATE mode recommended -- correlation guard "
            "should actively block correlated entries.",
            f"- **{len(clusters)} clusters** identified -- consider cluster-level "
            "position limits.",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by hf_correlation.py -- {tf.upper()} timeframe*",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="HF Correlation Analysis -- rolling pairwise Pearson correlation"
    )
    parser.add_argument(
        "--timeframe", "-tf",
        choices=["4h", "1h", "15m"],
        default="4h",
        help="Timeframe to analyze (default: 4h)",
    )
    args = parser.parse_args()

    tf = args.timeframe
    tf_cfg = TF_CONFIG[tf]
    bars_per_day = tf_cfg["bars_per_day"]
    window = bars_per_day * 10  # 10 days of data

    print("=" * 70)
    print(f"  HF Correlation Analysis -- {tf.upper()} Timeframe")
    print("  Question: Which signal coins are highly correlated?")
    print("=" * 70)

    # 1. Load data
    data, all_coins, data_path = load_data(tf)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from "
          f"{Path(data_path).name}")
    print(f"  Rolling window: {window} bars ({window // bars_per_day} days)")

    t_start = time.time()

    # 2. Find signal-generating coins
    print("\n  Finding signal-generating coins (GRID_BEST config)...")
    t0 = time.time()
    signal_coins, indicators = find_signal_coins(data, all_coins, GRID_BEST)
    t_signal = time.time() - t0
    sig_coin_names = [c for c, _ in signal_coins]
    print(f"  Found {len(signal_coins)} signal-generating coins ({t_signal:.1f}s)")
    if signal_coins:
        print(f"  Top 5: {', '.join(f'{c}({n})' for c, n in signal_coins[:5])}")

    if len(sig_coin_names) < 2:
        print("  ERROR: Need at least 2 signal coins for correlation analysis.")
        sys.exit(1)

    # 3. Compute log-returns for signal coins
    print("\n  Computing log-returns...")
    t0 = time.time()
    returns = compute_log_returns(data, sig_coin_names, n_bars)
    t_returns = time.time() - t0
    print(f"  Log-returns computed ({t_returns:.1f}s)")

    # 4. Compute pairwise correlation matrix
    n_sig = len(sig_coin_names)
    total_pairs = n_sig * (n_sig - 1) // 2
    print(f"\n  Computing pairwise correlations ({total_pairs} pairs, "
          f"window={window})...")
    t0 = time.time()
    corr_matrix, high_pairs = compute_pairwise_corr_matrix(
        returns, sig_coin_names, window
    )
    t_corr = time.time() - t0
    print(f"  Correlation matrix computed ({t_corr:.1f}s)")
    print(f"  High-correlation pairs (rho > {CORR_THRESHOLD}): {len(high_pairs)}")

    # 5. Correlation statistics
    corr_stats = compute_corr_stats(corr_matrix, sig_coin_names)
    print(f"  Mean rho={corr_stats['mean']}, median={corr_stats['median']}, "
          f"max={corr_stats['max']}")

    # 6. Find clusters
    print("\n  Detecting correlation clusters...")
    t0 = time.time()
    clusters = find_clusters(corr_matrix, sig_coin_names, CORR_THRESHOLD)
    t_cluster = time.time() - t0
    print(f"  Found {len(clusters)} clusters ({t_cluster:.1f}s)")
    for idx, cluster in enumerate(clusters, 1):
        print(f"    Cluster {idx}: {cluster['coins']} "
              f"(avg rho={cluster['avg_internal_corr']})")

    # 7. Per-coin profiles
    profiles = compute_per_coin_profile(corr_matrix, sig_coin_names)

    total_time = time.time() - t_start

    # 8. Build output
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timeframe": tf,
        "data_file": data_path,
        "n_coins_total": len(all_coins),
        "n_signal_coins": len(signal_coins),
        "n_bars": n_bars,
        "bars_per_day": bars_per_day,
        "rolling_window": window,
        "corr_threshold": CORR_THRESHOLD,
        "config_used": "GRID_BEST",
        "total_time_s": round(total_time, 2),
    }

    json_output = {
        "meta": meta,
        "signal_coins": [
            {"coin": c, "signals": n} for c, n in signal_coins
        ],
        "corr_stats": corr_stats,
        "high_pairs": [
            {"coin_a": a, "coin_b": b, "mean_rho": r}
            for a, b, r in high_pairs
        ],
        "clusters": clusters,
        "per_coin_profiles": profiles,
    }

    # Write JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"correlation_{tf}_001.json"
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown
    md_path = REPORTS_DIR / f"correlation_{tf}_001.md"
    md = generate_markdown(tf, meta, signal_coins, corr_stats,
                           high_pairs, clusters, profiles)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print(f"\n{'='*70}")
    print(f"  CORRELATION ANALYSIS COMPLETE ({tf.upper()})")
    print(f"  Signal coins: {len(signal_coins)}")
    print(f"  High-corr pairs: {len(high_pairs)}")
    print(f"  Clusters: {len(clusters)}")
    print(f"  Runtime: {total_time:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
