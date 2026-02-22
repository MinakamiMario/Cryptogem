"""
V12: Keltner Channel Cycle Breakout
-------------------------------------
Target: 60+ trades.

Concept: Keltner Channels (EMA + ATR bands) naturally expand/contract
with volatility cycles. Buy when price breaks above the channel after
a contraction (cycle bottom breakout), sell when it drops back in or
hits the upper extreme.

Rules:
- Buy: Close breaks above upper Keltner channel AND RSI > 50 (momentum)
       AND EMA(20) > EMA(50) (trend)
- Sell: Close drops below middle line (EMA) OR trailing stop
- Keltner uses 1.5 ATR for tighter channels = more signals
"""
import backtrader as bt


class KeltnerCycleBreakout(bt.Strategy):
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 1.5),
        ('trend_period', 50),
        ('rsi_period', 14),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def kc_upper(self):
        return self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult

    def next(self):
        if self.order:
            return

        upper = self.kc_upper()

        if not self.position:
            # Buy: breakout above upper KC + momentum + trend
            if (self.data.close[0] > upper and
                    self.rsi[0] > self.p.rsi_min and
                    self.kc_mid[0] > self.trend_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Sell: drop back below middle line or stop
            if self.data.close[0] < self.kc_mid[0]:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
