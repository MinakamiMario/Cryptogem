#!/usr/bin/env python3
"""
Compare Caches — Run robustness harness on two different cache files and compare.

Gebruik:
  python3 scripts/compare_universe.py --config C1_TPSL_RSI45
  python3 scripts/compare_universe.py --cache-a data/candle_cache_research_all.json --cache-b trading_bot/candle_cache_532.json
  python3 scripts/compare_universe.py --label-a RESEARCH --label-b LIVE --config C1_TPSL_RSI45 C4_TRAIL_BEST
"""
import sys
import json
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo('Europe/Amsterdam')
ROOT = Path(__file__).parent.parent
HARNESS = ROOT / 'trading_bot' / 'robustness_harness.py'
REPORT_DIR = ROOT / 'reports' / 'compare_caches'

DEFAULT_CACHE_A = ROOT / 'data' / 'candle_cache_research_all.json'
DEFAULT_CACHE_B = ROOT / 'trading_bot' / 'candle_cache_532.json'


def file_hash(path):
    """MD5 hash (first 12 chars) for reproducibility tracking."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


def coin_count(path):
    """Count coins in a cache file (keys with list value, len>50)."""
    with open(path) as f:
        data = json.load(f)
    return sum(1 for k, v in data.items() if isinstance(v, list) and len(v) > 50)


def run_harness(cache_path, config_args, output_dir):
    """Run robustness harness for a cache file with --universe all."""
    cmd = [
        sys.executable, str(HARNESS),
        '--universe', 'all',
        '--candle-cache', str(cache_path),
        '--output-dir', str(output_dir),
    ]
    if config_args:
        cmd.extend(['--config'] + config_args)

    print(f"\n{'='*65}")
    print(f"  Running harness: {Path(cache_path).name}")
    print(f"  Cache: {cache_path}")
    print(f"  Output: {output_dir}")
    print(f"{'='*65}")

    result = subprocess.run(cmd, timeout=600)
    if result.returncode != 0:
        print(f"  Harness failed for {cache_path}")
        sys.exit(1)
    return output_dir


def load_reports(report_dir):
    """Load all JSON reports from a harness output directory."""
    reports = {}
    for name in ['wf_report', 'friction_report', 'mc_report', 'jitter_report', 'universe_report']:
        path = Path(report_dir) / f'{name}.json'
        if path.exists():
            with open(path) as f:
                reports[name] = json.load(f)
    return reports


def extract_metrics(reports):
    """Extract key metrics per config from harness reports."""
    configs = {}
    wf = reports.get('wf_report', {}).get('results', {})
    fric = reports.get('friction_report', {}).get('results', {})
    mc = reports.get('mc_report', {}).get('results', {})
    jit = reports.get('jitter_report', {}).get('results', {})
    univ = reports.get('universe_report', {}).get('results', {})

    meta = reports.get('wf_report', {})
    universe_mode = meta.get('universe_mode', '?')
    n_coins = meta.get('coin_count', 0)

    all_cids = set(list(wf.keys()) + list(fric.keys()))
    for cid in sorted(all_cids):
        fric_data = fric.get(cid, {})
        base = fric_data.get('matrix', {}).get('1.0x_fee+0bps', {})
        fric_go = fric_data.get('go_pnl', 0)
        mc_data = mc.get(cid, {})
        jit_data = jit.get(cid, {})
        wf_data = wf.get(cid, {})
        univ_data = univ.get(cid, {})
        conc = univ_data.get('concentration', {})

        # Determine verdict
        fails = []
        if not wf_data.get('go') and not wf_data.get('soft_go'):
            fails.append('WF')
        if not fric_data.get('go'):
            fails.append('Friction')
        if not mc_data.get('go'):
            fails.append('MC')
        if not jit_data.get('go'):
            fails.append('Jitter')
        if not univ_data.get('go'):
            fails.append('Universe')

        if wf_data.get('soft_go') and not wf_data.get('go') and len(fails) == 0:
            verdict = 'SOFT-GO'
        elif len(fails) == 0:
            verdict = 'GO'
        else:
            verdict = 'NO-GO'

        configs[cid] = {
            'trades': base.get('trades', 0),
            'pnl': base.get('pnl', 0),
            'wr': base.get('wr', 0),
            'dd': base.get('dd', 0),
            'pf': base.get('pf', 0),
            'wf_label': wf_data.get('wf_label', '?'),
            'wf_pass': wf_data.get('passed_folds', 0),
            'wf_go': wf_data.get('go', False),
            'fric_go_pnl': fric_go,
            'fric_go': fric_data.get('go', False),
            'mc_ruin': mc_data.get('ruin_prob_pct', 99),
            'mc_p95_dd': mc_data.get('max_dd', {}).get('p95', 99),
            'mc_win_pct': mc_data.get('equity', {}).get('win_pct', 0),
            'mc_go': mc_data.get('go', False),
            'jitter_pct': jit_data.get('positive_pct', 0),
            'jitter_go': jit_data.get('go', False),
            'univ_n_pos': univ_data.get('n_positive_subsets', 0),
            'univ_go': univ_data.get('go', False),
            'top1_coin': conc.get('top1_coin', '?'),
            'top1_share': conc.get('top1_share', 0),
            'top3_share': conc.get('top3_share', 0),
            'notop_pnl': conc.get('notop_pnl', 0),
            'verdict': verdict,
            'fails': fails,
        }

    return {
        'universe_mode': universe_mode,
        'coin_count': n_coins,
        'dataset_hash': meta.get('dataset_hash', '?'),
        'configs': configs,
    }


def write_comparison(metrics_a, metrics_b, label_a, label_b, hash_a, hash_b, output_dir):
    """Write report.json + report.md comparing two cache runs."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(AMS).strftime('%Y-%m-%d %H:%M %Z')

    # --- JSON ---
    report = {
        'generated': now,
        'label_a': label_a,
        'label_b': label_b,
        'metrics_a': metrics_a,
        'metrics_b': metrics_b,
    }
    json_path = output_dir / 'report.json'
    with open(json_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Saved {json_path}")

    # --- MD ---
    lines = [
        f'# Cache Comparison: {label_a} vs {label_b}',
        f'Generated: {now}',
        f'{label_a}: {metrics_a["coin_count"]} coins (hash: `{hash_a}`)',
        f'{label_b}: {metrics_b["coin_count"]} coins (hash: `{hash_b}`)',
        '',
        '## Side-by-Side Summary',
        '',
        '| Config | Universe | Tr | P&L | WR | DD | PF | WF | Fric 2x+20 | MC ruin | Jitter | Univ | Top1% | Verdict |',
        '|--------|----------|-----|------|-----|-----|-----|-----|------------|---------|--------|------|-------|---------|',
    ]

    all_cids = sorted(set(list(metrics_a['configs'].keys()) +
                          list(metrics_b['configs'].keys())))

    for cid in all_cids:
        for label, metrics in [(label_a, metrics_a), (label_b, metrics_b)]:
            c = metrics['configs'].get(cid)
            if not c:
                continue
            sym = {'GO': '🟢', 'SOFT-GO': '🟡', 'NO-GO': '🔴'}.get(c['verdict'], '?')
            lines.append(
                f"| {cid} | {label} ({metrics['coin_count']}c) | "
                f"{c['trades']} | ${c['pnl']:.0f} | {c['wr']}% | {c['dd']}% | {c['pf']} | "
                f"{c['wf_label']} | ${c['fric_go_pnl']:.0f} | {c['mc_ruin']}% | "
                f"{c['jitter_pct']}% | {c['univ_n_pos']}/4 | {c['top1_share']*100:.0f}% | "
                f"{sym} {c['verdict']} |"
            )

    lines.append('')

    # --- Delta Analysis ---
    lines.append(f'## Delta Analysis')
    lines.append('')
    lines.append(f'| Config | Metric | {label_a} | {label_b} | Delta | Impact |')
    lines.append('|--------|--------|-----|------|-------|--------|')

    for cid in all_cids:
        a = metrics_a['configs'].get(cid)
        b = metrics_b['configs'].get(cid)
        if not a or not b:
            continue

        delta_trades = a['trades'] - b['trades']
        delta_pnl = a['pnl'] - b['pnl']
        delta_wr = a['wr'] - b['wr']
        delta_dd = a['dd'] - b['dd']

        lines.append(f"| {cid} | Trades | {a['trades']} | {b['trades']} | {delta_trades:+d} | "
                     f"{'meer sample' if delta_trades > 0 else 'minder sample'} |")
        lines.append(f"| | P&L | ${a['pnl']:.0f} | ${b['pnl']:.0f} | ${delta_pnl:+.0f} | "
                     f"{'beter' if delta_pnl > 0 else 'slechter'} |")
        lines.append(f"| | WR | {a['wr']}% | {b['wr']}% | {delta_wr:+.1f}% | "
                     f"{'beter' if delta_wr > 0 else 'slechter'} |")
        lines.append(f"| | DD | {a['dd']}% | {b['dd']}% | {delta_dd:+.1f}% | "
                     f"{'meer risico' if delta_dd > 0 else 'minder risico'} |")
        lines.append(f"| | WF | {a['wf_label']} | {b['wf_label']} | | "
                     f"{'verschil!' if a['wf_label'] != b['wf_label'] else 'gelijk'} |")
        lines.append(f"| | Verdict | {a['verdict']} | {b['verdict']} | | "
                     f"{'consistent' if a['verdict'] == b['verdict'] else 'VERSCHIL!'} |")

    lines.append('')

    # --- Conclusie ---
    lines.append('## Conclusie')
    lines.append('')
    for cid in all_cids:
        a = metrics_a['configs'].get(cid)
        b = metrics_b['configs'].get(cid)
        if not a or not b:
            if a and not b:
                lines.append(f'- **{cid}**: alleen in {label_a} (niet in {label_b})')
            elif b and not a:
                lines.append(f'- **{cid}**: alleen in {label_b} (niet in {label_a})')
            continue

        if a['verdict'] == b['verdict'] == 'GO':
            lines.append(f'- **{cid}**: GO op beide caches — strategie generaliseert')
        elif a['verdict'] == 'GO' and b['verdict'] != 'GO':
            lines.append(f'- **{cid}**: GO op {label_a} maar {b["verdict"]} op {label_b} — '
                         f'extra coins in {label_a} dragen de edge')
        elif a['verdict'] != 'GO' and b['verdict'] == 'GO':
            lines.append(f'- **{cid}**: {a["verdict"]} op {label_a} maar GO op {label_b} — '
                         f'extra coins in {label_a} verwateren performance')
        else:
            lines.append(f'- **{cid}**: {a["verdict"]} op {label_a}, {b["verdict"]} op {label_b}')

    lines.append('')

    # --- Interpretatie ---
    lines.append('## Interpretatie')
    lines.append('')
    configs_both = [cid for cid in all_cids
                    if cid in metrics_a['configs'] and cid in metrics_b['configs']]
    all_go_both = all(
        metrics_a['configs'][cid]['verdict'] == 'GO' and
        metrics_b['configs'][cid]['verdict'] == 'GO'
        for cid in configs_both
    ) if configs_both else False

    if all_go_both:
        lines.append(f'De strategie presteert consistent op zowel {label_a} '
                     f'({metrics_a["coin_count"]} coins) als {label_b} '
                     f'({metrics_b["coin_count"]} coins). '
                     'Dit wijst op **generaliseerbaarheid**: de edge is niet afhankelijk van '
                     'een specifieke coinset.')
    else:
        lines.append(f'Er zijn **verschillen** tussen {label_a} en {label_b} resultaten. '
                     'Check per config welke cache de edge levert en of de universes aansluiten.')

    lines.append('')
    lines.append(f'{label_a} en {label_b} bevatten mogelijk verschillende coinsets. ')
    lines.append(f'Als {label_a} significant beter presteert, overweeg de {label_b} pool uit te breiden. ')
    lines.append(f'Als {label_b} beter presteert, verwateren de extra coins in {label_a} de edge.')

    md_path = output_dir / 'report.md'
    with open(md_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  Saved {md_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Compare two cache files via robustness harness')
    parser.add_argument('--cache-a', metavar='PATH',
                        default=str(DEFAULT_CACHE_A),
                        help=f'Cache file A (default: {DEFAULT_CACHE_A.relative_to(ROOT)})')
    parser.add_argument('--cache-b', metavar='PATH',
                        default=str(DEFAULT_CACHE_B),
                        help=f'Cache file B (default: {DEFAULT_CACHE_B.relative_to(ROOT)})')
    parser.add_argument('--label-a', metavar='NAME', default='RESEARCH_ALL',
                        help='Label for cache A (default: RESEARCH_ALL)')
    parser.add_argument('--label-b', metavar='NAME', default='LIVE_CURRENT',
                        help='Label for cache B (default: LIVE_CURRENT)')
    parser.add_argument('--config', '-c', nargs='+', metavar='ID',
                        help='Config IDs to test (default: all candidates)')
    args = parser.parse_args()

    cache_a = Path(args.cache_a)
    cache_b = Path(args.cache_b)

    # Validate cache files exist
    for label, path in [(args.label_a, cache_a), (args.label_b, cache_b)]:
        if not path.exists():
            print(f"ERROR: Cache file for {label} not found: {path}")
            sys.exit(1)

    hash_a = file_hash(cache_a)
    hash_b = file_hash(cache_b)
    coins_a = coin_count(cache_a)
    coins_b = coin_count(cache_b)

    print("=" * 65)
    print(f"  COMPARE CACHES — {args.label_a} vs {args.label_b}")
    print(f"  {datetime.now(AMS).strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  {args.label_a}: {cache_a} ({coins_a} coins, hash: {hash_a})")
    print(f"  {args.label_b}: {cache_b} ({coins_b} coins, hash: {hash_b})")
    if args.config:
        print(f"  Configs: {', '.join(args.config)}")
    print("=" * 65)

    # Run harness twice — different cache files, both --universe all
    dir_a = REPORT_DIR / 'cache_a'
    dir_b = REPORT_DIR / 'cache_b'

    run_harness(cache_a, args.config, dir_a)
    run_harness(cache_b, args.config, dir_b)

    # Load reports and extract metrics
    print(f"\n{'='*65}")
    print("  Generating comparison report...")
    reports_a = load_reports(dir_a)
    reports_b = load_reports(dir_b)

    metrics_a = extract_metrics(reports_a)
    metrics_b = extract_metrics(reports_b)

    write_comparison(metrics_a, metrics_b, args.label_a, args.label_b,
                     hash_a, hash_b, REPORT_DIR)
    print("\n  Done.")


if __name__ == '__main__':
    main()
