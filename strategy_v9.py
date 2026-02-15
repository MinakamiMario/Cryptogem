"""
V9: Short-Cycle RSI Mean Reversion
-----------------------------------
Target: 100+ trades for statistical significance.

Concept: BTC oscillates in short 5-15 day cycles. Buy oversold dips,
sell overbought peaks. Use short EMAs for fast trend detection.

Rules:
- Buy: RSI(7) < 30 AND close > EMA(50) (buy dip in uptrend)
- Sell: RSI(7) > 70 OR trailing stop hit
- ATR trailing stop for risk management
- No 200 EMA filter (too restrictive)
"""
import backtrader as bt


class ShortCycleRSI(bt.Strategy):
    params = (
        ('rsi_period', 7),
        ('rsi_buy', 30),
        ('rsi_sell', 70),
        ('trend_period', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            if (self.rsi[0] < self.p.rsi_buy and
                    self.data.close[0] > self.trend_ema[0]):
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

            if self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
