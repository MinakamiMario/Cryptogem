"""
SuperHF Sprint 3 — 20 Signal Configs (5 families × 3-6 variants).

Track 1 — VWAP Deviation on 15m (Family F, 6 configs)
  F01-F03: Raw HLC3 VWAP deviation (price below VWAP + bounce)
  F04-F06: Z-score normalized deviation (handles HLC3 structural cap)

Track 2 — 1H Entry + 15m Timing (Families C, D, E, 10 configs)
  Family C: 1H Bounce at Pivot Low + DC-geometry gate (4 configs)
  Family D: 1H DC Low Reclaim (3 configs)
  Family E: 1H Vol Capitulation (3 configs, adapted from 4H sprint4_041)

Track 3 — DC-Geometry + VWAP Hybrid (Family G, 4 configs)
  Conjunction: close < dc_mid AND close < bb_mid AND RSI < threshold AND VWAP_dev > threshold

Signal protocol:
    signal_fn(candles, bar, indicators_15m, params, support_zone) -> dict | None
    Return: {'strength': float} or None

Exits handled by harness.py (hybrid_notrl).
Key exit params: rsi_recovery (True/False), time_max_bars, max_stop_pct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# Hypothesis dataclass (same as Sprint 1)
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str           # SHF-C01, SHF-F01, SHF-G01, ...
    name: str
    family: str
    signal_fn: Callable
    params: dict
    description: str


REGISTRY: dict[str, Hypothesis] = {}


def register(hyp: Hypothesis):
    REGISTRY[hyp.id] = hyp


# ===========================================================================
# TRACK 1 — Family F: VWAP Deviation on 15m
# ===========================================================================

def _check_bounce(ind: dict, bar: int) -> bool:
    """Bounce confirmation: close > prev_close (green recovery)."""
    if bar < 1:
        return False
    return ind['closes'][bar] > ind['closes'][bar - 1]


def signal_vwap_dev_raw(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """F01-F03: Raw HLC3 VWAP deviation entry.

    Conditions:
    1. vwap_dev > dev_thresh (price below VWAP by > threshold ATRs)
    2. Bounce: close > prev_close
    3. RSI < rsi_max (oversold filter)
    4. Optional: DC-geometry gate (close < dc_mid AND close < bb_mid)
    """
    n = ind.get('n', 0)
    if bar < 1 or bar >= n:
        return None

    vwap_dev = ind.get('vwap_dev', [])
    if bar >= len(vwap_dev) or vwap_dev[bar] is None:
        return None

    dev = vwap_dev[bar]
    dev_thresh = params.get('dev_thresh', 0.3)
    if dev < dev_thresh:
        return None

    # Bounce confirmation
    if not _check_bounce(ind, bar):
        return None

    # RSI filter
    rsi = ind['rsi'][bar]
    if rsi is None:
        return None
    rsi_max = params.get('rsi_max', 45)
    if rsi >= rsi_max:
        return None

    # Optional DC-geometry gate
    if params.get('dc_geometry', False):
        dc_mid = ind.get('dc_mid', [None] * n)
        bb_mid = ind.get('bb_mid', [None] * n)
        close = ind['closes'][bar]
        if (bar < len(dc_mid) and dc_mid[bar] is not None
                and close >= dc_mid[bar]):
            return None
        if (bar < len(bb_mid) and bb_mid[bar] is not None
                and close >= bb_mid[bar]):
            return None

    # Strength: deviation magnitude
    strength = min(1.0, dev / max(dev_thresh, 0.1))

    return {'strength': strength}


def signal_vwap_dev_zscore(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """F04-F06: Z-score normalized VWAP deviation entry.

    Solves HLC3 structural cap: raw HLC3 deviation is ~0.3 ATR max,
    but z-score normalizes against per-coin history so extreme
    deviations (z >= 1.5) still trigger reliably.

    Conditions:
    1. vwap_dev_zscore > zscore_thresh (normalized deviation extreme)
    2. Bounce: close > prev_close
    3. RSI < rsi_max
    """
    n = ind.get('n', 0)
    if bar < 1 or bar >= n:
        return None

    zscore_list = ind.get('vwap_dev_zscore', [])
    if bar >= len(zscore_list) or zscore_list[bar] is None:
        return None

    zscore = zscore_list[bar]
    zscore_thresh = params.get('zscore_thresh', 2.0)
    if zscore < zscore_thresh:
        return None

    # Bounce confirmation
    if not _check_bounce(ind, bar):
        return None

    # RSI filter
    rsi = ind['rsi'][bar]
    if rsi is None:
        return None
    rsi_max = params.get('rsi_max', 45)
    if rsi >= rsi_max:
        return None

    # Strength: z-score magnitude
    strength = min(1.0, zscore / max(zscore_thresh, 0.1) * 0.5)

    return {'strength': strength}


# ===========================================================================
# TRACK 2 — Family C: 1H Bounce at Pivot Low + DC-geometry gate
# ===========================================================================

def _check_dc_geometry(ind: dict, bar: int) -> bool:
    """DC-geometry gate: close MUST be below dc_mid AND below bb_mid.

    This is the key insight from 4H Sprint 4: entries that respect
    DC geometry (close < dc_mid, close < bb_mid) work with DC exits.
    Without this gate, 0/18 Sprint 3 configs passed.
    With this gate, 7/10 Sprint 4 configs had PF > 1.05.
    """
    n = ind.get('n', 0)
    if bar >= n:
        return False

    close = ind['closes'][bar]
    dc_mid = ind.get('dc_mid', [None] * n)
    bb_mid = ind.get('bb_mid', [None] * n)

    if bar >= len(dc_mid) or dc_mid[bar] is None:
        return False
    if bar >= len(bb_mid) or bb_mid[bar] is None:
        return False

    return close < dc_mid[bar] and close < bb_mid[bar]


def signal_pivot_reclaim_dcgate(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """C01-C04: Pivot reclaim with MANDATORY DC-geometry gate.

    Same as Sprint 1 Family A, but with DC-geometry enforcement.
    Sprint 1 A01-A06 all had PF < 1.0 WITHOUT this gate.
    4H Sprint 4 proved the gate is essential.

    Conditions:
    1. support_zone exists (1H pivot or stacked zone)
    2. 15m low ≤ support_zone (touch/break)
    3. 15m close > support_zone (reclaim)
    4. DC-geometry: close < dc_mid AND close < bb_mid (15m level)
    5. RSI < rsi_max
    """
    if support_zone is None or support_zone <= 0:
        return None

    n = ind.get('n', 0)
    if bar < 0 or bar >= n:
        return None

    close = ind['closes'][bar]
    low = ind['lows'][bar]
    rsi = ind['rsi'][bar]

    if rsi is None:
        return None

    # Entry: touch + reclaim
    if low > support_zone:
        return None
    if close <= support_zone:
        return None

    # DC-geometry gate (MANDATORY)
    if not _check_dc_geometry(ind, bar):
        return None

    # RSI filter
    rsi_max = params.get('rsi_max', 40)
    if rsi >= rsi_max:
        return None

    # Optional volume filter
    if params.get('vol_filter', False):
        vol = ind['volumes'][bar]
        vol_avg = ind['vol_avg'][bar]
        vol_mult = params.get('vol_mult', 1.5)
        if vol_avg is None or vol_avg <= 0 or vol < vol_avg * vol_mult:
            return None

    # Strength
    depth = (support_zone - low) / support_zone if support_zone > 0 else 0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, depth * 5 + rsi_score * 0.5)

    return {'strength': strength}


# ===========================================================================
# TRACK 2 — Family D: 1H DC Low Reclaim
# ===========================================================================

def signal_dc_low_reclaim(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """D01-D03: Entry when 15m price touches 15m DC prev_low + reclaim.

    Uses 15m Donchian low directly (not 1H support zone).
    DC-geometry gate enforced: close < dc_mid AND close < bb_mid.

    Conditions:
    1. 15m low ≤ dc_prev_low (touch/break the channel low)
    2. 15m close > dc_prev_low (reclaim above)
    3. DC-geometry: close < dc_mid AND close < bb_mid
    4. RSI < rsi_max
    5. Optional: 1H support zone confirmation (support_zone within ATR of dc_prev_low)
    """
    n = ind.get('n', 0)
    if bar < 1 or bar >= n:
        return None

    dc_prev_low = ind.get('dc_prev_low', [None] * n)
    if bar >= len(dc_prev_low) or dc_prev_low[bar] is None:
        return None

    dc_low = dc_prev_low[bar]
    close = ind['closes'][bar]
    low = ind['lows'][bar]
    rsi = ind['rsi'][bar]

    if rsi is None or dc_low <= 0:
        return None

    # Touch/break DC low
    if low > dc_low:
        return None

    # Reclaim
    if close <= dc_low:
        return None

    # DC-geometry gate
    if not _check_dc_geometry(ind, bar):
        return None

    # RSI filter
    rsi_max = params.get('rsi_max', 40)
    if rsi >= rsi_max:
        return None

    # Optional: 1H zone confirmation
    if params.get('zone_confirm', False) and support_zone is not None:
        atr = ind['atr'][bar]
        if atr is not None and atr > 0:
            dist = abs(dc_low - support_zone) / atr
            if dist > 2.0:  # 1H zone too far from DC low → weaker signal
                return None

    # Strength
    depth = (dc_low - low) / dc_low if dc_low > 0 else 0
    rsi_score = (rsi_max - rsi) / rsi_max
    strength = min(1.0, depth * 5 + rsi_score * 0.5)

    return {'strength': strength}


# ===========================================================================
# TRACK 2 — Family E: 1H Vol Capitulation (adapted from 4H sprint4_041)
# ===========================================================================

def signal_vol_capitulation_15m(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """E01-E03: Volume capitulation on 15m — ported from 4H sprint4_041.

    The VERIFIED pattern from 4H: volume spike + close below BB lower
    + RSI oversold + DC-geometry gate.

    Conditions:
    1. volume > vol_avg × vol_mult (capitulation volume spike)
    2. close < bb_lower (price pierces lower Bollinger)
    3. DC-geometry: close < dc_mid AND close < bb_mid
    4. RSI < rsi_max
    5. Bounce: close > prev_close (recovery started)
    """
    n = ind.get('n', 0)
    if bar < 1 or bar >= n:
        return None

    close = ind['closes'][bar]
    vol = ind['volumes'][bar]
    vol_avg = ind['vol_avg'][bar]
    rsi = ind['rsi'][bar]
    bb_lower = ind.get('bb_lower', [None] * n)

    if rsi is None or vol_avg is None or vol_avg <= 0:
        return None
    if bar >= len(bb_lower) or bb_lower[bar] is None:
        return None

    # Volume spike
    vol_mult = params.get('vol_mult', 3.0)
    if vol < vol_avg * vol_mult:
        return None

    # Close below BB lower (extreme reading)
    if close >= bb_lower[bar]:
        return None

    # DC-geometry gate
    if not _check_dc_geometry(ind, bar):
        return None

    # RSI filter
    rsi_max = params.get('rsi_max', 40)
    if rsi >= rsi_max:
        return None

    # Bounce confirmation
    if not _check_bounce(ind, bar):
        return None

    # Strength: volume magnitude + RSI depth
    vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
    rsi_depth = (rsi_max - rsi) / rsi_max
    strength = min(1.0, (vol_ratio / 10.0) * 0.6 + rsi_depth * 0.4)

    return {'strength': strength}


# ===========================================================================
# TRACK 3 — Family G: DC-Geometry + VWAP Hybrid
# ===========================================================================

def signal_dcgeo_vwap_hybrid(
    candles: list[dict],
    bar: int,
    ind: dict,
    params: dict,
    support_zone: float | None,
) -> dict | None:
    """G01-G04: Conjunction of DC-geometry + VWAP deviation.

    Combines TWO independently validated concepts:
    - DC-geometry gate (from 4H Sprint 4 — 7/10 configs PF > 1.05)
    - VWAP deviation (from HF VWAP_DEV — PF=2.86 maker on MEXC)

    Risk Governor recommended this as highest priority (Track 3).

    Conditions:
    1. DC-geometry: close < dc_mid AND close < bb_mid
    2. VWAP deviation > dev_thresh (price below VWAP)
    3. RSI < rsi_max
    4. Bounce: close > prev_close
    5. Optional: 1H zone confirmation (support_zone exists and is near close)
    """
    n = ind.get('n', 0)
    if bar < 1 or bar >= n:
        return None

    # DC-geometry gate (MANDATORY)
    if not _check_dc_geometry(ind, bar):
        return None

    # VWAP deviation
    vwap_dev = ind.get('vwap_dev', [])
    if bar >= len(vwap_dev) or vwap_dev[bar] is None:
        return None

    dev = vwap_dev[bar]
    dev_thresh = params.get('dev_thresh', 0.3)
    if dev < dev_thresh:
        return None

    # RSI filter
    rsi = ind['rsi'][bar]
    if rsi is None:
        return None
    rsi_max = params.get('rsi_max', 40)
    if rsi >= rsi_max:
        return None

    # Bounce confirmation
    if not _check_bounce(ind, bar):
        return None

    # Optional: 1H zone confirmation
    if params.get('zone_confirm', False):
        if support_zone is None:
            return None
        close = ind['closes'][bar]
        atr = ind['atr'][bar]
        if atr is not None and atr > 0:
            dist = abs(close - support_zone) / atr
            if dist > 3.0:  # too far from 1H support
                return None

    # Strength: VWAP dev + RSI depth
    rsi_depth = (rsi_max - rsi) / rsi_max
    dev_score = min(1.0, dev / max(dev_thresh, 0.1) * 0.3)
    strength = min(1.0, dev_score * 0.6 + rsi_depth * 0.4)

    return {'strength': strength}


# ===========================================================================
# Config Grids
# ===========================================================================

_BASE_EXIT_PARAMS = {
    "max_stop_pct": 15.0,
    "time_max_bars": 60,       # 60 × 15m = 15H
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 8,     # 8 × 15m = 2H
    "spread_cap_bps": 40,
    "pivot_lookback": 40,
}

# ── Track 1: Family F — VWAP Deviation (6 configs) ─────────────────────
# F01-F03: Raw deviation (dev_thresh calibrated for HLC3 ~0.2-0.5 range)
# F04-F06: Z-score (normalized, handles structural cap)
_FAMILY_F_CONFIGS = [
    {"id": "SHF-F01", "dev_thresh": 0.2, "rsi_max": 45, "rsi_recovery": True,
     "desc": "VWAP raw dev≥0.2 ATR, RSI<45, rsi_recovery ON"},
    {"id": "SHF-F02", "dev_thresh": 0.3, "rsi_max": 40, "rsi_recovery": True,
     "desc": "VWAP raw dev≥0.3 ATR, RSI<40, rsi_recovery ON"},
    {"id": "SHF-F03", "dev_thresh": 0.5, "rsi_max": 40, "rsi_recovery": False,
     "desc": "VWAP raw dev≥0.5 ATR, RSI<40, rsi_recovery OFF"},
    {"id": "SHF-F04", "zscore_thresh": 1.5, "rsi_max": 45, "rsi_recovery": True,
     "desc": "VWAP zscore≥1.5, RSI<45, rsi_recovery ON", "signal": "zscore"},
    {"id": "SHF-F05", "zscore_thresh": 2.0, "rsi_max": 40, "rsi_recovery": True,
     "desc": "VWAP zscore≥2.0, RSI<40, rsi_recovery ON", "signal": "zscore"},
    {"id": "SHF-F06", "zscore_thresh": 2.5, "rsi_max": 40, "rsi_recovery": False,
     "desc": "VWAP zscore≥2.5, RSI<40, rsi_recovery OFF", "signal": "zscore"},
]

# ── Track 2: Family C — 1H Bounce at Pivot Low + DC-geometry (4 configs) ───
_FAMILY_C_CONFIGS = [
    {"id": "SHF-C01", "rsi_max": 40, "zone_type": "pivot_only", "rsi_recovery": True,
     "desc": "Pivot reclaim + DC-geo, RSI<40, rsi_recovery ON"},
    {"id": "SHF-C02", "rsi_max": 35, "zone_type": "pivot_only", "rsi_recovery": True,
     "desc": "Pivot reclaim + DC-geo, RSI<35, rsi_recovery ON"},
    {"id": "SHF-C03", "rsi_max": 45, "zone_type": "pivot_only", "rsi_recovery": False,
     "desc": "Pivot reclaim + DC-geo, RSI<45, rsi_recovery OFF"},
    {"id": "SHF-C04", "rsi_max": 40, "zone_type": "dc_bb_stack", "rsi_recovery": True,
     "vol_filter": True, "vol_mult": 1.5,
     "desc": "Stacked zone + DC-geo, RSI<40, vol 1.5x, rsi_recovery ON"},
]

# ── Track 2: Family D — 1H DC Low Reclaim (3 configs) ──────────────────
_FAMILY_D_CONFIGS = [
    {"id": "SHF-D01", "rsi_max": 40, "zone_confirm": False, "rsi_recovery": True,
     "desc": "DC low reclaim, RSI<40, no 1H confirm, rsi_recovery ON"},
    {"id": "SHF-D02", "rsi_max": 35, "zone_confirm": True, "rsi_recovery": True,
     "desc": "DC low reclaim, RSI<35, 1H zone confirm, rsi_recovery ON"},
    {"id": "SHF-D03", "rsi_max": 45, "zone_confirm": False, "rsi_recovery": False,
     "desc": "DC low reclaim, RSI<45, no 1H confirm, rsi_recovery OFF"},
]

# ── Track 2: Family E — 1H Vol Capitulation (3 configs) ────────────────
_FAMILY_E_CONFIGS = [
    {"id": "SHF-E01", "vol_mult": 3.0, "rsi_max": 40, "rsi_recovery": True,
     "desc": "Vol cap 3x + DC-geo + BB-low, RSI<40, rsi_recovery ON"},
    {"id": "SHF-E02", "vol_mult": 3.0, "rsi_max": 35, "rsi_recovery": True,
     "desc": "Vol cap 3x + DC-geo + BB-low, RSI<35, rsi_recovery ON"},
    {"id": "SHF-E03", "vol_mult": 4.0, "rsi_max": 40, "rsi_recovery": False,
     "desc": "Vol cap 4x + DC-geo + BB-low, RSI<40, rsi_recovery OFF"},
]

# ── Track 3: Family G — DC-Geometry + VWAP Hybrid (4 configs) ──────────
_FAMILY_G_CONFIGS = [
    {"id": "SHF-G01", "dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": False,
     "rsi_recovery": True,
     "desc": "DC-geo + VWAP dev≥0.2, RSI<40, 15m only, rsi_recovery ON"},
    {"id": "SHF-G02", "dev_thresh": 0.3, "rsi_max": 40, "zone_confirm": False,
     "rsi_recovery": True,
     "desc": "DC-geo + VWAP dev≥0.3, RSI<40, 15m only, rsi_recovery ON"},
    {"id": "SHF-G03", "dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": True,
     "rsi_recovery": True,
     "desc": "DC-geo + VWAP dev≥0.2, RSI<40, 1H confirm, rsi_recovery ON"},
    {"id": "SHF-G04", "dev_thresh": 0.3, "rsi_max": 35, "zone_confirm": True,
     "rsi_recovery": False,
     "desc": "DC-geo + VWAP dev≥0.3, RSI<35, 1H confirm, rsi_recovery OFF"},
]


def build_all_configs() -> list[Hypothesis]:
    """Build all 20 Sprint 3 hypothesis configs and register them."""
    hypotheses: list[Hypothesis] = []

    # Family F — VWAP Deviation (6 configs)
    for cfg in _FAMILY_F_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **{k: v for k, v in cfg.items()
                                          if k not in ('id', 'desc', 'signal')}}
        # Zone type not needed for VWAP signal (ignores support_zone)
        params.setdefault("zone_type", "pivot_only")
        is_zscore = cfg.get("signal") == "zscore"
        sig_fn = signal_vwap_dev_zscore if is_zscore else signal_vwap_dev_raw
        variant = "zscore" if is_zscore else "raw"
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"VWAP_DEV_{variant}_{cfg['id'][-2:]}",
            family="vwap_deviation",
            signal_fn=sig_fn,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    # Family C — Pivot Reclaim + DC-geometry (4 configs)
    for cfg in _FAMILY_C_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **{k: v for k, v in cfg.items()
                                          if k not in ('id', 'desc')}}
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"PivotReclaim_DCgeo_{cfg['rsi_max']}",
            family="pivot_reclaim_dcgeo",
            signal_fn=signal_pivot_reclaim_dcgate,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    # Family D — DC Low Reclaim (3 configs)
    for cfg in _FAMILY_D_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **{k: v for k, v in cfg.items()
                                          if k not in ('id', 'desc')}}
        params.setdefault("zone_type", "pivot_only")
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"DCLowReclaim_{cfg['rsi_max']}",
            family="dc_low_reclaim",
            signal_fn=signal_dc_low_reclaim,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    # Family E — Vol Capitulation 15m (3 configs)
    for cfg in _FAMILY_E_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **{k: v for k, v in cfg.items()
                                          if k not in ('id', 'desc')}}
        params.setdefault("zone_type", "pivot_only")
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"VolCap15m_{cfg['vol_mult']}x_rsi{cfg['rsi_max']}",
            family="vol_capitulation_15m",
            signal_fn=signal_vol_capitulation_15m,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    # Family G — DC-Geometry + VWAP Hybrid (4 configs)
    for cfg in _FAMILY_G_CONFIGS:
        params = {**_BASE_EXIT_PARAMS, **{k: v for k, v in cfg.items()
                                          if k not in ('id', 'desc')}}
        params.setdefault("zone_type", "pivot_only")
        hyp = Hypothesis(
            id=cfg["id"],
            name=f"DCgeo_VWAP_{cfg['dev_thresh']}",
            family="dcgeo_vwap_hybrid",
            signal_fn=signal_dcgeo_vwap_hybrid,
            params=params,
            description=cfg["desc"],
        )
        register(hyp)
        hypotheses.append(hyp)

    return hypotheses


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    random.seed(42)

    passed = 0
    failed = 0

    def check(name, condition, msg=""):
        global passed, failed
        if condition:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name} — {msg}")
            failed += 1

    print("=== SuperHF Sprint 3 Hypotheses Self-Test ===\n")

    # Build all configs
    configs = build_all_configs()
    check("20_configs_registered", len(configs) == 20, f"got {len(configs)}")
    check("registry_has_20", len(REGISTRY) == 20, f"got {len(REGISTRY)}")

    # Check families
    fam_f = [h for h in configs if h.family == "vwap_deviation"]
    fam_c = [h for h in configs if h.family == "pivot_reclaim_dcgeo"]
    fam_d = [h for h in configs if h.family == "dc_low_reclaim"]
    fam_e = [h for h in configs if h.family == "vol_capitulation_15m"]
    fam_g = [h for h in configs if h.family == "dcgeo_vwap_hybrid"]

    check("family_f_has_6", len(fam_f) == 6, f"got {len(fam_f)}")
    check("family_c_has_4", len(fam_c) == 4, f"got {len(fam_c)}")
    check("family_d_has_3", len(fam_d) == 3, f"got {len(fam_d)}")
    check("family_e_has_3", len(fam_e) == 3, f"got {len(fam_e)}")
    check("family_g_has_4", len(fam_g) == 4, f"got {len(fam_g)}")

    # Check unique IDs
    ids = [h.id for h in configs]
    check("unique_ids", len(set(ids)) == 20, f"dupes: {[x for x in ids if ids.count(x) > 1]}")

    # Check all have required params
    for hyp in configs:
        has_exit = all(k in hyp.params for k in ["max_stop_pct", "time_max_bars"])
        check(f"{hyp.id}_has_exit_params", has_exit,
              f"missing keys in {list(hyp.params.keys())}")

    # Synthetic signal test — generate fake candles and indicators
    print("\n--- Signal Function Tests ---")

    n = 200
    candles = [{'time': i * 900, 'open': 100, 'high': 102, 'low': 98,
                'close': 100, 'volume': 1000} for i in range(n)]

    # Build fake indicators
    ind = {
        'n': n,
        'closes': [100.0] * n,
        'highs': [102.0] * n,
        'lows': [98.0] * n,
        'opens': [100.0] * n,
        'volumes': [1000.0] * n,
        'rsi': [30.0] * n,          # Oversold
        'atr': [2.0] * n,           # 2% ATR
        'vol_avg': [500.0] * n,     # Below current vol → spike
        'dc_prev_low': [97.0] * n,  # DC low below close
        'dc_mid': [101.0] * n,      # DC mid above close → geometry pass
        'bb_mid': [101.0] * n,      # BB mid above close → geometry pass
        'bb_lower': [96.0] * n,     # BB lower below close
        'bb_upper': [104.0] * n,
        'vwap': [100.5] * n,        # VWAP above close
        'vwap_dev': [0.25] * n,     # (vwap - close) / atr
        'vwap_dev_zscore': [2.5] * n,  # High z-score
    }

    # Make bar 50 a "bounce" (close > prev_close)
    ind['closes'][49] = 99.0
    ind['closes'][50] = 100.0

    # Test F01 (raw VWAP dev)
    sig_f01 = signal_vwap_dev_raw(candles, 50, ind, {"dev_thresh": 0.2, "rsi_max": 45}, None)
    check("F_raw_triggers", sig_f01 is not None, f"got {sig_f01}")

    # Test F04 (zscore VWAP dev)
    sig_f04 = signal_vwap_dev_zscore(candles, 50, ind, {"zscore_thresh": 2.0, "rsi_max": 45}, None)
    check("F_zscore_triggers", sig_f04 is not None, f"got {sig_f04}")

    # Test C01 (pivot reclaim + DC-geo) — needs support_zone
    ind['lows'][50] = 96.5  # Below support
    ind['closes'][50] = 100.0  # Reclaim
    sig_c = signal_pivot_reclaim_dcgate(candles, 50, ind, {"rsi_max": 40}, 97.0)
    check("C_dcgeo_triggers", sig_c is not None, f"got {sig_c}")

    # Test C01 without DC-geometry → should NOT trigger (close > dc_mid)
    ind['dc_mid'][50] = 99.0  # dc_mid below close → geometry FAILS
    sig_c_fail = signal_pivot_reclaim_dcgate(candles, 50, ind, {"rsi_max": 40}, 97.0)
    check("C_dcgeo_blocks_when_close_above_dcmid", sig_c_fail is None,
          f"should be None, got {sig_c_fail}")
    ind['dc_mid'][50] = 101.0  # Restore

    # Test D01 (DC low reclaim)
    ind['lows'][50] = 96.5   # Below dc_prev_low (97.0)
    ind['closes'][50] = 100.0  # Reclaim above
    sig_d = signal_dc_low_reclaim(candles, 50, ind, {"rsi_max": 40, "zone_confirm": False}, None)
    check("D_dclow_triggers", sig_d is not None, f"got {sig_d}")

    # Test E01 (vol capitulation)
    ind['closes'][50] = 95.0  # Below bb_lower (96.0)
    ind['closes'][49] = 94.0  # Prev close even lower → bounce
    ind['dc_mid'][50] = 101.0
    ind['bb_mid'][50] = 101.0
    ind['volumes'][50] = 2000.0  # 4x vol_avg (500)
    sig_e = signal_vol_capitulation_15m(candles, 50, ind, {"vol_mult": 3.0, "rsi_max": 40}, None)
    check("E_volcap_triggers", sig_e is not None, f"got {sig_e}")

    # Test G01 (DC-geo + VWAP hybrid)
    ind['closes'][50] = 100.0
    ind['closes'][49] = 99.0  # Bounce
    ind['dc_mid'][50] = 101.0
    ind['bb_mid'][50] = 101.0
    sig_g = signal_dcgeo_vwap_hybrid(
        candles, 50, ind, {"dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": False}, None
    )
    check("G_hybrid_triggers", sig_g is not None, f"got {sig_g}")

    # Test G03 with zone_confirm — no support → None
    sig_g_nozone = signal_dcgeo_vwap_hybrid(
        candles, 50, ind, {"dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": True}, None
    )
    check("G_hybrid_blocks_no_zone", sig_g_nozone is None,
          f"should be None, got {sig_g_nozone}")

    # Test G03 with zone_confirm — support too far → None
    sig_g_far = signal_dcgeo_vwap_hybrid(
        candles, 50, ind, {"dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": True}, 80.0
    )
    check("G_hybrid_blocks_far_zone", sig_g_far is None,
          f"should be None, got {sig_g_far}")

    # Test G03 with zone_confirm — support close → triggers
    sig_g_close = signal_dcgeo_vwap_hybrid(
        candles, 50, ind, {"dev_thresh": 0.2, "rsi_max": 40, "zone_confirm": True}, 99.0
    )
    check("G_hybrid_triggers_with_zone", sig_g_close is not None,
          f"got {sig_g_close}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        exit(1)
    print("All tests passed!")
