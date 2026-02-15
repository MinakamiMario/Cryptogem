"""
V15: Keltner Cycle + Volatility Regime (Best of V7 + V12)
-----------------------------------------------------------
Merges the two best approaches:
- V12's Keltner channel breakout (73 trades, 9490% return)
- V7's volatility regime filter (24.5% max DD)

Rules:
- Entry: Keltner breakout + RSI > 50 + trend + NOT high volatility regime
- Exit: Price drops below mid-channel OR trailing stop
- Vol regime: Skip entries when ATR is spiking (crash detection)
- Cooldown after stop-outs
"""
import backtrader as bt


class KeltnerVolRegime(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 1.5),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('vol_lookback', 30),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 5),
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
        self.bars_since_stop = 999
        self.was_stopped = False

    def kc_upper(self):
        return self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult

    def is_high_vol(self):
        if self.atr_sma[0] > 0:
            return self.atr[0] / self.atr_sma[0] > self.p.vol_threshold
        return False

    def next(self):
        if self.order:
            return

        if self.was_stopped:
            self.bars_since_stop += 1

        in_cooldown = self.was_stopped and self.bars_since_stop < self.p.cooldown_bars

        if not self.position:
            if (self.data.close[0] > self.kc_upper() and
                    self.rsi[0] > self.p.rsi_min and
                    self.kc_mid[0] > self.trend_ema[0] and
                    not self.is_high_vol() and
                    not in_cooldown):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
                self.was_stopped = False
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            # Adaptive stop: tighter in high vol
            mult = self.p.atr_stop_mult * 0.75 if self.is_high_vol() else self.p.atr_stop_mult
            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            if self.data.close[0] < self.kc_mid[0]:
                self.order = self.sell(size=self.position.size)
                self.was_stopped = False
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.was_stopped = True
                self.bars_since_stop = 0

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
