"""
V55: 1H VWAP Trend + ADX (Volume-Weighted Average Price)
-----------------------------------------------------------
VWAP = institutional reference price. When price > VWAP = bullish.
Since backtrader doesn't have built-in VWAP, we approximate it
using a volume-weighted moving average (VWMA).

Entry:
1. Triple EMA aligned (20>50>100) + EMA20 rising
2. Price > VWMA(20) (above volume-weighted fair value)
3. RSI 45-75
4. ADX > 20
5. Vol filter + cooldown
Exit: 6x ATR trailing stop only

Long only. No leverage.
"""
import backtrader as bt


class VWAPTrend1H(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('mid_period', 50),
        ('slow_period', 100),
        ('vwma_period', 20),
        ('rsi_period', 14),
        ('rsi_min', 45),
        ('rsi_max', 75),
        ('adx_period', 14),
        ('adx_min', 20),
        ('atr_period', 14),
        ('atr_stop_mult', 6.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 8),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.mid_ema = bt.indicators.EMA(self.data.close, period=self.p.mid_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        # VWMA approximation: SMA of (close * volume) / SMA of volume
        self.pv = self.data.close * self.data.volume
        self.pv_sma = bt.indicators.SMA(self.pv, period=self.p.vwma_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=self.p.vwma_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.adx = bt.indicators.AverageDirectionalMovementIndex(
            self.data, period=self.p.adx_period)
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

    def get_vwma(self):
        if self.vol_sma[0] > 0:
            return self.pv_sma[0] / self.vol_sma[0]
        return self.data.close[0]

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars
        ema_rising = self.fast_ema[0] > self.fast_ema[-1]
        triple_aligned = (self.fast_ema[0] > self.mid_ema[0] > self.slow_ema[0])
        vwma = self.get_vwma()
        above_vwma = self.data.close[0] > vwma

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    triple_aligned and
                    ema_rising and
                    self.data.close[0] > self.fast_ema[0] and
                    above_vwma and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max and
                    self.adx[0] > self.p.adx_min):
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
