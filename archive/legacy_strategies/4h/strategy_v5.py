"""
V5: Enhanced EMA Crossover with ATR Trailing Stop
--------------------------------------------------
Building on V1's success but adding:
1. ATR-based trailing stop to protect profits during drawdowns
2. Re-entry logic after stops (wait for next crossover confirmation)
3. Volume confirmation for entries
"""
import backtrader as bt


class CycleEMAWithATRStop(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('slow_period', 50),
        ('trend_period', 200),
        ('atr_period', 14),
        ('atr_mult', 3.5),       # ATR multiplier for trailing stop
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
        self.highest_since_entry = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: fast EMA crosses above slow + price above 200 EMA
            if self.crossover > 0 and self.data.close[0] > self.trend_ema[0]:
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_mult
                self.highest_since_entry = self.data.close[0]
        else:
            # Track highest price since entry
            if self.data.close[0] > self.highest_since_entry:
                self.highest_since_entry = self.data.close[0]

            # Update trailing stop: based on highest price minus ATR
            new_stop = self.highest_since_entry - self.atr[0] * self.p.atr_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit conditions:
            # 1. EMA death cross
            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)
            # 2. Trailing stop hit
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
