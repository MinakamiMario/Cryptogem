"""
V16: Ultra-Short RSI Snap-Back
-------------------------------
Target: 200+ trades, 1-3 day holds.

Concept: RSI(2) is extremely sensitive. When it drops below 10,
price almost always snaps back within 1-3 days. Sell when RSI(2)
recovers above 65 or after max 5 days.

No short selling - long only.
"""
import backtrader as bt


class RSISnapBack(bt.Strategy):
    params = (
        ('rsi_period', 2),
        ('rsi_entry', 10),
        ('rsi_exit', 65),
        ('ema_period', 20),
        ('max_hold_days', 5),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
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
            # Buy: RSI(2) extremely oversold + price near/above EMA
            if (self.rsi[0] < self.p.rsi_entry and
                    self.data.close[0] > self.ema[0] * 0.97):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            bars_held = len(self) - self.entry_bar

            # Exit: RSI recovered, max hold time, or stop loss
            if self.rsi[0] > self.p.rsi_exit:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
