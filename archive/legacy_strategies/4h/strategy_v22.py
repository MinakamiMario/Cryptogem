"""
V22: Combo Short-Term: Inside Bar + Keltner + RSI
---------------------------------------------------
Target: 100+ trades, 1-4 day holds.

Best of all worlds: combine the top short-term signals:
- Inside bar compression detection (V17 - 175 trades proven)
- Keltner channel for trend context (V13 - best Sharpe)
- RSI momentum filter (avoid bad entries)
- ATR trailing stop + time stop

No short selling - long only.
"""
import backtrader as bt


class ComboShortTerm(bt.Strategy):
    params = (
        ('kc_period', 15),
        ('kc_atr_mult', 1.2),
        ('ema_period', 21),
        ('rsi_period', 7),
        ('rsi_min', 40),
        ('rsi_max', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('atr_target_mult', 2.0),
        ('max_hold_days', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.target_price = 0

    def kc_upper(self):
        return self.kc_mid[0] + self.atr[0] * self.p.kc_atr_mult

    def next(self):
        if self.order:
            return

        if len(self.data) < 3:
            return

        if not self.position:
            # Signal 1: Inside bar breakout
            prev_inside = (self.data.high[-1] <= self.data.high[-2] and
                           self.data.low[-1] >= self.data.low[-2])
            ib_breakout = prev_inside and self.data.close[0] > self.data.high[-1]

            # Signal 2: Keltner breakout
            kc_breakout = self.data.close[0] > self.kc_upper()

            # Either signal works, plus filters
            if ((ib_breakout or kc_breakout) and
                    self.data.close[0] > self.ema[0] and
                    self.p.rsi_min < self.rsi[0] < self.p.rsi_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                if ib_breakout:
                    self.stop_price = self.data.low[-1]
                else:
                    self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.target_price = self.data.close[0] + self.atr[0] * self.p.atr_target_mult
        else:
            bars_held = len(self) - self.entry_bar

            if self.data.close[0] >= self.target_price:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.kc_mid[0] and bars_held >= 2:
                self.order = self.sell(size=self.position.size)
            elif bars_held >= self.p.max_hold_days:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
