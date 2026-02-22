"""
Core backtest runner.
Supports single strategy backtests and paper trade simulations.
"""
import backtrader as bt
import pandas as pd
from datetime import datetime

from .analyzers import TradeLogger, DetailedTradeLogger
from .data_loader import load_data, load_df


COMMISSION = 0.001  # 0.1%
INITIAL_CASH = 10000.0


def run_backtest(strategy_class, coin='BTC', timeframe='1h', cash=INITIAL_CASH,
                 commission=COMMISSION, verbose=False):
    """
    Run a full backtest for a single strategy.

    Args:
        strategy_class: Backtrader Strategy class
        coin: 'BTC', 'ETH', 'SOL', 'BNB'
        timeframe: '1h', '1d'
        cash: Starting capital
        commission: Commission per trade (0.001 = 0.1%)
        verbose: Print progress info

    Returns:
        dict with results: trades, return_pct, sharpe, max_dd, win_rate, pf, etc.
    """
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)

    data = load_data(coin, timeframe)
    cerebro.adddata(data)

    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')
    cerebro.addanalyzer(TradeLogger, _name='trades')

    if verbose:
        print(f"  Running {strategy_class.__name__} on {coin} {timeframe}...")

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    return_pct = (final_value - cash) / cash * 100

    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    max_dd = strat.analyzers.dd.get_analysis().max.drawdown or 0

    ta = strat.analyzers.ta.get_analysis()
    total_trades = ta.total.closed if hasattr(ta, 'total') and hasattr(ta.total, 'closed') else 0
    won = ta.won.total if hasattr(ta, 'won') and hasattr(ta.won, 'total') else 0
    lost = ta.lost.total if hasattr(ta, 'lost') and hasattr(ta.lost, 'total') else 0
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0

    gross_profit = ta.won.pnl.total if hasattr(ta, 'won') and hasattr(ta.won, 'pnl') else 0
    gross_loss = abs(ta.lost.pnl.total) if hasattr(ta, 'lost') and hasattr(ta.lost, 'pnl') else 0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else 0

    return {
        'strategy': strategy_class.__name__,
        'coin': coin,
        'timeframe': timeframe,
        'final_value': final_value,
        'return_pct': return_pct,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': win_rate,
        'profit_factor': pf,
        'trades': strat.analyzers.trades.get_analysis(),
    }


def run_paper_trade(strategy_class, coin='BTC', timeframe='1h',
                    start_date=None, end_date=None, paper_cash=1000.0,
                    commission=COMMISSION):
    """
    Run a paper trade simulation over a specific period.
    Runs the full backtest (indicators need history), then filters trades
    to the paper period and re-simulates with fixed starting capital.

    Args:
        strategy_class: Backtrader Strategy class
        coin: 'BTC', 'ETH', 'SOL', 'BNB'
        timeframe: '1h', '1d'
        start_date: datetime - start of paper period
        end_date: datetime - end of paper period
        paper_cash: Starting capital for paper simulation
        commission: Commission per trade

    Returns:
        dict with paper_trades list, start_capital, end_capital, coin_change
    """
    if start_date is None:
        start_date = datetime(2025, 2, 12)
    if end_date is None:
        end_date = datetime(2026, 2, 12, 23, 59)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)

    data = load_data(coin, timeframe)
    cerebro.adddata(data)

    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=commission)
    cerebro.addanalyzer(DetailedTradeLogger, _name='trade_log')

    results = cerebro.run()
    strat = results[0]

    trade_log = strat.analyzers.trade_log.get_analysis()

    # Filter trades within paper trade period
    raw_trades = [t for t in trade_log if t['entry_date'] >= start_date]
    if end_date:
        raw_trades = [t for t in raw_trades if t['entry_date'] <= end_date]

    # Re-simulate with fixed starting capital
    paper_trades, end_capital = _simulate_paper_trades(raw_trades, paper_cash, commission)

    # Get coin price change in period
    df = load_df(coin, timeframe)
    mask = (df.index >= start_date) & (df.index <= end_date)
    period_df = df[mask]

    coin_start = period_df.iloc[0]['Close'] if len(period_df) > 0 else 0
    coin_end = period_df.iloc[-1]['Close'] if len(period_df) > 0 else 0
    coin_change = ((coin_end - coin_start) / coin_start * 100) if coin_start > 0 else 0

    return {
        'strategy': strategy_class.__name__,
        'coin': coin,
        'timeframe': timeframe,
        'start_date': start_date,
        'end_date': end_date,
        'start_capital': paper_cash,
        'end_capital': end_capital,
        'trades': paper_trades,
        'coin_start_price': coin_start,
        'coin_end_price': coin_end,
        'coin_change_pct': coin_change,
    }


def _simulate_paper_trades(trades, start_capital, commission):
    """Re-simulate trades with fixed starting capital."""
    capital = start_capital
    results = []

    for t in trades:
        size = (capital * 0.95) / t['entry_price']
        pnl_per_unit = t['exit_price'] - t['entry_price']
        raw_pnl = pnl_per_unit * size
        commission_entry = t['entry_price'] * size * commission
        commission_exit = t['exit_price'] * size * commission
        net_pnl = raw_pnl - commission_entry - commission_exit
        pnl_pct = (net_pnl / capital) * 100

        results.append({
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'entry_price': t['entry_price'],
            'exit_price': t['exit_price'],
            'size': size,
            'pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'bars': t['bars'],
            'capital_before': capital,
            'capital_after': capital + net_pnl,
        })
        capital += net_pnl

    return results, capital
