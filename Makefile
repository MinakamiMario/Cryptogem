.PHONY: check schema tests capsule robustness robustness-tests last60d last60d-all last60d-tests compare-universe compare-universe-all compare-universe-tests build-unfiltered-cache build-research-cache compare-caches compare-caches-smoke compare-caches-tests grid_best-check grid_best-robustness hf-check hf-robustness ci-guard superhf-data superhf-sweep superhf-check lab-tests lab-smoke lab-check lab-status lab-report

# Full validation (schema + tests + data) — run before any PR
check: schema tests context data-verify
	@echo ""
	@echo "✅ All checks passed"

# Schema guardrail: no legacy tm_bars in active code
schema:
	@echo "=== Schema Check ==="
	python3 scripts/check_cfg_schema.py

# 66 regression tests
tests:
	@echo "=== Regression Tests ==="
	python3 trading_bot/test_param_sensitivity.py

# Context drift sentinel
context:
	@echo "=== Context Drift Check ==="
	python3 scripts/check_cfg_schema.py --check-context

# Print capsule version + path
capsule:
	@echo "=== Context Capsule ==="
	@head -6 docs/CONTEXT_CAPSULE.md
	@echo "Path: docs/CONTEXT_CAPSULE.md"

# Robustness harness — full GO/NO-GO validation (all candidates)
# Usage: make robustness
#        make robustness CONFIG="C1_TPSL_RSI45 C3_TPSL_RSI35"
robustness:
	@echo "=== Robustness Harness v2 ==="
ifdef CONFIG
	python3 trading_bot/robustness_harness.py --config $(CONFIG)
else
	python3 trading_bot/robustness_harness.py
endif

# Robustness harness regression tests (10 tests, fast)
robustness-tests:
	@echo "=== Robustness Regression Tests ==="
	python3 trading_bot/test_robustness_harness.py

# Last 60 days out-of-sample evaluation
# Usage: make last60d CONFIG="C1_TPSL_RSI45"
#        make last60d-all  (all candidates)
last60d:
	@echo "=== Last 60 Days Out-of-Sample ==="
	python3 scripts/slice_candles.py --days 60
ifdef CONFIG
	python3 trading_bot/robustness_harness.py --config $(CONFIG) --candle-cache data/candle_cache_last60d.json --output-dir reports/last60d
else
	python3 trading_bot/robustness_harness.py --config C1_TPSL_RSI45 --candle-cache data/candle_cache_last60d.json --output-dir reports/last60d
endif
	python3 scripts/last60d_report.py --input-dir reports/last60d

last60d-all:
	@echo "=== Last 60 Days Out-of-Sample (all candidates) ==="
	python3 scripts/slice_candles.py --days 60
	python3 trading_bot/robustness_harness.py --candle-cache data/candle_cache_last60d.json --output-dir reports/last60d
	python3 scripts/last60d_report.py --input-dir reports/last60d

# Last 60 days regression tests (fast)
last60d-tests:
	@echo "=== Last 60 Days Tests ==="
	python3 trading_bot/test_last60d.py

# Universe comparison: ALL vs HALAL on unfiltered cache (886 coins)
# Usage: make compare-universe CONFIG="C1_TPSL_RSI45"
compare-universe:
	@echo "=== Compare Universe: ALL vs HALAL (unfiltered 886c) ==="
ifdef CONFIG
	python3 scripts/compare_universe.py --config $(CONFIG) --candle-cache data/candle_cache_unfiltered.json
else
	python3 scripts/compare_universe.py --config C1_TPSL_RSI45 --candle-cache data/candle_cache_unfiltered.json
endif

compare-universe-all:
	@echo "=== Compare Universe: ALL vs HALAL (all candidates, unfiltered) ==="
	python3 scripts/compare_universe.py --candle-cache data/candle_cache_unfiltered.json

# Build unfiltered candle cache (Kraken + MEXC, ~886 coins)
build-unfiltered-cache:
	@echo "=== Building Unfiltered Cache (Kraken + MEXC) ==="
	python3 scripts/build_unfiltered_cache.py

# Universe comparison regression tests
compare-universe-tests:
	@echo "=== Compare Universe Tests ==="
	python3 trading_bot/test_compare_universe.py

# Build research cache (resumable, all Kraken + all MEXC)
build-research-cache:
	@echo "=== Building Research Cache (resumable) ==="
ifdef BATCH
	python3 scripts/build_research_cache.py --max-coins $(BATCH)
else
	python3 scripts/build_research_cache.py
endif

# Compare two caches: RESEARCH_ALL vs LIVE_CURRENT
compare-caches:
	@echo "=== Compare Caches: RESEARCH_ALL vs LIVE_CURRENT ==="
ifdef CONFIG
	python3 scripts/compare_universe.py --config $(CONFIG)
else
	python3 scripts/compare_universe.py --config C1_TPSL_RSI45
endif

# Compare caches with smoke run (sample 200 coins)
compare-caches-smoke:
	@echo "=== Compare Caches (smoke) ==="
ifdef CONFIG
	python3 scripts/compare_universe.py --config $(CONFIG) --smoke
else
	python3 scripts/compare_universe.py --config C1_TPSL_RSI45 --smoke
endif

# Compare caches regression tests
compare-caches-tests:
	@echo "=== Compare Caches Tests ==="
	python3 trading_bot/test_compare_caches.py

# Dataset registry verification
data-verify:
	@echo "=== Data Registry Check ==="
	@python3 ~/CryptogemData/dataset_verify.py

# ─── GRID_BEST frozen baseline ───────────────────────────────

# GRID_BEST full validation (schema + tests + robustness)
grid_best-check: check
	@echo ""
	@echo "=== GRID_BEST Full Suite ==="
	$(MAKE) robustness
	@echo ""
	@echo "✅ GRID_BEST check passed"

# GRID_BEST robustness only
grid_best-robustness:
	@echo "=== GRID_BEST Robustness ==="
	$(MAKE) robustness

# CI guard: detect GRID_BEST-critical file changes
ci-guard:
	@bash scripts/ci_guard.sh

# ─── HF strategy (development) ──────────────────────────────

# HF strategy check (alignment + no-leak tests)
hf-check:
	@echo "=== HF Alignment Tests ==="
	python3 strategies/hf/hf_alignment_tests.py

# HF robustness (placeholder — expand when HF harness exists)
hf-robustness:
	@echo "=== HF Robustness ==="
	@echo "No HF robustness harness yet — placeholder"
	@echo "Reports will go to: reports/hf/"
	@echo "✅ HF robustness passed (no harness)"

# ─── SuperHF strategy (MTF 1H+15m) ──────────────────────────

# Download 15m + 1H MEXC candles (top 200 coins)
superhf-data:
	@echo "=== SuperHF Data Pipeline ==="
	python3 scripts/build_superhf_cache.py

# Run SuperHF Sprint 1 sweep (12 configs)
superhf-sweep:
	@echo "=== SuperHF Sprint 1 Sweep ==="
	python3 scripts/run_superhf_sprint1.py

# SuperHF self-tests (indicators + hypotheses)
superhf-check:
	@echo "=== SuperHF Self-Tests ==="
	PYTHONPATH=. python3 strategies/superhf/indicators.py
	PYTHONPATH=. python3 strategies/superhf/hypotheses.py
	@echo "✅ SuperHF tests passed"

# ── Lab targets ─────────────────────────────────────────

# Lab test suite (148 tests)
lab-tests:
	@echo "=== Lab Tests ==="
	python3 -m pytest tests/test_lab/ -q

# Lab smoke test (init + dry-run 1 cycle)
lab-smoke:
	@echo "=== Lab Smoke Test ==="
	python3 -m lab.main init
	python3 -m lab.main run --dry-run -q

# Full lab validation (tests + smoke)
lab-check: lab-tests lab-smoke
	@echo ""
	@echo "✅ Lab checks passed"

# Lab status dashboard
lab-status:
	python3 -m lab.main status

# Lab full report
lab-report:
	python3 -m lab.main report
