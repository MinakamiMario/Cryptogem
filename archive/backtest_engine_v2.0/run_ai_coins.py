#!/usr/bin/env python3
"""
AI Agent Coins - Multi-Coin Multi-Strategy Backtest
=====================================================
Test onze beste bear market + trend strategies op top AI Agent coins.
"""
import backtrader as bt
import pandas as pd
import math
import os
from datetime import datetime

from strategies.bear_mean_reversion import (
    BearMeanReversion, BearRSICycle, BearVWAPBounce,
    BearKeltnerBounce, BearStochBounce, BearDonchianBounce,
)
from strategies.bear_optimized import (
    BearBBRSI_4H, BearRSIMomentum_4H, BearStochRSI_4H,
    BearVWAPCycle_1H, BearBBStoch_4H, BearMultiSignal_4H,
)
from strategies.v55_vwap_trend import VWAPTrend1H
from strategies.v69_vwap_chaikin import VWAPChaikin1H
from engine.analyzers import DetailedTradeLogger

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
COMMISSION = 0.001
PAPER_CASH = 1000.0

AI_COINS = ['VIRTUAL', 'FET', 'TRAC', 'IOTX', 'PIPPIN', 'AWE', 'KITE']

STRATEGIES = [
    # Bear market (mean reversion)
    ('BearBBRSI', BearBBRSI_4H),
    ('BearMeanRev', BearMeanReversion),
    ('BearRSICycle', BearRSICycle),
    ('BearVWAPBounce', BearVWAPBounce),
    ('BearStochRSI', BearStochRSI_4H),
    ('BearVWAPCycle', BearVWAPCycle_1H),
    ('BearDonchian', BearDonchianBounce),
    ('BearRSIMom', BearRSIMomentum_4H),
    # Trend following
    ('V55_VWAP', VWAPTrend1H),
    ('V69_Chaikin', VWAPChaikin1H),
]

TIMEFRAMES = ['1h', '4h']


def run_backtest_coin(strategy_class, coin, tf_key):
    """Run backtest on a coin/timeframe combo and return results."""
    filepath = os.path.join(DATA_DIR, f'{coin}_{tf_key}.csv')
    if not os.path.exists(filepath):
        return None

    df = pd.read_csv(filepath, index_col='Date', parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    if len(df) < 200:
        return None

    tf_map = {
        '1h': (bt.TimeFrame.Minutes, 60),
        '4h': (bt.TimeFrame.Minutes, 240),
    }
    tf, comp = tf_map[tf_key]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)
    data = bt.feeds.PandasData(dataname=df, timeframe=tf, compression=comp)
    cerebro.adddata(data)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

    try:
        results = cerebro.run()
    except Exception:
        return None

    strat = results[0]
    final = cerebro.broker.getvalue()
    ret = (final - 10000) / 10000 * 100

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
        gp = ta.won.pnl.total
    except (KeyError, AttributeError):
        gp = 0
    try:
        gl = abs(ta.lost.pnl.total)
    except (KeyError, AttributeError):
        gl = 0

    wr = (won / total * 100) if total > 0 else 0
    pf = (gp / gl) if gl > 0 else 0

    # Coin performance (buy & hold)
    coin_ret = (df.iloc[-1]['Close'] - df.iloc[0]['Close']) / df.iloc[0]['Close'] * 100

    return {
        'strategy': strategy_class.__name__,
        'coin': coin,
        'timeframe': tf_key,
        'return_pct': ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'total_trades': total,
        'win_rate': wr,
        'profit_factor': pf,
        'coin_return': coin_ret,
        'alpha': ret - coin_ret,  # Outperformance vs buy & hold
    }


def score(r):
    """Score: alpha + risk-adjusted."""
    ret = r['return_pct']
    alpha = r['alpha']
    sharpe = r['sharpe']
    dd = r['max_dd']
    wr = r['win_rate']
    pf = r['profit_factor']
    trades = r['total_trades']
    trade_bonus = min(trades / 5, 3.0)
    return (math.log1p(max(ret + 50, 0)) * 3 +
            alpha * 0.3 +
            sharpe * 20 +
            (100 - min(dd, 100)) * 0.5 +
            wr * 0.3 +
            pf * 10 +
            trade_bonus * 2)


def main():
    print("\n" + "=" * 130)
    print("  AI AGENT COINS - MULTI-COIN MULTI-STRATEGY BACKTEST")
    print("  Coins: " + ", ".join(AI_COINS))
    print("  Timeframes: 1H, 4H | Commissie: 0.1% | Long only")
    print("=" * 130)

    all_results = []

    for coin in AI_COINS:
        print(f"\n  --- {coin} ---")
        coin_results = []

        for tf_key in TIMEFRAMES:
            for name, cls in STRATEGIES:
                r = run_backtest_coin(cls, coin, tf_key)
                if r and r['total_trades'] >= 3:
                    all_results.append(r)
                    coin_results.append(r)

        # Beste voor deze coin
        if coin_results:
            best = max(coin_results, key=lambda x: score(x))
            bh = best['coin_return']
            print(f"    Buy & Hold: {bh:>+.1f}%")
            print(f"    Beste strategie: {best['strategy']} ({best['timeframe']}) "
                  f"{best['return_pct']:>+.1f}% | {best['total_trades']} trades | "
                  f"WR {best['win_rate']:.0f}% | PF {best['profit_factor']:.2f} | "
                  f"DD {best['max_dd']:.1f}%")
            print(f"    Alpha vs B&H: {best['alpha']:>+.1f}%")

    # === OVERALL RANKING ===
    if all_results:
        scored = [(score(r), r) for r in all_results]
        scored.sort(key=lambda x: x[0], reverse=True)

        print(f"\n{'=' * 130}")
        print(f"  TOP 20 COIN + STRATEGIE COMBINATIES")
        print(f"{'=' * 130}")
        print(f"  {'#':>3}  {'Coin':<8} {'Strategie':<22} {'TF':>4} {'Return':>8} "
              f"{'B&H':>8} {'Alpha':>8} {'Trades':>7} {'WR':>6} {'PF':>6} "
              f"{'MaxDD':>7} {'Sharpe':>7}")
        print(f"  {'-' * 118}")

        for i, (sc, r) in enumerate(scored[:20], 1):
            print(f"  {i:>3}  {r['coin']:<8} {r['strategy']:<22} {r['timeframe']:>4} "
                  f"{r['return_pct']:>+7.1f}% {r['coin_return']:>+7.1f}% "
                  f"{r['alpha']:>+7.1f}% {r['total_trades']:>6}  "
                  f"{r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} "
                  f"{r['max_dd']:>6.1f}% {r['sharpe']:>6.3f}")

        # Beste per coin
        print(f"\n  BESTE STRATEGIE PER COIN:")
        print(f"  {'Coin':<8} {'Strategie':<22} {'TF':>4} {'Return':>8} {'B&H':>8} "
              f"{'Alpha':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'DD':>7}")
        print(f"  {'-' * 100}")

        for coin in AI_COINS:
            coin_scored = [(s, r) for s, r in scored if r['coin'] == coin]
            if coin_scored:
                best_s, best_r = coin_scored[0]
                print(f"  {best_r['coin']:<8} {best_r['strategy']:<22} {best_r['timeframe']:>4} "
                      f"{best_r['return_pct']:>+7.1f}% {best_r['coin_return']:>+7.1f}% "
                      f"{best_r['alpha']:>+7.1f}% {best_r['total_trades']:>6}  "
                      f"{best_r['win_rate']:>5.1f}% {best_r['profit_factor']:>5.2f} "
                      f"{best_r['max_dd']:>6.1f}%")

        # Beste strategie overall (welke strategie werkt het beste OVER alle coins)
        print(f"\n  BESTE STRATEGIE OVERALL (gemiddeld over alle coins):")
        strat_perf = {}
        for sc, r in scored:
            sname = f"{r['strategy']}_{r['timeframe']}"
            if sname not in strat_perf:
                strat_perf[sname] = {'returns': [], 'alphas': [], 'wrs': [], 'pfs': [], 'dds': []}
            strat_perf[sname]['returns'].append(r['return_pct'])
            strat_perf[sname]['alphas'].append(r['alpha'])
            strat_perf[sname]['wrs'].append(r['win_rate'])
            strat_perf[sname]['pfs'].append(r['profit_factor'])
            strat_perf[sname]['dds'].append(r['max_dd'])

        strat_avg = []
        for sname, data in strat_perf.items():
            import numpy as np
            avg_ret = np.mean(data['returns'])
            avg_alpha = np.mean(data['alphas'])
            avg_wr = np.mean(data['wrs'])
            avg_pf = np.mean(data['pfs'])
            avg_dd = np.mean(data['dds'])
            coins_tested = len(data['returns'])
            strat_avg.append((sname, avg_ret, avg_alpha, avg_wr, avg_pf, avg_dd, coins_tested))

        strat_avg.sort(key=lambda x: x[2], reverse=True)  # Sort by alpha
        print(f"  {'Strategie':<30} {'Coins':>5} {'Avg Ret':>8} {'Avg Alpha':>10} "
              f"{'Avg WR':>7} {'Avg PF':>7} {'Avg DD':>7}")
        print(f"  {'-' * 85}")
        for s in strat_avg[:10]:
            print(f"  {s[0]:<30} {s[6]:>5} {s[1]:>+7.1f}% {s[2]:>+9.1f}% "
                  f"{s[3]:>6.1f}% {s[4]:>6.2f} {s[5]:>6.1f}%")

        print(f"\n{'=' * 130}\n")


if __name__ == '__main__':
    main()
