#!/usr/bin/env python3
"""
Continuous Research Pipeline — Automated strategy monitoring & optimization.

Runs as daemon or via cron. Three modes:
  --monitor     Every 4h: check strategy drift, alert on anomalies
  --daily       Every 24h: scan new coins, check delistings, spread changes
  --research    Weekly: parameter sweep on new data, signal screening

Usage:
  python scripts/research_pipeline.py --monitor   # run once (cron every 4h)
  python scripts/research_pipeline.py --daily     # run once (cron daily)
  python scripts/research_pipeline.py --research  # run once (cron weekly)
  python scripts/research_pipeline.py --daemon    # run all modes on schedule

Each mode writes results to reports/pipeline/ and sends alerts via Telegram.
"""
import os, sys, json, time, argparse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / 'reports' / 'pipeline'
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Telegram Alert ──────────────────────────────────────────
def send_telegram(msg: str, silent: bool = False):
    """Send alert via Telegram bot."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / 'trading_bot' / '.env')
        token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        if not token or not chat_id:
            print(f"  [TG] No credentials, skipping: {msg[:80]}")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({
            'chat_id': chat_id,
            'text': msg,
            'parse_mode': 'HTML',
            'disable_notification': silent,
        }).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"  [TG] Failed: {e}")


# ── Mode 1: MONITOR (every 4h) ─────────────────────────────
def run_monitor():
    """Check live strategy performance, detect drift, alert anomalies."""
    print("=" * 60)
    print(f"MONITOR — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    alerts = []

    # Check ms_018 live state
    ms018_state = ROOT / 'trading_bot' / 'state_ms_018_shift_pb_live.json'
    if ms018_state.exists():
        d = json.loads(ms018_state.read_text())
        equity = d.get('equity', 0)
        dd = d.get('dd_max', 0)
        total_pnl = d.get('total_pnl', 0)
        trades = d.get('total_trades', 0)
        wins = d.get('wins', 0)
        losses = d.get('losses', 0)
        consec_losses = d.get('consecutive_losses', 0)

        print(f"  MS-018 LIVE: equity=${equity:,.2f}, PnL=${total_pnl:+,.2f}, "
              f"trades={trades}, W/L={wins}/{losses}, DD={dd:.1f}%")

        # Alerts
        if dd > 15:
            alerts.append(f"⚠️ MS-018 DD={dd:.1f}% (>15% threshold)")
        if consec_losses >= 5:
            alerts.append(f"🚨 MS-018 {consec_losses} consecutive losses!")
        if trades >= 10 and wins / trades < 0.35:
            wr = 100 * wins / trades
            alerts.append(f"⚠️ MS-018 WR={wr:.0f}% (<35% after {trades} trades)")
    else:
        print("  MS-018 LIVE: no state file")
        alerts.append("ℹ️ MS-018 live state not found")

    # Check scalp state
    scalp_state = ROOT / 'trading_bot' / 'paper_state_scalp_1m_paper.json'
    if scalp_state.exists():
        d = json.loads(scalp_state.read_text())
        equity = d.get('equity', 0)
        total_pnl = d.get('total_pnl', 0)
        trades = d.get('total_trades', 0)
        wins = d.get('wins', 0)
        live_pnl = d.get('live_total_pnl', 0)
        live_trades = d.get('live_trades', 0)

        print(f"  SCALP FVG: paper PnL=${total_pnl:+,.2f} ({trades}t), "
              f"live PnL=${live_pnl:+,.4f} ({live_trades}t)")

        if trades >= 20 and total_pnl < -50:
            alerts.append(f"⚠️ Scalp paper PnL=${total_pnl:+,.2f} after {trades} trades")

    # Check processes running
    import subprocess
    ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
    live_running = 'live_trader.py' in ps.stdout
    scalp_running = 'paper_scalp_1m' in ps.stdout
    paper_running = 'paper_ms_4h' in ps.stdout

    status = []
    if live_running: status.append("✅ MS-018 live")
    else: status.append("❌ MS-018 live DOWN"); alerts.append("🚨 MS-018 live trader not running!")
    if scalp_running: status.append("✅ Scalp FVG")
    else: status.append("❌ Scalp DOWN"); alerts.append("⚠️ Scalp trader not running")
    if paper_running: status.append("✅ Paper MS-018")
    else: status.append("ℹ️ Paper MS-018 stopped")

    print(f"  Processes: {', '.join(status)}")

    # Save report
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': 'monitor',
        'alerts': alerts,
        'status': status,
    }
    report_file = REPORTS_DIR / f"monitor_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    report_file.write_text(json.dumps(report, indent=2))

    # Telegram alert if issues
    if alerts:
        msg = "🔍 <b>Pipeline Monitor</b>\n\n" + "\n".join(alerts)
        send_telegram(msg)
        print(f"\n  Sent {len(alerts)} alerts via Telegram")
    else:
        print("\n  All OK, no alerts")

    return alerts


# ── Mode 2: DAILY SCAN ──────────────────────────────────────
def run_daily():
    """Daily: check MEXC for delistings, new coins, spread changes."""
    print("=" * 60)
    print(f"DAILY SCAN — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    alerts = []

    # Load current whitelist
    whitelist_file = ROOT / 'trading_bot' / 'halal_coins.txt'
    whitelist = set()
    if whitelist_file.exists():
        for line in whitelist_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                whitelist.add(line.replace('/USDT', ''))

    print(f"  Current whitelist: {len(whitelist)} coins")

    # Check MEXC availability
    try:
        url = 'https://api.mexc.com/api/v3/exchangeInfo'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=30)
        info = json.loads(resp.read())

        active = set()
        for s in info.get('symbols', []):
            if s.get('quoteAsset') == 'USDT' and s.get('isSpotTradingAllowed'):
                active.add(s.get('baseAsset', ''))

        # Check delistings
        for coin in whitelist:
            if coin not in active:
                alerts.append(f"🚨 {coin} DELISTED from MEXC — remove from whitelist!")

        print(f"  MEXC active USDT pairs: {len(active)}")
        print(f"  Whitelist coins on MEXC: {len(whitelist & active)}/{len(whitelist)}")

    except Exception as e:
        print(f"  [ERROR] MEXC check failed: {e}")
        alerts.append(f"⚠️ MEXC API check failed: {e}")

    # Check live spreads for whitelist coins
    try:
        spread_results = {}
        for coin in sorted(whitelist & active):
            try:
                url = f"https://api.mexc.com/api/v3/depth?symbol={coin}USDT&limit=5"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=10)
                ob = json.loads(resp.read())
                bids = ob.get('bids', [])
                asks = ob.get('asks', [])
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    mid = (best_bid + best_ask) / 2
                    spread_bps = (best_ask - best_bid) / mid * 10000
                    spread_results[coin] = spread_bps

                    # Alert if spread widened significantly (>50bps for ms_018)
                    if spread_bps > 50:
                        alerts.append(f"⚠️ {coin} spread={spread_bps:.0f}bps — too wide for ms_018")

                time.sleep(0.2)
            except:
                pass

        if spread_results:
            avg_spread = sum(spread_results.values()) / len(spread_results)
            wide = {k: v for k, v in spread_results.items() if v > 30}
            print(f"  Avg spread: {avg_spread:.1f}bps across {len(spread_results)} coins")
            if wide:
                print(f"  Wide spreads (>30bps): {', '.join(f'{k}={v:.0f}bp' for k, v in sorted(wide.items(), key=lambda x: -x[1]))}")

    except Exception as e:
        print(f"  [ERROR] Spread check failed: {e}")

    # Save report
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': 'daily',
        'whitelist_size': len(whitelist),
        'alerts': alerts,
        'spreads': spread_results if 'spread_results' in dir() else {},
    }
    report_file = REPORTS_DIR / f"daily_{datetime.now().strftime('%Y%m%d')}.json"
    report_file.write_text(json.dumps(report, indent=2))

    if alerts:
        msg = "📊 <b>Daily Scan</b>\n\n" + "\n".join(alerts)
        send_telegram(msg)
        print(f"\n  Sent {len(alerts)} alerts")
    else:
        print("\n  All OK")

    return alerts


# ── Mode 3: WEEKLY RESEARCH ─────────────────────────────────
def run_research():
    """Weekly: backtest new coins, parameter sweep, signal screening."""
    print("=" * 60)
    print(f"WEEKLY RESEARCH — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    import importlib
    from strategies.ms.hypotheses import signal_structure_shift_pullback
    from strategies.ms.indicators import precompute_ms_indicators
    engine = importlib.import_module('strategies.4h.sprint3.engine')
    run_backtest = engine.run_backtest
    data_resolver = importlib.import_module('strategies.4h.data_resolver')

    PARAMS = {
        'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
        'max_stop_pct': 15.0, 'time_max_bars': 15,
        'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
    }
    MEXC_FEE = 0.001

    # Load data
    dataset_path = data_resolver.resolve_dataset('4h_default')
    with open(dataset_path) as f:
        raw = json.load(f)
    data = {k: v for k, v in raw.items() if not k.startswith('_') and isinstance(v, list)}
    all_coins = [c for c in data if len(data[c]) >= 360]
    print(f"  Universe: {len(all_coins)} coins")

    # Load whitelist
    whitelist_file = ROOT / 'trading_bot' / 'halal_coins.txt'
    whitelist_symbols = set()
    if whitelist_file.exists():
        for line in whitelist_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                whitelist_symbols.add(line.split('/')[0])

    # Screen ALL coins for new profitable ones not in whitelist
    new_opportunities = []
    for coin in all_coins:
        symbol = coin.split('/')[0]
        if symbol in whitelist_symbols:
            continue  # Already in whitelist

        single = {coin: data[coin]}
        ind = precompute_ms_indicators(single, [coin])
        res = run_backtest(single, [coin], signal_structure_shift_pullback, PARAMS, ind,
                           fee=MEXC_FEE, initial_capital=10000, max_pos=1)

        if res.pnl > 500 and (isinstance(res.trades, list) and len(res.trades) >= 5 or
                               isinstance(res.trades, int) and res.trades >= 5):
            trades_n = len(res.trades) if isinstance(res.trades, list) else res.trades
            new_opportunities.append({
                'coin': coin,
                'symbol': symbol,
                'pnl': res.pnl,
                'trades': trades_n,
                'pf': res.pf if hasattr(res, 'pf') else 0,
            })

    new_opportunities.sort(key=lambda x: x['pnl'], reverse=True)
    print(f"  New opportunities (PnL>$500, trades≥5): {len(new_opportunities)}")

    if new_opportunities:
        print(f"\n  Top new opportunities (not in whitelist):")
        for opp in new_opportunities[:10]:
            print(f"    {opp['symbol']:<10} PnL=${opp['pnl']:+,.0f}  trades={opp['trades']}  PF={opp['pf']:.2f}")

    # Re-validate current whitelist performance
    print(f"\n  Whitelist performance check:")
    wl_coins = [c for c in all_coins if c.split('/')[0] in whitelist_symbols]
    if wl_coins:
        wl_data = {c: data[c] for c in wl_coins}
        wl_ind = precompute_ms_indicators(wl_data, wl_coins)
        wl_res = run_backtest(wl_data, wl_coins, signal_structure_shift_pullback, PARAMS,
                              wl_ind, fee=MEXC_FEE, initial_capital=10000, max_pos=3)
        trades_n = len(wl_res.trades) if isinstance(wl_res.trades, list) else wl_res.trades
        print(f"    PF={wl_res.pf:.2f}, PnL=${wl_res.pnl:+,.0f}, trades={trades_n}, DD={wl_res.dd:.1f}%")

    # Save report
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'mode': 'research',
        'universe_size': len(all_coins),
        'whitelist_size': len(whitelist_symbols),
        'new_opportunities': new_opportunities[:20],
    }
    report_file = REPORTS_DIR / f"research_{datetime.now().strftime('%Y%m%d')}.json"
    report_file.write_text(json.dumps(report, indent=2))

    if len(new_opportunities) >= 3:
        coins_str = ", ".join(f"{o['symbol']}(${o['pnl']:+,.0f})" for o in new_opportunities[:5])
        msg = f"🔬 <b>Weekly Research</b>\n\n{len(new_opportunities)} nieuwe kansen gevonden:\n{coins_str}\n\nZie reports/pipeline/ voor details."
        send_telegram(msg)

    return new_opportunities


# ── Daemon Mode ──────────────────────────────────────────────
def run_daemon():
    """Run all modes on schedule."""
    print("Starting research pipeline daemon...")
    print("  Monitor: every 4h")
    print("  Daily:   every 24h at 06:00 UTC")
    print("  Research: every Sunday at 02:00 UTC")
    print()

    last_monitor = 0
    last_daily = 0
    last_research = 0

    while True:
        now = time.time()
        now_dt = datetime.now(timezone.utc)

        # Monitor every 4h
        if now - last_monitor >= 4 * 3600:
            try:
                run_monitor()
            except Exception as e:
                print(f"[ERROR] Monitor failed: {e}")
                send_telegram(f"🚨 Pipeline monitor crashed: {e}")
            last_monitor = now

        # Daily at 06:00 UTC
        if now_dt.hour == 6 and now - last_daily >= 20 * 3600:
            try:
                run_daily()
            except Exception as e:
                print(f"[ERROR] Daily failed: {e}")
                send_telegram(f"🚨 Pipeline daily scan crashed: {e}")
            last_daily = now

        # Weekly on Sunday at 02:00
        if now_dt.weekday() == 6 and now_dt.hour == 2 and now - last_research >= 6 * 86400:
            try:
                run_research()
            except Exception as e:
                print(f"[ERROR] Research failed: {e}")
                send_telegram(f"🚨 Pipeline research crashed: {e}")
            last_research = now

        time.sleep(300)  # Check every 5 minutes


# ── Main ─────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Continuous Research Pipeline')
    parser.add_argument('--monitor', action='store_true', help='Run monitor check')
    parser.add_argument('--daily', action='store_true', help='Run daily scan')
    parser.add_argument('--research', action='store_true', help='Run weekly research')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon (all modes)')
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    elif args.monitor:
        run_monitor()
    elif args.daily:
        run_daily()
    elif args.research:
        run_research()
    else:
        print("Usage: --monitor | --daily | --research | --daemon")
        print("  --monitor   Check strategy drift (every 4h)")
        print("  --daily     Scan delistings + spreads (daily)")
        print("  --research  Screen new coins + re-validate (weekly)")
        print("  --daemon    Run all on schedule")
