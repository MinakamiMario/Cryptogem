"""
Paper Trade Simulator - Simuleert de afgelopen maand trade-by-trade
Start: €1000
Draait op volledige data (indicators nodig), maar tracked alleen trades in de paper period.
Reset portfolio naar €1000 bij start van paper period.
"""
import backtrader as bt
import pandas as pd
import os
from datetime import datetime

from strategy_1h_v55 import VWAPTrend1H
from strategy_1h_v69 import VWAPChaikin1H

INITIAL_CASH = 10000.0  # Need enough for full backtest
PAPER_CASH = 1000.0     # Paper trade starting capital
COMMISSION = 0.001
DATA_FILE = os.path.join(os.path.dirname(__file__), 'btc_usd_1h.csv')

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


def run_paper_trade(strategy_class, name):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_class)

    df = pd.read_csv(DATA_FILE, index_col='Date', parse_dates=True)
    data = bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=60)
    cerebro.adddata(data)

    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.addanalyzer(DetailedTradeLogger, _name='trade_log')

    results = cerebro.run()
    strat = results[0]

    trade_log = strat.analyzers.trade_log.get_analysis()

    # Filter trades within paper trade period
    paper_trades = [t for t in trade_log if t['entry_date'] >= START_DATE]

    return paper_trades


def simulate_paper_trades(trades, start_capital):
    """Re-simulate trades with fixed starting capital."""
    capital = start_capital
    results = []

    for t in trades:
        # Size we can buy with current capital (95% position)
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


def print_paper_trades(name, trades, start_capital, end_capital):
    print(f"\n{'='*95}")
    print(f"  PAPER TRADE SIMULATIE: {name}")
    print(f"  Periode: 12 feb 2025 - 12 feb 2026 (1 jaar)")
    print(f"  Startkapitaal: €{start_capital:,.2f}")
    print(f"{'='*95}")

    if not trades:
        print(f"\n  Geen trades in deze periode.")
        print(f"  Portfolio waarde: €{end_capital:,.2f}")
        print(f"{'='*95}\n")
        return

    print(f"\n  {'#':>3}  {'Entry':<20} {'Prijs':>10}  {'Exit':<20} {'Prijs':>10}  {'P&L':>10} {'%':>7} {'Uren':>5}  {'Saldo':>10}")
    print(f"  {'-'*98}")

    wins = 0
    losses = 0
    max_win = 0
    max_loss = 0

    for i, t in enumerate(trades, 1):
        entry_dt = t['entry_date'].strftime('%d-%b-%y %H:%M')
        exit_dt = t['exit_date'].strftime('%d-%b-%y %H:%M')
        hours = t['bars']
        pnl = t['pnl']

        if pnl > 0:
            wins += 1
            result = "WIN"
            if pnl > max_win:
                max_win = pnl
        else:
            losses += 1
            result = "LOSS"
            if pnl < max_loss:
                max_loss = pnl

        print(f"  {i:>3}  {entry_dt:<20} ${t['entry_price']:>9,.0f}  {exit_dt:<20} ${t['exit_price']:>9,.0f}  "
              f"€{pnl:>+9.2f} {t['pnl_pct']:>+6.1f}% {hours:>4}h  €{t['capital_after']:>9.2f}  {result}")

    total_pnl = end_capital - start_capital
    total_pnl_pct = (total_pnl / start_capital) * 100
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    print(f"  {'-'*92}")
    print(f"\n  RESULTAAT:")
    print(f"  {'Startkapitaal:':<25} €{start_capital:,.2f}")
    print(f"  {'Eindkapitaal:':<25} €{end_capital:,.2f}")
    print(f"  {'Totaal P&L:':<25} €{total_pnl:>+,.2f} ({total_pnl_pct:>+.1f}%)")
    print(f"  {'Aantal trades:':<25} {total_trades}")
    print(f"  {'Gewonnen:':<25} {wins} ({win_rate:.0f}%)")
    print(f"  {'Verloren:':<25} {losses}")
    if max_win > 0:
        print(f"  {'Beste trade:':<25} €{max_win:>+,.2f}")
    if max_loss < 0:
        print(f"  {'Slechtste trade:':<25} €{max_loss:>+,.2f}")
    print(f"{'='*95}\n")


def main():
    print("\n" + "="*95)
    print("  BTC/USD 1H PAPER TRADE SIMULATIE")
    print("  Periode: 12 februari 2025 - 12 februari 2026 (1 jaar)")
    print("  Startkapitaal: €1.000")
    print("  Commissie: 0.1% per trade")
    print("="*95)

    # BTC price context
    df = pd.read_csv(DATA_FILE, index_col='Date', parse_dates=True)
    mask = (df.index >= START_DATE) & (df.index <= END_DATE)
    period_df = df[mask]
    btc_start = period_df.iloc[0]['Close']
    btc_end = period_df.iloc[-1]['Close']
    btc_change = (btc_end - btc_start) / btc_start * 100
    print(f"\n  BTC in deze periode: ${btc_start:,.0f} → ${btc_end:,.0f} ({btc_change:>+.1f}%)")
    if btc_change < 0:
        print(f"  (Als je BTC had gekocht en vastgehouden: €{1000 * btc_change/100:,.2f} verlies)")

    # Run V55
    print("\n  >>> V55 laden...")
    raw_trades55 = run_paper_trade(VWAPTrend1H, "V55")
    trades55, end55 = simulate_paper_trades(raw_trades55, PAPER_CASH)
    print_paper_trades("V55: VWAP Trend (Hoogste Rendement)", trades55, PAPER_CASH, end55)

    # Run V69
    print("  >>> V69 laden...")
    raw_trades69 = run_paper_trade(VWAPChaikin1H, "V69")
    trades69, end69 = simulate_paper_trades(raw_trades69, PAPER_CASH)
    print_paper_trades("V69: VWAP + Chaikin (Veiligste)", trades69, PAPER_CASH, end69)

    # Final comparison
    pnl55 = end55 - PAPER_CASH
    pnl69 = end69 - PAPER_CASH
    bh_pnl = PAPER_CASH * btc_change / 100

    print("="*95)
    print("  VERGELIJKING - WAT HAD JE VERDIEND/VERLOREN?")
    print("="*95)
    print(f"  {'Methode':<35} {'Start':>10} {'Eind':>10} {'P&L':>12} {'Return':>8}")
    print(f"  {'-'*75}")
    print(f"  {'V55: VWAP Trend':<35} €{PAPER_CASH:>9,.2f} €{end55:>9,.2f} €{pnl55:>+10,.2f} {pnl55/PAPER_CASH*100:>+6.1f}%")
    print(f"  {'V69: VWAP + Chaikin':<35} €{PAPER_CASH:>9,.2f} €{end69:>9,.2f} €{pnl69:>+10,.2f} {pnl69/PAPER_CASH*100:>+6.1f}%")
    print(f"  {'Buy & Hold BTC':<35} €{PAPER_CASH:>9,.2f} €{PAPER_CASH+bh_pnl:>9,.2f} €{bh_pnl:>+10,.2f} {btc_change:>+6.1f}%")
    print(f"  {'-'*75}")
    print(f"{'='*95}\n")


if __name__ == "__main__":
    main()
