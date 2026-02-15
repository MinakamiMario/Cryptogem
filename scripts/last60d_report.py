#!/usr/bin/env python3
"""
Last 60 Days Out-of-Sample Report Generator
============================================
Leest de harness artifacts uit reports/last60d/ en genereert
een compact samenvattend report.json + report.md.

Gebruik: python3 scripts/last60d_report.py [--input-dir reports/last60d]
"""
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo('Europe/Amsterdam')


def load_json(path):
    with open(path) as f:
        return json.load(f)


def build_report(input_dir):
    d = Path(input_dir)
    friction = load_json(d / 'friction_report.json')
    wf = load_json(d / 'wf_report.json')
    mc = load_json(d / 'mc_report.json')
    jitter = load_json(d / 'jitter_report.json')
    universe = load_json(d / 'universe_report.json')

    meta = {
        'generated': datetime.now(AMS).strftime('%Y-%m-%d %H:%M %Z'),
        'dataset': friction.get('dataset', '?'),
        'dataset_hash': friction.get('dataset_hash', '?'),
        'seed': friction.get('seed', 42),
    }

    configs = {}
    for cid in friction['results']:
        fric = friction['results'][cid]
        wf_r = wf['results'].get(cid, {})
        mc_r = mc['results'].get(cid, {})
        jit_r = jitter['results'].get(cid, {})
        univ_r = universe['results'].get(cid, {})

        # Baseline = friction 1.0x_fee+0bps
        base = fric['matrix'].get('1.0x_fee+0bps', {})

        # Friction ladder
        ladder = {}
        for key in ['1.0x_fee+0bps', '1.0x_fee+10bps', '1.0x_fee+20bps', '1.0x_fee+35bps',
                     '2.0x_fee+0bps', '2.0x_fee+10bps', '2.0x_fee+20bps', '2.0x_fee+35bps',
                     '3.0x_fee+0bps', '3.0x_fee+10bps', '3.0x_fee+20bps', '3.0x_fee+35bps',
                     '2x_fee+1candle_gap']:
            if key in fric['matrix']:
                r = fric['matrix'][key]
                ladder[key] = {
                    'pnl': r['pnl'],
                    'wr': r['wr'],
                    'dd': r['dd'],
                    'positive': r['pnl'] > 0,
                }

        # Concentration
        conc = univ_r.get('concentration', {})

        configs[cid] = {
            'baseline': {
                'trades': base.get('trades', 0),
                'pnl': base.get('pnl', 0),
                'wr': base.get('wr', 0),
                'dd': base.get('dd', 0),
                'pf': base.get('pf', 0),
            },
            'walk_forward': {
                'label': wf_r.get('wf_label', '?'),
                'passed': wf_r.get('passed_folds', 0),
                'n_folds': wf_r.get('n_folds', 5),
                'go': wf_r.get('go', False),
            },
            'friction_ladder': ladder,
            'friction_1candle': ladder.get('2x_fee+1candle_gap', {}),
            'friction_go_pnl': fric.get('go_pnl', 0),
            'monte_carlo': {
                'win_pct': mc_r.get('equity', {}).get('win_pct', 0),
                'median_equity': mc_r.get('equity', {}).get('median', 0),
                'p95_dd': mc_r.get('max_dd', {}).get('p95', 0),
                'ruin_pct': mc_r.get('ruin_prob_pct', 0),
                'go': mc_r.get('go', False),
            },
            'jitter': {
                'positive_pct': jit_r.get('positive_pct', 0),
                'worst_pnl': jit_r.get('worst_pnl', 0),
                'median_pnl': jit_r.get('median_pnl', 0),
                'go': jit_r.get('go', False),
            },
            'concentration': {
                'top1_coin': conc.get('top1_coin', '?'),
                'top1_share': conc.get('top1_share', 0),
                'top3_share': conc.get('top3_share', 0),
                'notop_pnl': conc.get('notop_pnl', 0),
            },
            'verdict': 'GO' if all([
                wf_r.get('go', False),
                fric.get('go', False),
                mc_r.get('go', False),
                jit_r.get('go', False),
                univ_r.get('go', False),
            ]) else 'NO-GO',
        }

    return {'meta': meta, 'configs': configs}


def write_report_json(report, output_dir):
    path = Path(output_dir) / 'report.json'
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"  💾 {path}")


def write_report_md(report, output_dir):
    meta = report['meta']
    lines = [
        '# Last 60 Days Out-of-Sample Report',
        f'Generated: {meta["generated"]}',
        f'Dataset: `{meta["dataset"]}` (hash: `{meta["dataset_hash"]}`)',
        f'Seed: {meta["seed"]}',
        '',
        '## Summary',
        '',
        '| Config | Tr | P&L | WR | PF | DD | WF | Fric 2x+20bps | MC ruin | Jitter | Top1% | Verdict |',
        '|--------|-----|------|-----|-----|-----|-----|---------------|---------|--------|-------|---------|',
    ]

    for cid, c in report['configs'].items():
        b = c['baseline']
        wf = c['walk_forward']
        fric_go = c['friction_go_pnl']
        mc = c['monte_carlo']
        jit = c['jitter']
        conc = c['concentration']
        v = c['verdict']
        sym = '🟢' if v == 'GO' else '🔴'
        lines.append(
            f"| {cid} | {b['trades']} | ${b['pnl']:.0f} | {b['wr']}% | {b['pf']} | "
            f"{b['dd']}% | {wf['label']} | ${fric_go:.0f} | {mc['ruin_pct']}% | "
            f"{jit['positive_pct']}% | {conc['top1_share']*100:.0f}% | {sym} {v} |"
        )

    lines.append('')

    # Detail per config
    for cid, c in report['configs'].items():
        b = c['baseline']
        lines.append(f'## {cid}')
        lines.append('')
        lines.append(f'**Baseline**: {b["trades"]}tr, ${b["pnl"]:.2f}, WR {b["wr"]}%, '
                     f'PF {b["pf"]}, DD {b["dd"]}%')
        lines.append('')

        # Friction ladder
        lines.append('**Fees × Slippage Ladder**:')
        lines.append('| Scenario | P&L | WR | DD | OK |')
        lines.append('|----------|------|-----|-----|-----|')
        for key, r in c['friction_ladder'].items():
            sym = '✅' if r['positive'] else '❌'
            lines.append(f"| {key} | ${r['pnl']:.0f} | {r['wr']}% | {r['dd']}% | {sym} |")
        lines.append('')

        # MC
        mc = c['monte_carlo']
        lines.append(f'**Monte Carlo**: win% {mc["win_pct"]}%, p95DD {mc["p95_dd"]}%, '
                     f'ruin {mc["ruin_pct"]}%, median equity ${mc["median_equity"]:.0f}')
        lines.append('')

        # Jitter
        jit = c['jitter']
        lines.append(f'**Param Jitter**: {jit["positive_pct"]}% positief, '
                     f'worst ${jit["worst_pnl"]:.0f}, median ${jit["median_pnl"]:.0f}')
        lines.append('')

        # Concentration
        conc = c['concentration']
        lines.append(f'**Coin Concentratie**: top1={conc["top1_coin"]} '
                     f'{conc["top1_share"]*100:.1f}%, top3 {conc["top3_share"]*100:.1f}%, '
                     f'noTop ${conc["notop_pnl"]:.0f}')
        lines.append('')

    path = Path(output_dir) / 'report.md'
    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  💾 {path}")


def main():
    parser = argparse.ArgumentParser(description='Last 60 Days Report Generator')
    parser.add_argument('--input-dir', default='reports/last60d',
                        help='Directory with harness artifacts')
    args = parser.parse_args()

    print(f"Generating last-60d report from {args.input_dir}...")
    report = build_report(args.input_dir)
    write_report_json(report, args.input_dir)
    write_report_md(report, args.input_dir)
    print("Done.")


if __name__ == '__main__':
    main()
