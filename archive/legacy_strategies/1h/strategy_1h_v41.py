"""
V41: 1H Keltner Wide Swing (V30 + V39 Hybrid)
-------------------------------------------------
V30 (+10.2%, 50 trades): Wide Keltner 2.5 ATR entry, Stoch confirm, mid-exit
V39 (-0.1%, 97 trades): EMA cross, 5x ATR stop, no mid-exit

Combine:
1. Keltner 2.5 ATR breakout entry (V30's strong filter)
2. RSI > 50 instead of Stochastic (simpler, more trades)
3. EMA50 trend filter (price + KC mid above EMA50)
4. Vol filter (skip crash entries)
5. Exit: ONLY trailing stop (5x ATR) - NO mid-channel exit
6. Trailing stop tightens in high vol (0.7x multiplier)
7. Cooldown 6 bars

Long only.
"""
import backtrader as bt


class KeltnerWideSwing1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.5),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 5.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
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

        kc_upper = self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    self.data.close[0] > kc_upper and
                    self.rsi[0] > self.p.rsi_min and
                    self.data.close[0] > self.trend_ema[0] and
                    self.kc_mid[0] > self.trend_ema[0]):
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

            # ONLY trailing stop - no mid-channel exit, no max hold
            if self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
