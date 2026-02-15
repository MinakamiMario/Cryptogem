"""
Paper Trade Vergelijking: 1D vs 1H strategieen
Periode: 12 feb 2025 - 12 feb 2026 (1 jaar)
Startkapitaal: €1.000
"""
import backtrader as bt
import pandas as pd
import os
from datetime import datetime

from strategy_v13 import KeltnerOptimizedStops
from strategy_v21 import KeltnerMicroBreakout
from strategy_1h_v55 import VWAPTrend1H
from strategy_1h_v69 import VWAPChaikin1H

INITIAL_CASH = 10000.0
PAPER_CASH = 1000.0
COMMISSION = 0.001
DATA_FILE_1H = os.path.join(os.path.dirname(__file__), 'btc_usd_1h.csv')
DATA_FILE_1D = os.path.join(os.path.dirname(__file__), 'btc_usd_1d.csv')

START_DATE = datetime(2025, 2, 12)
END_DATE = datetime(2026, 2, 12, 23, 59)


class DetailedTradeLogger(bt.Analyzer):
    def __init__(self):
        self.trades = []
        self._entry = None

    def notify_trade(self, trade):
        if trade.isopen and self._entry is None:
            self._entry = {
                'entry_date': self.data.datetime.datetime(0),
                'entry_price': trade.price,
                'size': trade.size,
            }
        if trade.isclosed and self._entry is not None:
            entry_cost = self._entry['entry_price'] * abs(self._entry['size'])
            if entry_cost > 0:
                exit_price = self._entry['entry_price'] + (trade.pnlcomm / abs(self._entry['size']))
                pnl_pct = (trade.pnlcomm / entry_cost) * 100
            else:
                exit_price = self._entry['entry_price']
                pnl_pct = 0

            self._entry['exit_date'] = self.data.datetime.datetime(0)
            self._entry['exit_price'] = exit_price
            self._entry['pnl'] = trade.pnlcomm
            self._entry['pnl_pct'] = pnl_pct
            self._entry['bars'] = trade.barlen
            self.trades.append(self._entry)
            self._entry = None

    def get_analysis(self):
        return self.trades


def run_backtest(strategy_class, data_file, timeframe, compression):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)

    df = pd.read_csv(data_file, index_col='Date', parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    data = bt.feeds.PandasData(dataname=df, timeframe=timeframe, compression=compression)
    cerebro.adddata(data)

    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addanalyzer(DetailedTradeLogger, _name='trade_log')

    results = cerebro.run()
    strat = results[0]
    trade_log = strat.analyzers.trade_log.get_analysis()

    # Filter trades in paper period
    paper_trades = [t for t in trade_log if t['entry_date'] >= START_DATE]
    return paper_trades


def simulate_paper_trades(trades, start_capital):
    capital = start_capital
    results = []

    for t in trades:
        size = (capital * 0.95) / t['entry_price']
        pnl_per_unit = t['exit_price'] - t['entry_price']
        raw_pnl = pnl_per_unit * size
        commission_entry = t['entry_price'] * size * COMMISSION
        commission_exit = t['exit_price'] * size * COMMISSION
        net_pnl = raw_pnl - commission_entry - commission_exit
        pnl_pct = (net_pnl / capital) * 100

        results.append({
            'entry_date': t['entry_date'],
            'exit_date': t['exit_date'],
            'entry_price': t['entry_price'],
            'exit_price': t['exit_price'],
            'size_btc': size,
            'pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'bars': t['bars'],
            'capital_before': capital,
            'capital_after': capital + net_pnl,
        })
        capital += net_pnl

    return results, capital


def print_trades(name, timeframe_label, trades, start_capital, end_capital):
    print(f"\n{'='*100}")
    print(f"  {name} [{timeframe_label}]")
    print(f"  Periode: 12 feb 2025 - 12 feb 2026 | Start: €{start_capital:,.2f}")
    print(f"{'='*100}")

    if not trades:
        print(f"  Geen trades in deze periode.")
        print(f"  Portfolio: €{end_capital:,.2f}")
        print(f"{'='*100}\n")
        return

    print(f"\n  {'#':>3}  {'Entry':<20} {'Prijs':>10}  {'Exit':<20} {'Prijs':>10}  {'P&L':>10} {'%':>7} {'Duur':>8}  {'Saldo':>10}")
    print(f"  {'-'*100}")

    wins = 0
    losses = 0
    max_win = 0
    max_loss = 0
    total_bars_win = 0
    total_bars_loss = 0

    for i, t in enumerate(trades, 1):
        entry_dt = t['entry_date'].strftime('%d-%b-%y %H:%M')
        exit_dt = t['exit_date'].strftime('%d-%b-%y %H:%M')
        bars = t['bars']
        pnl = t['pnl']

        # Duration label
        if timeframe_label == '1D':
            dur_label = f"{bars}d"
        else:
            if bars >= 24:
                dur_label = f"{bars/24:.1f}d"
            else:
                dur_label = f"{bars}h"

        if pnl > 0:
            wins += 1
            total_bars_win += bars
            result = "WIN"
            if pnl > max_win:
                max_win = pnl
        else:
            losses += 1
            total_bars_loss += bars
            result = "LOSS"
            if pnl < max_loss:
                max_loss = pnl

        print(f"  {i:>3}  {entry_dt:<20} ${t['entry_price']:>9,.0f}  {exit_dt:<20} ${t['exit_price']:>9,.0f}  "
              f"€{pnl:>+9.2f} {t['pnl_pct']:>+6.1f}% {dur_label:>7}  €{t['capital_after']:>9.2f}  {result}")

    total_pnl = end_capital - start_capital
    total_pnl_pct = (total_pnl / start_capital) * 100
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    avg_win_dur = total_bars_win / wins if wins > 0 else 0
    avg_loss_dur = total_bars_loss / losses if losses > 0 else 0

    print(f"  {'-'*100}")
    print(f"\n  RESULTAAT:")
    print(f"  {'Startkapitaal:':<25} €{start_capital:,.2f}")
    print(f"  {'Eindkapitaal:':<25} €{end_capital:,.2f}")
    print(f"  {'Totaal P&L:':<25} €{total_pnl:>+,.2f} ({total_pnl_pct:>+.1f}%)")
    print(f"  {'Trades:':<25} {total_trades} ({wins}W / {losses}L)")
    print(f"  {'Win Rate:':<25} {win_rate:.0f}%")
    if max_win > 0:
        print(f"  {'Beste trade:':<25} €{max_win:>+,.2f}")
    if max_loss < 0:
        print(f"  {'Slechtste trade:':<25} €{max_loss:>+,.2f}")
    if timeframe_label == '1D':
        print(f"  {'Gem. duur win:':<25} {avg_win_dur:.0f} dagen")
        print(f"  {'Gem. duur loss:':<25} {avg_loss_dur:.0f} dagen")
    else:
        print(f"  {'Gem. duur win:':<25} {avg_win_dur:.0f}h ({avg_win_dur/24:.1f}d)")
        print(f"  {'Gem. duur loss:':<25} {avg_loss_dur:.0f}h ({avg_loss_dur/24:.1f}d)")
    print(f"{'='*100}\n")


def main():
    print("\n" + "="*100)
    print("  BTC/USD STRATEGIE VERGELIJKING: 1D vs 1H")
    print("  Periode: 12 februari 2025 - 12 februari 2026 (1 jaar)")
    print("  Startkapitaal: €1.000 | Commissie: 0.1%")
    print("="*100)

    # BTC context
    df1h = pd.read_csv(DATA_FILE_1H, index_col='Date', parse_dates=True)
    mask = (df1h.index >= START_DATE) & (df1h.index <= END_DATE)
    period = df1h[mask]
    btc_start = period.iloc[0]['Close']
    btc_end = period.iloc[-1]['Close']
    btc_change = (btc_end - btc_start) / btc_start * 100
    btc_high = period['High'].max()
    btc_low = period['Low'].min()
    print(f"\n  BTC in deze periode: ${btc_start:,.0f} → ${btc_end:,.0f} ({btc_change:>+.1f}%)")
    print(f"  BTC range: ${btc_low:,.0f} (low) - ${btc_high:,.0f} (high)")

    strategies = []

    # 1D strategies
    print("\n  >>> V13 Keltner (1D) laden...")
    raw = run_backtest(KeltnerOptimizedStops, DATA_FILE_1D, bt.TimeFrame.Days, 1)
    trades, end = simulate_paper_trades(raw, PAPER_CASH)
    strategies.append(('V13: Keltner Optimized', '1D', trades, end))
    print_trades("V13: Keltner Optimized (Beste 1D Overall)", "1D", trades, PAPER_CASH, end)

    print("  >>> V21 Keltner Micro (1D) laden...")
    raw = run_backtest(KeltnerMicroBreakout, DATA_FILE_1D, bt.TimeFrame.Days, 1)
    trades, end = simulate_paper_trades(raw, PAPER_CASH)
    strategies.append(('V21: Keltner Micro-Breakout', '1D', trades, end))
    print_trades("V21: Keltner Micro-Breakout (Beste 1D Short-Term)", "1D", trades, PAPER_CASH, end)

    # 1H strategies
    print("  >>> V55 VWAP Trend (1H) laden...")
    raw = run_backtest(VWAPTrend1H, DATA_FILE_1H, bt.TimeFrame.Minutes, 60)
    trades, end = simulate_paper_trades(raw, PAPER_CASH)
    strategies.append(('V55: VWAP Trend', '1H', trades, end))
    print_trades("V55: VWAP Trend (Beste 1H Return)", "1H", trades, PAPER_CASH, end)

    print("  >>> V69 VWAP+Chaikin (1H) laden...")
    raw = run_backtest(VWAPChaikin1H, DATA_FILE_1H, bt.TimeFrame.Minutes, 60)
    trades, end = simulate_paper_trades(raw, PAPER_CASH)
    strategies.append(('V69: VWAP + Chaikin', '1H', trades, end))
    print_trades("V69: VWAP + Chaikin (Beste 1H Veilig)", "1H", trades, PAPER_CASH, end)

    # === FINAL COMPARISON ===
    print("\n" + "="*100)
    print("  EINDVERGELIJKING - ALLE STRATEGIEEN vs BUY & HOLD")
    print("  Periode: 12 feb 2025 - 12 feb 2026 | Start: €1.000")
    print("="*100)
    print(f"\n  {'Strategie':<35} {'TF':>4} {'Eind':>10} {'P&L':>12} {'Return':>8} {'Trades':>7} {'WR':>6}")
    print(f"  {'-'*82}")

    for name, tf, trd, end_val in strategies:
        pnl = end_val - PAPER_CASH
        wins = sum(1 for t in trd if t['pnl'] > 0)
        total = len(trd)
        wr = (wins / total * 100) if total > 0 else 0
        print(f"  {name:<35} {tf:>4} €{end_val:>9,.2f} €{pnl:>+10,.2f} {pnl/PAPER_CASH*100:>+6.1f}% {total:>7} {wr:>5.0f}%")

    bh_end = PAPER_CASH * (1 + btc_change / 100)
    bh_pnl = bh_end - PAPER_CASH
    print(f"  {'Buy & Hold BTC':<35} {'--':>4} €{bh_end:>9,.2f} €{bh_pnl:>+10,.2f} {btc_change:>+6.1f}% {'--':>7} {'--':>6}")
    print(f"  {'-'*82}")

    # Winner
    best = max(strategies, key=lambda x: x[3])
    print(f"\n  WINNAAR: {best[0]} ({best[1]}) met €{best[3]:,.2f} (+€{best[3]-PAPER_CASH:,.2f})")
    print(f"  vs Buy & Hold: €{best[3] - bh_end:>+,.2f} beter")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
