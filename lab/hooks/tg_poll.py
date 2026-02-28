#!/usr/bin/env python3
"""Hook: poll Telegram for new messages. Prints them so Claude sees them."""
import sys
sys.path.insert(0, '/Users/oussama/Cryptogem')

from lab.notifier import LabNotifier

n = LabNotifier(enabled=True)
_, messages = n.poll_telegram()
if messages:
    print(f"[Telegram] {len(messages)} bericht(en):")
    for m in messages:
        print(f"  💬 {m}")
