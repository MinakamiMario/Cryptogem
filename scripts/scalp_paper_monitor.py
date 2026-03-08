#!/usr/bin/env python3
"""
Scalp FVG Paper Trading Monitor — Tripwire Alert System
========================================================

Parses all paper trading logs, compares live behavior against backtest
reference profile, and raises tripwire alerts when behavior deviates.

Tripwires (from operational doctrine):
  T1: Paper PF vs Backtest PF gap
  T2: Average slippage (entry + exit)
  T3: Trades per day vs expected
  T4: PnL per coin (concentration)
  T5: Drawdown cluster detection
  T6: Consecutive loss days
  T7: Coin contribution concentration (HHI)

Reference profile: backtest on MEXC 30d data (Feb 6 - Mar 8 2026)

Usage:
    python scripts/scalp_paper_monitor.py
    python scripts/scalp_paper_monitor.py --json   # machine-readable output
"""
import sys, re, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent

# ─── Backtest Reference Profile ──────────────────────────────────
# From scalp_temporal_validation.json (MEXC 30d, fvg_x2027)
REFERENCE = {
    'XRP': {'pf': 1.62, 'tpd': 4.2, 'wr': 38.4, 'avg_hold': 5.4},
    'BTC': {'pf': 1.44, 'tpd': 7.7, 'wr': 31.9, 'avg_hold': 4.5},
    'ETH': {'pf': 1.05, 'tpd': 6.4, 'wr': 29.0, 'avg_hold': 4.0},
    'SUI': {'pf': 1.17, 'tpd': 5.0, 'wr': 31.8, 'avg_hold': 5.6},
}
PORTFOLIO_BACKTEST_PF = 1.30  # weighted portfolio PF from backtest

# ─── Tripwire Thresholds ─────────────────────────────────────────
THRESHOLDS = {
    'pf_gap_warn': 0.30,        # paper PF deviates >0.30 from backtest → WARN
    'pf_gap_alert': 0.50,       # paper PF deviates >0.50 → ALERT
    'avg_slip_warn_bps': 5.0,   # avg abs slippage > 5 bps → WARN
    'avg_slip_alert_bps': 10.0, # avg abs slippage > 10 bps → ALERT
    'tpd_ratio_low': 0.40,      # paper TPD < 40% of backtest → WARN
    'tpd_ratio_high': 2.50,     # paper TPD > 250% of backtest → WARN
    'consec_loss_days': 3,      # 3+ consecutive loss days → ALERT
    'dd_cluster_pct': 2.0,      # DD > 2% → WARN
    'dd_cluster_alert_pct': 5.0,# DD > 5% → ALERT
    'hhi_warn': 0.50,           # HHI > 0.50 → WARN (concentrated)
    'hhi_alert': 0.70,          # HHI > 0.70 → ALERT
    'min_trades_for_tripwire': 10,  # need ≥10 trades before tripwires activate
}

# ─── Log Parsing ─────────────────────────────────────────────────

LOG_DIR = ROOT / 'trading_bot' / 'logs'

# Pattern: WIN EXIT or LOSS EXIT line
EXIT_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
    r'(WIN|LOSS) EXIT (\w+)/USDT \[(\w+)\] '
    r'\$([0-9.]+) \| P&L=\$([+-][0-9.]+) \(([+-]?[0-9.]+)%\) '
    r'\| (\d+)bars \| Spread=([0-9.]+)bps \| Eq=\$([0-9.]+)'
)

# Pattern: LIVE BUY/SELL
LIVE_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?'
    r'LIVE (BUY|SELL) (\w+)/USDT: fill=\$([0-9.]+).*?slip=([+-]?[0-9.]+)bps'
)


def parse_all_logs():
    """Parse all paper_scalp logs and return trade list."""
    log_files = sorted(LOG_DIR.glob('paper_scalp_1m_paper_*.log'))

    trades = []
    slippages = []  # (timestamp, coin, side, slip_bps)

    seen_exits = set()  # dedup by (timestamp, coin)

    for log_file in log_files:
        with open(log_file) as f:
            for line in f:
                # Parse exits (paper P&L)
                m = EXIT_RE.search(line)
                if m:
                    ts_str, outcome, coin, exit_type, price, pnl, pnl_pct, bars, spread, equity = m.groups()
                    dedup_key = (ts_str, coin)
                    if dedup_key in seen_exits:
                        continue
                    seen_exits.add(dedup_key)

                    ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    trades.append({
                        'timestamp': ts,
                        'date': ts.strftime('%Y-%m-%d'),
                        'coin': coin,
                        'outcome': outcome,
                        'exit_type': exit_type,
                        'price': float(price),
                        'pnl': float(pnl),
                        'pnl_pct': float(pnl_pct),
                        'bars': int(bars),
                        'spread_bps': float(spread),
                        'equity': float(equity),
                    })

                # Parse live fills (slippage data)
                m2 = LIVE_RE.search(line)
                if m2:
                    ts_str, side, coin, price, slip = m2.groups()
                    ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    slippages.append({
                        'timestamp': ts,
                        'coin': coin,
                        'side': side,
                        'price': float(price),
                        'slip_bps': float(slip),
                    })

    # Sort by timestamp
    trades.sort(key=lambda t: t['timestamp'])
    slippages.sort(key=lambda s: s['timestamp'])

    return trades, slippages


def compute_metrics(trades, slippages):
    """Compute all monitoring metrics."""
    if not trades:
        return None

    first_ts = trades[0]['timestamp']
    last_ts = trades[-1]['timestamp']
    elapsed_days = max(1, (last_ts - first_ts).total_seconds() / 86400)

    # ─── Per-coin stats ──────────────────────────────────────
    coin_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0})
    for t in trades:
        c = t['coin']
        coin_stats[c]['trades'] += 1
        coin_stats[c]['pnl'] += t['pnl']
        if t['outcome'] == 'WIN':
            coin_stats[c]['wins'] += 1
            coin_stats[c]['gross_win'] += t['pnl']
        else:
            coin_stats[c]['gross_loss'] += abs(t['pnl'])

    for c in coin_stats:
        s = coin_stats[c]
        s['wr'] = s['wins'] / s['trades'] * 100 if s['trades'] > 0 else 0
        s['pf'] = s['gross_win'] / s['gross_loss'] if s['gross_loss'] > 0 else float('inf')
        s['tpd'] = s['trades'] / elapsed_days

    # ─── Portfolio stats ─────────────────────────────────────
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['outcome'] == 'WIN')
    total_pnl = sum(t['pnl'] for t in trades)
    gross_win = sum(t['pnl'] for t in trades if t['outcome'] == 'WIN')
    gross_loss = sum(abs(t['pnl']) for t in trades if t['outcome'] == 'LOSS')
    portfolio_pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    portfolio_wr = wins / total_trades * 100 if total_trades > 0 else 0
    portfolio_tpd = total_trades / elapsed_days

    # ─── Equity curve & drawdown ─────────────────────────────
    equity_curve = [2000.0]  # starting equity
    for t in trades:
        equity_curve.append(equity_curve[-1] + t['pnl'])

    peak = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)

    # ─── Daily P&L ───────────────────────────────────────────
    daily_pnl = defaultdict(float)
    for t in trades:
        daily_pnl[t['date']] += t['pnl']

    # Consecutive loss days
    sorted_days = sorted(daily_pnl.keys())
    max_consec_loss = 0
    cur_consec = 0
    for day in sorted_days:
        if daily_pnl[day] < 0:
            cur_consec += 1
            max_consec_loss = max(max_consec_loss, cur_consec)
        else:
            cur_consec = 0

    # ─── Slippage stats ──────────────────────────────────────
    coin_slippages = defaultdict(list)
    all_slip_abs = []
    for s in slippages:
        coin_slippages[s['coin']].append(s['slip_bps'])
        all_slip_abs.append(abs(s['slip_bps']))

    avg_slip_abs = sum(all_slip_abs) / len(all_slip_abs) if all_slip_abs else 0
    avg_slip_signed = sum(s['slip_bps'] for s in slippages) / len(slippages) if slippages else 0

    # ─── HHI concentration ───────────────────────────────────
    total_abs_pnl = sum(abs(s['pnl']) for s in coin_stats.values())
    hhi = 0.0
    if total_abs_pnl > 0:
        hhi = sum((abs(s['pnl']) / total_abs_pnl) ** 2 for s in coin_stats.values())

    return {
        'elapsed_days': round(elapsed_days, 1),
        'first_trade': first_ts.strftime('%Y-%m-%d %H:%M'),
        'last_trade': last_ts.strftime('%Y-%m-%d %H:%M'),
        'total_trades': total_trades,
        'portfolio': {
            'pf': round(portfolio_pf, 3),
            'wr': round(portfolio_wr, 1),
            'tpd': round(portfolio_tpd, 1),
            'pnl': round(total_pnl, 2),
            'max_dd_pct': round(max_dd_pct, 2),
            'max_dd_usd': round(max_dd, 2),
            'equity': round(equity_curve[-1], 2),
        },
        'per_coin': {c: {k: round(v, 3) if isinstance(v, float) else v
                         for k, v in s.items()}
                     for c, s in coin_stats.items()},
        'daily_pnl': {k: round(v, 2) for k, v in sorted(daily_pnl.items())},
        'max_consec_loss_days': max_consec_loss,
        'slippage': {
            'avg_abs_bps': round(avg_slip_abs, 1),
            'avg_signed_bps': round(avg_slip_signed, 1),
            'total_fills': len(slippages),
            'per_coin': {c: {
                'avg_abs': round(sum(abs(s) for s in slips) / len(slips), 1),
                'avg_signed': round(sum(slips) / len(slips), 1),
                'count': len(slips),
            } for c, slips in coin_slippages.items()},
        },
        'hhi': round(hhi, 3),
    }


def evaluate_tripwires(metrics):
    """Evaluate all tripwires against thresholds."""
    alerts = []
    T = THRESHOLDS

    n = metrics['total_trades']
    if n < T['min_trades_for_tripwire']:
        return [{'tripwire': 'T0:DATA', 'level': 'INFO',
                 'msg': f'Only {n} trades — need ≥{T["min_trades_for_tripwire"]} for tripwires to activate'}]

    port = metrics['portfolio']

    # T1: Paper PF vs Backtest PF gap
    pf_gap = PORTFOLIO_BACKTEST_PF - port['pf']
    if abs(pf_gap) > T['pf_gap_alert']:
        alerts.append({'tripwire': 'T1:PF_GAP', 'level': 'ALERT',
                       'msg': f'Paper PF ({port["pf"]:.2f}) deviates {pf_gap:+.2f} from backtest ({PORTFOLIO_BACKTEST_PF:.2f})'})
    elif abs(pf_gap) > T['pf_gap_warn']:
        alerts.append({'tripwire': 'T1:PF_GAP', 'level': 'WARN',
                       'msg': f'Paper PF ({port["pf"]:.2f}) deviates {pf_gap:+.2f} from backtest ({PORTFOLIO_BACKTEST_PF:.2f})'})
    else:
        alerts.append({'tripwire': 'T1:PF_GAP', 'level': 'OK',
                       'msg': f'Paper PF ({port["pf"]:.2f}) within {pf_gap:+.2f} of backtest ({PORTFOLIO_BACKTEST_PF:.2f})'})

    # T2: Average slippage
    slip = metrics['slippage']['avg_abs_bps']
    if slip > T['avg_slip_alert_bps']:
        alerts.append({'tripwire': 'T2:SLIPPAGE', 'level': 'ALERT',
                       'msg': f'Avg absolute slippage {slip:.1f} bps > {T["avg_slip_alert_bps"]} bps threshold'})
    elif slip > T['avg_slip_warn_bps']:
        alerts.append({'tripwire': 'T2:SLIPPAGE', 'level': 'WARN',
                       'msg': f'Avg absolute slippage {slip:.1f} bps > {T["avg_slip_warn_bps"]} bps threshold'})
    else:
        alerts.append({'tripwire': 'T2:SLIPPAGE', 'level': 'OK',
                       'msg': f'Avg absolute slippage {slip:.1f} bps — within bounds'})

    # T3: Trades per day vs expected
    expected_tpd = sum(REFERENCE[c]['tpd'] for c in REFERENCE)  # portfolio total
    actual_tpd = port['tpd']
    tpd_ratio = actual_tpd / expected_tpd if expected_tpd > 0 else 0
    if tpd_ratio < T['tpd_ratio_low']:
        alerts.append({'tripwire': 'T3:TPD', 'level': 'WARN',
                       'msg': f'TPD {actual_tpd:.1f} is {tpd_ratio:.0%} of expected {expected_tpd:.1f} (too few trades)'})
    elif tpd_ratio > T['tpd_ratio_high']:
        alerts.append({'tripwire': 'T3:TPD', 'level': 'WARN',
                       'msg': f'TPD {actual_tpd:.1f} is {tpd_ratio:.0%} of expected {expected_tpd:.1f} (too many trades)'})
    else:
        alerts.append({'tripwire': 'T3:TPD', 'level': 'OK',
                       'msg': f'TPD {actual_tpd:.1f} = {tpd_ratio:.0%} of expected {expected_tpd:.1f}'})

    # T4: Per-coin PnL vs reference
    for coin, ref in REFERENCE.items():
        cs = metrics['per_coin'].get(coin)
        if cs and cs['trades'] >= 3:
            coin_pf_gap = ref['pf'] - cs['pf']
            if abs(coin_pf_gap) > T['pf_gap_alert']:
                alerts.append({'tripwire': f'T4:COIN_{coin}', 'level': 'ALERT',
                               'msg': f'{coin}: Paper PF={cs["pf"]:.2f} vs backtest PF={ref["pf"]:.2f} (gap={coin_pf_gap:+.2f})'})
            elif abs(coin_pf_gap) > T['pf_gap_warn']:
                alerts.append({'tripwire': f'T4:COIN_{coin}', 'level': 'WARN',
                               'msg': f'{coin}: Paper PF={cs["pf"]:.2f} vs backtest PF={ref["pf"]:.2f} (gap={coin_pf_gap:+.2f})'})

    # T5: Drawdown cluster
    dd = port['max_dd_pct']
    if dd > T['dd_cluster_alert_pct']:
        alerts.append({'tripwire': 'T5:DRAWDOWN', 'level': 'ALERT',
                       'msg': f'Max drawdown {dd:.1f}% > {T["dd_cluster_alert_pct"]}% threshold'})
    elif dd > T['dd_cluster_pct']:
        alerts.append({'tripwire': 'T5:DRAWDOWN', 'level': 'WARN',
                       'msg': f'Max drawdown {dd:.1f}% > {T["dd_cluster_pct"]}% threshold'})
    else:
        alerts.append({'tripwire': 'T5:DRAWDOWN', 'level': 'OK',
                       'msg': f'Max drawdown {dd:.1f}% — within bounds'})

    # T6: Consecutive loss days
    cld = metrics['max_consec_loss_days']
    if cld >= T['consec_loss_days']:
        alerts.append({'tripwire': 'T6:LOSS_STREAK', 'level': 'ALERT',
                       'msg': f'{cld} consecutive loss days (threshold: {T["consec_loss_days"]})'})
    else:
        alerts.append({'tripwire': 'T6:LOSS_STREAK', 'level': 'OK',
                       'msg': f'{cld} consecutive loss days — below threshold'})

    # T7: Coin contribution concentration
    hhi = metrics['hhi']
    if hhi > T['hhi_alert']:
        alerts.append({'tripwire': 'T7:CONCENTRATION', 'level': 'ALERT',
                       'msg': f'HHI={hhi:.3f} — highly concentrated (>{T["hhi_alert"]:.2f})'})
    elif hhi > T['hhi_warn']:
        alerts.append({'tripwire': 'T7:CONCENTRATION', 'level': 'WARN',
                       'msg': f'HHI={hhi:.3f} — moderately concentrated (>{T["hhi_warn"]:.2f})'})
    else:
        alerts.append({'tripwire': 'T7:CONCENTRATION', 'level': 'OK',
                       'msg': f'HHI={hhi:.3f} — balanced'})

    return alerts


def print_report(metrics, alerts):
    """Human-readable tripwire report."""
    print("=" * 80)
    print("SCALP FVG PAPER TRADING MONITOR — TRIPWIRE REPORT")
    print(f"Period: {metrics['first_trade']} → {metrics['last_trade']} ({metrics['elapsed_days']}d)")
    print(f"Trades: {metrics['total_trades']}  |  Target: 200+")
    print("=" * 80)

    # Portfolio summary
    p = metrics['portfolio']
    print(f"\n  PORTFOLIO: PF={p['pf']:.2f}  WR={p['wr']:.0f}%  TPD={p['tpd']:.1f}  "
          f"PnL=${p['pnl']:+.2f}  DD={p['max_dd_pct']:.1f}%  Eq=${p['equity']:.2f}")

    # Per-coin
    print(f"\n  PER COIN:")
    for coin in ['XRP', 'BTC', 'ETH', 'SUI']:
        cs = metrics['per_coin'].get(coin)
        ref = REFERENCE.get(coin, {})
        if cs:
            pf_delta = cs['pf'] - ref.get('pf', 0)
            print(f"    {coin:<4} Paper: PF={cs['pf']:.2f} WR={cs['wr']:.0f}% "
                  f"Trades={cs['trades']} PnL=${cs['pnl']:+.2f}  |  "
                  f"Backtest: PF={ref.get('pf', '?')} TPD={ref.get('tpd', '?')}  |  "
                  f"Δ PF={pf_delta:+.2f}")

    # Slippage
    s = metrics['slippage']
    print(f"\n  SLIPPAGE ({s['total_fills']} fills):")
    print(f"    Portfolio avg: |slip|={s['avg_abs_bps']:.1f}bps  signed={s['avg_signed_bps']:+.1f}bps")
    for coin, cs in sorted(s['per_coin'].items()):
        print(f"    {coin:<4} |slip|={cs['avg_abs']:.1f}bps  signed={cs['avg_signed']:+.1f}bps  ({cs['count']} fills)")

    # Daily P&L
    print(f"\n  DAILY P&L:")
    for day, pnl in sorted(metrics['daily_pnl'].items()):
        bar = "█" * max(1, int(abs(pnl) * 10))
        color = "+" if pnl >= 0 else "-"
        print(f"    {day}: ${pnl:>+6.2f}  {bar if pnl >= 0 else ''}")

    print(f"\n  Consecutive loss days: {metrics['max_consec_loss_days']}")

    # Tripwires
    print(f"\n{'='*80}")
    print("TRIPWIRE STATUS")
    print(f"{'='*80}")

    level_icons = {'OK': '✅', 'INFO': 'ℹ️', 'WARN': '⚠️', 'ALERT': '🚨'}
    has_alerts = False
    has_warns = False

    for a in alerts:
        icon = level_icons.get(a['level'], '?')
        print(f"  {icon} {a['tripwire']:<20} [{a['level']:<5}] {a['msg']}")
        if a['level'] == 'ALERT':
            has_alerts = True
        if a['level'] == 'WARN':
            has_warns = True

    # Overall status
    print(f"\n{'─'*80}")
    if has_alerts:
        print("  🚨 STATUS: ALERT — Review required before any scale-up")
    elif has_warns:
        print("  ⚠️  STATUS: WARN — Monitor closely, no immediate action needed")
    else:
        print("  ✅ STATUS: OK — All tripwires within bounds")

    # Phase gate
    n = metrics['total_trades']
    print(f"\n  PHASE GATE:")
    print(f"    Paper trades: {n}/200 ({n/200*100:.0f}%)")
    if n >= 200:
        print(f"    → ELIGIBLE for Phase 2 (micro live) review")
    elif n >= 100:
        print(f"    → Interim review possible at 100+ trades")
    else:
        print(f"    → Continue paper trading ({200-n} more trades needed)")


# ─── Main ────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='Output JSON')
    args = parser.parse_args()

    trades, slippages = parse_all_logs()

    if not trades:
        print("No paper trades found in logs.")
        sys.exit(1)

    metrics = compute_metrics(trades, slippages)
    alerts = evaluate_tripwires(metrics)

    if args.json:
        output = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metrics': metrics,
            'alerts': alerts,
        }
        # Convert datetime objects for JSON
        for t in output['metrics'].get('per_coin', {}).values():
            for k, v in list(t.items()):
                if isinstance(v, datetime):
                    t[k] = v.isoformat()
        print(json.dumps(output, indent=2, default=str))
    else:
        print_report(metrics, alerts)

    # Save report
    report_dir = ROOT / 'reports' / 'pipeline'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / 'scalp_paper_monitor.json'
    with open(report_file, 'w') as f:
        output = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metrics': metrics,
            'alerts': alerts,
        }
        json.dump(output, f, indent=2, default=str)
