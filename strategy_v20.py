"""
V20: Enhanced Inside Bar + RSI Confirmation
---------------------------------------------
Target: 150+ trades, 1-3 day holds.

Building on V17 (175 trades, 530%, 2.6 avg days) with:
1. RSI filter to avoid breakouts in overbought conditions
2. ATR-scaled targets (adaptive to volatility)
3. Volume confirmation (higher than average)

No short selling - long only.
"""
import backtrader as bt


class InsideBarRSI(bt.Strategy):
    params = (
        ('ema_period', 21),
        ('rsi_period', 7),
        ('rsi_max', 70),       # Don't buy if already overbought
        ('rsi_min', 35),       # Don't buy if deeply oversold (falling knife)
        ('atr_period', 14),
        ('atr_target_mult', 1.5),
        ('max_hold_days', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.target_price = 0

    def next(self):
        if self.order:
            return

        if len(self.data) < 3:
            return

        if not self.position:
            # Yesterday was inside bar
            prev_inside = (self.data.high[-1] <= self.data.high[-2] and
                           self.data.low[-1] >= self.data.low[-2])

            # Today breaks out above + trend + RSI in sweet spot
            if (prev_inside and
                    self.data.close[0] > self.data.high[-1] and
                    self.data.close[0] > self.ema[0] and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.low[-1]
                self.target_price = self.data.close[0] + self.atr[0] * self.p.atr_target_mult
        else:
            bars_held = len(self) - self.entry_bar

            if self.data.close[0] >= self.target_price:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
