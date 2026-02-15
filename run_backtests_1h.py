"""
Backtest Runner - BTC/USD 1H Strategies
"""
import backtrader as bt
import pandas as pd
import os
import math

from strategy_1h_v23 import Keltner1H
from strategy_1h_v24 import RSI1HScalper
from strategy_1h_v25 import EMAPullback1H
from strategy_1h_v26 import BBSqueeze1H
from strategy_1h_v27 import InsideKeltner1H
from strategy_1h_v28 import KeltnerTrendRider1H
from strategy_1h_v29 import MultiEMAMomentum1H
from strategy_1h_v30 import KeltnerStoch1H
from strategy_1h_v31 import DualKeltnerVol1H
from strategy_1h_v32 import MomentumATR1H
from strategy_1h_v33 import TrendPullback1H
from strategy_1h_v34 import KeltnerPullback1H
from strategy_1h_v35 import PureTrendFollower1H
from strategy_1h_v36 import KeltnerWideTrend1H
from strategy_1h_v37 import HybridKeltnerSwing1H
from strategy_1h_v38 import SwingRider1H
from strategy_1h_v39 import EMACrossSwing1H
from strategy_1h_v40 import KeltnerNoMidExit1H
from strategy_1h_v41 import KeltnerWideSwing1H
from strategy_1h_v42 import EMACrossRSI1H
from strategy_1h_v43 import UltraWideMomentum1H
from strategy_1h_v44 import UltraWideMomentumV2_1H
from strategy_1h_v45 import UltraWideMomentumV3_1H
from strategy_1h_v46 import UltraWideDualSlope1H
from strategy_1h_v47 import UltraWideMomentumV4_1H
from strategy_1h_v48 import UltraWideMomentumV5_1H
from strategy_1h_v49 import UltraWideMomentumADX_1H
from strategy_1h_v50 import UltraWideADXv2_1H
from strategy_1h_v51 import UltraWideADXv3_1H
from strategy_1h_v52 import UltraWideADXv4_1H
from strategy_1h_v53 import VolumePriceTrend1H
from strategy_1h_v54 import VolumeTrend1H
from strategy_1h_v55 import VWAPTrend1H
from strategy_1h_v56 import MACDMomentum1H
from strategy_1h_v57 import SupertrendMomentum1H
from strategy_1h_v58 import CCIMomentum1H
from strategy_1h_v59 import DonchianBreakout1H
from strategy_1h_v60 import ParabolicSARMomentum1H
from strategy_1h_v61 import AroonMomentum1H
from strategy_1h_v62 import UltimateHybrid1H
from strategy_1h_v63 import IchimokuTrend1H
from strategy_1h_v64 import ROCMomentum1H
from strategy_1h_v65 import ChaikinVolMomentum1H
from strategy_1h_v66 import VWAPTrendV2_1H
from strategy_1h_v67 import VWAPTrendV3_1H
from strategy_1h_v68 import VWAPTrendV4_1H
from strategy_1h_v69 import VWAPChaikin1H
from strategy_1h_v70 import VWAPTrendV5_1H
from strategy_1h_v71 import ChaikinVolV2_1H
from strategy_1h_v72 import VWAPSupertrend1H

INITIAL_CASH = 10000.0
COMMISSION = 0.001
DATA_FILE = os.path.join(os.path.dirname(__file__), 'btc_usd_1h.csv')


class TradeLogger(bt.Analyzer):
    def __init__(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm,
                'barlen': trade.barlen,
            })

    def get_analysis(self):
        return self.trades


def run_backtest(strategy_class, name, data_feed):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Minutes, compression=60, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(TradeLogger, _name='trade_log')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - INITIAL_CASH) / INITIAL_CASH * 100

    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trade_analysis = strat.analyzers.trades.get_analysis()
    trade_log = strat.analyzers.trade_log.get_analysis()

    total_trades = trade_analysis.get('total', {}).get('total', 0)
    won = trade_analysis.get('won', {}).get('total', 0)
    lost = trade_analysis.get('lost', {}).get('total', 0)
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0

    avg_duration = 0
    if trade_log:
        avg_duration = sum(t['barlen'] for t in trade_log) / len(trade_log)

    gross_profit = trade_analysis.get('won', {}).get('pnl', {}).get('total', 0)
    gross_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 1))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    max_dd = drawdown.get('max', {}).get('drawdown', 0)

    sharpe_ratio = sharpe.get('sharperatio', None)
    if sharpe_ratio is None:
        sharpe_ratio = 0.0

    avg_win = trade_analysis.get('won', {}).get('pnl', {}).get('average', 0)
    avg_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('average', 1))
    risk_reward = avg_win / avg_loss if avg_loss > 0 else 0

    return {
        'name': name,
        'final_value': final_value,
        'total_return_pct': total_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown_pct': max_dd,
        'total_trades': total_trades,
        'win_rate_pct': win_rate,
        'profit_factor': profit_factor,
        'avg_trade_hours': avg_duration,
        'risk_reward': risk_reward,
        'won': won,
        'lost': lost,
    }


def load_data():
    df = pd.read_csv(DATA_FILE, index_col='Date', parse_dates=True)
    data = bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=60)
    return data


def print_results(results_list):
    print("\n" + "=" * 110)
    print("BTC/USD 1H CYCLE STRATEGY BACKTEST COMPARISON")
    print(f"Initial Capital: ${INITIAL_CASH:,.0f} | Commission: {COMMISSION*100}% | Data: ~730 days of 1H candles")
    print("=" * 110)

    header = f"{'Strategy':<40} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'WinRate':>8} {'Trades':>7} {'PF':>6} {'R:R':>6} {'AvgHrs':>7}"
    print(header)
    print("-" * 110)

    for r in results_list:
        line = (
            f"{r['name']:<40} "
            f"{r['total_return_pct']:>9.1f}% "
            f"{r['sharpe_ratio']:>8.3f} "
            f"{r['max_drawdown_pct']:>7.1f}% "
            f"{r['win_rate_pct']:>7.1f}% "
            f"{r['total_trades']:>7d} "
            f"{r['profit_factor']:>6.2f} "
            f"{r['risk_reward']:>6.2f} "
            f"{r['avg_trade_hours']:>6.1f}h"
        )
        print(line)

    print("-" * 110)

    # Filter to strategies with 50+ trades
    valid = [r for r in results_list if r['total_trades'] >= 50]
    if not valid:
        valid = results_list

    best = max(valid, key=lambda x: (
        math.log1p(max(0, x['total_return_pct'])) * 5 +
        x['sharpe_ratio'] * 30 +
        (100 - x['max_drawdown_pct']) * 0.5 +
        x['win_rate_pct'] * 0.2 +
        x['profit_factor'] * 8
    ))

    print(f"\n>>> BEST STRATEGY (min 50 trades): {best['name']}")
    print(f"    Final Portfolio: ${best['final_value']:,.2f}")
    print(f"    Total Return:    {best['total_return_pct']:.1f}%")
    print(f"    Sharpe Ratio:    {best['sharpe_ratio']:.3f}")
    print(f"    Max Drawdown:    {best['max_drawdown_pct']:.1f}%")
    print(f"    Win Rate:        {best['win_rate_pct']:.1f}% ({best['won']}W / {best['lost']}L)")
    print(f"    Profit Factor:   {best['profit_factor']:.2f}")
    print(f"    Risk:Reward:     {best['risk_reward']:.2f}")
    print(f"    Total Trades:    {best['total_trades']}")
    print(f"    Avg Hold:        {best['avg_trade_hours']:.1f} hours")
    print("=" * 110)

    return best


def main():
    strategies = [
        (Keltner1H, "V23: Keltner Micro-Breakout 1H"),
        (RSI1HScalper, "V24: RSI(3) Snap-Back 1H"),
        (EMAPullback1H, "V25: EMA Pullback + RSI 1H"),
        (BBSqueeze1H, "V26: BB Squeeze Breakout 1H"),
        (InsideKeltner1H, "V27: Inside Bar + Keltner 1H"),
        (KeltnerTrendRider1H, "V28: Keltner Trend-Rider 1H"),
        (MultiEMAMomentum1H, "V29: Multi-EMA Momentum 1H"),
        (KeltnerStoch1H, "V30: Keltner Wide + Stoch 1H"),
        (DualKeltnerVol1H, "V31: Dual Keltner + Vol 1H"),
        (MomentumATR1H, "V32: Momentum + ATR Filter 1H"),
        (TrendPullback1H, "V33: Trend Pullback 1H"),
        (KeltnerPullback1H, "V34: Keltner Pullback to Mid 1H"),
        (PureTrendFollower1H, "V35: Pure Trend Follower 1H"),
        (KeltnerWideTrend1H, "V36: Keltner Wide Trend 1H"),
        (HybridKeltnerSwing1H, "V37: Hybrid Keltner Swing 1H"),
        (SwingRider1H, "V38: Swing Rider 1H"),
        (EMACrossSwing1H, "V39: EMA Cross Swing 1H"),
        (KeltnerNoMidExit1H, "V40: Keltner No Mid-Exit 1H"),
        (KeltnerWideSwing1H, "V41: Keltner Wide Swing 1H"),
        (EMACrossRSI1H, "V42: EMA Cross + RSI 1H"),
        (UltraWideMomentum1H, "V43: Ultra-Wide Momentum 1H"),
        (UltraWideMomentumV2_1H, "V44: Ultra-Wide + Keltner 1H"),
        (UltraWideMomentumV3_1H, "V45: Ultra-Wide + Profit Lock 1H"),
        (UltraWideDualSlope1H, "V46: Ultra-Wide Dual Slope 1H"),
        (UltraWideMomentumV4_1H, "V47: Ultra-Wide Fast EMA 1H"),
        (UltraWideMomentumV5_1H, "V48: Ultra-Wide 5x ATR 1H"),
        (UltraWideMomentumADX_1H, "V49: Ultra-Wide + ADX 1H"),
        (UltraWideADXv2_1H, "V50: Ultra-Wide ADX>15 1H"),
        (UltraWideADXv3_1H, "V51: Ultra-Wide ADX Rising 1H"),
        (UltraWideADXv4_1H, "V52: Ultra-Wide ADX>25 1H"),
        (VolumePriceTrend1H, "V53: Volume-Price Trend 1H"),
        (VolumeTrend1H, "V54: Volume Trend 1H"),
        (VWAPTrend1H, "V55: VWAP Trend 1H"),
        (MACDMomentum1H, "V56: MACD Momentum 1H"),
        (SupertrendMomentum1H, "V57: Supertrend + ADX 1H"),
        (CCIMomentum1H, "V58: CCI Momentum 1H"),
        (DonchianBreakout1H, "V59: Donchian Breakout 1H"),
        (ParabolicSARMomentum1H, "V60: Parabolic SAR 1H"),
        (AroonMomentum1H, "V61: Aroon Momentum 1H"),
        (UltimateHybrid1H, "V62: Ultimate Hybrid 1H"),
        (IchimokuTrend1H, "V63: Ichimoku Cloud Trend 1H"),
        (ROCMomentum1H, "V64: ROC Momentum 1H"),
        (ChaikinVolMomentum1H, "V65: Chaikin Vol Momentum 1H"),
        (VWAPTrendV2_1H, "V66: VWAP Short VWMA+LowADX 1H"),
        (VWAPTrendV3_1H, "V67: VWAP Long VWMA+7xATR 1H"),
        (VWAPTrendV4_1H, "V68: VWAP + ADX Rising 1H"),
        (VWAPChaikin1H, "V69: VWAP + Chaikin Hybrid 1H"),
        (VWAPTrendV5_1H, "V70: VWAP Cooldown-4 1H"),
        (ChaikinVolV2_1H, "V71: Chaikin Vol v2 1H"),
        (VWAPSupertrend1H, "V72: VWAP + Supertrend 1H"),
    ]

    all_results = []

    for strat_class, name in strategies:
        print(f"\nRunning: {name}...")
        data = load_data()
        try:
            result = run_backtest(strat_class, name, data)
            all_results.append(result)
            print(f"  -> Return: {result['total_return_pct']:.1f}% | "
                  f"Sharpe: {result['sharpe_ratio']:.3f} | "
                  f"Trades: {result['total_trades']} | "
                  f"Avg: {result['avg_trade_hours']:.1f}h")
        except Exception as e:
            print(f"  -> ERROR: {e}")
            import traceback
            traceback.print_exc()

    if all_results:
        best = print_results(all_results)
        return best

    return None


if __name__ == "__main__":
    main()
