"""
V28: 1H Keltner Trend-Rider (Strict Filters)
----------------------------------------------
Problems with V23: win rate 33.9%, too many false breakouts.

Fixes:
1. Wider Keltner channel (2.0 ATR) - fewer but higher quality breakouts
2. Longer trend EMA (50) - stronger trend confirmation
3. RSI must be rising - momentum confirmation
4. Wider trailing stop (2.5 ATR) - give trades room to breathe
5. Max hold 24 bars (24h) - proper swing trades
6. Cooldown of 3 bars after exit - avoid whipsaw re-entries

Long only.
"""
import backtrader as bt


class KeltnerTrendRider1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.0),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('max_hold_bars', 24),
        ('cooldown_bars', 3),
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
        self.last_exit_bar = -999
        self.prev_rsi = 50

    def next(self):
        if self.order:
            return

        rsi_rising = self.rsi[0] > self.prev_rsi
        self.prev_rsi = self.rsi[0]

        kc_upper = self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            if (not in_cooldown and
                    self.data.close[0] > kc_upper and
                    self.rsi[0] > self.p.rsi_min and
                    rsi_rising and
                    self.data.close[0] > self.trend_ema[0] and
                    self.kc_mid[0] > self.trend_ema[0]):
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

            if self.data.close[0] < self.kc_mid[0]:
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
