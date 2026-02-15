"""
V63: 1H Ichimoku Cloud Trend (Tenkan-Kijun Cross + Cloud)
-----------------------------------------------------------
Ichimoku Kinko Hyo - Japanese trend system:
- Tenkan-sen (conversion line): 9-period midpoint
- Kijun-sen (base line): 26-period midpoint
- Senkou Span A & B form the "cloud"
- Price above cloud = bullish

Entry:
1. Triple EMA aligned (20>50>100) + EMA20 rising
2. Close > Kijun-sen (above base line)
3. Tenkan > Kijun (conversion above base = momentum)
4. Close > Senkou Span A AND Close > Senkou Span B (above cloud)
5. RSI 45-75
6. Vol filter + cooldown
Exit: 6x ATR trailing stop only

Long only. No leverage.
"""
import backtrader as bt


class IchimokuTrend1H(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('mid_period', 50),
        ('slow_period', 100),
        ('tenkan_period', 9),
        ('kijun_period', 26),
        ('senkou_b_period', 52),
        ('rsi_period', 14),
        ('rsi_min', 45),
        ('rsi_max', 75),
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
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
        # Ichimoku components (manual calculation)
        self.tenkan_high = bt.indicators.Highest(self.data.high, period=self.p.tenkan_period)
        self.tenkan_low = bt.indicators.Lowest(self.data.low, period=self.p.tenkan_period)
        self.kijun_high = bt.indicators.Highest(self.data.high, period=self.p.kijun_period)
        self.kijun_low = bt.indicators.Lowest(self.data.low, period=self.p.kijun_period)
        self.senkou_b_high = bt.indicators.Highest(self.data.high, period=self.p.senkou_b_period)
        self.senkou_b_low = bt.indicators.Lowest(self.data.low, period=self.p.senkou_b_period)
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

        # Ichimoku lines
        tenkan = (self.tenkan_high[0] + self.tenkan_low[0]) / 2
        kijun = (self.kijun_high[0] + self.kijun_low[0]) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (self.senkou_b_high[0] + self.senkou_b_low[0]) / 2

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars
        ema_rising = self.fast_ema[0] > self.fast_ema[-1]
        triple_aligned = (self.fast_ema[0] > self.mid_ema[0] > self.slow_ema[0])

        # Ichimoku conditions
        above_cloud = self.data.close[0] > senkou_a and self.data.close[0] > senkou_b
        tenkan_above_kijun = tenkan > kijun
        above_kijun = self.data.close[0] > kijun

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    triple_aligned and
                    ema_rising and
                    above_cloud and
                    tenkan_above_kijun and
                    above_kijun and
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
