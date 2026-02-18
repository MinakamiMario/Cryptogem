"""
Sprint 3 — Entry Adapters for DualConfirm Exit Intelligence.

Top-3 Sprint 2 entries x DC exit parameter grid.
Entry signal_fn's are IMPORTED from Sprint 2 (not duplicated).
Exit params replace fixed TP/SL with max_stop_pct, time_max_bars, rsi_rec_target.

Families (from Sprint 2 best PF):
    H4S3-04: RSI + Regime Filter (DC Exits)        — best S2 PF=0.85
    H4S3-03: Cross-Sectional Relative Strength (DC) — best S2 PF=0.81
    H4S3-02: Volatility Exhaustion Fade (DC)        — best S2 PF=0.81

Config matrix: 3 families x 2 entry variants x 3 DC exit variants = 18 configs.

IMPORTANT: signal_fn from Sprint 2 still computes stop_price and target_price
(needed for its return dict), but the Sprint 3 engine in DC mode IGNORES those
and uses max_stop_pct + dynamic DC/BB/RSI targets instead.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# Import signal functions from Sprint 2 (no duplication)
# ---------------------------------------------------------------------------
s2_hyp = importlib.import_module("strategies.4h.sprint2.hypotheses")

signal_h4s04_rsi_regime = s2_hyp.signal_h4s04_rsi_regime
signal_h4s03_relative_strength = s2_hyp.signal_h4s03_relative_strength
signal_h4s02_vol_exhaustion_fade = s2_hyp.signal_h4s02_vol_exhaustion_fade


# ---------------------------------------------------------------------------
# DC Exit Parameter Grid (3 variants)
# ---------------------------------------------------------------------------
DC_EXIT_VARIANTS = [
    {
        "label": "dc_tight",
        "max_stop_pct": 12.0,
        "time_max_bars": 10,
        "rsi_recovery": True,
        "rsi_rec_target": 45,
        "rsi_rec_min_bars": 2,
    },
    {
        "label": "dc_medium",
        "max_stop_pct": 15.0,
        "time_max_bars": 15,
        "rsi_recovery": True,
        "rsi_rec_target": 45,
        "rsi_rec_min_bars": 2,
    },
    {
        "label": "dc_wide",
        "max_stop_pct": 20.0,
        "time_max_bars": 20,
        "rsi_recovery": True,
        "rsi_rec_target": 42,
        "rsi_rec_min_bars": 2,
    },
]


# ---------------------------------------------------------------------------
# Entry parameter variants — best 2 from Sprint 2 per family
# ---------------------------------------------------------------------------

# H4S-04: RSI + Regime Filter
# Best: regime_type B, rsi_max=35 (PF=0.85)
# Alt:  regime_type A, rsi_max=40 (PF=0.61, different regime)
H4S04_ENTRY_VARIANTS = [
    {
        "label": "regime_typeB_rsi_max35",
        "rsi_max": 35,
        "regime_type": "B",
        "adx_min": 20,
        "vol_floor_mult": 1.0,
        "sl_pct": 5,
        "tp_pct": 8,
        "time_limit": 15,
        "max_pos": 3,
    },
    {
        "label": "regime_typeA_rsi_max40",
        "rsi_max": 40,
        "regime_type": "A",
        "slope_lookback": 10,
        "vol_floor_mult": 1.0,
        "sl_pct": 5,
        "tp_pct": 8,
        "time_limit": 15,
        "max_pos": 3,
    },
]

# H4S-03: Cross-Sectional Relative Strength
# Best: breadth=0.4, top_pct=5 (PF=0.81)
# Alt:  breadth=0.3, top_pct=10 (PF=0.80)
H4S03_ENTRY_VARIANTS = [
    {
        "label": "breadth04_top5",
        "momentum_period": 10,
        "top_pct": 5,
        "vol_mult": 2.0,
        "require_positive_return": True,
        "sma_filter": True,
        "breadth_min": 0.4,
        "sl_pct": 8,
        "tp_pct": 12,
        "time_limit": 25,
        "max_pos": 3,
    },
    {
        "label": "breadth03_top10",
        "momentum_period": 10,
        "top_pct": 10,
        "vol_mult": 1.5,
        "require_positive_return": True,
        "sma_filter": True,
        "breadth_min": 0.3,
        "sl_pct": 8,
        "tp_pct": 12,
        "time_limit": 25,
        "max_pos": 3,
    },
]

# H4S-02: Volatility Exhaustion Fade
# Best: bb_width_pct_high=70, decline_bars=1 (PF=0.81)
# Alt:  bb_width_pct_high=80, decline_bars=2 (PF=0.69)
H4S02_ENTRY_VARIANTS = [
    {
        "label": "bbw70_dec1",
        "expansion_lookback": 15,
        "bb_width_pct_high": 70,
        "decline_bars": 1,
        "no_new_low_bars": 3,
        "rsi_max": 40,
        "vol_decline_max": 1.0,
        "sl_pct": 5,
        "tp_pct": 8,
        "time_limit": 15,
        "max_pos": 3,
    },
    {
        "label": "bbw80_dec2",
        "expansion_lookback": 20,
        "bb_width_pct_high": 80,
        "decline_bars": 2,
        "no_new_low_bars": 5,
        "rsi_max": 40,
        "vol_decline_max": 0.8,
        "sl_pct": 5,
        "tp_pct": 5,
        "time_limit": 10,
        "max_pos": 3,
    },
]


# ---------------------------------------------------------------------------
# Family definitions — signal_fn + entry variants
# ---------------------------------------------------------------------------

_FAMILIES = [
    {
        "id_prefix": "H4S3-04",
        "name": "RSI + Regime Filter (DC Exits)",
        "category": "mean_reversion",
        "signal_fn": signal_h4s04_rsi_regime,
        "entry_variants": H4S04_ENTRY_VARIANTS,
        "description": (
            "RSI oversold + green bar + regime filter (SMA slope / ADX+DI), "
            "paired with DualConfirm hybrid_notrl exit intelligence."
        ),
    },
    {
        "id_prefix": "H4S3-03",
        "name": "Cross-Sectional Relative Strength (DC Exits)",
        "category": "momentum",
        "signal_fn": signal_h4s03_relative_strength,
        "entry_variants": H4S03_ENTRY_VARIANTS,
        "description": (
            "Top momentum cohort with cross-sectional ranking + volume/trend filters, "
            "paired with DualConfirm hybrid_notrl exit intelligence."
        ),
    },
    {
        "id_prefix": "H4S3-02",
        "name": "Volatility Exhaustion Fade (DC Exits)",
        "category": "mean_reversion",
        "signal_fn": signal_h4s02_vol_exhaustion_fade,
        "entry_variants": H4S02_ENTRY_VARIANTS,
        "description": (
            "BB width expansion -> decline + oversold + no new low, "
            "paired with DualConfirm hybrid_notrl exit intelligence."
        ),
    },
]


# ---------------------------------------------------------------------------
# Hypothesis dataclass (consistent with Sprint 2)
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str
    name: str
    category: str
    signal_fn: Callable
    param_variants: list[dict]
    description: str


# ---------------------------------------------------------------------------
# Registry — 3 Hypothesis entries
# ---------------------------------------------------------------------------

def _build_registry() -> list[Hypothesis]:
    """Build REGISTRY from families x entry_variants x DC exit grid."""
    registry = []
    for fam in _FAMILIES:
        all_variants = []
        for entry_v in fam["entry_variants"]:
            for exit_v in DC_EXIT_VARIANTS:
                merged = dict(entry_v)  # copy entry params
                # Overlay DC exit params (skip 'label')
                merged["max_stop_pct"] = exit_v["max_stop_pct"]
                merged["time_max_bars"] = exit_v["time_max_bars"]
                merged["rsi_recovery"] = exit_v["rsi_recovery"]
                merged["rsi_rec_target"] = exit_v["rsi_rec_target"]
                merged["rsi_rec_min_bars"] = exit_v["rsi_rec_min_bars"]
                # Store exit template label for tracking
                merged["_exit_template"] = exit_v["label"]
                merged["_entry_label"] = entry_v["label"]
                all_variants.append(merged)

        registry.append(Hypothesis(
            id=fam["id_prefix"],
            name=fam["name"],
            category=fam["category"],
            signal_fn=fam["signal_fn"],
            param_variants=all_variants,
            description=fam["description"],
        ))
    return registry


REGISTRY: list[Hypothesis] = _build_registry()


def get_hypothesis(hypothesis_id: str) -> Hypothesis:
    """Look up a hypothesis by ID."""
    for h in REGISTRY:
        if h.id == hypothesis_id:
            return h
    raise KeyError(f"Unknown hypothesis: {hypothesis_id}. Available: {[h.id for h in REGISTRY]}")


# ---------------------------------------------------------------------------
# Config generation — 18 configs total
# ---------------------------------------------------------------------------

_DC_EXIT_KEYS = {"max_stop_pct", "time_max_bars", "rsi_recovery", "rsi_rec_target", "rsi_rec_min_bars"}


def build_sweep_configs() -> list[dict]:
    """Generate all configs for Sprint 3 sweep.

    Returns list of 18 dicts:
      3 families x 2 entry variants x 3 DC exit variants.

    Each dict has keys:
      id, idx, label, hypothesis_id, hypothesis_name, category,
      signal_fn, params, exit_template.
    """
    configs = []
    idx = 0

    for hyp in REGISTRY:
        for variant in hyp.param_variants:
            idx += 1

            entry_label = variant.get("_entry_label", "unk")
            exit_template = variant.get("_exit_template", "unk")

            # Build label: family + entry + exit
            family_tag = hyp.id.lower().replace("-", "")
            label = f"{family_tag}_{entry_label}_{exit_template}"

            # Build clean params (strip internal tracking keys)
            params = {k: v for k, v in variant.items()
                      if not k.startswith("_") and k != "label"}

            configs.append({
                "id": f"sprint3_{idx:03d}_{label}",
                "idx": idx,
                "label": label,
                "hypothesis_id": hyp.id,
                "hypothesis_name": hyp.name,
                "category": hyp.category,
                "signal_fn": hyp.signal_fn,
                "params": params,
                "exit_template": exit_template,
            })

    return configs


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Sprint 3 hypotheses.py self-test ===\n")

    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Count per family
    from collections import Counter
    family_counts = Counter(c["hypothesis_id"] for c in configs)
    for fam_id, count in sorted(family_counts.items()):
        hyp = get_hypothesis(fam_id)
        print(f"    {fam_id}: {hyp.name} -- {count} variants")

    # --- Check 1: exactly 18 configs ---
    assert len(configs) == 18, f"Expected 18 configs, got {len(configs)}"
    print("\n  [PASS] 18 configs generated")

    # --- Check 2: all IDs unique ---
    ids = [c["id"] for c in configs]
    dupes = [x for x in ids if ids.count(x) > 1]
    assert len(ids) == len(set(ids)), f"Duplicate IDs: {dupes}"
    print("  [PASS] All config IDs are unique")

    # --- Check 3: all signal_fn's are callable ---
    for c in configs:
        assert callable(c["signal_fn"]), f"signal_fn not callable in {c['id']}"
    print("  [PASS] All signal_fn's are callable")

    # --- Check 4: all DC exit params present in every config ---
    required_dc_keys = {"max_stop_pct", "time_max_bars", "rsi_recovery",
                        "rsi_rec_target", "rsi_rec_min_bars"}
    for c in configs:
        missing = required_dc_keys - set(c["params"].keys())
        assert not missing, f"Missing DC exit keys {missing} in {c['id']}"
    print("  [PASS] All DC exit params present in every config")

    # --- Check 5: 6 configs per family (2 entry x 3 exit) ---
    for fam_id, count in family_counts.items():
        assert count == 6, f"Expected 6 configs for {fam_id}, got {count}"
    print("  [PASS] 6 configs per family (2 entry x 3 exit)")

    # --- Check 6: exit_template values match DC_EXIT_VARIANTS labels ---
    valid_templates = {v["label"] for v in DC_EXIT_VARIANTS}
    for c in configs:
        assert c["exit_template"] in valid_templates, \
            f"Invalid exit_template '{c['exit_template']}' in {c['id']}"
    print("  [PASS] All exit_template labels are valid")

    # --- Print sample config ---
    print(f"\n  Sample config (first):")
    sample = configs[0]
    for k, v in sample.items():
        if k == "signal_fn":
            print(f"    {k}: {v.__name__}")
        elif k == "params":
            print(f"    {k}:")
            for pk, pv in sorted(v.items()):
                print(f"      {pk}: {pv}")
        else:
            print(f"    {k}: {v}")

    print(f"\n{'='*50}")
    print(f"  ALL CHECKS PASSED ({len(configs)} configs validated)")
