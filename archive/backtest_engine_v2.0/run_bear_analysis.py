#!/usr/bin/env python3
"""
Bear Market Multi-Timeframe Strategy Analysis
===============================================
Test bear market cycle trading strategies across 15m, 1h, 4h, 1d timeframes.
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
from engine.analyzers import TradeLogger

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
COMMISSION = 0.001
CASH = 10000.0

# Bear market period
BEAR_START = datetime(2025, 2, 12)
BEAR_END = datetime(2026, 2, 12, 23, 59)

BEAR_STRATEGIES = [
    ('BearMeanReversion', BearMeanReversion),
    ('BearRSICycle', BearRSICycle),
    ('BearKeltnerBounce', BearKeltnerBounce),
    ('BearStochBounce', BearStochBounce),
    ('BearVWAPBounce', BearVWAPBounce),
    ('BearEMADip', BearEMADip),
    ('BearDonchianBounce', BearDonchianBounce),
    ('BearCCIBounce', BearCCIBounce),
]

TREND_STRATEGIES = [
    ('V55_VWAPTrend', VWAPTrend1H),
    ('V69_VWAPChaikin', VWAPChaikin1H),
]

DAILY_STRATEGIES = [
    ('V13_Keltner', KeltnerOptimizedStops),
    ('V21_KeltnerMicro', KeltnerMicroBreakout),
]

TIMEFRAMES = {
    '15m': {'file': 'BTC_15m.csv', 'tf': bt.TimeFrame.Minutes, 'comp': 15},
    '1h':  {'file': 'BTC_1h.csv',  'tf': bt.TimeFrame.Minutes, 'comp': 60},
    '4h':  {'file': 'BTC_4h.csv',  'tf': bt.TimeFrame.Minutes, 'comp': 240},
    '1d':  {'file': 'BTC_1d.csv',  'tf': bt.TimeFrame.Days,    'comp': 1},
}


def run_single(strategy_class, timeframe_key):
    """Run a single strategy on a single timeframe."""
    tf_info = TIMEFRAMES[timeframe_key]
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

    cerebro.broker.setcash(CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

    try:
        results = cerebro.run()
    except Exception as e:
        return None

    strat = results[0]
    final_value = cerebro.broker.getvalue()
    ret = (final_value - CASH) / CASH * 100

    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    max_dd = strat.analyzers.dd.get_analysis().max.drawdown or 0

    ta = strat.analyzers.ta.get_analysis()
    try:
        total = ta.total.closed
    except (KeyError, AttributeError):
        total = 0
    try:
        won = ta.won.total
    except (KeyError, AttributeError):
        won = 0
    try:
        lost = ta.lost.total
    except (KeyError, AttributeError):
        lost = 0
    wr = (won / total * 100) if total > 0 else 0

    try:
        gp = ta.won.pnl.total
    except (KeyError, AttributeError):
        gp = 0
    try:
        gl = abs(ta.lost.pnl.total)
    except (KeyError, AttributeError):
        gl = 0
    pf = (gp / gl) if gl > 0 else 0

    return {
        'strategy': strategy_class.__name__,
        'timeframe': timeframe_key,
        'return_pct': ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'total_trades': total,
        'won': won,
        'lost': lost,
        'win_rate': wr,
        'profit_factor': pf,
    }


def score(r):
    """Scoring formula optimized for bear market: prioritize PF, WR, and low DD."""
    ret = r['return_pct']
    sharpe = r['sharpe']
    dd = r['max_dd']
    wr = r['win_rate']
    pf = r['profit_factor']
    # Bear market scoring: veiligheid en consistentie > rauwe return
    return (math.log1p(max(ret, 0)) * 3 +
            sharpe * 25 +
            (100 - dd) * 0.8 +
            wr * 0.4 +
            pf * 12)


def main():
    print("\n" + "=" * 120)
    print("  BEAR MARKET MULTI-TIMEFRAME STRATEGY ANALYSE")
    print("  BTC/USD | Alle data | Commissie: 0.1%")
    print("=" * 120)

    all_results = []

    # Test bear market strategies on all timeframes
    for tf_key in ['15m', '1h', '4h', '1d']:
        strats = BEAR_STRATEGIES[:]
        if tf_key in ['1h']:
            strats += TREND_STRATEGIES
        if tf_key in ['1d']:
            strats += DAILY_STRATEGIES

        print(f"\n  --- {tf_key.upper()} TIMEFRAME ---")
        for name, cls in strats:
            r = run_single(cls, tf_key)
            if r and r['total_trades'] > 0:
                all_results.append(r)
                print(f"    {name:<25} {r['return_pct']:>+7.1f}%  {r['total_trades']:>4} trades  "
                      f"WR {r['win_rate']:>5.1f}%  PF {r['profit_factor']:>5.2f}  "
                      f"DD {r['max_dd']:>5.1f}%  Sharpe {r['sharpe']:>6.3f}")
            elif r:
                print(f"    {name:<25}   0 trades - geen signalen")

    # Ranking
    if all_results:
        scored = [(score(r), r) for r in all_results]
        scored.sort(key=lambda x: x[0], reverse=True)

        print(f"\n{'=' * 120}")
        print(f"  TOP 15 BEAR MARKET STRATEGIEEN (ALLE TIMEFRAMES)")
        print(f"{'=' * 120}")
        print(f"  {'#':>3}  {'Strategie':<25} {'TF':>4} {'Return':>8} {'Trades':>7} "
              f"{'WR':>6} {'Sharpe':>7} {'MaxDD':>7} {'PF':>6} {'Score':>7}")
        print(f"  {'-' * 108}")

        for i, (sc, r) in enumerate(scored[:15], 1):
            print(f"  {i:>3}  {r['strategy']:<25} {r['timeframe']:>4} {r['return_pct']:>+7.1f}% "
                  f"{r['total_trades']:>6}  {r['win_rate']:>5.1f}% {r['sharpe']:>6.3f} "
                  f"{r['max_dd']:>6.1f}% {r['profit_factor']:>5.2f} {sc:>7.1f}")

        print(f"  {'-' * 108}")

        # Best per timeframe
        print(f"\n  BESTE PER TIMEFRAME:")
        for tf in ['15m', '1h', '4h', '1d']:
            tf_results = [x for x in scored if x[1]['timeframe'] == tf]
            if tf_results:
                best = tf_results[0]
                r = best[1]
                print(f"    {tf:>4}: {r['strategy']:<25} {r['return_pct']:>+7.1f}% "
                      f"WR {r['win_rate']:>5.1f}% PF {r['profit_factor']:>5.2f} "
                      f"DD {r['max_dd']:>5.1f}% ({r['total_trades']} trades)")

        print(f"\n{'=' * 120}\n")


if __name__ == '__main__':
    main()
