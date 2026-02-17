#!/usr/bin/env python3
"""
4H Scoreboard Builder — Aggregates sweep results into a ranked scoreboard.

Reads all reports/4h/sweep_v1_*/results.json, applies ranking rules,
and produces scoreboard_sweep_v1.{json,md}.

Usage:
    python scripts/build_4h_scoreboard.py
    python scripts/build_4h_scoreboard.py --sweep-dir reports/4h --prefix sweep_v1_
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_hash() -> str:
    """Return short git commit hash, or 'unknown' if not in a repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5,
            cwd=str(REPO_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def _extract_idx(run_id: str, prefix: str) -> str:
    """Extract 3-digit index from run_id.

    sweep_v1_001_trail_rsi38_abc1234 -> '001'
    Falls back to the directory position if pattern doesn't match.
    """
    # Strip prefix, then take leading digits
    suffix = run_id
    if run_id.startswith(prefix):
        suffix = run_id[len(prefix):]
    m = re.match(r'(\d{1,4})', suffix)
    return m.group(1) if m else '???'


def _extract_label(run_id: str, prefix: str) -> str:
    """Extract human-readable label from run_id.

    sweep_v1_001_trail_rsi38_abc1234 -> 'trail_rsi38'
    Strips prefix + idx + trailing git hash.
    """
    suffix = run_id
    if run_id.startswith(prefix):
        suffix = run_id[len(prefix):]

    # Remove leading digits + underscore
    suffix = re.sub(r'^\d{1,4}_?', '', suffix)

    # Remove trailing _<7-char-hex> git hash
    suffix = re.sub(r'_[0-9a-f]{7}$', '', suffix)

    return suffix if suffix else run_id


def _load_sweep_plan(plan_path: Path) -> tuple[dict, dict]:
    """Load sweep plan and build idx -> block mapping + extract provenance metadata.

    Returns (block_map, provenance) where provenance contains:
      dataset_id, fee_model_id, universe_id, time_window, initial_capital, etc.
    """
    if not plan_path.exists():
        return {}, {}
    try:
        with open(plan_path) as f:
            plan = json.load(f)
        # Plan can be a list of configs or a dict with 'configs' key
        configs = plan if isinstance(plan, list) else plan.get('configs', [])
        mapping = {}
        for entry in configs:
            idx = str(entry.get('idx', '')).zfill(3)
            block = entry.get('block', '')
            mapping[idx] = block

        # Extract provenance from sweep plan metadata
        provenance = {}
        ds = plan.get('data_source', {}) if isinstance(plan, dict) else {}
        if ds:
            provenance['dataset_id'] = ds.get('registry_id', ds.get('dataset_id', ''))
            provenance['source'] = ds.get('source', '')
            provenance['venue'] = ds.get('venue', '')
            provenance['exchange'] = ds.get('exchange', '')
            provenance['fee_bps_per_side'] = ds.get('fee_bps_per_side')
            provenance['coins'] = ds.get('coins')
            provenance['bars'] = ds.get('bars')
            provenance['time_range'] = ds.get('range', '')
        # Also check top-level keys
        if isinstance(plan, dict):
            provenance.setdefault('dataset_id', plan.get('dataset_id', ''))
            provenance['sweep_version'] = plan.get('version', '')
            provenance['sweep_description'] = plan.get('description', '')
        # Clean empty strings
        provenance = {k: v for k, v in provenance.items() if v not in ('', None)}

        return mapping, provenance
    except (json.JSONDecodeError, KeyError):
        return {}, {}


def _load_run(run_dir: Path, prefix: str, block_map: dict) -> dict | None:
    """Load a single run's results.json and optional gates.json.

    Returns a normalized row dict or None if the run is broken.
    """
    results_path = run_dir / 'results.json'
    if not results_path.exists():
        return None

    try:
        with open(results_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARN: Skipping {run_dir.name} — broken JSON: {e}", file=sys.stderr)
        return None

    run_id = run_dir.name
    meta = data.get('metadata', {})
    summary = data.get('summary', {})

    # Extract identifiers
    idx = _extract_idx(run_id, prefix)
    label = _extract_label(run_id, prefix)

    # Core metrics
    trades = summary.get('trades', 0)
    wr = summary.get('wr', 0.0)
    pnl = summary.get('pnl', 0.0)
    pf = summary.get('pf', 0.0)
    dd = summary.get('dd', 0.0)
    ev_per_trade = round(pnl / trades, 2) if trades > 0 else 0.0

    # Exit type: from metadata config_source, or from params.json
    exit_type = ''
    params_path = run_dir / 'params.json'
    if params_path.exists():
        try:
            with open(params_path) as f:
                params = json.load(f)
            exit_type = params.get('exit_type', '')
        except (json.JSONDecodeError, OSError):
            pass
    if not exit_type:
        exit_type = meta.get('config_source', '')

    # Block from sweep plan
    block = block_map.get(idx, '')

    # Gate verdicts: prefer gates.json, fall back to embedded gate data
    gates_path = run_dir / 'gates.json'
    verdict = ''
    gate_details = {}

    if gates_path.exists():
        try:
            with open(gates_path) as f:
                gates_data = json.load(f)
            verdict = gates_data.get('verdict', '')
            # Build G1..G5 pass/fail map
            for g in gates_data.get('gates', []):
                # Gate name format: "G1:MIN_TRADES"
                gname = g.get('name', '')
                short = gname.split(':')[0] if ':' in gname else gname
                gate_details[short] = g.get('passed', False)
        except (json.JSONDecodeError, OSError):
            pass

    # If no gates.json, check if results.json has embedded gate info
    if not verdict:
        embedded_gates = data.get('gates', {})
        if embedded_gates:
            verdict = embedded_gates.get('verdict', '')
            for g in embedded_gates.get('gates', []):
                gname = g.get('name', '')
                short = gname.split(':')[0] if ':' in gname else gname
                gate_details[short] = g.get('passed', False)

    # Normalize gate keys to G1..G5
    gates_map = {}
    for i in range(1, 6):
        key = f'G{i}'
        gates_map[key] = gate_details.get(key, None)  # None = not evaluated

    return {
        'run_id': run_id,
        'idx': idx,
        'label': label,
        'exit_type': exit_type,
        'block': block,
        'trades': trades,
        'wr': round(wr, 1),
        'pnl': round(pnl, 2),
        'pf': round(min(pf, 99.99), 2) if pf != float('inf') else 99.99,
        'dd': round(dd, 1),
        'ev_per_trade': ev_per_trade,
        'verdict': verdict,
        'gates': gates_map,
    }


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _rank_results(rows: list[dict]) -> list[dict]:
    """Apply ranking rules to GO configs and assign rank numbers.

    Ranking rules (from contract):
    1. Filter: only verdict == 'GO'
    2. Primary sort: pf descending
    3. Tiebreaker 1: ev_per_trade descending
    4. Tiebreaker 2: dd ascending
    5. Tiebreaker 3: trades descending
    """
    go_rows = [r for r in rows if r['verdict'] == 'GO']

    go_rows.sort(key=lambda r: (
        -r['pf'],
        -r['ev_per_trade'],
        r['dd'],
        -r['trades'],
    ))

    for i, row in enumerate(go_rows, 1):
        row['rank'] = i

    # Non-GO configs get no rank
    for r in rows:
        if r['verdict'] != 'GO':
            r['rank'] = None

    return go_rows


# ---------------------------------------------------------------------------
# Output: JSON
# ---------------------------------------------------------------------------

def _build_json_output(
    all_rows: list[dict],
    go_ranked: list[dict],
    provenance: dict | None = None,
) -> dict:
    """Build the scoreboard JSON payload with provenance metadata."""
    total = len(all_rows)
    n_go = sum(1 for r in all_rows if r['verdict'] == 'GO')
    n_nogo = sum(1 for r in all_rows if r['verdict'] == 'NO-GO')
    n_insuf = sum(1 for r in all_rows if r['verdict'] == 'INSUFFICIENT_SAMPLE')
    n_other = total - n_go - n_nogo - n_insuf

    top_3 = go_ranked[:3]

    payload = {
        'version': 'v2',
        'generated': datetime.now(timezone.utc).isoformat(),
        'git_hash': _git_hash(),
    }

    # Add provenance block if available
    if provenance:
        payload['provenance'] = provenance

    payload.update({
        'total_runs': total,
        'passed_gates': n_go,
        'failed_gates': n_nogo,
        'insufficient_sample': n_insuf,
        'other': n_other if n_other > 0 else None,
        'top_3': top_3,
        'all_results': sorted(all_rows, key=lambda r: (
            0 if r['verdict'] == 'GO' else (1 if r['verdict'] == 'NO-GO' else 2),
            r.get('rank') or 9999,
            r['idx'],
        )),
    })
    return payload


# ---------------------------------------------------------------------------
# Output: Markdown
# ---------------------------------------------------------------------------

def _fmt_pnl(v: float) -> str:
    """Format P&L with sign and thousand separator."""
    if v >= 0:
        return f"+{v:,.0f}"
    return f"{v:,.0f}"


def _fmt_ev(v: float) -> str:
    """Format EV/trade with sign."""
    if v >= 0:
        return f"+{v:.0f}"
    return f"{v:.0f}"


def _gate_mark(passed: bool | None) -> str:
    """Render gate pass/fail as checkmark or cross."""
    if passed is None:
        return '-'
    return 'Y' if passed else 'N'


def _failed_gates_str(gates: dict) -> str:
    """List which gates failed for a NO-GO config."""
    failed = [k for k, v in gates.items() if v is False]
    return ', '.join(failed) if failed else '-'


def _build_md_output(
    all_rows: list[dict],
    go_ranked: list[dict],
    json_payload: dict,
    prefix: str = 'sweep_v1_',
) -> str:
    """Build the scoreboard Markdown string."""
    lines: list[str] = []

    git_hash = json_payload['git_hash']
    total = json_payload['total_runs']
    n_go = json_payload['passed_gates']
    n_nogo = json_payload['failed_gates']
    n_insuf = json_payload['insufficient_sample']
    generated = json_payload['generated'][:10]

    # Header — derive version from prefix
    version_tag = prefix.rstrip('_').replace('sweep_', '').upper()
    lines.append(f'# 4H DualConfirm Sweep {version_tag} — Scoreboard')
    lines.append('')
    lines.append(f'Generated: {generated} | Git: {git_hash} | Runs: {total}')
    lines.append('')

    # Provenance block
    prov = json_payload.get('provenance', {})
    if prov:
        lines.append('## Provenance')
        if prov.get('dataset_id'):
            lines.append(f'- **Dataset**: `{prov["dataset_id"]}`')
        if prov.get('exchange'):
            lines.append(f'- **Exchange**: {prov["exchange"]}')
        if prov.get('source'):
            lines.append(f'- **Source**: {prov["source"]} ({prov.get("venue", "")})')
        if prov.get('fee_bps_per_side') is not None:
            lines.append(f'- **Fee**: {prov["fee_bps_per_side"]} bps/side')
        if prov.get('coins'):
            lines.append(f'- **Coins**: {prov["coins"]}')
        if prov.get('time_range'):
            lines.append(f'- **Time range**: {prov["time_range"]}')
        lines.append('')

    # Summary
    lines.append('## Summary')
    lines.append(f'- **Passed (GO)**: {n_go}/{total}')
    lines.append(f'- **Failed (NO-GO)**: {n_nogo}/{total}')
    lines.append(f'- **Insufficient Sample**: {n_insuf}/{total}')
    lines.append('')

    # Top 3
    if go_ranked:
        top_3 = go_ranked[:3]
        lines.append('## Top 3 Recommendation')
        lines.append('')
        lines.append('| # | Label | Exit | Tr | WR% | P&L | PF | DD% | EV/t |')
        lines.append('|---|-------|------|----|-----|-----|----|-----|------|')
        for r in top_3:
            lines.append(
                f"| {r['rank']} "
                f"| {r['label']} "
                f"| {r['exit_type']} "
                f"| {r['trades']} "
                f"| {r['wr']} "
                f"| {_fmt_pnl(r['pnl'])} "
                f"| {r['pf']} "
                f"| {r['dd']} "
                f"| {_fmt_ev(r['ev_per_trade'])} |"
            )
        lines.append('')

    # Full scoreboard (GO configs)
    if go_ranked:
        lines.append('## Full Scoreboard (GO configs, ranked)')
        lines.append('')
        lines.append('| Rank | Idx | Label | Exit | Tr | WR% | P&L | PF | DD% | EV/t | G1 | G2 | G3 | G4 | G5 |')
        lines.append('|------|-----|-------|------|----|-----|-----|----|-----|------|----|----|----|----|-----|')
        for r in go_ranked:
            g = r['gates']
            lines.append(
                f"| {r['rank']} "
                f"| {r['idx']} "
                f"| {r['label']} "
                f"| {r['exit_type']} "
                f"| {r['trades']} "
                f"| {r['wr']} "
                f"| {_fmt_pnl(r['pnl'])} "
                f"| {r['pf']} "
                f"| {r['dd']} "
                f"| {_fmt_ev(r['ev_per_trade'])} "
                f"| {_gate_mark(g.get('G1'))} "
                f"| {_gate_mark(g.get('G2'))} "
                f"| {_gate_mark(g.get('G3'))} "
                f"| {_gate_mark(g.get('G4'))} "
                f"| {_gate_mark(g.get('G5'))} |"
            )
        lines.append('')

    # Failed configs
    nogo_rows = [r for r in all_rows if r['verdict'] == 'NO-GO']
    if nogo_rows:
        nogo_rows.sort(key=lambda r: r['idx'])
        lines.append('## Failed Configs (NO-GO)')
        lines.append('')
        lines.append('| Idx | Label | Exit | Tr | WR% | P&L | PF | DD% | Failed Gates |')
        lines.append('|-----|-------|------|----|-----|-----|----|-----|--------------|')
        for r in nogo_rows:
            lines.append(
                f"| {r['idx']} "
                f"| {r['label']} "
                f"| {r['exit_type']} "
                f"| {r['trades']} "
                f"| {r['wr']} "
                f"| {_fmt_pnl(r['pnl'])} "
                f"| {r['pf']} "
                f"| {r['dd']} "
                f"| {_failed_gates_str(r['gates'])} |"
            )
        lines.append('')

    # Insufficient sample
    insuf_rows = [r for r in all_rows if r['verdict'] == 'INSUFFICIENT_SAMPLE']
    if insuf_rows:
        insuf_rows.sort(key=lambda r: r['idx'])
        lines.append('## Insufficient Sample')
        lines.append('')
        lines.append('| Idx | Label | Exit | Tr | Reason |')
        lines.append('|-----|-------|------|----|--------|')
        for r in insuf_rows:
            lines.append(
                f"| {r['idx']} "
                f"| {r['label']} "
                f"| {r['exit_type']} "
                f"| {r['trades']} "
                f"| < 15 trades |"
            )
        lines.append('')

    # Unclassified (no verdict / no gates run)
    unclass_rows = [r for r in all_rows if r['verdict'] not in ('GO', 'NO-GO', 'INSUFFICIENT_SAMPLE')]
    if unclass_rows:
        unclass_rows.sort(key=lambda r: r['idx'])
        lines.append('## Unclassified (no gate evaluation)')
        lines.append('')
        lines.append('| Idx | Label | Exit | Tr | WR% | P&L | PF | DD% |')
        lines.append('|-----|-------|------|----|-----|-----|----|-----|')
        for r in unclass_rows:
            lines.append(
                f"| {r['idx']} "
                f"| {r['label']} "
                f"| {r['exit_type']} "
                f"| {r['trades']} "
                f"| {r['wr']} "
                f"| {_fmt_pnl(r['pnl'])} "
                f"| {r['pf']} "
                f"| {r['dd']} |"
            )
        lines.append('')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_scoreboard(
    sweep_dir: Path,
    prefix: str,
    plan_path: Path,
    output_dir: Path,
) -> dict:
    """Discover sweep runs, rank them, and write scoreboard files.

    Returns the JSON payload for programmatic use.
    """
    # 1. Discover run directories
    pattern = f'{prefix}*'
    run_dirs = sorted([
        d for d in sweep_dir.iterdir()
        if d.is_dir() and d.name.startswith(prefix)
    ])

    if not run_dirs:
        print(f"  No sweep runs found matching '{pattern}' in {sweep_dir}")
        print(f"  Expected directories like: {sweep_dir / f'{prefix}001_trail_rsi38_abc1234'}")
        sys.exit(1)

    print(f"  Found {len(run_dirs)} run directories in {sweep_dir}")

    # 2. Load sweep plan for block info + provenance
    block_map, provenance = _load_sweep_plan(plan_path)
    if block_map:
        print(f"  Loaded sweep plan with {len(block_map)} entries")
    if provenance:
        print(f"  Provenance: {', '.join(f'{k}={v}' for k, v in provenance.items() if k != 'sweep_description')}")

    # 3. Load all runs
    all_rows: list[dict] = []
    skipped = 0
    for run_dir in run_dirs:
        row = _load_run(run_dir, prefix, block_map)
        if row is not None:
            all_rows.append(row)
        else:
            skipped += 1

    print(f"  Loaded {len(all_rows)} runs ({skipped} skipped)")

    if not all_rows:
        print("  ERROR: No valid runs found. Nothing to build.")
        sys.exit(1)

    # 4. Rank GO configs
    go_ranked = _rank_results(all_rows)
    print(f"  GO: {len(go_ranked)} | NO-GO: {sum(1 for r in all_rows if r['verdict'] == 'NO-GO')} | "
          f"INSUFFICIENT: {sum(1 for r in all_rows if r['verdict'] == 'INSUFFICIENT_SAMPLE')}")

    # 5. Build outputs
    json_payload = _build_json_output(all_rows, go_ranked, provenance)
    md_content = _build_md_output(all_rows, go_ranked, json_payload, prefix)

    # 6. Write files
    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive scoreboard filename from prefix (sweep_v1_ -> scoreboard_sweep_v1)
    scoreboard_name = f"scoreboard_{prefix.rstrip('_')}"
    json_path = output_dir / f'{scoreboard_name}.json'
    with open(json_path, 'w') as f:
        json.dump(json_payload, f, indent=2, default=str)
    print(f"  Wrote: {json_path}")

    md_path = output_dir / f'{scoreboard_name}.md'
    with open(md_path, 'w') as f:
        f.write(md_content)
    print(f"  Wrote: {md_path}")

    # 7. Print top 3 summary
    if go_ranked:
        print(f"\n  === TOP 3 ===")
        for r in go_ranked[:3]:
            print(f"  #{r['rank']} {r['label']} ({r['exit_type']}) "
                  f"| {r['trades']}tr | PF={r['pf']} | P&L=${r['pnl']:+,.0f} "
                  f"| DD={r['dd']}% | EV=${r['ev_per_trade']:+,.0f}")
    else:
        print(f"\n  No configs passed all gates (GO).")

    return json_payload


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='build_4h_scoreboard',
        description='Aggregate 4H sweep results into a ranked scoreboard',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/build_4h_scoreboard.py\n"
            "  python scripts/build_4h_scoreboard.py --sweep-dir reports/4h --prefix sweep_v1_\n"
            "  python scripts/build_4h_scoreboard.py --plan strategies/4h/sweep_plan_v1.json\n"
        ),
    )
    parser.add_argument(
        '--sweep-dir', default=str(REPO_ROOT / 'reports' / '4h'),
        help='Base directory containing sweep run folders (default: reports/4h)',
    )
    parser.add_argument(
        '--prefix', default='sweep_v1_',
        help='Run ID prefix to match (default: sweep_v1_)',
    )
    parser.add_argument(
        '--plan', default=str(REPO_ROOT / 'strategies' / '4h' / 'sweep_plan_v1.json'),
        help='Path to sweep plan JSON for block info (default: strategies/4h/sweep_plan_v1.json)',
    )
    parser.add_argument(
        '--output-dir', default=str(REPO_ROOT / 'reports' / '4h'),
        help='Where to write scoreboard files (default: reports/4h)',
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    sweep_dir = Path(args.sweep_dir)
    plan_path = Path(args.plan)
    output_dir = Path(args.output_dir)

    print(f"\n{'='*60}")
    print(f"  4H Scoreboard Builder")
    print(f"{'='*60}")
    print(f"  Sweep dir: {sweep_dir}")
    print(f"  Prefix:    {args.prefix}")
    print(f"  Plan:      {plan_path}")
    print(f"  Output:    {output_dir}")
    print()

    build_scoreboard(sweep_dir, args.prefix, plan_path, output_dir)


if __name__ == '__main__':
    main()
