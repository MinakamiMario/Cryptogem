"""
V8: Ultimate Cycle Rider - Final Optimized Strategy
-----------------------------------------------------
Combines the best elements discovered across V1-V7:

From V1: EMA 21/50 crossover for cycle timing (proven best signal)
From V5: ATR trailing stop (protects profits)
From V6: RSI momentum confirmation (filters weak entries)
From V7: Volatility regime filter + cooldown after stops

Additions:
1. Wider ATR stop (4x) to let BTC breathe during bull cycles
2. RSI lower threshold (40) to catch more entries
3. Regime detection: skip entries when ATR is spiking (crash indicator)
4. No exit on EMA death cross alone - use trailing stop to ride momentum
   (V1 held too long, V5-V7 exited too early on EMA cross)
5. Sell only on: trailing stop OR extreme RSI (>85) + EMA cross
"""
import backtrader as bt


class UltimateCycleRider(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('slow_period', 50),
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_entry_min', 40),
        ('rsi_extreme', 85),
        ('atr_period', 14),
        ('atr_stop_mult', 4.0),
        ('vol_lookback', 30),
        ('vol_threshold', 1.5),
        ('cooldown_bars', 7),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.trend_ema = bt.indicators.EMA(self.data.close, period=self.p.trend_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.bars_since_stop = 999
        self.was_stopped = False

    def is_vol_spike(self):
        if self.atr_sma[0] > 0:
            return self.atr[0] / self.atr_sma[0] > self.p.vol_threshold
        return False

    def next(self):
        if self.order:
            return

        if self.was_stopped:
            self.bars_since_stop += 1

        if not self.position:
            in_cooldown = self.was_stopped and self.bars_since_stop < self.p.cooldown_bars

            if (self.crossover > 0 and
                    self.data.close[0] > self.trend_ema[0] and
                    self.slow_ema[0] > self.trend_ema[0] and
                    self.rsi[0] > self.p.rsi_entry_min and
                    not self.is_vol_spike() and
                    not in_cooldown):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
                self.was_stopped = False
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            # Trailing stop - adaptive: tighter when vol spikes
            mult = self.p.atr_stop_mult * 0.7 if self.is_vol_spike() else self.p.atr_stop_mult
            new_stop = self.highest - self.atr[0] * mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit: trailing stop OR (extreme RSI + EMA death cross)
            if self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.was_stopped = True
                self.bars_since_stop = 0
            elif self.crossover < 0 and self.rsi[0] > self.p.rsi_extreme:
                self.order = self.sell(size=self.position.size)
                self.was_stopped = False

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
