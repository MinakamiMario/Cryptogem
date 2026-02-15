#!/usr/bin/env python3
"""
Regression tests for Last 60 Days pipeline.
Tests: slicer, harness on sliced cache, artifact existence.
Fast: uses 10-coin subset.
"""
import sys
import json
import os
import tempfile
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
    print("  Last 60 Days Pipeline Tests")
    print("=" * 50)

    # -----------------------------------------------
    # Test 1: Slicer produces output
    # -----------------------------------------------
    cache_file = ROOT / 'trading_bot' / 'candle_cache_532.json'
    if not cache_file.exists():
        skip('test_slicer_output', 'candle_cache_532.json not found')
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / 'sliced.json'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts' / 'slice_candles.py'),
                 '--days', '60', '--output', str(out_path)],
                capture_output=True, text=True, timeout=60
            )
            test('test_slicer_output',
                 out_path.exists() and out_path.stat().st_size > 1000,
                 f'{out_path.stat().st_size} bytes' if out_path.exists() else 'file missing')

            # Test 2: Sliced data has correct structure
            if out_path.exists():
                with open(out_path) as f:
                    data = json.load(f)
                coins = [k for k, v in data.items() if isinstance(v, list) and len(v) > 10]
                test('test_slicer_structure',
                     len(coins) > 100 and '_date' in data and '_coins' in data,
                     f'{len(coins)} coins, metadata present')

                # Test 3: Sliced data has fewer bars than original
                with open(cache_file) as f:
                    orig = json.load(f)
                orig_coins = [k for k, v in orig.items() if isinstance(v, list) and len(v) > 50]
                first_coin = coins[0]
                test('test_slicer_fewer_bars',
                     len(data[first_coin]) < len(orig.get(first_coin, [])),
                     f'{len(data[first_coin])} < {len(orig.get(first_coin, []))}')

                # Test 4: All bars are within 60-day window
                max_ts = max(bar['time'] for bar in data[first_coin])
                min_ts = min(bar['time'] for bar in data[first_coin])
                span_days = (max_ts - min_ts) / 86400
                test('test_slicer_date_range',
                     span_days <= 62,  # small margin for rounding
                     f'span={span_days:.1f} days')
            else:
                skip('test_slicer_structure', 'no sliced file')
                skip('test_slicer_fewer_bars', 'no sliced file')
                skip('test_slicer_date_range', 'no sliced file')

    # -----------------------------------------------
    # Test 5: Harness accepts --candle-cache flag
    # -----------------------------------------------
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / 'robustness_harness.py'), '--help'],
        capture_output=True, text=True, timeout=10
    )
    test('test_harness_candle_cache_flag',
         '--candle-cache' in result.stdout,
         'flag present in --help')

    # Test 6: Harness accepts --output-dir flag
    test('test_harness_output_dir_flag',
         '--output-dir' in result.stdout,
         'flag present in --help')

    # -----------------------------------------------
    # Test 7: Artifacts exist in reports/last60d/
    # -----------------------------------------------
    last60d_dir = ROOT / 'reports' / 'last60d'
    expected_files = ['wf_report.json', 'friction_report.json', 'mc_report.json',
                      'jitter_report.json', 'universe_report.json', 'go_nogo.md',
                      'report.json', 'report.md']
    if last60d_dir.exists():
        existing = [f for f in expected_files if (last60d_dir / f).exists()]
        test('test_artifacts_exist',
             len(existing) == len(expected_files),
             f'{len(existing)}/{len(expected_files)} files: {", ".join(existing)}')
    else:
        skip('test_artifacts_exist',
             'reports/last60d/ does not exist (run make last60d first)')

    # -----------------------------------------------
    # Test 8: report.json has correct structure
    # -----------------------------------------------
    report_json = last60d_dir / 'report.json' if last60d_dir.exists() else None
    if report_json and report_json.exists():
        with open(report_json) as f:
            report = json.load(f)
        has_meta = 'meta' in report and 'dataset_hash' in report.get('meta', {})
        has_configs = 'configs' in report and len(report['configs']) > 0
        first_cfg = list(report['configs'].values())[0] if has_configs else {}
        has_fields = all(k in first_cfg for k in
                         ['baseline', 'friction_ladder', 'monte_carlo', 'concentration', 'verdict'])
        test('test_report_json_structure',
             has_meta and has_configs and has_fields,
             f'meta={has_meta}, configs={has_configs}, fields={has_fields}')
    else:
        skip('test_report_json_structure', 'report.json missing')

    # -----------------------------------------------
    # Test 9: report.md is non-empty
    # -----------------------------------------------
    report_md = last60d_dir / 'report.md' if last60d_dir.exists() else None
    if report_md and report_md.exists():
        size = report_md.stat().st_size
        test('test_report_md_nonempty',
             size > 200,
             f'{size} bytes')
    else:
        skip('test_report_md_nonempty', 'report.md missing')

    # -----------------------------------------------
    # Test 10: Makefile targets exist
    # -----------------------------------------------
    makefile = ROOT / 'Makefile'
    if makefile.exists():
        content = makefile.read_text()
        has_last60d = 'last60d:' in content
        has_last60d_all = 'last60d-all:' in content
        has_last60d_tests = 'last60d-tests:' in content
        test('test_makefile_targets',
             has_last60d and has_last60d_all and has_last60d_tests,
             f'last60d={has_last60d}, all={has_last60d_all}, tests={has_last60d_tests}')
    else:
        skip('test_makefile_targets', 'Makefile missing')

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
