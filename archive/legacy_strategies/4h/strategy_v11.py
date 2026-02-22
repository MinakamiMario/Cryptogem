"""
V11: EMA Pullback Cycle Trader
-------------------------------
Target: 80+ trades.

Concept: In an uptrend, buy pullbacks to fast EMA support.
This catches every mini-cycle dip within the broader trend.

Rules:
- Uptrend: EMA(21) > EMA(50), close > EMA(50)
- Buy: Price pulls back and touches/crosses below EMA(21) then closes above it
  (using close vs EMA21 cross up as signal)
- Sell: Price closes below EMA(50) OR RSI > 75 OR trailing stop
- Fast exits for quick cycles
"""
import backtrader as bt


class EMAPullbackCycle(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('slow_period', 50),
        ('rsi_period', 14),
        ('rsi_exit', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        # Detect when price bounces off EMA21
        self.price_cross_fast = bt.indicators.CrossOver(self.data.close, self.fast_ema)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def next(self):
        if self.order:
            return

        # Uptrend condition
        uptrend = (self.fast_ema[0] > self.slow_ema[0] and
                   self.data.close[0] > self.slow_ema[0])

        if not self.position:
            # Buy: price crosses back above EMA21 (pullback bounce) in uptrend
            if uptrend and self.price_cross_fast > 0:
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

            # Sell conditions
            if self.data.close[0] < self.slow_ema[0]:
                # Lost the trend - exit
                self.order = self.sell(size=self.position.size)
            elif self.rsi[0] > self.p.rsi_exit:
                # Overbought - cycle top
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
