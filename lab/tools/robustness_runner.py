"""Robustness runner — wraps robustness_harness for lab agents (READ-ONLY).

Provides safe access to the robustness harness validation framework.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from lab.config import TRADING_BOT_DIR
from lab.tools.backtest_runner import get_indicators, normalize_cfg

logger = logging.getLogger('lab.tools.robustness')

# ── Lazy imports ─────────────────────────────────────────
_harness = None


def _load_harness():
    """Lazily import robustness_harness functions."""
    global _harness
    if _harness is not None:
        return _harness

    sys.path.insert(0, str(TRADING_BOT_DIR))
    try:
        from robustness_harness import run_candidate, GO, KILL_SWITCH
        _harness = {
            'run_candidate': run_candidate,
            'GO': GO,
            'KILL_SWITCH': KILL_SWITCH,
        }
    except ImportError as e:
        logger.error(f"Cannot import robustness_harness: {e}")
        raise
    return _harness


# ── Public API ───────────────────────────────────────────

def run_candidate(cfg: dict, candidate_id: str,
                  label: str = '') -> dict:
    """Run full robustness validation on a config.

    Returns dict with:
        - baseline: summary from full-sample backtest
        - walk_forward: 5-fold walk-forward results
        - friction: fee/slippage stress test
        - monte_carlo: MC shuffle results
        - param_jitter: ±10% sensitivity results
        - universe: coin universe shift results
        - fails: list of failed thresholds
        - verdict: 'GO' | 'SOFT-GO' | 'NO-GO'
    """
    harness = _load_harness()
    indicators, coins = get_indicators()
    cfg = normalize_cfg(cfg)

    logger.info(f"Running robustness harness for {candidate_id}...")
    result = harness['run_candidate'](
        indicators, coins, cfg, candidate_id, label or candidate_id,
    )
    logger.info(f"Verdict for {candidate_id}: {result.get('verdict', 'unknown')}")
    return result


def get_go_thresholds() -> dict:
    """Get GO/NO-GO threshold constants."""
    return dict(_load_harness()['GO'])


def get_kill_switch() -> dict:
    """Get live kill-switch thresholds."""
    return dict(_load_harness()['KILL_SWITCH'])


def check_gates(result: dict) -> dict:
    """Extract gate pass/fail status from a run_candidate result.

    Returns dict with each gate's pass/fail status and details.
    """
    gates = {}
    go = _load_harness()['GO']

    # Walk-forward
    wf = result.get('walk_forward', {})
    wf_positive = wf.get('passed_folds', 0)
    wf_total = wf.get('n_folds', 5)
    gates['walk_forward'] = {
        'pass': wf_positive >= go.get('wf_min_pass', 4),
        'ratio': f"{wf_positive}/{wf_total}",
        'threshold': f">={go.get('wf_min_pass', 4)}/{wf_total}",
    }

    # Monte Carlo
    mc = result.get('monte_carlo', {})
    mc_ruin = mc.get('ruin_prob_pct', 100)
    gates['monte_carlo'] = {
        'pass': mc_ruin <= go.get('mc_ruin_max', 5.0),
        'ruin_pct': mc_ruin,
        'threshold': f"<={go.get('mc_ruin_max', 5.0)}%",
    }

    # Param jitter
    jitter = result.get('param_jitter', {})
    jitter_pct = jitter.get('positive_pct', 0)
    gates['param_jitter'] = {
        'pass': jitter_pct >= go.get('jitter_min_positive_pct', 70.0),
        'positive_pct': jitter_pct,
        'threshold': f">={go.get('jitter_min_positive_pct', 70.0)}%",
    }

    # Universe
    univ = result.get('universe', {})
    n_pos = univ.get('n_positive_subsets', 0)
    gates['universe'] = {
        'pass': n_pos >= go.get('univ_min_subsets_positive', 2),
        'n_positive': n_pos,
        'threshold': f">={go.get('univ_min_subsets_positive', 2)}/4",
    }

    # Overall
    gates['verdict'] = result.get('verdict', 'NO-GO')
    gates['all_pass'] = all(g.get('pass', False) for g in gates.values()
                           if isinstance(g, dict))

    return gates
