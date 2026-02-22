"""
V21: Keltner Micro-Breakout (Short-Term V13)
----------------------------------------------
Target: 150+ trades, 2-5 day holds.

Take the proven Keltner concept from V13 but make it faster:
1. Shorter Keltner (10 period instead of 20)
2. Tighter channel (1.0 ATR instead of 1.8)
3. Max hold 5 days
4. Faster RSI (7 period)

No short selling - long only.
"""
import backtrader as bt


class KeltnerMicroBreakout(bt.Strategy):
    params = (
        ('kc_period', 10),
        ('kc_atr_mult', 1.0),
        ('trend_period', 21),
        ('rsi_period', 7),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_days', 5),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.entry_bar = 0
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
                    self.data.close[0] > self.trend_ema[0]):
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

            # Exit: mid-channel, max hold, or stop
            if self.data.close[0] < self.kc_mid[0]:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
