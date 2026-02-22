"""
V19: Williams %R Fast Cycle Scalper
-------------------------------------
Target: 150+ trades, 1-4 day holds.

Concept: Williams %R(5) is very fast. Buy when it spikes to
extreme oversold (-90 to -100), sell when it recovers to
overbought (-10 to 0). Very responsive to short cycles.

No short selling - long only.
"""
import backtrader as bt


class WilliamsRScalper(bt.Strategy):
    params = (
        ('wr_period', 5),
        ('wr_buy', -90),
        ('wr_sell', -20),
        ('ema_period', 21),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_days', 5),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.wr = bt.indicators.WilliamsR(self.data, period=self.p.wr_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: Williams %R at extreme oversold + near uptrend
            if (self.wr[0] < self.p.wr_buy and
                    self.data.close[0] > self.ema[0] * 0.97):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            bars_held = len(self) - self.entry_bar

            # Exit: %R recovered, max hold, or stop
            if self.wr[0] > self.p.wr_sell:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
