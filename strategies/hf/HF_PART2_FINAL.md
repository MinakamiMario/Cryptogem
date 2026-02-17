# HF Part 2 — Frozen Artifacts Manifest

> **READ-ONLY**: These artifacts are frozen as of tag `hf-part2-closed-v1` (2026-02-17).
> Do not modify or overwrite. Reference only.

## Final MEXC Reports

| File | Description | MD5 |
|------|-------------|-----|
| `reports/hf/mexc_orderbook_costs_001.json` | 19,500 OB snapshots: spread/slippage distributions | `c16e9407719f3615c3f1065cdaf28321` |
| `reports/hf/mexc_orderbook_costs_001.md` | (human-readable) | `1e16f64f598b16d4cf09a416051e163b` |
| `reports/hf/part2_measured_cost_rerun_001.json` | 24-combo final results (14/24 PASS) | `57b27e416fe0bde08533c1a871099408` |
| `reports/hf/part2_measured_cost_rerun_001.md` | (human-readable) | `70e8db1d731408797ded48eaaa5194dd` |
| `reports/hf/mexc_sanity_001.md` | OB data quality (39/42 coins, 0% crossed) | `87ff7f71f46e6bd4cb6f156f1d57845b` |
| `reports/hf/mexc_slippage_verification_001.md` | Slippage walk (9/9 exact, 0.00bps delta) | `4f3e6077aed334a1ca558069cfdcbbd0` |
| `reports/hf/regime_decomposition_001.json` | Anti-double-count (12/12 verified) | `e884f999d95171b496289601ed1c118b` |

## Final Bybit Reports

| File | Description | MD5 |
|------|-------------|-----|
| `reports/hf/bybit_orderbook_costs_001.json` | 35,869 OB snapshots: cost regimes | `6d443436f8f9fe71e5cd00e69e4a24b2` |
| `reports/hf/bybit_orderbook_costs_001.md` | (human-readable) | `633956feba3774e382cb8f8b47961ca2` |
| `reports/hf/bybit_signal_diagnostics_001.json` | Per-coin VWAP deviation distributions | `fe5f4e6fbc9f971c8e342a8a99f24813` |
| `reports/hf/bybit_signal_diagnostics_001.md` | (human-readable) | `06c8a17188e4b492ef5339513df10f27` |
| `reports/hf/bybit_signal_bakeoff_001.json` | 5 signals × 120 combos (0/24 pass) | `9268d5429237d9906c3b785f52453fc4` |
| `reports/hf/bybit_signal_bakeoff_001.md` | (human-readable) | `cb0a395af8e163f704de1b076de2282c` |
| `reports/hf/part2_bybit_h20_vwap1m_001.json` | Real 1m VWAP 24-combo (0/24 pass) | `b1a24d0286f677352a9bfb3d8610d977` |
| `reports/hf/part2_bybit_h20_vwap1m_001.md` | (human-readable) | `c8941d39df7ac305b429ed079d4ab380` |
| `reports/hf/bybit_vwap1m_diagnostics_001.json` | 166 coins × 721 bars VWAP diagnostics | `315eed5c33e8b0a0f0cfa3e358d175fc` |
| `reports/hf/bybit_vwap1m_diagnostics_001.md` | (human-readable) | `511f3ad5dbf4846d39cf21a0d2a4d2f5` |
| `reports/hf/bybit_vwap_1m_aggregation_001.json` | 1m aggregation metadata (37.8M bars) | `6c5e3d26902a4a68fd615e4072e2b198` |
| `reports/hf/part2_bybit_measured_cost_001.json` | Bybit measured cost backtest | `5fdc907e4127457971d684ff8b1d113b` |
| `reports/hf/part2_bybit_measured_cost_001.md` | (human-readable) | `c659e80f210dff0981955a6c1e4deb20` |
| `reports/hf/part2_bybit_h20z_001.json` | Z-score VWAP variant (0/24 pass) | `212c789e5362b2fe70e180c53859b896` |
| `reports/hf/part2_bybit_h20z_001.md` | (human-readable) | `20cdd0c1a358c1655cf32e2dfce8a4ba` |
| `reports/hf/diagnostic_intersection_bybit_mexc.json` | MEXC/Bybit coin intersection | `7d1fc41f2e3c127e9a0c04d928d6f454` |

## ADR Canon

| ADR | Title | Status | Location |
|-----|-------|--------|----------|
| HF-034 | Measured OB 24-backtest rerun | GO MAINTAINED (maker) | `strategies/hf/DECISIONS.md` |
| HF-035 | Bybit NO-GO — signal does not transfer | NO-GO | `strategies/hf/DECISIONS.md` |
| HF-036 | Bybit signal exploration — comprehensive NO-GO | NO-GO | `strategies/hf/DECISIONS.md` |
| HF-037 | Bybit real 1m VWAP validation — definitive NO-GO | NO-GO | `strategies/hf/DECISIONS.md` |

## Tracking Documents (final state)

| File | Description | MD5 |
|------|-------------|-----|
| `reports/hf/part2_scoreboard.md` | Gate leaderboard (CLOSED) | `1e6a26808b380ddaec6439973cae634a` |
| `reports/hf/part2_backlog.md` | Priority queue — 10 cycles, CLOSED | `e464209c0c13842f32fbe4c6494b480a` |
| `reports/hf/part2_teamlog.md` | Cycle-by-cycle execution log | `f8c0e40119d93f04b10378abf25257be` |
| `strategies/hf/CONTEXT_HANDOFF.md` | Session handoff (frozen) | `2c7b43ace4a64927d02dfa582de9663c` |
