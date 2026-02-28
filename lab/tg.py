"""Quick Telegram send — usage: python -m lab.tg 'bericht hier'"""
import sys
from lab.notifier import LabNotifier

if __name__ == '__main__':
    text = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else ''
    if not text:
        sys.exit(0)
    n = LabNotifier(enabled=True)
    n._send(text)
