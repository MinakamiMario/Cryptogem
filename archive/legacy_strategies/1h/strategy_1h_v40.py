"""
V40: 1H Keltner Breakout - No Mid Exit (V30 improved)
-------------------------------------------------------
V30 was the only positive (+10.2%). Main issue: 50 trades (barely enough).
Improve by:
1. Tighter Keltner (2.0 ATR instead of 2.5) → more entries
2. Remove Stochastic filter → more entries
3. Remove mid-channel exit → let winners run longer
4. Keep vol filter + wide stop (3.0 ATR)
5. Keep RSI 50+ filter

Long only.
"""
import backtrader as bt


class KeltnerNoMidExit1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.0),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 3.0),
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

            # ONLY trailing stop - no mid-channel exit
            if self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
