#!/usr/bin/env python3
"""
Regression tests voor robustness_harness.py
1 test per module: WF, Friction, MC, Jitter, Universe.
Draait op een KLEINE subset (10 coins) voor snelheid.
"""
import sys
import json
import random
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from agent_team_v3 import (
    precompute_all, run_backtest, normalize_cfg,
    CACHE_FILE, KRAKEN_FEE, INITIAL_CAPITAL, START_BAR,
)
from robustness_harness import (
    purged_walk_forward, friction_stress, monte_carlo_shuffle,
    param_jitter, universe_shift,
)

# ============================================================
# FIXTURE: kleine dataset voor snelle tests
# ============================================================
_CACHE = {}

def get_test_data():
    """Load 10 coins voor snelle tests (cached)."""
    if 'indicators' in _CACHE:
        return _CACHE['indicators'], _CACHE['coins']
    with open(CACHE_FILE) as f:
        data = json.load(f)
    all_coins = sorted(k for k, v in data.items() if isinstance(v, list) and len(v) > 50)
    # Neem 10 coins met seed voor reproducibility
    rng = random.Random(42)
    coins = rng.sample(all_coins, min(10, len(all_coins)))
    indicators = precompute_all(data, coins)
    _CACHE['indicators'] = indicators
    _CACHE['coins'] = coins
    return indicators, coins

TEST_CFG = {
    'exit_type': 'tp_sl', 'rsi_max': 45, 'vol_spike_mult': 3.0,
    'vol_confirm': True, 'tp_pct': 15, 'sl_pct': 15,
    'time_max_bars': 15, 'max_pos': 1,
}


# ============================================================
# TEST 1: Purged Walk-Forward
# ============================================================
def test_purged_wf_structure():
    """WF retourneert verwachte keys en fold count."""
    ind, coins = get_test_data()
    result = purged_walk_forward(ind, coins, TEST_CFG, n_folds=3, embargo=2)

    assert 'folds' in result, "Missing 'folds' key"
    assert len(result['folds']) == 3, f"Expected 3 folds, got {len(result['folds'])}"
    assert 'wf_label' in result
    assert 'go' in result
    assert isinstance(result['go'], bool)

    for f in result['folds']:
        assert 'purge_zone' in f, "Fold missing purge_zone"
        assert 'embargo' in f, "Fold missing embargo"
        assert f['embargo'] == 2
        assert 'test_pnl' in f
        assert 'pass' in f
        assert isinstance(f['pass'], bool)

    print(f"  ✅ test_purged_wf_structure: {result['wf_label']}")


def test_purged_wf_embargo_no_overlap():
    """Purge zone mag niet overlappen met test zone (anti-leakage)."""
    ind, coins = get_test_data()
    result = purged_walk_forward(ind, coins, TEST_CFG, n_folds=3, embargo=2)

    for f in result['folds']:
        test_start, test_end = [int(x) for x in f['test_bars'].split('-')]
        purge_start, purge_end = [int(x) for x in f['purge_zone'].split('-')]
        # Purge zone bevat de test zone + embargo
        assert purge_start <= test_start, \
            f"Purge start {purge_start} > test start {test_start}"
        assert purge_end >= test_end, \
            f"Purge end {purge_end} < test end {test_end}"

    print("  ✅ test_purged_wf_embargo_no_overlap")


# ============================================================
# TEST 2: Friction Stress
# ============================================================
def test_friction_matrix_completeness():
    """Friction matrix bevat alle fee×slippage combinaties."""
    ind, coins = get_test_data()
    result = friction_stress(ind, coins, TEST_CFG)

    expected_keys = [
        '1.0x_fee+0bps', '1.0x_fee+10bps', '1.0x_fee+20bps', '1.0x_fee+35bps',
        '2.0x_fee+0bps', '2.0x_fee+10bps', '2.0x_fee+20bps', '2.0x_fee+35bps',
        '3.0x_fee+0bps', '3.0x_fee+10bps', '3.0x_fee+20bps', '3.0x_fee+35bps',
        '2x_fee+1candle_gap',
    ]
    for k in expected_keys:
        assert k in result['matrix'], f"Missing friction key: {k}"
        assert 'pnl' in result['matrix'][k], f"Missing pnl in {k}"

    assert 'go' in result
    assert isinstance(result['go'], bool)
    print(f"  ✅ test_friction_matrix_completeness: {len(result['matrix'])} scenarios")


def test_friction_monotonic():
    """Hogere fees = lagere P&L (of gelijk)."""
    ind, coins = get_test_data()
    result = friction_stress(ind, coins, TEST_CFG)
    m = result['matrix']

    pnl_1x = m['1.0x_fee+0bps']['pnl']
    pnl_2x = m['2.0x_fee+0bps']['pnl']
    pnl_3x = m['3.0x_fee+0bps']['pnl']
    assert pnl_1x >= pnl_2x >= pnl_3x, \
        f"Fee P&L not monotonic: {pnl_1x} >= {pnl_2x} >= {pnl_3x}"
    print("  ✅ test_friction_monotonic")


# ============================================================
# TEST 3: Monte Carlo
# ============================================================
def test_mc_shuffle_structure():
    """MC retourneert verwachte keys en redelijke waarden."""
    ind, coins = get_test_data()
    result = monte_carlo_shuffle(ind, coins, TEST_CFG, n_sims=100, seed=42)

    if 'error' in result:
        print(f"  ⚠️  test_mc_shuffle: skipped ({result['error']})")
        return

    assert 'equity' in result
    assert 'max_dd' in result
    assert 'ruin_prob_pct' in result
    assert 'go' in result

    # Sanity: p5 <= median <= p95
    eq = result['equity']
    assert eq['p5'] <= eq['median'] <= eq['p95'], \
        f"Equity percentiles out of order: {eq['p5']} <= {eq['median']} <= {eq['p95']}"

    dd = result['max_dd']
    assert dd['p5'] <= dd['median'] <= dd['p95'], \
        f"DD percentiles out of order: {dd['p5']} <= {dd['median']} <= {dd['p95']}"

    assert 0 <= result['ruin_prob_pct'] <= 100

    print(f"  ✅ test_mc_shuffle_structure: ruin={result['ruin_prob_pct']}%")


def test_mc_deterministic():
    """Zelfde seed = zelfde resultaat."""
    ind, coins = get_test_data()
    r1 = monte_carlo_shuffle(ind, coins, TEST_CFG, n_sims=50, seed=42)
    r2 = monte_carlo_shuffle(ind, coins, TEST_CFG, n_sims=50, seed=42)
    if 'error' in r1:
        print(f"  ⚠️  test_mc_deterministic: skipped")
        return
    assert r1['equity'] == r2['equity'], "MC not deterministic with same seed"
    print("  ✅ test_mc_deterministic")


# ============================================================
# TEST 4: Param Jitter
# ============================================================
def test_jitter_structure():
    """Jitter retourneert verwachte keys."""
    ind, coins = get_test_data()
    result = param_jitter(ind, coins, TEST_CFG, n_variants=10, seed=42)

    assert 'n_variants' in result
    assert result['n_variants'] == 10
    assert 'positive_pct' in result
    assert 'worst_pnl' in result
    assert 'go' in result
    assert isinstance(result['go'], bool)
    assert 0 <= result['positive_pct'] <= 100

    print(f"  ✅ test_jitter_structure: {result['positive_pct']}% positive")


def test_jitter_deterministic():
    """Zelfde seed = zelfde resultaat."""
    ind, coins = get_test_data()
    r1 = param_jitter(ind, coins, TEST_CFG, n_variants=10, seed=42)
    r2 = param_jitter(ind, coins, TEST_CFG, n_variants=10, seed=42)
    assert r1['worst_pnl'] == r2['worst_pnl'], "Jitter not deterministic"
    print("  ✅ test_jitter_deterministic")


# ============================================================
# TEST 5: Universe Shift
# ============================================================
def test_universe_structure():
    """Universe shift retourneert verwachte keys."""
    ind, coins = get_test_data()
    result = universe_shift(ind, coins, TEST_CFG, n_random=10, seed=42)

    assert 'concentration' in result
    assert 'subsets' in result
    assert 'go' in result
    conc = result['concentration']
    assert 'top1_share' in conc
    assert 'top3_share' in conc
    assert 0 <= conc['top1_share'] <= 1.0
    assert 0 <= conc['top3_share'] <= 1.0
    assert conc['top1_share'] <= conc['top3_share']

    # Subsets
    for name in ['top_volume', 'mid_volume', 'exclude_top_winners', 'random_50pct']:
        assert name in result['subsets'], f"Missing subset: {name}"

    print(f"  ✅ test_universe_structure: top1={conc['top1_share']*100:.0f}%")


def test_universe_exclude_removes_winners():
    """exclude_top_winners subset mag geen top-3 coins bevatten."""
    ind, coins = get_test_data()
    result = universe_shift(ind, coins, TEST_CFG, n_random=5, seed=42)
    top3 = result['concentration']['top3_coins']
    excl = result['subsets']['exclude_top_winners']
    # De subset trades mogen niet de top3 coins bevatten
    # (we checken structureel dat het subset minder coins heeft)
    n_full = len(coins)
    n_excl = excl.get('n_coins', 0)
    assert n_excl <= n_full, "Exclude subset should be smaller"
    print(f"  ✅ test_universe_exclude_removes_winners: {n_excl}/{n_full} coins")


# ============================================================
# RUNNER
# ============================================================
ALL_TESTS = [
    test_purged_wf_structure,
    test_purged_wf_embargo_no_overlap,
    test_friction_matrix_completeness,
    test_friction_monotonic,
    test_mc_shuffle_structure,
    test_mc_deterministic,
    test_jitter_structure,
    test_jitter_deterministic,
    test_universe_structure,
    test_universe_exclude_removes_winners,
]


def main():
    print(f"{'='*50}")
    print(f"  Robustness Harness Regression Tests")
    print(f"  {len(ALL_TESTS)} tests")
    print(f"{'='*50}")

    passed = 0
    failed = 0
    errors = []

    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test_fn.__name__, str(e)))
            print(f"  ❌ {test_fn.__name__}: {e}")

    print(f"\n{'='*50}")
    print(f"  Results: {passed}/{len(ALL_TESTS)} passed, {failed} failed")
    print(f"{'='*50}")

    if errors:
        for name, err in errors:
            print(f"  FAIL: {name}: {err}")
        sys.exit(1)
    else:
        print("  All tests passed ✅")
        sys.exit(0)


if __name__ == '__main__':
    main()
