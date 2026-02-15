#!/usr/bin/env python3
"""
Bear Market Period Analysis - Feb 2025 to Feb 2026
=====================================================
Test ALLEEN de bear market periode met paper trading.
Zo zien we welke strategie het beste werkt in een dalende markt.
"""
import backtrader as bt
import pandas as pd
import math
import os
from datetime import datetime

from strategies.bear_mean_reversion import (
    BearMeanReversion, BearRSICycle, BearKeltnerBounce,
    BearStochBounce, BearVWAPBounce, BearEMADip,
    BearDonchianBounce, BearCCIBounce,
)
from strategies.v55_vwap_trend import VWAPTrend1H
from strategies.v69_vwap_chaikin import VWAPChaikin1H
from strategies.v13_keltner_optimized import KeltnerOptimizedStops
from strategies.v21_keltner_micro import KeltnerMicroBreakout
from engine.analyzers import DetailedTradeLogger

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
COMMISSION = 0.001
PAPER_CASH = 1000.0

BEAR_START = datetime(2025, 2, 12)
BEAR_END = datetime(2026, 2, 12, 23, 59)

STRATEGIES = [
    ('BearMeanReversion', BearMeanReversion),
    ('BearRSICycle', BearRSICycle),
    ('BearKeltnerBounce', BearKeltnerBounce),
    ('BearStochBounce', BearStochBounce),
    ('BearVWAPBounce', BearVWAPBounce),
    ('BearEMADip', BearEMADip),
    ('BearDonchianBounce', BearDonchianBounce),
    ('BearCCIBounce', BearCCIBounce),
]

TIMEFRAMES = {
    '15m': {'file': 'BTC_15m.csv', 'tf': bt.TimeFrame.Minutes, 'comp': 15},
    '1h':  {'file': 'BTC_1h.csv',  'tf': bt.TimeFrame.Minutes, 'comp': 60},
    '4h':  {'file': 'BTC_4h.csv',  'tf': bt.TimeFrame.Minutes, 'comp': 240},
    '1d':  {'file': 'BTC_1d.csv',  'tf': bt.TimeFrame.Days,    'comp': 1},
}


def run_paper(strategy_class, tf_key):
    """Run full backtest then filter trades to bear period, re-simulate with EUR 1000."""
    tf_info = TIMEFRAMES[tf_key]
    filepath = os.path.join(DATA_DIR, tf_info['file'])

    if not os.path.exists(filepath):
        return None

    df = pd.read_csv(filepath, index_col='Date', parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)
    data = bt.feeds.PandasData(
        dataname=df, timeframe=tf_info['tf'], compression=tf_info['comp'])
    cerebro.adddata(data)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addanalyzer(DetailedTradeLogger, _name='trade_log')

    try:
        results = cerebro.run()
    except Exception:
        return None

    strat = results[0]
    trade_log = strat.analyzers.trade_log.get_analysis()

    # Filter to bear period
    raw_trades = [t for t in trade_log
                  if t['entry_date'] >= BEAR_START and t['entry_date'] <= BEAR_END]

    if not raw_trades:
        return {
            'strategy': strategy_class.__name__,
            'timeframe': tf_key,
            'trades': [],
            'total_trades': 0,
            'start_capital': PAPER_CASH,
            'end_capital': PAPER_CASH,
            'return_pct': 0,
            'win_rate': 0,
            'max_dd': 0,
            'profit_factor': 0,
        }

    # Re-simulate with fixed capital
    capital = PAPER_CASH
    results_list = []
    peak = capital
    max_dd = 0
    gross_profit = 0
    gross_loss = 0
    wins = 0

    for t in raw_trades:
        size = (capital * 0.95) / t['entry_price']
        pnl_per_unit = t['exit_price'] - t['entry_price']
        raw_pnl = pnl_per_unit * size
        comm = t['entry_price'] * size * COMMISSION + t['exit_price'] * size * COMMISSION
        net_pnl = raw_pnl - comm

        results_list.append({
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'entry_price': t['entry_price'],
            'exit_price': t['exit_price'],
            'pnl': net_pnl,
            'pnl_pct': (net_pnl / capital) * 100,
            'capital_after': capital + net_pnl,
        })

        if net_pnl > 0:
            wins += 1
            gross_profit += net_pnl
        else:
            gross_loss += abs(net_pnl)

        capital += net_pnl
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    total = len(raw_trades)
    wr = (wins / total * 100) if total > 0 else 0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 0
    ret = (capital - PAPER_CASH) / PAPER_CASH * 100

    return {
        'strategy': strategy_class.__name__,
        'timeframe': tf_key,
        'trades': results_list,
        'total_trades': total,
        'start_capital': PAPER_CASH,
        'end_capital': capital,
        'return_pct': ret,
        'win_rate': wr,
        'max_dd': max_dd,
        'profit_factor': pf,
        'wins': wins,
        'losses': total - wins,
    }


def score(r):
    """Bear market score: safety first."""
    ret = r['return_pct']
    wr = r['win_rate']
    dd = r['max_dd']
    pf = r['profit_factor']
    trades = r['total_trades']
    # Bonus for having enough trades (statistical significance)
    trade_bonus = min(trades / 10, 3.0)
    return (math.log1p(max(ret + 30, 0)) * 5 +  # +30 offset zodat ook lichte verliezen scoren
            (100 - dd) * 1.0 +
            wr * 0.5 +
            pf * 15 +
            trade_bonus * 3)


def main():
    print("\n" + "=" * 120)
    print("  BEAR MARKET PAPER TRADE ANALYSE (EUR 1.000 startkapitaal)")
    print("  BTC/USD | Periode: 12 feb 2025 - 12 feb 2026 (BTC: -29.7%)")
    print("  Commissie: 0.1% | Long only | Geen leverage")
    print("=" * 120)

    all_results = []

    for tf_key in ['15m', '1h', '4h', '1d']:
        strats = STRATEGIES[:]
        if tf_key == '1h':
            strats += [('V55_VWAPTrend', VWAPTrend1H), ('V69_VWAPChaikin', VWAPChaikin1H)]
        if tf_key == '1d':
            strats += [('V13_Keltner', KeltnerOptimizedStops), ('V21_KeltnerMicro', KeltnerMicroBreakout)]

        print(f"\n  --- {tf_key.upper()} TIMEFRAME ---")
        for name, cls in strats:
            r = run_paper(cls, tf_key)
            if r is None:
                continue
            all_results.append(r)
            if r['total_trades'] > 0:
                pnl = r['end_capital'] - PAPER_CASH
                print(f"    {name:<25} EUR{pnl:>+8.2f} ({r['return_pct']:>+6.1f}%)  "
                      f"{r['total_trades']:>4} trades  WR {r['win_rate']:>5.1f}%  "
                      f"PF {r['profit_factor']:>5.2f}  DD {r['max_dd']:>5.1f}%")
            else:
                print(f"    {name:<25}   geen trades")

    # Filter out zero-trade results
    valid = [r for r in all_results if r['total_trades'] > 0]

    if valid:
        scored = [(score(r), r) for r in valid]
        scored.sort(key=lambda x: x[0], reverse=True)

        print(f"\n{'=' * 120}")
        print(f"  TOP 15 BEAR MARKET STRATEGIEEN - PAPER TRADE RESULTATEN")
        print(f"  Ranking: veiligheid (lage DD) + consistentie (hoge WR/PF) > rauwe return")
        print(f"{'=' * 120}")
        print(f"  {'#':>3}  {'Strategie':<25} {'TF':>4} {'P&L':>10} {'Return':>8} "
              f"{'Trades':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7} {'Score':>7}")
        print(f"  {'-' * 108}")

        for i, (sc, r) in enumerate(scored[:15], 1):
            pnl = r['end_capital'] - PAPER_CASH
            marker = " <-- BEST" if i == 1 else ""
            print(f"  {i:>3}  {r['strategy']:<25} {r['timeframe']:>4} EUR{pnl:>+8.2f} "
                  f"{r['return_pct']:>+7.1f}% {r['total_trades']:>6}  "
                  f"{r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} "
                  f"{r['max_dd']:>6.1f}% {sc:>7.1f}{marker}")

        print(f"  {'-' * 108}")

        # Best per timeframe
        print(f"\n  BESTE PER TIMEFRAME (bear market periode):")
        for tf in ['15m', '1h', '4h', '1d']:
            tf_results = [(s, r) for s, r in scored if r['timeframe'] == tf]
            if tf_results:
                best = tf_results[0]
                r = best[1]
                pnl = r['end_capital'] - PAPER_CASH
                print(f"    {tf:>4}: {r['strategy']:<25} EUR{pnl:>+8.2f} ({r['return_pct']:>+6.1f}%)  "
                      f"WR {r['win_rate']:>5.1f}%  PF {r['profit_factor']:>5.2f}  "
                      f"DD {r['max_dd']:>5.1f}%  ({r['total_trades']} trades)")

        # Buy & Hold vergelijking
        print(f"\n  VERSUS BUY & HOLD:")
        bh_pnl = PAPER_CASH * (-29.7 / 100)
        print(f"    Buy & Hold BTC:            EUR{bh_pnl:>+8.2f} (-29.7%)")
        best_r = scored[0][1]
        best_pnl = best_r['end_capital'] - PAPER_CASH
        print(f"    Beste strategie:           EUR{best_pnl:>+8.2f} ({best_r['return_pct']:>+.1f}%) "
              f"= {best_r['strategy']} ({best_r['timeframe']})")
        diff = best_pnl - bh_pnl
        print(f"    Verschil:                  EUR{diff:>+8.2f} beter dan Buy & Hold")

        # Detail van top 3
        print(f"\n{'=' * 120}")
        print(f"  DETAIL TOP 3 STRATEGIEEN - TRADE-BY-TRADE")
        print(f"{'=' * 120}")

        for rank, (sc, r) in enumerate(scored[:3], 1):
            pnl_total = r['end_capital'] - PAPER_CASH
            print(f"\n  #{rank} {r['strategy']} ({r['timeframe'].upper()})")
            print(f"  Return: EUR{pnl_total:>+.2f} ({r['return_pct']:>+.1f}%) | "
                  f"WR: {r['win_rate']:.0f}% | PF: {r['profit_factor']:.2f} | DD: {r['max_dd']:.1f}%")
            print(f"  {'#':>3}  {'Entry':<18} {'Prijs':>10}  {'Exit':<18} {'Prijs':>10}  "
                  f"{'P&L':>10} {'%':>7}  {'Saldo':>10}")
            print(f"  {'-'*95}")

            for i, t in enumerate(r['trades'][:20], 1):
                entry_dt = t['entry_date'].strftime('%d-%b-%y %H:%M')
                exit_dt = t['exit_date'].strftime('%d-%b-%y %H:%M')
                result = "WIN" if t['pnl'] > 0 else "LOSS"
                print(f"  {i:>3}  {entry_dt:<18} ${t['entry_price']:>9,.0f}  "
                      f"{exit_dt:<18} ${t['exit_price']:>9,.0f}  "
                      f"EUR{t['pnl']:>+9.2f} {t['pnl_pct']:>+6.1f}%  "
                      f"EUR{t['capital_after']:>9.2f}  {result}")
            if len(r['trades']) > 20:
                print(f"  ... en nog {len(r['trades'])-20} trades meer")

        print(f"\n{'=' * 120}\n")


if __name__ == '__main__':
    main()
