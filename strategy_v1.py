"""
V1: Dual Moving Average Cycle Strategy
---------------------------------------
Concept: Use a fast/slow EMA crossover to detect cycle transitions.
- Buy when fast EMA crosses above slow EMA (cycle bottom → upswing)
- Sell when fast EMA crosses below slow EMA (cycle top → downswing)
- Additional filter: Only buy when price is above 200 EMA (long-term trend)
"""
import backtrader as bt


class CycleMACrossover(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('slow_period', 50),
        ('trend_period', 200),
        ('risk_pct', 0.95),  # % of portfolio per trade
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: fast crosses above slow AND price above long-term trend
            if self.crossover > 0 and self.data.close[0] > self.trend_ema[0]:
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
        else:
            # Sell: fast crosses below slow
            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
