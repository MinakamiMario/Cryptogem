"""
V4: Composite Adaptive Cycle Strategy
--------------------------------------
Concept: Combine multiple cycle indicators into a composite score,
with adaptive thresholds based on recent volatility.

Components:
1. Detrended Price Oscillator (DPO) - cycle position
2. RSI - momentum within cycle
3. Stochastic - overbought/oversold within cycle
4. Bollinger Band %B - price position relative to volatility envelope
5. ATR-based adaptive stops

Scoring: Each indicator contributes a normalized score (0-100).
Buy when composite score indicates cycle bottom, sell at cycle top.
"""
import backtrader as bt
import math


class AdaptiveCycleComposite(bt.Strategy):
    params = (
        # Cycle detection
        ('dpo_period', 21),
        ('rsi_period', 14),
        ('stoch_period', 14),
        ('stoch_smooth', 3),
        ('bb_period', 20),
        ('bb_devs', 2.0),
        # Trend
        ('fast_trend', 50),
        ('slow_trend', 200),
        # Composite thresholds
        ('buy_threshold', 25),   # Composite score below = buy signal
        ('sell_threshold', 75),  # Composite score above = sell signal
        # Risk
        ('atr_period', 14),
        ('atr_stop_mult', 3.0),  # ATR multiplier for trailing stop
        ('risk_pct', 0.95),
        # Adaptive
        ('lookback', 60),  # Period for adaptive threshold adjustment
    )

    def __init__(self):
        # Indicators
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period,
            period_dfast=self.p.stoch_smooth, period_dslow=self.p.stoch_smooth,
        )
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_devs
        )
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_trend)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_trend)

        # DPO (manual)
        self.sma_dpo = bt.indicators.SMA(self.data.close, period=self.p.dpo_period)

        self.order = None
        self.stop_price = 0
        self.entry_price = 0
        self.scores_history = []

    def get_dpo(self):
        shift = self.p.dpo_period // 2 + 1
        if len(self.data) > shift:
            return self.data.close[0] - self.sma_dpo[-shift]
        return 0.0

    def get_bb_pctb(self):
        """Bollinger Band %B: 0 = lower band, 1 = upper band."""
        band_width = self.bb.lines.top[0] - self.bb.lines.bot[0]
        if band_width > 0:
            return (self.data.close[0] - self.bb.lines.bot[0]) / band_width
        return 0.5

    def compute_composite_score(self):
        """
        Compute a 0-100 composite score:
        0 = extreme cycle low (buy zone)
        100 = extreme cycle high (sell zone)
        """
        # RSI component (0-100 direct)
        rsi_score = self.rsi[0]

        # Stochastic component (0-100 direct)
        stoch_score = self.stoch.percK[0]

        # BB %B component (0-100)
        bb_score = max(0, min(100, self.get_bb_pctb() * 100))

        # DPO component - normalize based on recent range
        dpo = self.get_dpo()
        # Normalize DPO to 0-100 using recent ATR as reference
        atr_val = self.atr[0] if self.atr[0] > 0 else 1
        dpo_normalized = 50 + (dpo / (atr_val * 5)) * 50
        dpo_score = max(0, min(100, dpo_normalized))

        # Weighted composite
        composite = (
            rsi_score * 0.30 +
            stoch_score * 0.25 +
            bb_score * 0.25 +
            dpo_score * 0.20
        )

        return composite

    def get_adaptive_thresholds(self):
        """Adjust buy/sell thresholds based on recent score distribution."""
        if len(self.scores_history) < self.p.lookback:
            return self.p.buy_threshold, self.p.sell_threshold

        recent = self.scores_history[-self.p.lookback:]
        avg = sum(recent) / len(recent)
        std = math.sqrt(sum((x - avg) ** 2 for x in recent) / len(recent))

        # In high volatility, widen thresholds; in low volatility, tighten
        adaptive_buy = max(15, self.p.buy_threshold - std * 0.3)
        adaptive_sell = min(85, self.p.sell_threshold + std * 0.3)

        return adaptive_buy, adaptive_sell

    def next(self):
        if self.order:
            return

        score = self.compute_composite_score()
        self.scores_history.append(score)

        buy_thresh, sell_thresh = self.get_adaptive_thresholds()

        # Trend filter: fast EMA above slow EMA = uptrend
        uptrend = self.fast_ema[0] > self.slow_ema[0]

        if not self.position:
            # Buy: composite score at cycle low + uptrend confirmed
            if score < buy_thresh and uptrend:
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            # Update trailing stop
            new_stop = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            # Sell: composite at cycle high OR trailing stop hit
            if score > sell_thresh:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None
