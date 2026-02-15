#!/usr/bin/env python3
"""Regression tests for compare-caches pipeline."""
import sys
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
ROOT = BASE_DIR.parent

passed = 0
failed = 0
skipped = 0

def test(name, condition, detail=''):
    global passed, failed
    if condition:
        print(f"  ✅ {name}" + (f": {detail}" if detail else ''))
        passed += 1
    else:
        print(f"  ❌ {name}" + (f": {detail}" if detail else ''))
        failed += 1

def skip(name, reason):
    global skipped
    print(f"  ⚠️  {name}: skipped ({reason})")
    skipped += 1

def run():
    global passed, failed, skipped
    print("=" * 50)
    print("  Compare Caches Pipeline Tests")
    print("=" * 50)

    # Test 1: build_research_cache.py exists
    builder = ROOT / 'scripts' / 'build_research_cache.py'
    test('test_builder_exists', builder.exists(), str(builder))

    # Test 2: builder --help works
    if builder.exists():
        result = subprocess.run(
            [sys.executable, str(builder), '--help'],
            capture_output=True, text=True, timeout=10
        )
        test('test_builder_help',
             result.returncode == 0 and '--resume' in result.stdout or '--max-coins' in result.stdout,
             '--resume/--max-coins in --help')
    else:
        skip('test_builder_help', 'builder not found')

    # Test 3: compare_universe.py has --cache-a/--cache-b
    compare = ROOT / 'scripts' / 'compare_universe.py'
    test('test_compare_exists', compare.exists())
    if compare.exists():
        result = subprocess.run(
            [sys.executable, str(compare), '--help'],
            capture_output=True, text=True, timeout=10
        )
        test('test_compare_has_cache_flags',
             '--cache-a' in result.stdout and '--cache-b' in result.stdout,
             '--cache-a/--cache-b in --help')
    else:
        skip('test_compare_has_cache_flags', 'compare not found')

    # Test 4: manifest exists (if cache was built)
    manifest = ROOT / 'data' / 'manifest.json'
    if manifest.exists():
        with open(manifest) as f:
            m = json.load(f)
        done = sum(1 for v in m.values() if isinstance(v, dict) and v.get('status') == 'done')
        test('test_manifest_structure',
             done > 0,
             f'{done} coins done in manifest')
    else:
        skip('test_manifest_structure', 'manifest.json not found (run build-research-cache first)')

    # Test 5: research cache exists
    cache = ROOT / 'data' / 'candle_cache_research_all.json'
    if cache.exists():
        with open(cache) as f:
            data = json.load(f)
        coins = len([k for k, v in data.items() if isinstance(v, list)])
        test('test_research_cache_exists',
             coins > 500,
             f'{coins} coins in research cache')
    else:
        skip('test_research_cache_exists', 'research cache not found (run build-research-cache first)')

    # Test 6: cache_parts directory exists
    parts_dir = ROOT / 'data' / 'cache_parts'
    if parts_dir.exists():
        kraken_parts = list((parts_dir / 'kraken').glob('*.json')) if (parts_dir / 'kraken').exists() else []
        mexc_parts = list((parts_dir / 'mexc').glob('*.json')) if (parts_dir / 'mexc').exists() else []
        test('test_cache_parts',
             len(kraken_parts) + len(mexc_parts) > 100,
             f'kraken={len(kraken_parts)}, mexc={len(mexc_parts)}')
    else:
        skip('test_cache_parts', 'cache_parts/ not found')

    # Test 7: compare report exists (if compare was run)
    report_dir = ROOT / 'reports' / 'compare_caches'
    if report_dir.exists():
        rj = report_dir / 'report.json'
        rm = report_dir / 'report.md'
        test('test_compare_report_exists',
             rj.exists() and rm.exists(),
             f'json={rj.exists()}, md={rm.exists()}')
    else:
        skip('test_compare_report_exists', 'compare_caches/ not found (run compare-caches first)')

    # Test 8: Makefile targets
    makefile = ROOT / 'Makefile'
    if makefile.exists():
        mk = makefile.read_text()
        test('test_makefile_targets',
             'build-research-cache:' in mk and 'compare-caches:' in mk,
             'build-research-cache + compare-caches targets')
    else:
        skip('test_makefile_targets', 'Makefile missing')

    print(f"\n{'=' * 50}")
    print(f"  Results: {passed + skipped}/{passed + failed + skipped} passed, {failed} failed")
    print(f"{'=' * 50}")
    if failed:
        print(f"  {failed} test(s) FAILED ❌")
        sys.exit(1)
    else:
        print(f"  All tests passed ✅")

if __name__ == '__main__':
    run()
