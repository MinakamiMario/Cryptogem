#!/usr/bin/env python3
"""
Slippage Regime Stress Tests
=============================
Test strategy survival under various fee and slippage regimes.

Regimes (13 per universe x config combo):
  - Fee multipliers: x1, x2, x3  (base fee = 0.0026 per side)
  - Slippage: 0, 10, 20, 35 bps per side
  - Special: "1-candle-later fill" = 2x fees + 50bps gap

Verdicts:
  GO      - positive at 2x fees+20bps AND at 1-candle-later
  SOFT-GO - positive at 2x fees+20bps BUT negative at 1-candle-later
  NO-GO   - negative at 2x fees+20bps
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    START_BAR, INITIAL_CAPITAL, KRAKEN_FEE
)

CONFIGS = {
    'C1': {
        'exit_type': 'tp_sl', 'max_pos': 1, 'rsi_max': 45,
        'sl_pct': 15, 'time_max_bars': 15, 'tp_pct': 15,
        'vol_confirm': True, 'vol_spike_mult': 3.0,
    },
    'GRID_BEST': {
        'exit_type': 'tp_sl', 'max_pos': 1, 'rsi_max': 45,
        'sl_pct': 10, 'time_max_bars': 15, 'tp_pct': 12,
        'vol_confirm': True, 'vol_spike_mult': 2.5,
    },
}

UNIVERSES = {
    'TRADEABLE': Path('/Users/oussama/Cryptogem/data/candle_cache_tradeable.json'),
    'LIVE_CURRENT': Path('/Users/oussama/Cryptogem/trading_bot/candle_cache_532.json'),
}

FEE_MULTS = [1, 2, 3]
SLIPPAGE_BPS = [0, 10, 20, 35]


def build_regimes():
    regimes = []
    for fm in FEE_MULTS:
        for sb in SLIPPAGE_BPS:
            label = f"{fm}x_fees_{sb}bps"
            eff_fee = KRAKEN_FEE * fm + sb / 10_000
            regimes.append({
                'label': label, 'fee_mult': fm, 'slippage_bps': sb,
                'effective_fee': eff_fee, 'special': False,
            })
    eff_fee_special = KRAKEN_FEE * 2 + 0.005
    regimes.append({
        'label': '1_candle_later', 'fee_mult': 2, 'slippage_bps': 50,
        'effective_fee': eff_fee_special, 'special': True,
    })
    return regimes


def find_breakeven_bps(indicators, coins, cfg, fee_mult=2):
    last_positive = -1
    for bps in range(0, 201, 5):
        eff_fee = KRAKEN_FEE * fee_mult + bps / 10_000
        result = run_backtest(indicators, coins, cfg, fee_override=eff_fee)
        if result['pnl'] > 0:
            last_positive = bps
        else:
            if last_positive >= 0:
                for fine_bps in range(last_positive, bps + 1):
                    eff = KRAKEN_FEE * fee_mult + fine_bps / 10_000
                    r = run_backtest(indicators, coins, cfg, fee_override=eff)
                    if r['pnl'] <= 0:
                        return fine_bps - 1 if fine_bps > 0 else 0
            return last_positive
    return last_positive


def run_all():
    regimes = build_regimes()
    results = {}
    t0 = time.time()

    for uni_name, uni_path in UNIVERSES.items():
        print(f"\n{'='*70}")
        print(f"  UNIVERSE: {uni_name}")
        print(f"  File: {uni_path}")
        print(f"{'='*70}")

        with open(uni_path) as f:
            data = json.load(f)
        coins = sorted(k for k in data.keys() if not k.startswith("_"))
        print(f"  Coins: {len(coins)}")

        print("  Precomputing indicators...")
        t_pre = time.time()
        indicators = precompute_all(data, coins)
        print(f"  Done in {time.time()-t_pre:.1f}s")

        results[uni_name] = {}

        for cfg_name, cfg in CONFIGS.items():
            print(f"\n  CONFIG: {cfg_name}")
            cfg_results = []

            for regime in regimes:
                r = run_backtest(indicators, coins, cfg,
                                 fee_override=regime['effective_fee'])
                entry = {
                    'regime': regime['label'],
                    'effective_fee': round(regime['effective_fee'], 6),
                    'effective_fee_pct': round(regime['effective_fee'] * 100, 4),
                    'fee_mult': regime['fee_mult'],
                    'slippage_bps': regime['slippage_bps'],
                    'special': regime['special'],
                    'trades': r['trades'],
                    'pnl': round(r['pnl'], 2),
                    'wr': round(r['wr'], 1),
                    'pf': round(r['pf'], 2) if r['pf'] != float('inf') else 999.99,
                    'dd': round(r['dd'], 1),
                    'pass': r['pnl'] > 0,
                }
                cfg_results.append(entry)
                status = 'PASS' if entry['pass'] else 'FAIL'
                print(f"    {regime['label']:>20s}  fee={entry['effective_fee_pct']:.3f}%  "
                      f"trades={entry['trades']:3d}  P&L=${entry['pnl']:>8.2f}  "
                      f"WR={entry['wr']:.1f}%  PF={entry['pf']:.2f}  DD={entry['dd']:.1f}%  "
                      f"[{status}]")

            print(f"\n    Breakeven analysis (at 2x fees)...")
            be_bps = find_breakeven_bps(indicators, coins, cfg)
            print(f"    Breakeven slippage at 2x fees: {be_bps} bps")

            ref_2x_20 = next((r for r in cfg_results
                              if r['fee_mult'] == 2 and r['slippage_bps'] == 20
                              and not r['special']), None)
            ref_1candle = next((r for r in cfg_results if r['special']), None)

            if ref_2x_20 and ref_2x_20['pass']:
                if ref_1candle and ref_1candle['pass']:
                    verdict = 'GO'
                else:
                    verdict = 'SOFT-GO'
            else:
                verdict = 'NO-GO'

            print(f"\n    VERDICT: {verdict}")

            results[uni_name][cfg_name] = {
                'regimes': cfg_results,
                'breakeven_bps_at_2x': be_bps,
                'verdict': verdict,
            }

    elapsed = time.time() - t0
    print(f"\n\nTotal runtime: {elapsed:.1f}s")

    report_dir = Path('/Users/oussama/Cryptogem/reports')
    report_dir.mkdir(exist_ok=True)

    json_path = report_dir / 'slippage_regimes.json'
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Saved: {json_path}")

    md = generate_markdown(results, elapsed)
    md_path = report_dir / 'slippage_regimes.md'
    with open(md_path, 'w') as f:
        f.write(md)
    print(f"Saved: {md_path}")

    return results


def generate_markdown(results, elapsed):
    lines = [
        '# Slippage Regime Stress Test Report',
        f'*Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*',
        f'*Runtime: {elapsed:.1f}s*',
        '',
        '## Methodology',
        f'- Base fee: {KRAKEN_FEE*100:.2f}% per side (Kraken taker)',
        f'- Fee multipliers: {FEE_MULTS}',
        f'- Slippage: {SLIPPAGE_BPS} bps per side',
        f'- Special: 1-candle-later fill = 2x fees + 50bps gap (eff. fee = {KRAKEN_FEE*2 + 0.005:.4f} = {(KRAKEN_FEE*2+0.005)*100:.3f}% per side)',
        f'- Initial capital: ${INITIAL_CAPITAL:,}',
        '',
        '## Verdicts Legend',
        '- **GO**: Positive P&L at 2x fees + 20bps AND at 1-candle-later fill',
        '- **SOFT-GO**: Positive at 2x fees + 20bps BUT negative at 1-candle-later',
        '- **NO-GO**: Negative at 2x fees + 20bps',
        '',
    ]

    for uni_name, uni_data in results.items():
        lines.append('---')
        lines.append(f'## Universe: {uni_name}')
        lines.append('')

        for cfg_name, cfg_data in uni_data.items():
            verdict = cfg_data['verdict']
            be = cfg_data['breakeven_bps_at_2x']

            lines.append(f'### Config: {cfg_name} -- [{verdict}]')
            lines.append('')
            lines.append(f'Breakeven slippage at 2x fees: **{be} bps**')
            lines.append('')
            lines.append('| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass/Fail |')
            lines.append('|--------|---------|--------|-----|-----|----|-----|-----------|')

            for r in cfg_data['regimes']:
                pf_str = f"{r['pf']:.2f}" if r['pf'] < 999 else 'inf'
                status = 'PASS' if r['pass'] else 'FAIL'
                label = r['regime']
                if r['special']:
                    label = '**1-candle-later**'
                lines.append(
                    f"| {label} | {r['effective_fee_pct']:.3f}% | "
                    f"{r['trades']} | ${r['pnl']:,.2f} | "
                    f"{r['wr']:.1f}% | {pf_str} | {r['dd']:.1f}% | {status} |"
                )
            lines.append('')

        lines.append('')

    lines.append('---')
    lines.append('## Summary')
    lines.append('')
    lines.append('| Universe | Config | Verdict | Breakeven (2x fees) | P&L @baseline | P&L @2x+20bps | P&L @1-candle |')
    lines.append('|----------|--------|---------|---------------------|---------------|---------------|---------------|')

    for uni_name, uni_data in results.items():
        for cfg_name, cfg_data in uni_data.items():
            v = cfg_data['verdict']
            be = cfg_data['breakeven_bps_at_2x']
            regs = cfg_data['regimes']
            baseline = next((r for r in regs if r['fee_mult'] == 1 and r['slippage_bps'] == 0), None)
            ref_2x20 = next((r for r in regs if r['fee_mult'] == 2 and r['slippage_bps'] == 20 and not r['special']), None)
            ref_1c = next((r for r in regs if r['special']), None)
            bl_pnl = f"${baseline['pnl']:,.2f}" if baseline else 'N/A'
            r2_pnl = f"${ref_2x20['pnl']:,.2f}" if ref_2x20 else 'N/A'
            r1_pnl = f"${ref_1c['pnl']:,.2f}" if ref_1c else 'N/A'
            lines.append(f"| {uni_name} | {cfg_name} | [{v}] | {be} bps | {bl_pnl} | {r2_pnl} | {r1_pnl} |")

    lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    run_all()
