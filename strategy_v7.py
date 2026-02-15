"""
V7: Multi-Cycle EMA with Volatility Regime Filter
---------------------------------------------------
The best hybrid approach:
1. Core: EMA crossover (proven cycle detection from V1)
2. Volatility regime: Reduce exposure in high-vol environments (bear markets)
3. Multi-period cycle confirmation: 21/50 fast cycle + 50/200 macro cycle
4. ATR trailing stop with tightening in high volatility
5. Re-entry delay after stop-outs to avoid whipsaws
"""
import backtrader as bt


class MultiCycleVolRegime(bt.Strategy):
    params = (
        ('fast_period', 21),
        ('mid_period', 50),
        ('slow_period', 200),
        ('atr_period', 14),
        ('atr_stop_base', 3.0),
        ('vol_lookback', 30),     # Period for volatility regime detection
        ('vol_threshold', 1.5),   # ATR ratio above which = high vol regime
        ('cooldown_bars', 10),    # Bars to wait after a stop-out before re-entry
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.mid_ema = bt.indicators.EMA(self.data.close, period=self.p.mid_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)

        # Fast crossover (21/50) for cycle timing
        self.fast_cross = bt.indicators.CrossOver(self.fast_ema, self.mid_ema)
        # Macro trend (50/200) for cycle direction
        self.macro_bull = bt.indicators.CrossOver(self.mid_ema, self.slow_ema)

        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.vol_lookback)

        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.bars_since_stop = 999  # Start high so first trade isn't blocked
        self.stopped_out = False

    def is_high_vol(self):
        """Check if current volatility is elevated vs recent average."""
        if self.atr_sma[0] > 0:
            return self.atr[0] / self.atr_sma[0] > self.p.vol_threshold
        return False

    def get_atr_mult(self):
        """Adaptive ATR multiplier: tighter in high vol, wider in low vol."""
        if self.is_high_vol():
            return self.p.atr_stop_base * 0.75  # Tighter stop in high vol
        return self.p.atr_stop_base

    def next(self):
        if self.order:
            return

        # Track cooldown
        if self.stopped_out:
            self.bars_since_stop += 1

        if not self.position:
            # Macro trend must be bullish: mid > slow EMA
            macro_bullish = self.mid_ema[0] > self.slow_ema[0]

            # Don't enter during cooldown period after a stop-out
            in_cooldown = self.stopped_out and self.bars_since_stop < self.p.cooldown_bars

            # Don't enter in high vol regime (likely bear market crash)
            high_vol = self.is_high_vol()

            # Buy: fast cycle crossover + macro bull + not in cooldown + not high vol
            if (self.fast_cross > 0 and
                    macro_bullish and
                    not in_cooldown and
                    not high_vol and
                    self.data.close[0] > self.slow_ema[0]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                atr_mult = self.get_atr_mult()
                self.stop_price = self.data.close[0] - self.atr[0] * atr_mult
                self.highest = self.data.close[0]
                self.stopped_out = False
        else:
            # Track highest
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]

            # Adaptive trailing stop
            atr_mult = self.get_atr_mult()
            new_stop = self.highest - self.atr[0] * atr_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Exit conditions
            if self.fast_cross < 0:
                # EMA death cross - full exit
                self.order = self.sell(size=self.position.size)
                self.stopped_out = False
            elif self.data.close[0] < self.stop_price:
                # Trailing stop hit
                self.order = self.sell(size=self.position.size)
                self.stopped_out = True
                self.bars_since_stop = 0

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
