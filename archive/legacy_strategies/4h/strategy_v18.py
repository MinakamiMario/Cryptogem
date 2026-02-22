"""
V18: 3-Bar Momentum Burst
---------------------------
Target: 200+ trades, 1-2 day holds.

Concept: After 2 consecutive red days, if the 3rd day opens lower
but closes higher (hammer/reversal), buy the snap-back.
Exit next day or on any weakness. Ultra-fast cycle trading.

No short selling - long only.
"""
import backtrader as bt


class ThreeBarMomentum(bt.Strategy):
    params = (
        ('ema_period', 21),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_days', 2),
        ('min_body_pct', 0.3),  # Minimum bullish body as % of range
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0

    def next(self):
        if self.order:
            return

        if len(self.data) < 3:
            return

        if not self.position:
            # Pattern: 2 red candles followed by bullish reversal candle
            red1 = self.data.close[-2] < self.data.open[-2]
            red2 = self.data.close[-1] < self.data.open[-1]

            # Today: bullish candle (close > open) with decent body
            today_range = self.data.high[0] - self.data.low[0]
            today_body = self.data.close[0] - self.data.open[0]
            bullish_today = (today_body > 0 and
                             today_range > 0 and
                             today_body / today_range > self.p.min_body_pct)

            # Must be in general uptrend area
            near_ema = self.data.close[0] > self.ema[0] * 0.95

            if red1 and red2 and bullish_today and near_ema:
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.data.low[0] - self.atr[0] * 0.5
        else:
            bars_held = len(self) - self.entry_bar

            # Quick exit: max hold or stop
            if bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
