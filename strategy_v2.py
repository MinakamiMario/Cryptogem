"""
V2: RSI + Bollinger Bands Mean Reversion Cycle Strategy
-------------------------------------------------------
Concept: BTC cycles exhibit mean-reverting behavior within trends.
- Buy when RSI is oversold AND price touches lower Bollinger Band (cycle low)
- Sell when RSI is overbought AND price touches upper Bollinger Band (cycle high)
- Trend filter: 100 EMA to avoid buying in downtrends
"""
import backtrader as bt


class CycleMeanReversion(bt.Strategy):
    params = (
        ('rsi_period', 14),
        ('rsi_oversold', 35),
        ('rsi_overbought', 70),
        ('bb_period', 20),
        ('bb_devs', 2.0),
        ('trend_period', 100),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_devs
        )
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            # Buy: RSI oversold + price at/below lower BB + above trend
            if (self.rsi[0] < self.p.rsi_oversold and
                    self.data.close[0] <= self.bb.lines.bot[0] and
                    self.data.close[0] > self.trend_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
        else:
            # Sell: RSI overbought + price at/above upper BB
            if (self.rsi[0] > self.p.rsi_overbought and
                    self.data.close[0] >= self.bb.lines.top[0]):
                self.order = self.sell(size=self.position.size)
            # Stop loss: price drops below trend EMA by 5%
            elif self.data.close[0] < self.trend_ema[0] * 0.95:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
