"""
MS Scalp Screening Gates — Adjusted for structural signal characteristics.
=========================================================================

MS signals fire less frequently than indicator signals, so trade count
thresholds are lower. Breakeven spread gate (S4) is NEW and CRITICAL:
indicator approach failed at breakeven_spread = 2.1 bps vs P95 spread 2.97 bps.

Gate hierarchy:
    G0 TRADES:      ≥ 100          (hard) — was ≥500, MS fires less often
    G1 PF:          ≥ 1.10         (hard) — higher bar compensates lower N
    G2 PF_ADV:      ≥ 1.20         (soft) — promotes to verification
    S1 DD:          ≤ 30%          (soft) — unchanged
    S2 TPD:         ≥ 0.5/day      (soft) — was ≥3/day, MS is rarer
    S3 WR:          ≥ 40%          (info) — low WR + high PF = edge
    S4 BRK_SPREAD:  ≥ 3.0 bps      (hard) — MUST survive P95 spread (2.97 bps)
"""

from __future__ import annotations
from strategies.scalp.harness import BacktestResult

# Gate thresholds
G0_TRADES = 100       # was 500 for indicator sweep
G1_PF = 1.10          # was 1.05
G2_PF_ADV = 1.20      # was 1.15
S1_DD = 30.0          # unchanged
S2_TPD = 0.5          # was 3.0
S3_WR = 40.0          # informational
S4_BRK_SPREAD = 3.0   # NEW — breakeven spread in bps (hard gate)


def compute_breakeven_spread(result: BacktestResult, base_spread_bps: float) -> float:
    """Compute breakeven spread = spread at which strategy becomes PF=1.0.

    Logic: At base_spread_bps, the strategy generates gross_wins and gross_losses.
    Each trade has 2 * spread_fraction * trade_value deducted.
    Breakeven is the spread where net_pnl = 0.

    Returns breakeven spread in bps, or 0.0 if insufficient data.
    """
    if not result.trade_list or result.trades == 0:
        return 0.0

    net_pnl = result.pnl
    if net_pnl <= 0:
        return 0.0  # Already unprofitable, breakeven < base_spread

    # Total spread cost at current bps
    # Each trade: entry spread + exit spread = 2 * spread_fraction * capital
    # spread_fraction = spread_bps / 10000
    # Total cost = n_trades * 2 * spread_fraction * avg_trade_value
    spread_fraction = base_spread_bps / 10000.0

    # Estimate total spread cost from the trades
    # Entry fill = price * (1 + spread_fraction), exit fill = price * (1 - spread_fraction)
    # Net spread cost per trade ≈ 2 * spread_fraction * capital_per_trade
    # Since we know net_pnl at base_spread, we can compute:
    # gross_pnl = net_pnl + total_spread_cost
    # breakeven_spread = gross_pnl / (n_trades * 2 * avg_capital * 10000)

    # More precise: use trade list to compute what PnL would be at 0 spread
    # Then solve for spread where PnL = 0
    n_trades = result.trades

    # Approximate: each side costs spread_fraction * capital (~$200)
    # 2 sides per trade, so total cost = n_trades * 2 * 200 * spread_fraction
    capital_per_trade = 200.0  # Standard from harness
    total_spread_cost = n_trades * 2 * capital_per_trade * spread_fraction
    gross_pnl = net_pnl + total_spread_cost

    if gross_pnl <= 0:
        return 0.0

    # At breakeven: gross_pnl = n_trades * 2 * capital * be_spread_fraction
    be_spread_fraction = gross_pnl / (n_trades * 2 * capital_per_trade)
    be_spread_bps = be_spread_fraction * 10000.0

    return round(be_spread_bps, 2)


def evaluate_gates(
    result: BacktestResult,
    base_spread_bps: float = 1.5,
) -> dict:
    """Evaluate a BacktestResult against MS screening gates.

    Args:
        result: BacktestResult from harness
        base_spread_bps: spread used in the backtest (for breakeven calc)

    Returns:
        dict with gate results, verdict, and breakeven spread
    """
    brk_spread = compute_breakeven_spread(result, base_spread_bps)

    g0 = result.trades >= G0_TRADES
    g1 = result.pf >= G1_PF
    g2 = result.pf >= G2_PF_ADV
    s1 = result.dd <= S1_DD
    s2 = result.trades_per_day >= S2_TPD
    s3 = result.wr >= S3_WR  # informational
    s4 = brk_spread >= S4_BRK_SPREAD

    # Verdict: hard gates = G0 + G1 + S4
    hard_pass = g0 and g1 and s4
    if hard_pass and g2:
        verdict = 'GO_ADVANCED'
    elif hard_pass:
        verdict = 'GO'
    elif g0 and g1 and not s4:
        verdict = 'GO_SPREAD_RISK'  # PF OK but won't survive P95 spread
    elif g0 and result.pf >= 1.0:
        verdict = 'MARGINAL'
    else:
        verdict = 'NO_GO'

    return {
        'g0_trades': g0,
        'g1_pf': g1,
        'g2_pf_adv': g2,
        's1_dd': s1,
        's2_tpd': s2,
        's3_wr': s3,
        's4_brk_spread': s4,
        'breakeven_spread_bps': brk_spread,
        'verdict': verdict,
        'hard_pass': hard_pass,
        'soft_flags': sum([s1, s2, s3]),
    }
