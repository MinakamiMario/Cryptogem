"""
V29: 1H Multi-EMA Momentum Breakout
--------------------------------------
Clean momentum strategy: buy when price breaks above all EMAs
with confirmed momentum. Hold 6-48 hours.

Uses 3 EMAs (9, 21, 50) all aligned = strong trend.
RSI between 55-75 = confirmed momentum without being overbought.

Long only.
"""
import backtrader as bt


class MultiEMAMomentum1H(bt.Strategy):
    params = (
        ('fast_ema', 9),
        ('mid_ema', 21),
        ('slow_ema', 50),
        ('rsi_period', 14),
        ('rsi_min', 55),
        ('rsi_max', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('max_hold_bars', 48),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.mid = bt.indicators.EMA(self.data.close, period=self.p.mid_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.p.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        # Detect fast EMA crossing above mid EMA
        self.fast_cross_mid = bt.indicators.CrossOver(self.fast, self.mid)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        # All EMAs aligned: fast > mid > slow
        emas_aligned = (self.fast[0] > self.mid[0] > self.slow[0])

        if not self.position:
            # Buy: fast crosses above mid + all aligned + RSI sweet spot
            if (not in_cooldown and
                    self.fast_cross_mid > 0 and
                    emas_aligned and
                    self.data.close[0] > self.slow[0] and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            bars_held = len(self) - self.entry_bar
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit: price drops below mid EMA, max hold, or stop
            if self.data.close[0] < self.mid[0]:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif bars_held >= self.p.max_hold_bars:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
