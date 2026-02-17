"""
Screening Report Writer — JSON + Markdown
==========================================
Generates structured reports for Layer 1 screening and Layer 2 promotion results.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


REPORTS_DIR = Path(__file__).parent.parent.parent.parent / 'reports' / 'hf' / 'screening'


def ensure_reports_dir():
    """Create reports directory if it doesn't exist."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Layer 1 — Screening Report
# ============================================================

def write_screen_json(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """
    Write Layer 1 screening results to JSON.

    results: list of dicts, each with:
        hypothesis_id, variant_idx, params,
        trades, pnl, pf, wr, dd,
        expectancy, wf_positive, wf_folds,
        top1_pct, top3_pct,
        gate_results: {S1: bool, S1b: bool, S2: bool, S3: bool, S4: bool, S5: bool},
        killed: bool, score: float,
        tier_results: {tier1: {...}, tier2: {...}}
    meta: dict with timestamp, timeframe, universe info, runtime_s, etc.
    """
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'screen_001.json'

    output = {
        'meta': meta,
        'results': results,
        'summary': _build_screen_summary(results),
    }

    path.write_text(json.dumps(output, indent=2, default=str))
    return path


def write_screen_md(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """Write Layer 1 screening results to Markdown."""
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'screen_001.md'

    summary = _build_screen_summary(results)
    survivors = [r for r in results if not r.get('killed', True)]
    killed = [r for r in results if r.get('killed', True)]

    lines = []
    lines.append('# Sprint 4 — Layer 1 Screening Report')
    lines.append('')
    lines.append(f'**Date**: {meta.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))}')
    lines.append(f'**Timeframe**: {meta.get("timeframe", "1H")}')
    lines.append(f'**Universe**: T1 ({meta.get("t1_coins", "?")} coins) + T2 ({meta.get("t2_coins", "?")} coins)')
    lines.append(f'**Configs tested**: {summary["total_configs"]}')
    lines.append(f'**Runtime**: {meta.get("runtime_s", 0):.1f}s')
    lines.append('')

    # --- Verdict ---
    lines.append('## Verdict')
    lines.append('')
    if summary['survivors'] > 0:
        lines.append(f'**{summary["survivors"]} survivor(s)** out of {summary["total_configs"]} configs passed KILL gates (S1 + S2).')
    else:
        lines.append(f'**NO SURVIVORS** — all {summary["total_configs"]} configs failed KILL gates.')
        lines.append('')
        lines.append('No hypothesis has a positive expectancy at 1H with sufficient trades.')
    lines.append('')

    # --- Gate Summary Table ---
    lines.append('## Gate Summary')
    lines.append('')
    lines.append('| Gate | Pass | Fail | Rate |')
    lines.append('|------|------|------|------|')
    for gate in ['S1', 'S2', 'S3', 'S4', 'S5']:
        passed = sum(1 for r in results if r.get('gate_results', {}).get(gate, False))
        failed = len(results) - passed
        rate = f'{passed/len(results)*100:.0f}%' if results else '0%'
        lines.append(f'| {gate} | {passed} | {failed} | {rate} |')
    lines.append('')

    # --- Survivors (if any) ---
    if survivors:
        lines.append('## Survivors (passed S1 + S2)')
        lines.append('')
        lines.append('| Rank | ID | Name | Params | Trades | Exp/Trade | PF | WR% | DD% | Score |')
        lines.append('|------|----|------|--------|--------|-----------|----|----|-----|-------|')
        survivors_sorted = sorted(survivors, key=lambda x: x.get('score', 0), reverse=True)
        for i, r in enumerate(survivors_sorted, 1):
            params_str = _params_short(r.get('params', {}))
            lines.append(
                f'| {i} | {r["hypothesis_id"]} | {r.get("name", "")} | {params_str} '
                f'| {r["trades"]} | ${r.get("expectancy", 0):.2f} '
                f'| {r.get("pf", 0):.2f} | {r.get("wr", 0):.1f}% '
                f'| {r.get("dd", 0):.1f}% | {r.get("score", 0):.1f} |'
            )
        lines.append('')

        # Per-tier breakdown for survivors
        lines.append('### Per-Tier Breakdown (Survivors)')
        lines.append('')
        for r in survivors_sorted[:5]:  # top 5
            lines.append(f'**{r["hypothesis_id"]}** ({_params_short(r.get("params", {}))})')
            tier_results = r.get('tier_results', {})
            if tier_results:
                lines.append('')
                lines.append('| Tier | Trades | P&L | PF | Exp/Trade |')
                lines.append('|------|--------|-----|----|-----------|')
                for tier_name in sorted(tier_results.keys()):
                    tr = tier_results[tier_name]
                    exp = tr.get('pnl', 0) / tr.get('trades', 1) if tr.get('trades', 0) > 0 else 0
                    lines.append(
                        f'| {tier_name} | {tr.get("trades", 0)} '
                        f'| ${tr.get("pnl", 0):.2f} | {tr.get("pf", 0):.2f} '
                        f'| ${exp:.2f} |'
                    )
            lines.append('')

    # --- Best Per Hypothesis ---
    lines.append('## Best Variant Per Hypothesis')
    lines.append('')
    lines.append('| ID | Name | Category | Best PF | Best Exp | Trades | Killed? |')
    lines.append('|----|------|----------|---------|----------|--------|---------|')

    by_hyp = {}
    for r in results:
        hid = r['hypothesis_id']
        if hid not in by_hyp or r.get('pf', 0) > by_hyp[hid].get('pf', 0):
            by_hyp[hid] = r

    for hid in sorted(by_hyp.keys()):
        r = by_hyp[hid]
        killed = '❌ KILL' if r.get('killed', True) else '✅'
        lines.append(
            f'| {hid} | {r.get("name", "")} | {r.get("category", "")} '
            f'| {r.get("pf", 0):.2f} | ${r.get("expectancy", 0):.2f} '
            f'| {r.get("trades", 0)} | {killed} |'
        )
    lines.append('')

    # --- Walk-Forward Detail for survivors ---
    if survivors:
        lines.append('## Walk-Forward Detail (Survivors)')
        lines.append('')
        survivors_sorted = sorted(survivors, key=lambda x: x.get('score', 0), reverse=True)
        for r in survivors_sorted[:3]:
            wf = r.get('wf_detail', [])
            if wf:
                lines.append(f'### {r["hypothesis_id"]} ({_params_short(r.get("params", {}))})')
                lines.append('')
                lines.append('| Fold | Trades | P&L | PF | WR% | Positive |')
                lines.append('|------|--------|-----|----|-----|----------|')
                for i, f in enumerate(wf, 1):
                    pos = '✅' if f.get('pnl', 0) > 0 else '❌'
                    lines.append(
                        f'| {i} | {f.get("trades", 0)} | ${f.get("pnl", 0):.2f} '
                        f'| {f.get("pf", 0):.2f} | {f.get("wr", 0):.1f}% | {pos} |'
                    )
                lines.append('')

    # --- Footer ---
    lines.append('---')
    lines.append(f'*Generated by screening/report.py at {datetime.now().strftime("%Y-%m-%d %H:%M")} — Layer 1 screening*')

    path.write_text('\n'.join(lines))
    return path


# ============================================================
# Layer 2 — Promotion Report
# ============================================================

def write_promote_json(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """Write Layer 2 promotion results to JSON."""
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'promote_001.json'

    output = {
        'meta': meta,
        'results': results,
    }

    path.write_text(json.dumps(output, indent=2, default=str))
    return path


def write_promote_md(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """Write Layer 2 promotion results to Markdown."""
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'promote_001.md'

    lines = []
    lines.append('# Sprint 4 — Layer 2 Promotion Report')
    lines.append('')
    lines.append(f'**Date**: {meta.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))}')
    lines.append(f'**Candidates**: {len(results)}')
    lines.append('')

    promoted = [r for r in results if r.get('promoted', False)]

    if promoted:
        lines.append(f'## {len(promoted)} PROMOTED for 15m build')
    else:
        lines.append('## NO candidates promoted')
        lines.append('')
        lines.append('All candidates failed Layer 2 promotion gates.')
    lines.append('')

    for r in results:
        hid = r.get('hypothesis_id', '?')
        lines.append(f'### {hid} — {"✅ PROMOTED" if r.get("promoted") else "❌ FAILED"}')
        lines.append('')

        gates = r.get('gate_results', {})
        lines.append('| Gate | Threshold | Result | Value |')
        lines.append('|------|-----------|--------|-------|')
        for gate_id, gate_info in sorted(gates.items()):
            status = '✅' if gate_info.get('passed', False) else '❌'
            lines.append(
                f'| {gate_id} | {gate_info.get("threshold", "")} '
                f'| {status} | {gate_info.get("value", "")} |'
            )
        lines.append('')

    lines.append('---')
    lines.append(f'*Generated by screening/report.py at {datetime.now().strftime("%Y-%m-%d %H:%M")} — Layer 2 promotion*')

    path.write_text('\n'.join(lines))
    return path


# ============================================================
# Sprint 5 — Layer 1 Screening Report (enhanced scoreboard)
# ============================================================

def write_screen_s5_json(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """
    Write Sprint 5 Layer 1 screening results to JSON.

    Same structure as write_screen_json but defaults to screen_s5_001.json
    and includes Sprint 5 summary with KILL gate stats.
    """
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'screen_s5_001.json'

    output = {
        'meta': meta,
        'results': results,
        'summary': _build_screen_summary(results),
        'summary_s5': _build_s5_summary(results),
    }

    path.write_text(json.dumps(output, indent=2, default=str))
    return path


def write_screen_s5_md(results: list, meta: dict, path: Optional[Path] = None) -> Path:
    """Write Sprint 5 Layer 1 screening results to Markdown with enhanced scoreboard."""
    ensure_reports_dir()
    if path is None:
        path = REPORTS_DIR / 'screen_s5_001.md'

    summary = _build_screen_summary(results)
    s5_summary = _build_s5_summary(results)
    survivors = [r for r in results if not r.get('killed', True)]

    # --- Coverage info ---
    vwap_cov = meta.get('vwap_coverage', {})
    count_cov = meta.get('count_coverage', {})
    vwap_pct = vwap_cov.get('vwap_pct', 0)
    vwap_available = vwap_cov.get('vwap_available', 0)
    count_pct = count_cov.get('count_pct', 0)
    count_available = count_cov.get('count_available', 0)
    total_coins = meta.get('t1_coins', 0) + meta.get('t2_coins', 0)

    lines = []
    lines.append('# Sprint 5 — Layer 1 Screening Report')
    lines.append('')
    lines.append(f'**Date**: {meta.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))}')
    lines.append(f'**Timeframe**: {meta.get("timeframe", "1H")}')
    lines.append(f'**Universe**: T1 ({meta.get("t1_coins", "?")} coins) + T2 ({meta.get("t2_coins", "?")} coins)')
    lines.append(f'**Configs tested**: {summary["total_configs"]}')
    lines.append(f'**Runtime**: {meta.get("runtime_s", 0):.1f}s')
    lines.append(f'**VWAP coverage**: {vwap_pct:.0f}% ({vwap_available}/{total_coins} coins)')
    lines.append(f'**Count coverage**: {count_pct:.0f}% ({count_available}/{total_coins} coins)')
    lines.append('')

    # --- Verdict ---
    lines.append('## Verdict')
    lines.append('')
    if summary['survivors'] > 0:
        lines.append(f'**{summary["survivors"]} survivor(s)** out of {summary["total_configs"]} configs passed Sprint 5 KILL gates.')
    else:
        lines.append(f'**NO SURVIVORS** — all {summary["total_configs"]} configs failed Sprint 5 KILL gates.')
        lines.append('')
        lines.append('No hypothesis has a positive expectancy at 1H with sufficient trades.')
    lines.append('')

    # --- Sprint 5 KILL Gates ---
    lines.append('## Sprint 5 KILL Gates')
    lines.append('')
    lines.append('| Gate | Criteria | Pass | Fail |')
    lines.append('|------|----------|------|------|')
    for gate_key, gate_label in [
        ('K1_exp_week', 'exp/week > $0'),
        ('K2_trades_week', 'trades/week >= 7'),
        ('K3_be_ratio', 'be_trade_ratio < 40%'),
    ]:
        passed = s5_summary['kill_gates'].get(gate_key, {}).get('passed', 0)
        failed = s5_summary['kill_gates'].get(gate_key, {}).get('failed', 0)
        lines.append(f'| {gate_key} | {gate_label} | {passed} | {failed} |')
    lines.append('')

    # --- Scoreboard ---
    lines.append('## Scoreboard')
    lines.append('')
    lines.append(
        '| Rank | ID | Name | Cat | Trades | tr/wk | exp/tr | exp/wk '
        '| PF | WR% | DD% | fee_drag% | be_ratio% | stress$ | WF+ | Score | Kill |'
    )
    lines.append(
        '|------|----|------|-----|--------|-------|--------|--------'
        '|----|----|-----|-----------|-----------|---------|-----|-------|------|'
    )

    results_sorted = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    for i, r in enumerate(results_sorted, 1):
        killed_str = '❌' if r.get('killed', True) else '✅'
        wf_pos = r.get('wf_positive', 0)
        wf_folds = r.get('wf_folds', 5)
        lines.append(
            f'| {i} '
            f'| {r.get("hypothesis_id", "")} '
            f'| {r.get("name", "")} '
            f'| {r.get("category", "")} '
            f'| {r.get("trades", 0)} '
            f'| {_fmt_float(r.get("trades_per_week"), "{:.1f}")} '
            f'| ${r.get("expectancy", 0):.2f} '
            f'| {_fmt_dollar(r.get("exp_per_week"))} '
            f'| {r.get("pf", 0):.2f} '
            f'| {r.get("wr", 0):.1f}% '
            f'| {r.get("dd", 0):.1f}% '
            f'| {_fmt_pct(r.get("fee_drag_pct"))} '
            f'| {_fmt_pct(r.get("be_trade_ratio"))} '
            f'| {_fmt_dollar(r.get("stress_2x_pnl"))} '
            f'| {wf_pos}/{wf_folds} '
            f'| {r.get("score", 0):.1f} '
            f'| {killed_str} |'
        )
    lines.append('')

    # --- Best Variant Per Hypothesis ---
    lines.append('## Best Variant Per Hypothesis')
    lines.append('')
    lines.append(
        '| ID | Name | Category | Best PF | Best Exp | tr/wk | exp/wk '
        '| fee_drag% | be_ratio% | stress$ | Trades | Killed? |'
    )
    lines.append(
        '|----|------|----------|---------|----------|-------|--------'
        '|-----------|-----------|---------|--------|---------|'
    )

    by_hyp = {}
    for r in results:
        hid = r.get('hypothesis_id', '?')
        if hid not in by_hyp or r.get('pf', 0) > by_hyp[hid].get('pf', 0):
            by_hyp[hid] = r

    for hid in sorted(by_hyp.keys()):
        r = by_hyp[hid]
        killed = '❌ KILL' if r.get('killed', True) else '✅'
        lines.append(
            f'| {hid} '
            f'| {r.get("name", "")} '
            f'| {r.get("category", "")} '
            f'| {r.get("pf", 0):.2f} '
            f'| ${r.get("expectancy", 0):.2f} '
            f'| {_fmt_float(r.get("trades_per_week"), "{:.1f}")} '
            f'| {_fmt_dollar(r.get("exp_per_week"))} '
            f'| {_fmt_pct(r.get("fee_drag_pct"))} '
            f'| {_fmt_pct(r.get("be_trade_ratio"))} '
            f'| {_fmt_dollar(r.get("stress_2x_pnl"))} '
            f'| {r.get("trades", 0)} '
            f'| {killed} |'
        )
    lines.append('')

    # --- Walk-Forward Detail for survivors ---
    if survivors:
        lines.append('## Walk-Forward Detail (Survivors)')
        lines.append('')
        survivors_sorted = sorted(survivors, key=lambda x: x.get('score', 0), reverse=True)
        for r in survivors_sorted[:5]:
            wf = r.get('wf_detail', [])
            if wf:
                lines.append(f'### {r["hypothesis_id"]} ({_params_short(r.get("params", {}))})')
                lines.append('')
                lines.append('| Fold | Trades | P&L | PF | WR% | Positive |')
                lines.append('|------|--------|-----|----|-----|----------|')
                for i, f in enumerate(wf, 1):
                    pos = '✅' if f.get('pnl', 0) > 0 else '❌'
                    lines.append(
                        f'| {i} | {f.get("trades", 0)} | ${f.get("pnl", 0):.2f} '
                        f'| {f.get("pf", 0):.2f} | {f.get("wr", 0):.1f}% | {pos} |'
                    )
                lines.append('')

    # --- Footer ---
    lines.append('---')
    lines.append(
        f'*Generated by screening/report.py at {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        f' — Sprint 5 Layer 1 screening*'
    )

    path.write_text('\n'.join(lines))
    return path


# ============================================================
# Helpers
# ============================================================

def _build_screen_summary(results: list) -> dict:
    """Build summary statistics from screening results."""
    survivors = [r for r in results if not r.get('killed', True)]
    return {
        'total_configs': len(results),
        'survivors': len(survivors),
        'killed': len(results) - len(survivors),
        'best_pf': max((r.get('pf', 0) for r in results), default=0),
        'best_expectancy': max((r.get('expectancy', 0) for r in results), default=0),
        'max_trades': max((r.get('trades', 0) for r in results), default=0),
        'gate_pass_rates': {
            gate: sum(1 for r in results if r.get('gate_results', {}).get(gate, False)) / max(len(results), 1)
            for gate in ['S1', 'S1b', 'S2', 'S3', 'S4', 'S5']
        },
    }


def _params_short(params: dict) -> str:
    """Short string representation of params for table display."""
    # Exclude common fixed params from display
    skip = {'tp_pct', 'sl_pct', 'time_limit', 'macd_slow', 'macd_signal'}
    parts = []
    for k, v in sorted(params.items()):
        if k in skip:
            continue
        if isinstance(v, float):
            parts.append(f'{k}={v:.1f}')
        else:
            parts.append(f'{k}={v}')
    return ', '.join(parts) if parts else str(params)


def _build_s5_summary(results: list) -> dict:
    """Build Sprint 5 summary with KILL gate statistics."""
    n = max(len(results), 1)
    kill_gates = {}
    for gate_key in ['K1_exp_week', 'K2_trades_week', 'K3_be_ratio']:
        passed = sum(
            1 for r in results
            if r.get('gate_results', {}).get(gate_key, False)
        )
        kill_gates[gate_key] = {
            'passed': passed,
            'failed': len(results) - passed,
            'rate': passed / n,
        }

    soft_gates = {}
    for gate_key in ['S3', 'S4', 'S5']:
        passed = sum(
            1 for r in results
            if r.get('gate_results', {}).get(gate_key, False)
        )
        soft_gates[gate_key] = {
            'passed': passed,
            'failed': len(results) - passed,
            'rate': passed / n,
        }

    return {
        'kill_gates': kill_gates,
        'soft_gates': soft_gates,
        'avg_trades_per_week': (
            sum(r.get('trades_per_week', 0) for r in results) / n
        ),
        'avg_exp_per_week': (
            sum(r.get('exp_per_week', 0) for r in results) / n
        ),
        'avg_fee_drag_pct': (
            sum(r.get('fee_drag_pct', 0) for r in results) / n
        ),
        'avg_be_trade_ratio': (
            sum(r.get('be_trade_ratio', 0) for r in results) / n
        ),
    }


def _fmt_float(value, fmt: str = '{:.1f}') -> str:
    """Format a float value, returning 'N/A' if None."""
    if value is None:
        return 'N/A'
    try:
        return fmt.format(value)
    except (TypeError, ValueError):
        return 'N/A'


def _fmt_dollar(value) -> str:
    """Format a value as $X.XX, returning 'N/A' if None."""
    if value is None:
        return 'N/A'
    try:
        return f'${value:.2f}'
    except (TypeError, ValueError):
        return 'N/A'


def _fmt_pct(value) -> str:
    """Format a value as X.X%, returning 'N/A' if None."""
    if value is None:
        return 'N/A'
    try:
        return f'{value:.1f}%'
    except (TypeError, ValueError):
        return 'N/A'
