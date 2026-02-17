# Robustness Notes — Sweep V1

## Anti-Overfit Checks

### Outlier Concentration (G6, advisory)
- What: Does 1 trade dominate total profit?
- Threshold: top1 trade < 70% of total positive P&L
- Why: Historical lesson — ZEUS trade ($3,333) was 84% of BASELINE P&L
- Action if flagged: candidate needs extra scrutiny (Monte Carlo, NoTop analysis)

### Coin Concentration (G7, advisory)
- What: Does 1 coin dominate total profit?
- Threshold: top1 coin < 70% of total positive P&L
- Why: Strategy should work across diverse coins, not be a 1-coin wonder
- Action if flagged: run universe shift test (see robustness_harness.py)

### Trade Sufficiency
- G1 (MIN_TRADES >= 15) already covers this
- But note: configs with < 25 trades have higher variance
- Sweep will flag configs with 15-25 trades as "borderline sample"

### Split Robustness Weight
- G5 (ROBUSTNESS_SPLIT) is the cheapest walk-forward proxy
- Important: configs that pass G5 should still run full 5-fold WF before deployment
- The trade-list split is an approximation (no independent equity curves)

## Known Limitations
- Gates-Lite does NOT test friction stress (2x fees)
- Gates-Lite does NOT test Monte Carlo shuffle robustness
- Gates-Lite does NOT test parameter jitter (sensitivity)
- These are deferred to post-sweep full validation for top-3 candidates

## Recommendations for Sweep Interpretation
1. Rank by PF first, but weight heavily against high outlier/coin concentration
2. Configs with >= 30 trades are more trustworthy than 15-trade borderline configs
3. exit_type comparison: compare WITHIN blocks (A vs A, B vs B) before cross-block
4. If no hybrid_notrl configs pass gates -> the exit type may be structurally weaker
