"""
V10: Stochastic Cycle Swing Trader
-----------------------------------
Target: 80+ trades.

Concept: Use Stochastic %K/%D crossovers in oversold/overbought zones
to catch short swing cycles. Faster signals than RSI.

Rules:
- Buy: Stoch %K crosses above %D while both < 20 AND close > EMA(50)
- Sell: Stoch %K crosses below %D while both > 80 OR trailing stop
- Short holding period (3-15 days per cycle)
"""
import backtrader as bt


class StochCycleSwing(bt.Strategy):
    params = (
        ('stoch_period', 14),
        ('stoch_k', 3),
        ('stoch_d', 3),
        ('oversold', 20),
        ('overbought', 80),
        ('trend_period', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.stoch = bt.indicators.Stochastic(
            self.data,
            period=self.p.stoch_period,
            period_dfast=self.p.stoch_k,
            period_dslow=self.p.stoch_d,
        )
        self.stoch_cross = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: %K crosses above %D in oversold zone + uptrend
            if (self.stoch_cross > 0 and
                    self.stoch.percK[0] < self.p.oversold and
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

            # Sell: overbought crossover or stop
            if (self.stoch_cross < 0 and
                    self.stoch.percK[0] > self.p.overbought):
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
