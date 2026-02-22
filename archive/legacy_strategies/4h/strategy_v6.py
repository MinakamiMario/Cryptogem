"""
V6: EMA Crossover + RSI Momentum + Weekly Trend Confirmation
-------------------------------------------------------------
Building on V1 with:
1. RSI momentum filter - only enter when RSI confirms momentum direction
2. Sell on RSI divergence (price rising, RSI falling = weakness)
3. ATR trailing stop
4. Partial profit taking at 2x ATR gain
"""
import backtrader as bt


class CycleEMARSIMomentum(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('slow_period', 50),
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_entry_min', 45),   # RSI must be above this to confirm momentum
        ('rsi_exit', 75),        # RSI above this = potential cycle top
        ('atr_period', 14),
        ('atr_stop_mult', 3.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.rsi_at_high = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: EMA crossover + trend filter + RSI momentum confirmation
            if (self.crossover > 0 and
                    self.data.close[0] > self.trend_ema[0] and
                    self.rsi[0] > self.p.rsi_entry_min):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
                self.rsi_at_high = self.rsi[0]
        else:
            # Track highest and RSI at that point
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
                self.rsi_at_high = self.rsi[0]

            # Trailing stop
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit conditions:
            sell = False

            # 1. EMA death cross
            if self.crossover < 0:
                sell = True
            # 2. Trailing stop
            elif self.data.close[0] < self.stop_price:
                sell = True
            # 3. RSI bearish divergence: price near highs but RSI declining
            elif (self.rsi[0] > self.p.rsi_exit and
                  self.data.close[0] > self.highest * 0.95 and
                  self.rsi[0] < self.rsi_at_high - 10):
                sell = True

            if sell:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
