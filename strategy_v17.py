"""
V17: Inside Bar Momentum Breakout
----------------------------------
Target: 150+ trades, 1-3 day holds.

Concept: An inside bar (today's range fits within yesterday's range)
signals compression. Break above = momentum burst up.
Very short holding: exit after 1-3 days or on weakness.

No short selling - long only.
"""
import backtrader as bt


class InsideBarBreakout(bt.Strategy):
    params = (
        ('ema_period', 21),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('atr_target_mult', 2.0),
        ('max_hold_days', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.target_price = 0

    def is_inside_bar(self):
        """Current bar's range is within previous bar's range."""
        if len(self.data) < 2:
            return False
        return (self.data.high[0] <= self.data.high[-1] and
                self.data.low[0] >= self.data.low[-1])

    def next(self):
        if self.order:
            return

        if not self.position:
            # Look for inside bar that breaks out upward in an uptrend
            if len(self.data) < 3:
                return

            # Yesterday was inside bar, today breaks above yesterday's high
            prev_inside = (self.data.high[-1] <= self.data.high[-2] and
                           self.data.low[-1] >= self.data.low[-2])

            if (prev_inside and
                    self.data.close[0] > self.data.high[-1] and
                    self.data.close[0] > self.ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.low[-1]  # Stop below inside bar low
                self.target_price = self.data.close[0] + self.atr[0] * self.p.atr_target_mult
        else:
            bars_held = len(self) - self.entry_bar

            # Exit: target hit, max hold, or stop
            if self.data.close[0] >= self.target_price:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
