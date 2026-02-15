"""
V38: 1H Swing Rider (Final Optimized)
---------------------------------------
Key insights from 15 rounds of 1H testing:
- Win rate is THE problem on 1H (30-42% typical)
- Mid-channel exits kill profits (winners get cut too short)
- Wider stops (3-4 ATR) are essential on 1H BTC
- Longer holds (20-80h) are more profitable
- Vol filter helps avoid crash entries
- Cooldown prevents whipsaw losses

Design:
- Entry: Keltner breakout (1.5 ATR) + RSI 50-72 + EMA50 > EMA100 + no vol spike
- Exit: ONLY trailing stop (4x ATR) or EMA death cross
  NO mid-channel exit (this was cutting winners too short!)
- Trailing stop only ratchets up, never down
- Cooldown 6 bars after stop-outs

Long only.
"""
import backtrader as bt


class SwingRider1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 1.5),
        ('fast_ema', 50),
        ('slow_ema', 100),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('rsi_max', 72),
        ('atr_period', 14),
        ('atr_stop_mult', 4.0),
        ('vol_lookback', 48),
        ('vol_threshold', 1.4),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.fast = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.p.slow_ema)
        self.ema_cross = bt.indicators.CrossOver(self.fast, self.slow)
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

        kc_upper = self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars
        trend_up = self.fast[0] > self.slow[0]

        if not self.position:
            if (not in_cooldown and
                    not self.is_high_vol() and
                    self.data.close[0] > kc_upper and
                    trend_up and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max and
                    self.data.close[0] > self.slow[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            # Adaptive stop: tighter in high vol
            mult = self.p.atr_stop_mult * 0.7 if self.is_high_vol() else self.p.atr_stop_mult
            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit ONLY on: EMA death cross or trailing stop
            # NO mid-channel exit - let winners run!
            if self.ema_cross < 0:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
