"""
V30: 1H Keltner Wide + Stochastic Confirmation
-------------------------------------------------
Wider Keltner (2.5 ATR) for only the strongest breakouts.
Stochastic %K must be rising from below 50 (momentum building).
Hold 12-72 hours.

Long only.
"""
import backtrader as bt


class KeltnerStoch1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.5),
        ('trend_period', 50),
        ('stoch_period', 14),
        ('stoch_k', 3),
        ('stoch_d', 3),
        ('stoch_min', 30),
        ('stoch_max', 80),
        ('atr_period', 14),
        ('atr_stop_mult', 3.0),
        ('max_hold_bars', 72),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period,
            period_dfast=self.p.stoch_k, period_dslow=self.p.stoch_d,
        )
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999
        self.prev_stoch = 50

    def next(self):
        if self.order:
            return

        kc_upper = self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        stoch_rising = self.stoch.percK[0] > self.prev_stoch
        self.prev_stoch = self.stoch.percK[0]

        if not self.position:
            if (not in_cooldown and
                    self.data.close[0] > kc_upper and
                    self.p.stoch_min < self.stoch.percK[0] < self.p.stoch_max and
                    stoch_rising and
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
