"""
Backtest Runner - Compare all BTC/USD 1D cycle strategy versions.
"""
import backtrader as bt
import pandas as pd
import os
import sys
from datetime import datetime

from strategy_v1 import CycleMACrossover
from strategy_v2 import CycleMeanReversion
from strategy_v3 import CycleDPOStochastic
from strategy_v4 import AdaptiveCycleComposite
from strategy_v5 import CycleEMAWithATRStop
from strategy_v6 import CycleEMARSIMomentum
from strategy_v7 import MultiCycleVolRegime
from strategy_v8 import UltimateCycleRider
from strategy_v9 import ShortCycleRSI
from strategy_v10 import StochCycleSwing
from strategy_v11 import EMAPullbackCycle
from strategy_v12 import KeltnerCycleBreakout
from strategy_v13 import KeltnerOptimizedStops
from strategy_v14 import KeltnerRSIMomentum
from strategy_v15 import KeltnerVolRegime
from strategy_v16 import RSISnapBack
from strategy_v17 import InsideBarBreakout
from strategy_v18 import ThreeBarMomentum
from strategy_v19 import WilliamsRScalper
from strategy_v20 import InsideBarRSI
from strategy_v21 import KeltnerMicroBreakout
from strategy_v22 import ComboShortTerm

INITIAL_CASH = 10000.0
COMMISSION = 0.001  # 0.1% per trade (typical exchange fee)
DATA_FILE = os.path.join(os.path.dirname(__file__), 'btc_usd_1d.csv')


class TradeLogger(bt.Analyzer):
    """Track all trades for analysis."""

    def __init__(self):
        self.trades = []
        self.current_trade = None

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
    """Run a single backtest and return results."""
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    # Analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(TradeLogger, _name='trade_log')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value - INITIAL_CASH) / INITIAL_CASH * 100

    # Extract analyzer results
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trade_analysis = strat.analyzers.trades.get_analysis()
    trade_log = strat.analyzers.trade_log.get_analysis()

    # Calculate win rate
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    won = trade_analysis.get('won', {}).get('total', 0)
    lost = trade_analysis.get('lost', {}).get('total', 0)
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0

    # Average trade duration
    avg_duration = 0
    if trade_log:
        avg_duration = sum(t['barlen'] for t in trade_log) / len(trade_log)

    # Profit factor
    gross_profit = trade_analysis.get('won', {}).get('pnl', {}).get('total', 0)
    gross_loss = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 1))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    # Max drawdown
    max_dd = drawdown.get('max', {}).get('drawdown', 0)

    # Sharpe ratio
    sharpe_ratio = sharpe.get('sharperatio', None)
    if sharpe_ratio is None:
        sharpe_ratio = 0.0

    # Average win / average loss
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
        'avg_trade_days': avg_duration,
        'risk_reward': risk_reward,
        'won': won,
        'lost': lost,
    }


def load_data():
    """Load BTC/USD data as backtrader feed."""
    df = pd.read_csv(DATA_FILE, index_col='Date', parse_dates=True)
    data = bt.feeds.PandasData(dataname=df)
    return data


def print_results(results_list):
    """Pretty-print comparison table."""
    print("\n" + "=" * 100)
    print("BTC/USD 1D CYCLE STRATEGY BACKTEST COMPARISON")
    print(f"Initial Capital: ${INITIAL_CASH:,.0f} | Commission: {COMMISSION*100}% per trade")
    print("=" * 100)

    header = f"{'Strategy':<45} {'Return':>10} {'Sharpe':>8} {'MaxDD':>8} {'WinRate':>8} {'Trades':>7} {'PF':>6} {'R:R':>6} {'AvgDays':>8}"
    print(header)
    print("-" * 100)

    for r in results_list:
        line = (
            f"{r['name']:<45} "
            f"{r['total_return_pct']:>9.1f}% "
            f"{r['sharpe_ratio']:>8.3f} "
            f"{r['max_drawdown_pct']:>7.1f}% "
            f"{r['win_rate_pct']:>7.1f}% "
            f"{r['total_trades']:>7d} "
            f"{r['profit_factor']:>6.2f} "
            f"{r['risk_reward']:>6.2f} "
            f"{r['avg_trade_days']:>7.1f}"
        )
        print(line)

    print("-" * 100)

    # Find best strategy (risk-adjusted scoring)
    # Normalize returns to log scale so 9000% doesn't dominate
    import math
    best = max(results_list, key=lambda x: (
        math.log1p(max(0, x['total_return_pct'])) * 5 +  # Log return
        x['sharpe_ratio'] * 30 +                           # Sharpe heavily weighted
        (100 - x['max_drawdown_pct']) * 0.5 +             # Lower DD = better
        x['win_rate_pct'] * 0.2 +                          # Win rate
        x['profit_factor'] * 8                             # Profit factor
    ))

    print(f"\n>>> BEST STRATEGY: {best['name']}")
    print(f"    Final Portfolio: ${best['final_value']:,.2f}")
    print(f"    Total Return:    {best['total_return_pct']:.1f}%")
    print(f"    Sharpe Ratio:    {best['sharpe_ratio']:.3f}")
    print(f"    Max Drawdown:    {best['max_drawdown_pct']:.1f}%")
    print(f"    Win Rate:        {best['win_rate_pct']:.1f}% ({best['won']}W / {best['lost']}L)")
    print(f"    Profit Factor:   {best['profit_factor']:.2f}")
    print(f"    Risk:Reward:     {best['risk_reward']:.2f}")
    print(f"    Avg Trade Len:   {best['avg_trade_days']:.0f} days")
    print("=" * 100)

    return best


def main():
    strategies = [
        (CycleMACrossover, "V1: Dual EMA Crossover Cycle"),
        (CycleMeanReversion, "V2: RSI + BB Mean Reversion"),
        (CycleDPOStochastic, "V3: DPO + Stochastic Cycle"),
        (AdaptiveCycleComposite, "V4: Composite Adaptive Cycle"),
        (CycleEMAWithATRStop, "V5: EMA + ATR Trailing Stop"),
        (CycleEMARSIMomentum, "V6: EMA + RSI Momentum"),
        (MultiCycleVolRegime, "V7: Multi-Cycle Vol Regime"),
        (UltimateCycleRider, "V8: Ultimate Cycle Rider"),
        (ShortCycleRSI, "V9: Short-Cycle RSI Mean Rev"),
        (StochCycleSwing, "V10: Stoch Cycle Swing"),
        (EMAPullbackCycle, "V11: EMA Pullback Cycle"),
        (KeltnerCycleBreakout, "V12: Keltner Channel Breakout"),
        (KeltnerOptimizedStops, "V13: Keltner Optimized Stops"),
        (KeltnerRSIMomentum, "V14: Keltner + RSI Momentum"),
        (KeltnerVolRegime, "V15: Keltner + Vol Regime"),
        (RSISnapBack, "V16: RSI(2) Snap-Back"),
        (InsideBarBreakout, "V17: Inside Bar Breakout"),
        (ThreeBarMomentum, "V18: 3-Bar Momentum Burst"),
        (WilliamsRScalper, "V19: Williams %R Scalper"),
        (InsideBarRSI, "V20: Inside Bar + RSI Filter"),
        (KeltnerMicroBreakout, "V21: Keltner Micro-Breakout"),
        (ComboShortTerm, "V22: Combo Short-Term"),
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
                  f"Trades: {result['total_trades']}")
        except Exception as e:
            print(f"  -> ERROR: {e}")

    if all_results:
        best = print_results(all_results)
        return best

    return None


if __name__ == "__main__":
    best = main()
