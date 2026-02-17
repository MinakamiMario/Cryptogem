"""
MEXC execution cost model v2 -- canonical source of truth for all cost numbers.

Supersedes ad-hoc constants in fill_model.py and run_h20_robustness.py.

Assumptions:
  Fees:     MEXC taker 10bps, maker 0bps (promo since Q4 2022). Source: mexc.com/fee
  Spread:   half_spread = 150/sqrt(daily_vol)*10000 bps (Kaiko CEX calibration)
  Slippage: impact = 0.05*sqrt(200/daily_vol)*10000 bps (sigma=5%)
  Size:     $200/trade.  Volume: universe_tiering_001.json (T1 $7.7M/d, T2 $269K/d)

fill_model.py handles fill-rate/adverse-selection ON TOP of costs defined here.
run_h20_robustness.py should use get_harness_fee() instead of local constants.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, List

# -----------------------------------------------------------------------
# Cost regimes
# -----------------------------------------------------------------------

COST_REGIMES: Dict[str, dict] = {
    "mexc_market": {
        "description": "MEXC taker (market orders), P50 spread+slippage",
        "tier1": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 1.7,
            "slippage_bps": 0.8,
            "total_per_side_bps": 12.5,
        },
        "tier2": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 9.2,
            "slippage_bps": 4.3,
            "total_per_side_bps": 23.5,
        },
        "percentile": "p50",
    },
    "mexc_market_p90": {
        "description": "MEXC taker conservative (P90 spread+slippage)",
        "tier1": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 3.8,
            "slippage_bps": 1.8,
            "total_per_side_bps": 15.6,
        },
        "tier2": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 21.3,
            "slippage_bps": 10.1,
            "total_per_side_bps": 41.4,
        },
        "percentile": "p90",
    },
    "mexc_market_p95": {
        "description": "MEXC taker stress (P95 spread+slippage)",
        "tier1": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 6.7,
            "slippage_bps": 2.5,
            "total_per_side_bps": 19.2,
        },
        "tier2": {
            "exchange_fee_bps": 10.0,
            "spread_bps": 33.5,
            "slippage_bps": 15.8,
            "total_per_side_bps": 59.3,
        },
        "percentile": "p95",
    },
    "mexc_maker": {
        "description": "MEXC maker (limit orders, 0% fee promotion)",
        "tier1": {
            "exchange_fee_bps": 0.0,
            "spread_bps": 0.0,
            "slippage_bps": 0.0,
            "adverse_selection_bps": 2.5,
            "total_per_side_bps": 2.5,
        },
        "tier2": {
            "exchange_fee_bps": 0.0,
            "spread_bps": 0.0,
            "slippage_bps": 0.0,
            "adverse_selection_bps": 13.5,
            "total_per_side_bps": 13.5,
        },
        "percentile": "p50",
    },
    "kraken_baseline": {
        "description": "Kraken taker (reference, harness default)",
        "tier1": {
            "exchange_fee_bps": 26.0,
            "spread_bps": 0.0,
            "slippage_bps": 5.0,
            "total_per_side_bps": 31.0,
        },
        "tier2": {
            "exchange_fee_bps": 26.0,
            "spread_bps": 0.0,
            "slippage_bps": 30.0,
            "total_per_side_bps": 56.0,
        },
        "percentile": "p50",
    },
}

# -----------------------------------------------------------------------
# Module-level correctness assertions
# -----------------------------------------------------------------------

_COMPONENT_KEYS = ("exchange_fee_bps", "spread_bps", "slippage_bps")

for _regime_name, _regime in COST_REGIMES.items():
    for _tier_key in ("tier1", "tier2"):
        _tier = _regime[_tier_key]
        _expected = _tier["total_per_side_bps"]
        _computed = sum(_tier.get(k, 0.0) for k in _COMPONENT_KEYS)
        _computed += _tier.get("adverse_selection_bps", 0.0)
        assert abs(_computed - _expected) < 0.15, (
            f"Total mismatch in {_regime_name}/{_tier_key}: "
            f"sum={_computed:.1f} vs declared={_expected:.1f}"
        )


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def get_regime_names() -> List[str]:
    """List all available cost regime names."""
    return list(COST_REGIMES.keys())


def get_cost_breakdown(regime: str, tier: str) -> dict:
    """Return full cost breakdown dict for a regime + tier."""
    if regime not in COST_REGIMES:
        raise ValueError(
            f"Unknown regime {regime!r}. Choose from {get_regime_names()}"
        )
    if tier not in ("tier1", "tier2"):
        raise ValueError(f"Unknown tier {tier!r}. Choose 'tier1' or 'tier2'.")

    tier_data = deepcopy(COST_REGIMES[regime][tier])
    total = tier_data["total_per_side_bps"]
    tier_data["total_round_trip_bps"] = total * 2
    tier_data["harness_fee_decimal"] = total / 10_000.0
    tier_data["regime"] = regime
    tier_data["tier"] = tier
    tier_data["percentile"] = COST_REGIMES[regime]["percentile"]
    tier_data["description"] = COST_REGIMES[regime]["description"]
    return tier_data


def get_harness_fee(regime: str, tier: str) -> float:
    """Return fee decimal for harness.run_backtest(fee=...)."""
    breakdown = get_cost_breakdown(regime, tier)
    return breakdown["harness_fee_decimal"]


def stress_multiplier(regime: str, multiplier: float) -> dict:
    """Return regime dict with all cost components scaled by *multiplier*."""
    if regime not in COST_REGIMES:
        raise ValueError(
            f"Unknown regime {regime!r}. Choose from {get_regime_names()}"
        )
    base = deepcopy(COST_REGIMES[regime])
    result = {
        "description": f"{base['description']} x{multiplier}",
        "percentile": base["percentile"],
    }
    for tier_key in ("tier1", "tier2"):
        t = base[tier_key]
        new_t = {}
        for k in ("exchange_fee_bps", "spread_bps", "slippage_bps",
                   "adverse_selection_bps"):
            if k in t:
                new_t[k] = round(t[k] * multiplier, 1)
        new_t["total_per_side_bps"] = round(
            sum(new_t.get(k, 0.0) for k in (
                "exchange_fee_bps", "spread_bps", "slippage_bps",
                "adverse_selection_bps",
            )),
            1,
        )
        result[tier_key] = new_t
    return result


def register_regime(name: str, regime: dict) -> None:
    """Register measured regime at runtime (no hardcoded values changed).

    Validates regime structure and anti-double-counting invariant:
    component sum must match total_per_side_bps within 0.15 bps tolerance.

    Args:
        name: regime name, e.g. 'measured_ob_maker_p50'
        regime: dict with 'execution_mode', 'tier1', 'tier2', each tier having
                'total_per_side_bps' and cost components that sum to total.

    Raises:
        AssertionError: if regime structure is invalid or components don't sum to total.
    """
    assert "execution_mode" in regime, "Regime must specify execution_mode"
    for tier_key in ("tier1", "tier2"):
        assert tier_key in regime, f"Missing {tier_key} in regime"
        t = regime[tier_key]
        assert "total_per_side_bps" in t, f"Missing total_per_side_bps in {tier_key}"
        # Anti-double-counting: component sum must match total
        computed = sum(t.get(k, 0.0) for k in _COMPONENT_KEYS)
        computed += t.get("adverse_selection_bps", 0.0)
        assert abs(computed - t["total_per_side_bps"]) < 0.15, (
            f"Component sum {computed:.1f} != total {t['total_per_side_bps']:.1f} "
            f"in {name}/{tier_key}"
        )
    COST_REGIMES[name] = regime
