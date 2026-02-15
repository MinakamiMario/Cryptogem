"""
V46: 1H Ultra-Wide Dual Timeframe (V43 + momentum slope)
-----------------------------------------------------------
V43 was +31.6% with 102 trades.
Add momentum slope confirmation and dual EMA speed check:

Changes from V43:
1. Check that EMA50 is also rising (not just EMA20)
   = confirms medium-term trend, not just short-term
2. RSI must be RISING (current > 2 bars ago)
3. Lower RSI range to 42-78 (slightly wider)
4. Keep 6x ATR trailing stop
5. Add partial tightening: stop becomes 4x ATR when price > EMA20 by > 1 ATR
   (price extended above support = protect gains)

Long only.
"""
import backtrader as bt


class UltraWideDualSlope1H(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('mid_period', 50),
        ('slow_period', 100),
        ('rsi_period', 14),
        ('rsi_min', 42),
        ('rsi_max', 78),
        ('atr_period', 14),
        ('atr_stop_mult', 6.0),
        ('atr_stop_extended', 4.0),
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

        # Both fast AND mid EMA rising
        fast_rising = self.fast_ema[0] > self.fast_ema[-1]
        mid_rising = self.mid_ema[0] > self.mid_ema[-1]

        # RSI rising
        rsi_rising = self.rsi[0] > self.rsi[-2]

        triple_aligned = (self.fast_ema[0] > self.mid_ema[0] > self.slow_ema[0])

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    triple_aligned and
                    fast_rising and
                    mid_rising and
                    rsi_rising and
                    self.data.close[0] > self.fast_ema[0] and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            # Extended price protection: tighten stop when far above EMA20
            price_extended = (self.data.close[0] - self.fast_ema[0]) > self.atr[0]
            if price_extended:
                mult = self.p.atr_stop_extended
            elif self.is_high_vol():
                mult = self.p.atr_stop_mult * 0.7
            else:
                mult = self.p.atr_stop_mult

            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            if self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
