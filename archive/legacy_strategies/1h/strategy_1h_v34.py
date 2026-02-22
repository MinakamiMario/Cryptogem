"""
V34: 1H Keltner Trend + Pullback to Mid-Channel
--------------------------------------------------
Instead of buying breakouts above the upper Keltner, buy when:
1. Price was above the upper Keltner recently (confirmed momentum)
2. Price pulls back TO the mid-channel (EMA20) = support
3. RSI still above 40 (momentum not dead)
4. Exit when price hits upper channel again (take profit at resistance)

Higher win rate because buying at support, selling at resistance.

Long only.
"""
import backtrader as bt


class KeltnerPullback1H(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.0),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 40),
        ('lookback_bars', 12),    # Check if price was above KC upper in last N bars
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('max_hold_bars', 36),
        ('cooldown_bars', 4),
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
        self.last_exit_bar = -999

    def was_above_kc_recently(self):
        """Check if price was above upper KC in the last N bars."""
        for i in range(1, min(self.p.lookback_bars + 1, len(self.data))):
            kc_upper_hist = self.kc_mid[-i] + self.atr[-i] * self.p.kc_atr_mult
            if self.data.close[-i] > kc_upper_hist:
                return True
        return False

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars
        kc_upper = self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult

        if not self.position:
            # Buy: price pulling back to mid-channel after being above upper
            touching_mid = abs(self.data.close[0] - self.kc_mid[0]) < self.atr[0] * 0.3

            if (not in_cooldown and
                    touching_mid and
                    self.was_above_kc_recently() and
                    self.rsi[0] > self.p.rsi_min and
                    self.data.close[0] > self.trend_ema[0] and
                    self.kc_mid[0] > self.trend_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.kc_mid[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            bars_held = len(self) - self.entry_bar

            # Exit: price reaches upper KC (take profit), drops below mid, max hold, or stop
            if self.data.close[0] > kc_upper:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.kc_mid[0] - self.atr[0] * 0.5:
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
