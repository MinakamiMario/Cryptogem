"""
V35: 1H Pure Trend Follower (EMA Cross + Wide Stops)
------------------------------------------------------
Root cause analysis: win rates are low because stops are too tight
for 1H BTC volatility. BTC can swing 2-3% in an hour easily.

Fix: Use the V1 EMA crossover logic (proven on 1D) but on 1H
with parameters scaled up:
- EMA 50/100 crossover (not 21/50 - too noisy on 1H)
- EMA 200 trend filter
- ATR stop 4x (very wide - let trades breathe)
- Hold until death cross (no max hold)

This is essentially swing trading on 1H candles.

Long only.
"""
import backtrader as bt


class PureTrendFollower1H(bt.Strategy):
    params = (
        ('fast_period', 50),
        ('slow_period', 100),
        ('trend_period', 200),
        ('atr_period', 14),
        ('atr_stop_mult', 4.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            if (self.crossover > 0 and
                    self.data.close[0] > self.trend_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit: death cross or trailing stop
            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
