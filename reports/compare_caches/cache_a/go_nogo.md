# GO/NO-GO Rapport
Datum: 2026-02-15 00:50:01
Dataset: `candle_cache_research_all.json` (hash: `a68399c0da2e`)
Seed: 42

## GO Thresholds
```
wf_min_pass: 4
wf_soft_pass: 3
wf_max_dd: 40.0
friction_go: 2x_fee+20bps
mc_p95_dd_max: 50.0
mc_ruin_max: 5.0
jitter_min_positive_pct: 70.0
univ_min_subsets_positive: 2
univ_top1_share_max: 0.5
univ_top3_share_max: 0.8
```

## Resultaten

| Config | Tr | P&L | WR | DD | WF | Fric 2x+20bps | MC ruin% | Jitter pos% | Univ | Top1% | Verdict |
|--------|-----|------|-----|-----|-----|---------------|----------|-------------|------|-------|---------|
| C1_TPSL_RSI45 | 45 | $528.52 | 51.1% | 40.8% | 3/5 | $-333.86 | 37.5% | 26.0% | 2/4 | 12% | 🔴 NO-GO |

## GEEN GO configs gevonden

## NO-GO Configs
- **C1_TPSL_RSI45**: Friction: $-333.86 at 2.0x_fee+20bps, MC ruin=37.5% p95DD=62.6%, Jitter 26.0% < 70.0%

## Kill-Switch Thresholds (micro-live)
```
max_dd_pct: 30.0
max_consecutive_losses: 6
max_loss_streak_usd: -400
min_trades_before_eval: 10
wr_floor: 40.0
```

Als een van deze drempels wordt bereikt tijdens micro-live: stop trading onmiddellijk, evalueer.