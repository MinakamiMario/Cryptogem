"""
V13: Keltner Cycle Breakout - Optimized Stops
----------------------------------------------
Based on V12 (73 trades, 9490% return, Sharpe 1.069) but with:
1. Tighter ATR trailing stop (1.5x instead of 2x) to reduce 42.8% max DD
2. Faster exit when price returns to mid-channel
3. Slightly wider channel (1.8 ATR) for fewer false breakouts
"""
import backtrader as bt


class KeltnerOptimizedStops(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 1.8),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def kc_upper(self):
        return self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult

    def next(self):
        if self.order:
            return

        if not self.position:
            if (self.data.close[0] > self.kc_upper() and
                    self.rsi[0] > self.p.rsi_min and
                    self.kc_mid[0] > self.trend_ema[0]):
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

            if self.data.close[0] < self.kc_mid[0]:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
