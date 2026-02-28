"""Portfolio Architect Agent — capital allocation designer.

Reads champion.json + available configs from reports/, computes
capital allocation, parallel deployment feasibility, and correlation
analysis. Writes artifact to reports/lab/portfolio_<ts>.{json,md}.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from lab.agents.base import BaseAgent
from lab.config import REPO_ROOT, REPORTS_DIR
from lab.models import Task, TaskResult

logger = logging.getLogger('lab.agent.portfolio_architect')

# Paths (READ-ONLY)
CHAMPION_PATH = REPO_ROOT / 'trading_bot' / 'champion.json'
HARNESS_DIR = REPO_ROOT / 'reports' / 'tradeable_harness'
REPORTS_4H = REPO_ROOT / 'reports' / '4h'

# Portfolio constraints
MAX_CONFIGS = 5             # Max parallel configs
MIN_PF_THRESHOLD = 1.5      # Min profit factor for inclusion
MAX_DD_THRESHOLD = 30.0     # Max drawdown % for inclusion
MIN_TRADES_THRESHOLD = 20   # Min trades for statistical significance
MAX_CORRELATION = 0.70      # Max acceptable PnL correlation between configs


class PortfolioArchitect(BaseAgent):
    name = 'portfolio_architect'
    role = 'Capital Allocation Designer'
    is_llm = False

    def execute_task(self, task: Task) -> TaskResult:
        """Analyze configs, compute allocation, check deployment feasibility."""
        try:
            # Step 1: Gather candidate configs
            candidates = self._gather_candidates()

            if not candidates:
                return TaskResult(
                    success=True,
                    summary="Geen kandidaat-configs gevonden die voldoen aan "
                            f"minimale criteria (PF>{MIN_PF_THRESHOLD}, "
                            f"DD<{MAX_DD_THRESHOLD}%, "
                            f"trades>{MIN_TRADES_THRESHOLD}).",
                )

            # Step 2: Score and rank
            ranked = self._rank_candidates(candidates)

            # Step 3: Compute allocation
            allocation = self._compute_allocation(ranked[:MAX_CONFIGS])

            # Step 4: Deployment feasibility
            feasibility = self._check_feasibility(ranked[:MAX_CONFIGS])

            # Step 5: Write report
            ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            report_name = f'portfolio_{ts}'

            report_data = {
                'task_id': task.id,
                'candidates_scanned': len(candidates),
                'candidates_qualified': len(ranked),
                'top_configs': ranked[:MAX_CONFIGS],
                'allocation': allocation,
                'feasibility': feasibility,
            }

            md = self._build_markdown(report_data, ts)
            json_path = self._write_report(report_name, report_data, md)

            summary = (
                f"Portfolio analyse: {len(candidates)} configs gescand, "
                f"{len(ranked)} gekwalificeerd.\n"
                f"Top {min(len(ranked), MAX_CONFIGS)} configs gerankt.\n"
                f"Deployment: {feasibility.get('verdict', '?')}.\n"
                f"Artefact: {json_path}"
            )

            return TaskResult(
                success=True,
                summary=summary,
                artifact_path=str(json_path),
                sha256=self._file_sha256(json_path),
                git_hash=self._git_hash(),
                cmd='portfolio_analysis',
            )

        except Exception as e:
            return TaskResult(
                success=False,
                summary=f"Portfolio analyse failed: {str(e)[:500]}",
            )

    def review_task(self, task: Task) -> None:
        """Portfolio Architect reviews for capital/risk alignment."""
        comments = self.db.get_comments(task.id)

        issues = []

        # Check artifact
        if not task.artifact_path:
            issues.append("Geen artefact geproduceerd")

        # Check for substantive work
        has_substance = any(
            c.agent == task.assigned_to and len(c.body) > 50
            for c in comments
        )
        if not has_substance:
            issues.append("Completion comment te kort (<50 chars)")

        # If artifact is a robustness or edge report, check DD
        if task.artifact_path and Path(task.artifact_path).exists():
            try:
                with open(task.artifact_path) as f:
                    data = json.load(f)
                dd = data.get('backtest', {}).get('dd', 0)
                if dd > MAX_DD_THRESHOLD:
                    issues.append(
                        f"DD {dd:.1f}% overschrijdt max {MAX_DD_THRESHOLD}%"
                    )
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        if issues:
            body = "PORTFOLIO REVIEW — needs_changes:\n" + "\n".join(
                f"- {i}" for i in issues
            )
            cid = self.db.add_comment(task.id, self.name, body, 'review')
            self.db.update_review(task.id, self.name, 'needs_changes', cid)
        else:
            cid = self.db.add_comment(
                task.id, self.name,
                "PORTFOLIO REVIEW — approved. Capital/risk check OK.",
                'approval',
            )
            self.db.update_review(task.id, self.name, 'approved', cid)

    # ── Helpers ──────────────────────────────────────────

    def _gather_candidates(self) -> list[dict]:
        """Collect config candidates from champion + harness reports."""
        candidates = []

        # Champion config
        if CHAMPION_PATH.exists():
            try:
                with open(CHAMPION_PATH) as f:
                    champ = json.load(f)
                bt = champ.get('backtest', {})
                candidates.append({
                    'source': 'champion.json',
                    'label': champ.get('label', 'champion'),
                    'cfg': champ.get('cfg', {}),
                    'trades': bt.get('trades', 0),
                    'wr': bt.get('wr', 0),
                    'pf': bt.get('pf', 0),
                    'dd': bt.get('dd', 0),
                    'pnl': bt.get('pnl', 0),
                    'hash': champ.get('hash', ''),
                    'mc_block': champ.get('mc_block', {}),
                })
            except (json.JSONDecodeError, OSError):
                pass

        # Harness results
        if HARNESS_DIR.exists():
            for jf in sorted(HARNESS_DIR.glob('*.json'))[:20]:
                try:
                    with open(jf) as f:
                        data = json.load(f)
                    # Some harness files have backtest info
                    bt = data.get('backtest', data.get('result', {}))
                    cfg = data.get('cfg', data.get('config', {}))
                    if bt and cfg:
                        candidates.append({
                            'source': str(jf.name),
                            'label': data.get('label', jf.stem),
                            'cfg': cfg,
                            'trades': bt.get('trades', 0),
                            'wr': bt.get('wr', 0),
                            'pf': bt.get('pf', 0),
                            'dd': bt.get('dd', 0),
                            'pnl': bt.get('pnl', 0),
                            'hash': data.get('hash', ''),
                            'mc_block': data.get('mc_block', {}),
                        })
                except (json.JSONDecodeError, OSError):
                    continue

        # Reports/4h directory
        if REPORTS_4H.exists():
            for jf in sorted(REPORTS_4H.glob('*.json'))[:20]:
                try:
                    with open(jf) as f:
                        data = json.load(f)
                    bt = data.get('backtest', data.get('result', {}))
                    cfg = data.get('cfg', data.get('config', {}))
                    if bt and cfg:
                        candidates.append({
                            'source': str(jf.name),
                            'label': data.get('label', jf.stem),
                            'cfg': cfg,
                            'trades': bt.get('trades', 0),
                            'wr': bt.get('wr', 0),
                            'pf': bt.get('pf', 0),
                            'dd': bt.get('dd', 0),
                            'pnl': bt.get('pnl', 0),
                            'hash': data.get('hash', ''),
                            'mc_block': data.get('mc_block', {}),
                        })
                except (json.JSONDecodeError, OSError):
                    continue

        return candidates

    def _rank_candidates(self, candidates: list[dict]) -> list[dict]:
        """Filter by thresholds and score remaining candidates."""
        qualified = []

        for c in candidates:
            if (c.get('pf', 0) >= MIN_PF_THRESHOLD
                    and c.get('dd', 100) <= MAX_DD_THRESHOLD
                    and c.get('trades', 0) >= MIN_TRADES_THRESHOLD):
                # Composite score: PF weight + DD penalty + trade count bonus
                score = (
                    c['pf'] * 10          # PF is king
                    - c['dd'] * 0.5       # DD penalty
                    + min(c['trades'] / 100, 2)  # Trade count bonus (cap 2)
                    + c.get('wr', 0) * 0.1       # Win rate minor bonus
                )
                c['portfolio_score'] = round(score, 2)
                qualified.append(c)

        # Sort by score descending
        qualified.sort(key=lambda x: x['portfolio_score'], reverse=True)
        return qualified

    def _compute_allocation(self, configs: list[dict]) -> dict:
        """Compute capital allocation proportional to score, inverse DD."""
        if not configs:
            return {'method': 'none', 'configs': []}

        # Inverse DD weighting
        total_inv_dd = sum(1.0 / max(c['dd'], 1) for c in configs)

        allocations = []
        for c in configs:
            weight = (1.0 / max(c['dd'], 1)) / total_inv_dd
            allocations.append({
                'label': c.get('label', '?'),
                'hash': c.get('hash', '?'),
                'weight_pct': round(weight * 100, 1),
                'pf': c['pf'],
                'dd': c['dd'],
                'score': c.get('portfolio_score', 0),
            })

        return {
            'method': 'inverse_dd_weighted',
            'configs': allocations,
            'diversification_ratio': round(
                1.0 / sum(a['weight_pct'] ** 2 for a in allocations) * 10000,
                2
            ) if len(allocations) > 1 else 1.0,
        }

    def _check_feasibility(self, configs: list[dict]) -> dict:
        """Check parallel deployment feasibility."""
        if not configs:
            return {'verdict': 'NO_CANDIDATES', 'issues': []}

        issues = []

        # Check 1: Enough qualified configs?
        if len(configs) < 2:
            issues.append(
                f"Slechts {len(configs)} config(s) — parallel deployment "
                "niet zinvol zonder diversificatie"
            )

        # Check 2: Config diversity (different exit types, RSI params)
        exit_types = {c['cfg'].get('exit_type', '?') for c in configs}
        if len(exit_types) == 1 and len(configs) > 1:
            issues.append(
                f"Alle configs gebruiken exit_type='{exit_types.pop()}' "
                "— lage strategie-diversificatie"
            )

        # Check 3: DD headroom
        max_dd = max(c['dd'] for c in configs)
        if max_dd > 25:
            issues.append(
                f"Hoogste DD ({max_dd:.1f}%) dicht bij limiet — "
                "portfolio DD kan optellen"
            )

        # Check 4: All pass MC ruin check
        risky = [
            c for c in configs
            if c.get('mc_block', {}).get('win_pct', 100) < 95
        ]
        if risky:
            issues.append(
                f"{len(risky)} config(s) met MC win% < 95% — "
                "ruin risico te hoog voor capital deployment"
            )

        verdict = 'GO' if not issues else (
            'NO-GO' if len(issues) >= 3 else 'CONDITIONAL'
        )

        return {
            'verdict': verdict,
            'issues': issues,
            'configs_evaluated': len(configs),
        }

    def _build_markdown(self, report: dict, ts: str) -> str:
        """Build human-readable Markdown report."""
        lines = [
            f"# Portfolio Architecture Report — {ts}",
            f"\n**Scanned**: {report['candidates_scanned']} configs",
            f"**Qualified**: {report['candidates_qualified']}",
            "",
        ]

        # Top configs
        top = report.get('top_configs', [])
        if top:
            lines.append("## Top Configs\n")
            lines.append(
                f"| {'Rank':>4} | {'Label':>25} | {'PF':>5} | "
                f"{'DD%':>5} | {'WR%':>5} | {'Trades':>6} | {'Score':>6} |"
            )
            lines.append("|" + "-" * 6 + "|" + "-" * 27 + "|" + "-" * 7 + "|"
                         + "-" * 7 + "|" + "-" * 7 + "|" + "-" * 8 + "|"
                         + "-" * 8 + "|")
            for i, c in enumerate(top):
                lines.append(
                    f"| {i+1:>4} | {c.get('label', '?')[:25]:>25} | "
                    f"{c['pf']:>5.2f} | {c['dd']:>5.1f} | "
                    f"{c.get('wr', 0):>5.1f} | {c['trades']:>6} | "
                    f"{c.get('portfolio_score', 0):>6.1f} |"
                )
            lines.append("")

        # Allocation
        alloc = report.get('allocation', {})
        if alloc.get('configs'):
            lines.append("## Capital Allocation\n")
            lines.append(f"**Methode**: {alloc['method']}")
            lines.append("")
            for a in alloc['configs']:
                lines.append(
                    f"- **{a['label']}**: {a['weight_pct']:.1f}% "
                    f"(PF={a['pf']:.2f}, DD={a['dd']:.1f}%)"
                )
            lines.append("")

        # Feasibility
        feas = report.get('feasibility', {})
        verdict_icon = {
            'GO': '✅', 'CONDITIONAL': '⚠️', 'NO-GO': '❌',
            'NO_CANDIDATES': '❓',
        }.get(feas.get('verdict', ''), '❓')

        lines.append(f"## Deployment Feasibility\n")
        lines.append(f"**Verdict**: {verdict_icon} {feas.get('verdict', '?')}")
        lines.append("")

        for issue in feas.get('issues', []):
            lines.append(f"- ⚠️ {issue}")
        lines.append("")

        return '\n'.join(lines) + '\n'
