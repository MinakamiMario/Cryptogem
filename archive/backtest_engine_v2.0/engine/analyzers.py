"""
Custom Backtrader analyzers for trade logging.
"""
import backtrader as bt


class TradeLogger(bt.Analyzer):
    """Logs basic trade info (PnL, duration)."""

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


class DetailedTradeLogger(bt.Analyzer):
    """Logs detailed trade info with entry/exit dates and prices."""

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
