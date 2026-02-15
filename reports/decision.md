# Decision Document — Universe & Config Selectie

**Datum**: 2026-02-15 | **Agent 5 — Synthese van Agents 1-4**

---

## 1. Resultaten Matrix

| Universe | Config | Coins | Trades | P&L | WR% | PF | DD% | WF | Fric2x20 | MC ruin | Jitter% | Verdict |
|----------|--------|-------|--------|-----|-----|-----|-----|-----|----------|---------|---------|---------|
| LIVE_CURRENT (523c) | C1 tp15/sl15/vs3.0 | 523 | 30 | $3,746 | 70.0 | 3.31 | 27.9 | 4/5 | $2,370 | 0.0% | 100% | **GO** |
| TRADEABLE (425c) | C1 tp15/sl15/vs3.0 | 425 | 27 | $1,930 | 66.7 | 1.83 | 29.3 | 3/5 | $1,068 | 1.0% | 100% | SOFT-GO |
| TRADEABLE (425c) | GRID tp12/sl10/vs2.5 | 425 | 32 | $4,718 | 68.8 | 2.61 | 16.4 | **5/5** | $3,019 | 0.0% | 100% | **GO** |
| RESEARCH_ALL (2086c) | C1 tp15/sl15/vs3.0 | 2086 | 45 | $529 | 51.1 | 1.14 | 40.8 | 3/5 | -$334 | 37.5% | 42% | **NO-GO** |

## 2. Keuze: Universe

**Winnaar: TRADEABLE (425 coins)**

| Criterium | LIVE_CURRENT | TRADEABLE | RESEARCH_ALL |
|-----------|-------------|-----------|--------------|
| Data kwaliteit | Goed (Kraken-only) | Goed (gefilterd op 95% coverage) | Slecht (76% <95% cov) |
| MEXC exposure | 0% | 0% (eruit gefilterd) | 1501/1568 MEXC <95% cov |
| MEXC P&L bijdrage | n.v.t. | n.v.t. | -$213 (verwatert edge) |
| Tradeable op Kraken | Ja | Ja | Nee (meeste MEXC-only) |
| Beste WF score | 4/5 | **5/5** (met GRID) | 3/5 |
| Friction survival | $2,370 | **$3,019** (met GRID) | -$334 (FAIL) |

**Reden**: TRADEABLE combineert het beste van beide werelden — gefilterde data kwaliteit (geen <95% coverage rommel) en een groter zoekgebied dan LIVE_CURRENT waardoor de grid search een betere config vindt. RESEARCH_ALL is NO-GO: MEXC long-tail coins zijn niet tradeable op Kraken en verwateren de edge tot nul.

## 3. Keuze: Config

**Winnaar: GRID_BEST (tp12/sl10/vs2.5)**

| Metric | C1 (tp15/sl15/vs3.0) | GRID_BEST (tp12/sl10/vs2.5) | Verschil |
|--------|----------------------|------------------------------|----------|
| WF | 3/5 | **5/5** | +2 folds |
| P&L | $1,930 | **$4,718** | +$2,788 |
| DD | 29.3% | **16.4%** | -12.9pp |
| MC ruin | 1.0% | **0.0%** | cleaner |
| Fric 2x+20bps | $1,068 | **$3,019** | +$1,951 |
| Top1 share | 17.0% | **12.0%** | minder concentratie |
| NoTop P&L | $1,205 | **$3,802** | winstgevend zonder top coin |
| Subsets positive | 2/4 | **4/4** | alle volume-segmenten werken |

GRID_BEST domineert op ELKE metric. Strakkere SL (10% vs 15%) beperkt downside, lagere TP (12% vs 15%) pakt winst sneller, en lagere vol_spike (2.5x vs 3.0x) laat meer trades toe die alsnog winstgevend zijn.

## 4. Non-Negotiable Gates voor Micro-Live

| Gate | Threshold | GRID_BEST score | Status |
|------|-----------|----------------|--------|
| Walk-Forward | >= 4/5 folds positief | 5/5 | PASS |
| Friction 2x+20bps | > $0 P&L | $3,019 | PASS |
| MC ruin (1000 shuffles) | < 5% | 0.0% | PASS |
| Jitter (50 varianten) | >= 90% positief | 100% | PASS |
| Max Drawdown | < 35% | 16.4% | PASS |
| NoTop P&L | > $0 (zonder top coin) | $3,802 | PASS |
| Top1 coin share | < 25% | 12.0% | PASS |
| Min trades | >= 20 | 32 | PASS |

**Alle 8 gates PASS.**

## 5. Config Parameters

```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 10,
  "time_max_bars": 15,
  "tp_pct": 12,
  "vol_confirm": true,
  "vol_spike_mult": 2.5
}
```

---

**DOEN: TRADEABLE (425c), GRID_BEST (tp12/sl10/vs2.5), `python trading_bot/paper_backfill_v4.py --hours 168 --config grid_best`**
