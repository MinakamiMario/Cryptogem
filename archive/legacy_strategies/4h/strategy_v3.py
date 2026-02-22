"""
V3: Detrended Price Oscillator + Stochastic Cycle Strategy
----------------------------------------------------------
Concept: Use DPO to identify price cycles independent of trend,
combined with Stochastic for timing entries within cycles.
- DPO removes trend to reveal underlying cycles
- Stochastic identifies overbought/oversold within the cycle
- EMA trend filter for direction bias
"""
import backtrader as bt


class DetrendedPriceOscillator(bt.Indicator):
    """Custom DPO indicator - measures price deviation from its moving average."""
    lines = ('dpo',)
    params = (('period', 21),)

    def __init__(self):
        # DPO = Close - SMA(period) shifted back by (period/2 + 1)
        # Simplified: we compare current close to SMA offset
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

    def next(self):
        shift = self.p.period // 2 + 1
        if len(self.data) > shift:
            self.lines.dpo[0] = self.data[0] - self.sma[-shift]
        else:
            self.lines.dpo[0] = 0.0


class CycleDPOStochastic(bt.Strategy):
    params = (
        ('dpo_period', 21),
        ('stoch_period', 14),
        ('stoch_smooth_k', 3),
        ('stoch_smooth_d', 3),
        ('stoch_oversold', 20),
        ('stoch_overbought', 80),
        ('trend_period', 100),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.dpo = DetrendedPriceOscillator(self.data.close, period=self.p.dpo_period)
        self.stoch = bt.indicators.Stochastic(
            self.data,
            period=self.p.stoch_period,
            period_dfast=self.p.stoch_smooth_k,
            period_dslow=self.p.stoch_smooth_d,
        )
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.order = None
        self.prev_dpo = 0.0

    def next(self):
        if self.order:
            return

        dpo_val = self.dpo.dpo[0]
        dpo_rising = dpo_val > self.prev_dpo
        self.prev_dpo = dpo_val

        if not self.position:
            # Buy: DPO crossing up from negative (cycle bottom) +
            #       Stochastic oversold + above trend
            if (dpo_val < 0 and dpo_rising and
                    self.stoch.percK[0] < self.p.stoch_oversold and
                    self.data.close[0] > self.trend_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
        else:
            # Sell: DPO positive and falling (cycle top) + Stochastic overbought
            if (dpo_val > 0 and not dpo_rising and
                    self.stoch.percK[0] > self.p.stoch_overbought):
                self.order = self.sell(size=self.position.size)
            # Stop: price below trend by 5%
            elif self.data.close[0] < self.trend_ema[0] * 0.95:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
