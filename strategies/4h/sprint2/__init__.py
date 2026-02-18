"""
Sprint 2: Entry-Edge Discovery for 4H Strategy Screening
---------------------------------------------------------
4 signal families with multi-condition entries, cross-sectional context,
and relaxed Stage 0 gates (PF > 1.05).

Key components:
  indicators.py     -- Extended indicator library (dc_prev_high, plus_di, minus_di)
  market_context.py  -- Cross-sectional momentum rank + breadth (causal)
  hypotheses.py      -- 4 signal families with param variants
  gates.py           -- Sprint 2 gate evaluator (relaxed PF > 1.05)

Engine: Reuses strategies/4h/sprint1/engine.py (Stage 0 prefilter).
"""
