# Sprint 4 Guardrails Report

**Timestamp**: 2026-02-17T21:30:21.402329+00:00
**Git Hash**: 9a606d9
**Overall Status**: PASS
**Checks Passed**: 6/6

---

## Dataset Integrity
**Status**: PASS

- Total coins: 529
- Universe coins: 487
- Checksum samples:
  - CFG/USD: 721 bars, first=0.2223, last=0.0781
  - AKE/USD: 721 bars, first=0.0016116, last=0.00030117
  - MIRA/USD: 721 bars, first=0.3138, last=0.0908
  - L3/USD: 721 bars, first=0.0238, last=0.00815
  - JAILSTOOL/USD: 721 bars, first=0.002372, last=0.000917

## Provenance Audit
**Status**: PASS

- Files checked: 44
- Files with provenance: 44

## Deterministic Replay
**Status**: PASS

- Configs tested: 3
- Configs passed: 3
- Details:
  - sprint4_041_h4s4g05_vol3x_bblow_rsi40: PASS (trades: 216, PF: 1.4058, P&L: $2283.84)
  - sprint4_032_h4s4f02_z2.5_dclow_rsi40: PASS (trades: 206, PF: 1.3548, P&L: $4915.03)
  - sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35: PASS (trades: 214, PF: 1.2784, P&L: $823.92)

## Accounting Verification
**Status**: PASS

- Files checked: 10
- Files passed: 10

## Fee Consistency
**Status**: PASS

- Trades checked: 1972
- Trades passed: 1972
- Trades skipped (entry=0): 25
- Max fee deviation: $529.138294

## Cross File Consistency
**Status**: PASS

- Strict scoreboard match: True
- Research scoreboard match: True
- Decomposition match: True
- Compat scores complete: True
