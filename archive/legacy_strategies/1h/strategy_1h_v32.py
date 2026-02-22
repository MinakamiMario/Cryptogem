"""
V32: 1H Momentum Breakout + ATR Filter
-----------------------------------------
Only trade when:
1. Price makes a strong hourly move (close > open by at least 0.5 ATR)
2. RSI confirms momentum (55-78)
3. Price above EMA50
4. Volatility is not extreme
5. Trail with 2x ATR stop

Long only.
"""
import backtrader as bt


class MomentumATR1H(bt.Strategy):
    params = (
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 55),
        ('rsi_max', 78),
        ('atr_period', 14),
        ('min_body_atr', 0.5),   # Min candle body as fraction of ATR
        ('atr_stop_mult', 2.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.5),
        ('max_hold_bars', 24),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
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

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        # Strong bullish candle: body >= min_body_atr * ATR
        body = self.data.close[0] - self.data.open[0]
        strong_candle = body > 0 and body >= self.atr[0] * self.p.min_body_atr

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    strong_candle and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max and
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

            if self.data.close[0] < self.trend_ema[0]:
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
