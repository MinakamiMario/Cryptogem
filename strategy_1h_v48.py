"""
V48: 1H Ultra-Wide Momentum v5 (V43 exact + 5x ATR stop)
-----------------------------------------------------------
Test V43 with different stop multipliers to find optimal:
V43 used 6x ATR → +31.6%
V48 tests 5x ATR → might lock in more profits

Same entry logic as V43 exactly.

Long only.
"""
import backtrader as bt


class UltraWideMomentumV5_1H(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('mid_period', 50),
        ('slow_period', 100),
        ('rsi_period', 14),
        ('rsi_min', 45),
        ('rsi_max', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 5.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 8),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.mid_ema = bt.indicators.EMA(self.data.close, period=self.p.mid_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
        self.order = None
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

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars
        ema_rising = self.fast_ema[0] > self.fast_ema[-1]
        triple_aligned = (self.fast_ema[0] > self.mid_ema[0] > self.slow_ema[0])

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    triple_aligned and
                    ema_rising and
                    self.data.close[0] > self.fast_ema[0] and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            mult = self.p.atr_stop_mult * 0.7 if self.is_high_vol() else self.p.atr_stop_mult
            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            if self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
