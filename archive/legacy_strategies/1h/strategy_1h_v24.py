"""
V24: 1H RSI Snap-Back Scalper
-------------------------------
RSI(3) on 1H is ultra-fast. Buy extreme oversold, sell on recovery.
Hold 1-6 hours max.

Long only.
"""
import backtrader as bt


class RSI1HScalper(bt.Strategy):
    params = (
        ('rsi_period', 3),
        ('rsi_entry', 15),
        ('rsi_exit', 60),
        ('ema_period', 20),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            if (self.rsi[0] < self.p.rsi_entry and
                    self.data.close[0] > self.ema[0] * 0.98):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            bars_held = len(self) - self.entry_bar

            if self.rsi[0] > self.p.rsi_exit:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_bars:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
