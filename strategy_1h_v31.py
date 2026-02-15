"""
V31: 1H Dual Keltner + Vol Filter (V7 logic on 1H)
-----------------------------------------------------
Proven V7 logic (vol regime filter) adapted for 1H with Keltner entry.
Uses dual timeframe concept: wider Keltner for trend, narrow for entry.

Long only.
"""
import backtrader as bt


class DualKeltnerVol1H(bt.Strategy):
    params = (
        ('kc_fast_period', 10),
        ('kc_fast_mult', 1.5),
        ('kc_slow_period', 30),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('vol_lookback', 48),     # 48 hours = 2 days
        ('vol_threshold', 1.4),
        ('max_hold_bars', 48),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_fast_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_fast_period)
        self.kc_slow_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def is_high_vol(self):
        if self.atr_sma[0] > 0:
            return self.atr[0] / self.atr_sma[0] > self.p.vol_threshold
        return False

    def next(self):
        if self.order:
            return

        kc_fast_upper = self.kc_fast_mid[0] + self.atr[0] * self.p.kc_fast_mult
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # Price above fast Keltner + slow Keltner mid trending up +
            # trend filter + RSI + not high vol + not in cooldown
            if (not in_cooldown and
                    not self.is_high_vol() and
                    self.data.close[0] > kc_fast_upper and
                    self.kc_slow_mid[0] > self.trend_ema[0] and
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

            mult = self.p.atr_stop_mult * 0.75 if self.is_high_vol() else self.p.atr_stop_mult
            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            if self.data.close[0] < self.kc_fast_mid[0]:
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
