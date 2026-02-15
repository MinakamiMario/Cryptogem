"""
V33: 1H Trend-Following Pullback (High Win Rate Design)
---------------------------------------------------------
Problem diagnosis: all previous 1H strategies have 30-42% win rate.
We need 50%+ win rate to be profitable.

Approach: Instead of buying breakouts (which have low win rate on 1H),
buy PULLBACKS in confirmed strong trends. Wait for:
1. Strong confirmed uptrend (EMA50 rising, price well above it)
2. Pullback to EMA9 support
3. RSI bouncing from 35-50 zone (not oversold, just pulled back)
4. Wide stop below EMA21 (gives room)
5. Exit when RSI > 70 or trailing stop

This catches the high-probability bounce off moving average support.

Long only.
"""
import backtrader as bt


class TrendPullback1H(bt.Strategy):
    params = (
        ('fast_ema', 9),
        ('mid_ema', 21),
        ('slow_ema', 50),
        ('rsi_period', 14),
        ('rsi_pullback_min', 35),
        ('rsi_pullback_max', 50),
        ('rsi_exit', 70),
        ('atr_period', 14),
        ('atr_stop_mult', 3.0),
        ('max_hold_bars', 48),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.mid = bt.indicators.EMA(self.data.close, period=self.p.mid_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.p.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        # Detect price bouncing off fast EMA
        self.price_cross_fast = bt.indicators.CrossOver(self.data.close, self.fast)
        self.order = None
        self.entry_bar = 0
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        # Strong uptrend: all EMAs aligned AND slow EMA rising
        strong_uptrend = (self.fast[0] > self.mid[0] > self.slow[0] and
                          self.slow[0] > self.slow[-1])

        if not self.position:
            # Pullback entry: price bounces off fast EMA + RSI in pullback zone
            if (not in_cooldown and
                    strong_uptrend and
                    self.price_cross_fast > 0 and
                    self.p.rsi_pullback_min < self.rsi[0] < self.p.rsi_pullback_max):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_bar = len(self)
                self.stop_price = self.mid[0] - self.atr[0] * 0.5  # Stop below EMA21
                self.highest = self.data.close[0]
        else:
            bars_held = len(self) - self.entry_bar
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit: RSI overbought, lost trend, max hold, or stop
            if self.rsi[0] > self.p.rsi_exit:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.mid[0]:
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
