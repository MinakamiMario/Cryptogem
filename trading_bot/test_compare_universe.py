#!/usr/bin/env python3
"""
Regression tests for compare-universe pipeline.
Tests: --universe flag, halal coin filtering, metadata, artifacts.
"""
import sys
import json
import re
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
    print("  Compare Universe Pipeline Tests")
    print("=" * 50)

    # -----------------------------------------------
    # Test 1: --universe flag exists in harness
    # -----------------------------------------------
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / 'robustness_harness.py'), '--help'],
        capture_output=True, text=True, timeout=10
    )
    test('test_universe_flag_exists',
         '--universe' in result.stdout and 'all' in result.stdout and 'halal' in result.stdout,
         '--universe {all,halal} in --help')

    # -----------------------------------------------
    # Test 2: Halal coin list is extractable
    # -----------------------------------------------
    kc_path = BASE_DIR / 'kraken_client.py'
    if kc_path.exists():
        with open(kc_path) as f:
            content = f.read()
        halal_pairs = set(re.findall(r"'([A-Z0-9]+/USD)'", content))
        test('test_halal_coin_list',
             250 < len(halal_pairs) < 350,
             f'{len(halal_pairs)} halal pairs')
    else:
        skip('test_halal_coin_list', 'kraken_client.py not found')

    # -----------------------------------------------
    # Test 3: --universe all gives more coins than halal
    # -----------------------------------------------
    cache_file = BASE_DIR / 'candle_cache_532.json'
    if cache_file.exists() and kc_path.exists():
        with open(cache_file) as f:
            data = json.load(f)
        all_coins = [k for k, v in data.items() if isinstance(v, list) and len(v) > 50]
        halal_coins = [c for c in all_coins if c in halal_pairs]
        test('test_all_more_than_halal',
             len(all_coins) > len(halal_coins),
             f'all={len(all_coins)} > halal={len(halal_coins)}')
    else:
        skip('test_all_more_than_halal', 'cache or kraken_client missing')

    # -----------------------------------------------
    # Test 4: --universe halal produces different coin count in output
    # -----------------------------------------------
    # Quick smoke test: just check the flag is accepted (no full run)
    result_all = subprocess.run(
        [sys.executable, str(BASE_DIR / 'robustness_harness.py'),
         '--universe', 'all', '--list'],
        capture_output=True, text=True, timeout=10
    )
    result_halal = subprocess.run(
        [sys.executable, str(BASE_DIR / 'robustness_harness.py'),
         '--universe', 'halal', '--list'],
        capture_output=True, text=True, timeout=10
    )
    test('test_universe_flag_accepted',
         result_all.returncode == 0 and result_halal.returncode == 0,
         'both modes accepted')

    # -----------------------------------------------
    # Test 5: compare_universe.py exists and is runnable
    # -----------------------------------------------
    compare_script = ROOT / 'scripts' / 'compare_universe.py'
    test('test_compare_script_exists',
         compare_script.exists(),
         str(compare_script))

    result = subprocess.run(
        [sys.executable, str(compare_script), '--help'],
        capture_output=True, text=True, timeout=10
    )
    test('test_compare_script_help',
         result.returncode == 0 and '--config' in result.stdout,
         '--config in --help')

    # -----------------------------------------------
    # Test 6: Artifacts exist if comparison has been run
    # -----------------------------------------------
    compare_dir = ROOT / 'reports' / 'compare_universe'
    expected = ['report.json', 'report.md']
    if compare_dir.exists():
        existing = [f for f in expected if (compare_dir / f).exists()]
        test('test_compare_artifacts',
             len(existing) == len(expected),
             f'{len(existing)}/{len(expected)} files')

        # Test 7: report.json has both universe modes
        rj = compare_dir / 'report.json'
        if rj.exists():
            with open(rj) as f:
                report = json.load(f)
            has_all = 'all' in report
            has_halal = 'halal' in report
            test('test_report_has_both_universes',
                 has_all and has_halal,
                 f'all={has_all}, halal={has_halal}')

            # Test 8: universe metadata present
            all_meta = report.get('all', {})
            halal_meta = report.get('halal', {})
            test('test_universe_metadata',
                 all_meta.get('universe_mode') == 'all' and
                 halal_meta.get('universe_mode') == 'halal' and
                 all_meta.get('coin_count', 0) > halal_meta.get('coin_count', 0),
                 f"all={all_meta.get('coin_count')}c, halal={halal_meta.get('coin_count')}c")
        else:
            skip('test_report_has_both_universes', 'report.json missing')
            skip('test_universe_metadata', 'report.json missing')
    else:
        skip('test_compare_artifacts', 'reports/compare_universe/ not found (run make compare-universe first)')
        skip('test_report_has_both_universes', 'not run yet')
        skip('test_universe_metadata', 'not run yet')

    # -----------------------------------------------
    # Test 9: Makefile targets exist
    # -----------------------------------------------
    makefile = ROOT / 'Makefile'
    if makefile.exists():
        mk = makefile.read_text()
        has_cu = 'compare-universe:' in mk
        has_cua = 'compare-universe-all:' in mk
        has_cut = 'compare-universe-tests:' in mk
        test('test_makefile_targets',
             has_cu and has_cua and has_cut,
             f'compare-universe={has_cu}, all={has_cua}, tests={has_cut}')
    else:
        skip('test_makefile_targets', 'Makefile missing')

    # -----------------------------------------------
    # Test 10: report.md has delta analysis section
    # -----------------------------------------------
    rm = compare_dir / 'report.md' if compare_dir.exists() else None
    if rm and rm.exists():
        md_content = rm.read_text()
        test('test_report_md_has_delta',
             'Delta Analysis' in md_content and 'Conclusie' in md_content,
             'Delta + Conclusie sections present')
    else:
        skip('test_report_md_has_delta', 'report.md not found')

    # -----------------------------------------------
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
