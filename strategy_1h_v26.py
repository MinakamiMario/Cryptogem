"""
V26: 1H Bollinger Squeeze Breakout
-------------------------------------
Bollinger Band width contraction = compression (low vol).
When bands expand (breakout), ride the momentum.
Hold 2-12 hours.

Long only.
"""
import backtrader as bt


class BBSqueeze1H(bt.Strategy):
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('squeeze_lookback', 20),
        ('squeeze_threshold', 0.5),  # Band width must be below 50th percentile
        ('ema_period', 21),
        ('rsi_period', 7),
        ('rsi_min', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('max_hold_bars', 12),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.highest = 0
        self.bw_history = []

    def get_bandwidth(self):
        mid = self.bb.lines.mid[0]
        if mid > 0:
            return (self.bb.lines.top[0] - self.bb.lines.bot[0]) / mid
        return 0

    def is_squeeze(self):
        bw = self.get_bandwidth()
        self.bw_history.append(bw)
        if len(self.bw_history) > self.p.squeeze_lookback:
            self.bw_history = self.bw_history[-self.p.squeeze_lookback:]
        if len(self.bw_history) < self.p.squeeze_lookback:
            return False
        sorted_bw = sorted(self.bw_history)
        threshold_idx = int(len(sorted_bw) * self.p.squeeze_threshold)
        return bw <= sorted_bw[threshold_idx]

    def next(self):
        if self.order:
            return

        squeeze = self.is_squeeze()

        if not self.position:
            # Breakout from squeeze above upper BB
            if (self.data.close[0] > self.bb.lines.top[0] and
                    self.rsi[0] > self.p.rsi_min and
                    self.data.close[0] > self.ema[0]):
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

            # Exit: back to mid BB, max hold, or stop
            if self.data.close[0] < self.bb.lines.mid[0]:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_bars:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
