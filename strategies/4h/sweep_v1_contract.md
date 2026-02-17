# Sweep V1 — Contract Document

**Scope**: Brede screening van 30 strategie-varianten op de 4H DualConfirm engine.
**Doel**: Top-3 shortlist voor volledige robustheidvalidatie.
**Status**: COMPLETED (2026-02-17, git 2659755)

## Inputs

| Item | Waarde |
|------|--------|
| Engine | `agent_team_v3.run_backtest()` via `strategies.4h.runner` |
| Dataset | `candle_cache_532` (526 coins, ~721 bars, 4H Kraken) |
| Dataset ID | `ohlcv_4h_kraken_spot_usd_526` / alias `4h_default` |
| Exchange | Kraken (fee: 26 bps/side) |
| Initial Capital | $2000 |
| Start Bar | 50 (indicator warmup) |
| Gates | Gates-Lite 5-gate (`strategies/4h/gates_4h.py`) |

## Outputs

| Artifact | Pad |
|----------|-----|
| Sweep plan | `strategies/4h/sweep_plan_v1.json` |
| Per-run results | `reports/4h/sweep_v1_{idx:03d}_{label}_{git}/` |
| Scoreboard JSON | `reports/4h/scoreboard_sweep_v1.json` |
| Scoreboard MD | `reports/4h/scoreboard_sweep_v1.md` |
| Robustness notes | `strategies/4h/robustness_notes_v1.md` |
| ADR entry | `strategies/4h/DECISIONS_4H.md` → ADR-4H-002 |

## Run ID Format

```
sweep_v1_{idx:03d}_{label}_{gitshort}
```
- `idx`: 3-digit volgnummer (001, 002, ...)
- `label`: korte config-label (bv. `trail_rsi38_atr15`, max 30 chars)
- `gitshort`: 7-char git commit hash

## Sweep Scope: 30 Varianten

### Dimensies

1. **Exit type** (3): `trail`, `hybrid_notrl`, `tp_sl`
2. **Entry filters** (variabel per exit type):
   - `rsi_max`: [35, 38, 40, 42, 45]
   - `vol_spike_mult`: [2.0, 2.5, 3.0, 4.0]
3. **Exit parameters** (per exit type):
   - trail: `atr_mult` [1.5, 2.0, 2.5], `be_trigger` [2.0, 3.0], `time_max_bars` [6, 10]
   - hybrid_notrl: `max_stop_pct` [12, 15, 20], `time_max_bars` [15, 20]
   - tp_sl: `tp_pct` [7, 10], `sl_pct` [10, 15]
4. **Position sizing**: `max_pos` [1, 2]

### Structuur (≈30 configs)

| Blok | Exit Type | # Configs | Wat varieert |
|------|-----------|-----------|--------------|
| A | trail | 12 | rsi_max, atr_mult, be_trigger, time_max_bars |
| B | hybrid_notrl | 10 | rsi_max, max_stop_pct, time_max_bars, max_pos |
| C | tp_sl | 6 | rsi_max, tp_pct, sl_pct |
| D | structural | 2 | max_pos=2 op BASELINE + HYBRID_NOTRL |
| TOTAL | | 30 | |

## Gates-Lite Thresholds

| Gate | Threshold | Kill Rule |
|------|-----------|-----------|
| G1: MIN_TRADES | >= 15 | SKIP als onmogelijk (exit type + filters combinatie) |
| G2: MAX_DRAWDOWN | <= 40% | — |
| G3: PROFIT_FACTOR | >= 1.3 | — |
| G4: EXPECTANCY | > $0 | — |
| G5: ROBUSTNESS_SPLIT | both halves P&L > $0 | — |

## Scoreboard Columns

```
idx | label | exit_type | trades | wr% | pnl | pf | dd% | ev/trade | gates | g1..g5 | rank
```

### Ranking Regels

1. Filter: alleen configs met `verdict == GO` (alle 5 gates pass)
2. Primary sort: `pf` descending (profit factor)
3. Tiebreaker 1: `ev_per_trade` descending
4. Tiebreaker 2: `dd` ascending (lager is beter)
5. Tiebreaker 3: `trades` descending (meer trades = robuuster)

## Kill Rules (Early Stop)

- **Pre-run**: Skip als `exit_type` + parameter combo wiskundig onmogelijk is (bv. tp_pct=3 met 26bps fees)
- **Post-run**: Markeer als `KILLED` als `trades == 0` (geen trades gegenereerd)
- **No resume**: Als run_id directory al bestaat met `results.json` → SKIP (idempotent)

## Stopcriteria (Sweep Level)

- Alle 30 runs voltooid OF
- ≥90% runs voltooid en de rest geblokkeerd/killed

## Concurrency

- Max 1 worker (sequentieel) — backtests zijn CPU-bound en delen dezelfde precomputed indicators
- Precompute indicators 1x, hergebruik voor alle runs
- Geschatte totaaltijd: 30 × ~0.5s backtest = ~15s + 1× ~50s precompute = ~65s

## Reproducibility

```bash
# Exact dezelfde sweep opnieuw draaien:
python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --force
```

## Constraints

- Geen wijzigingen aan `trading_bot/` bestanden (GRID_BEST-critical)
- Geen wijzigingen aan `strategies/hf/` bestanden (CLOSED project)
- `make check` moet groen blijven (66/66 tests)
- Alle resultaten reproduceerbaar via sweep_plan_v1.json + git commit
