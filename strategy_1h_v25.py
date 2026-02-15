"""
V25: 1H EMA Pullback + RSI Momentum
-------------------------------------
Buy pullbacks to the 9 EMA in an uptrend (9 > 21 EMA).
RSI confirms momentum isn't dead. Hold 2-10 hours.

Long only.
"""
import backtrader as bt


class EMAPullback1H(bt.Strategy):
    params = (
        ('fast_ema', 9),
        ('slow_ema', 21),
        ('rsi_period', 7),
        ('rsi_min', 40),
        ('rsi_exit', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_bars', 10),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.p.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.price_cross_fast = bt.indicators.CrossOver(self.data.close, self.fast)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0

    def next(self):
        if self.order:
            return

        uptrend = self.fast[0] > self.slow[0] and self.data.close[0] > self.slow[0]

        if not self.position:
            # Price bounces off fast EMA in uptrend
            if (uptrend and
                    self.price_cross_fast > 0 and
                    self.rsi[0] > self.p.rsi_min):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            bars_held = len(self) - self.entry_bar

            if self.data.close[0] < self.slow[0]:
                self.order = self.sell(size=self.position.size)
            elif self.rsi[0] > self.p.rsi_exit:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_bars:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
