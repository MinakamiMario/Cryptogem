#!/usr/bin/env python3
"""
Schema guardrail: scan for legacy tm_bars usage in active code.

Usage: python3 scripts/check_cfg_schema.py
Exit code: 0 = clean, 1 = legacy key in active code
"""
import argparse
import re
import sys
from pathlib import Path

TRADING_BOT = Path(__file__).parent.parent / 'trading_bot'

# Files where legacy tm_bars in active code is a FAIL
CRITICAL_FILES = {'agent_team_v3.py', 'overnight_optimizer.py'}

# Patterns that indicate ACTIVE usage (not just data/comments/tests)
ACTIVE_PATTERNS = [
    r"cfg\.get\(['\"]tm_bars['\"]",
    r"cfg\[['\"]tm_bars['\"]",
    r"\.get\(['\"]tm_bars['\"]",
]

# Patterns that indicate COMPAT (normalize_cfg)
COMPAT_PATTERNS = [
    r"normalize_cfg",
    r"# ?canonical",
    r"# ?legacy",
    r"cfg\.pop\(['\"]tm_bars['\"]",
]

# Patterns for test files
TEST_PATTERNS = [
    r"^test_",
    r"_test\.py$",
]

def classify_file(filepath):
    name = filepath.name
    if any(re.match(p, name) for p in TEST_PATTERNS):
        return 'TEST'
    return 'CODE'

def scan_file(filepath):
    hits = []
    try:
        lines = filepath.read_text().splitlines()
    except Exception:
        return hits

    for i, line in enumerate(lines, 1):
        for pat in ACTIVE_PATTERNS:
            if re.search(pat, line):
                # Check if it's in a compat context
                context = '\n'.join(lines[max(0,i-3):i+2])
                is_compat = any(re.search(cp, context, re.IGNORECASE) for cp in COMPAT_PATTERNS)
                is_comment = line.strip().startswith('#')
                is_string = "'" in line and line.count("'") >= 4  # likely in a string/print

                if is_comment:
                    classification = 'DATA'
                elif is_compat:
                    classification = 'COMPAT'
                elif classify_file(filepath) == 'TEST':
                    classification = 'TEST'
                else:
                    classification = 'ACTIVE'

                hits.append({
                    'file': filepath.name,
                    'line': i,
                    'type': classification,
                    'content': line.strip()[:80],
                })
                break  # one hit per line
    return hits

def check_context():
    """Verify required context documents exist and are non-empty."""
    base = Path(__file__).parent.parent
    required = {
        'docs/CONTEXT_CAPSULE.md': 'Context capsule (schema, invariants, fixes)',
        'prompts/LOAD_IN_PROMPT.md': 'Load-in prompt for new chats',
        'docs/DECISIONS.md': 'Architecture decision records',
    }

    fails = 0
    for rel_path, desc in required.items():
        full = base / rel_path
        if not full.exists():
            print(f'  ❌ MISSING: {rel_path} — {desc}')
            fails += 1
        elif full.stat().st_size < 50:
            print(f'  ❌ EMPTY: {rel_path} — {desc} ({full.stat().st_size} bytes)')
            fails += 1
        else:
            print(f'  ✅ OK: {rel_path} ({full.stat().st_size} bytes)')

    # Check DECISIONS.md has at least 2 entries
    decisions = base / 'docs/DECISIONS.md'
    if decisions.exists():
        content = decisions.read_text()
        adr_count = content.count('## ADR-')
        if adr_count < 2:
            print(f'  ⚠️  WARN: DECISIONS.md has only {adr_count} ADR entries (expected ≥2)')
        else:
            print(f'  ✅ DECISIONS.md has {adr_count} ADR entries')

    if fails > 0:
        print(f'\n❌ Context drift: {fails} required file(s) missing or empty')
        return 1
    print(f'\n✅ All context documents present')
    return 0

def main():
    parser = argparse.ArgumentParser(description='Config schema guardrail')
    parser.add_argument('--check-context', action='store_true',
                        help='Check required context docs exist')
    args = parser.parse_args()

    if args.check_context:
        return check_context()

    all_hits = []
    for py_file in sorted(TRADING_BOT.glob('*.py')):
        hits = scan_file(py_file)
        all_hits.extend(hits)

    if not all_hits:
        print('✅ No legacy tm_bars usage found in trading_bot/')
        return 0

    # Print table
    print(f'{"FILE":<35} {"LINE":>5} {"TYPE":<8} CONTENT')
    print('-' * 90)

    fails = 0
    warns = 0
    for h in all_hits:
        marker = ''
        if h['type'] == 'ACTIVE' and h['file'] in CRITICAL_FILES:
            marker = ' ❌ FAIL'
            fails += 1
        elif h['type'] == 'ACTIVE':
            marker = ' ⚠️  WARN'
            warns += 1
        print(f"{h['file']:<35} {h['line']:>5} {h['type']:<8} {h['content']}{marker}")

    print()
    print(f'Summary: {len(all_hits)} hits | {fails} FAIL | {warns} WARN | '
          f'{sum(1 for h in all_hits if h["type"]=="COMPAT")} COMPAT | '
          f'{sum(1 for h in all_hits if h["type"]=="TEST")} TEST | '
          f'{sum(1 for h in all_hits if h["type"]=="DATA")} DATA')

    if fails > 0:
        print(f'\n❌ FAILED: {fails} legacy tm_bars usage in critical files')
        return 1
    elif warns > 0:
        print(f'\n⚠️  WARNINGS: {warns} legacy tm_bars usage in non-critical files')
        return 0
    else:
        print(f'\n✅ PASSED: no active legacy tm_bars usage')
        return 0

if __name__ == '__main__':
    sys.exit(main())
