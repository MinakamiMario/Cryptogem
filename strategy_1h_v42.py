"""
V42: 1H EMA Cross + RSI Filter (V39 improved)
------------------------------------------------
V39 was -0.1% with 97 trades - essentially break-even!
Win rate 28.9% was the weakness. Add RSI filter to cut bad entries.

Improve:
1. Keep EMA 20/50 cross entry + EMA200 trend filter (V39 base)
2. Add RSI > 55 filter (stronger momentum confirmation)
3. Add volume filter (skip high-vol crash entries)
4. Keep 5x ATR trailing stop (V39's wide stop)
5. Exit: death cross OR trailing stop only
6. Add cooldown 6 bars (reduce whipsaw)

Long only.
"""
import backtrader as bt


class EMACrossRSI1H(bt.Strategy):
    params = (
        ('fast_period', 20),
        ('slow_period', 50),
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_min', 55),
        ('atr_period', 14),
        ('atr_stop_mult', 5.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)
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

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    self.crossover > 0 and
                    self.rsi[0] > self.p.rsi_min and
                    self.data.close[0] > self.trend_ema[0]):
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

            if self.crossover < 0:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
