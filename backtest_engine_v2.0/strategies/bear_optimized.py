"""
Bear Market Optimized Strategies - V2
---------------------------------------
Gebaseerd op analyse van de bear market feb 2025 - feb 2026:
- 4H BearMeanReversion was winstgevend (+2.8%, PF 1.50)
- 4H BearRSICycle was best (+8.0%, PF 1.50)
- 1H BearVWAPBounce was bijna break-even met 58% WR, 5.5% DD

Nu: combineer de beste elementen en optimaliseer parameters.

Long only. No leverage.
"""
import backtrader as bt


class BearBBRSI_4H(bt.Strategy):
    """
    Bollinger + RSI optimized for 4H bear market cycles.
    Wider BB (2.5 dev) + faster RSI (9) + trend filter.
    """
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.5),
        ('rsi_period', 9),
        ('rsi_buy', 30),
        ('rsi_sell', 65),
        ('ema_trend', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_trend)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            if (not in_cooldown and
                    self.data.close[0] <= self.bb.lines.bot[0] and
                    self.rsi[0] < self.p.rsi_buy and
                    self.data.close[0] > self.data.close[-1]):
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

            if self.data.close[0] >= self.bb.lines.mid[0]:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearRSIMomentum_4H(bt.Strategy):
    """
    RSI cycle + momentum confirmation for 4H.
    RSI(9) oversold bounce + price momentum + volume confirmation.
    """
    params = (
        ('rsi_period', 9),
        ('rsi_buy', 28),
        ('rsi_sell', 60),
        ('mom_lookback', 2),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('target_pct', 4.0),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)
        self.order = None
        self.entry_price = 0
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # RSI oversold + stijgend + prijs bounced + volume boven gemiddelde
            if (not in_cooldown and
                    self.rsi[0] < self.p.rsi_buy and
                    self.rsi[0] > self.rsi[-1] and
                    self.data.close[0] > self.data.close[-1] and
                    self.data.close[-1] > self.data.close[-2] and
                    self.data.volume[0] > self.vol_sma[0] * 0.8):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
                self.highest = self.data.close[0]
        else:
            if self.data.close[0] > self.highest:
                self.highest = self.data.close[0]
            new_stop = self.highest - self.atr[0] * self.p.atr_stop_mult
            if new_stop > self.stop_price:
                self.stop_price = new_stop

            target = self.entry_price * (1 + self.p.target_pct / 100)
            if self.data.close[0] >= target:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearStochRSI_4H(bt.Strategy):
    """
    Stochastic + RSI dual oversold for 4H.
    Dubbele bevestiging: both Stoch AND RSI moeten oversold zijn.
    """
    params = (
        ('stoch_period', 14),
        ('stoch_slow', 3),
        ('stoch_buy', 25),
        ('stoch_sell', 75),
        ('rsi_period', 14),
        ('rsi_buy', 35),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period, period_dfast=self.p.stoch_slow)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # Dubbele oversold: Stoch bullish cross + RSI laag
            if (not in_cooldown and
                    self.stoch.lines.percK[0] < self.p.stoch_buy and
                    self.rsi[0] < self.p.rsi_buy and
                    self.stoch.lines.percK[0] > self.stoch.lines.percD[0] and
                    self.data.close[0] > self.data.close[-1]):
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

            if self.stoch.lines.percK[0] > self.p.stoch_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearVWAPCycle_1H(bt.Strategy):
    """
    VWAP cycle optimized for 1H bear market.
    Koop onder VWMA + RSI oversold + 2 bullish candles.
    Verkoop boven VWMA. Strakke stop.
    Optimized version of BearVWAPBounce.
    """
    params = (
        ('vwma_period', 20),
        ('rsi_period', 9),
        ('rsi_buy', 35),
        ('rsi_sell', 60),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 6),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.pv = self.data.close * self.data.volume
        self.pv_sma = bt.indicators.SMA(self.pv, period=self.p.vwma_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=self.p.vwma_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def get_vwma(self):
        if self.vol_sma[0] > 0:
            return self.pv_sma[0] / self.vol_sma[0]
        return self.data.close[0]

    def next(self):
        if self.order:
            return

        vwma = self.get_vwma()
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            if (not in_cooldown and
                    self.data.close[0] < vwma and
                    self.rsi[0] < self.p.rsi_buy and
                    self.rsi[0] > self.rsi[-1] and
                    self.data.close[0] > self.data.close[-1] and
                    self.data.close[-1] > self.data.close[-2]):
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

            if self.data.close[0] >= vwma:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearBBStoch_4H(bt.Strategy):
    """
    Bollinger + Stochastic dual confirmation for 4H.
    Koop: prijs bij lower BB + Stoch oversold cross.
    Verkoop: mid BB of Stoch overbought.
    """
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('stoch_period', 14),
        ('stoch_slow', 3),
        ('stoch_buy', 25),
        ('stoch_sell', 75),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period, period_dfast=self.p.stoch_slow)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # BB lower + Stoch oversold bullish cross
            if (not in_cooldown and
                    self.data.close[0] <= self.bb.lines.bot[0] and
                    self.stoch.lines.percK[0] < self.p.stoch_buy and
                    self.stoch.lines.percK[0] > self.stoch.lines.percD[0] and
                    self.data.close[0] > self.data.close[-1]):
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

            if self.data.close[0] >= self.bb.lines.mid[0]:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.stoch.lines.percK[0] > self.p.stoch_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearCCIRSI_4H(bt.Strategy):
    """
    CCI + RSI dual oversold for 4H.
    CCI < -100 (extreme oversold) + RSI < 35 + bounce.
    """
    params = (
        ('cci_period', 20),
        ('cci_buy', -100),
        ('cci_sell', 50),
        ('rsi_period', 14),
        ('rsi_buy', 35),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.cci = bt.indicators.CommodityChannelIndex(
            self.data, period=self.p.cci_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            if (not in_cooldown and
                    self.cci[0] < self.p.cci_buy and
                    self.rsi[0] < self.p.rsi_buy and
                    self.cci[0] > self.cci[-1] and
                    self.data.close[0] > self.data.close[-1]):
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

            if self.cci[0] > self.p.cci_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearMultiSignal_4H(bt.Strategy):
    """
    Multi-signal bear market strategy for 4H.
    Combineert BB + RSI + Stoch + CCI voor maximum bevestiging.
    Koopt alleen als 3 van 4 indicatoren oversold zijn.
    Zeer selectief = weinig maar goede trades.
    """
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('rsi_period', 14),
        ('rsi_buy', 35),
        ('rsi_sell', 65),
        ('stoch_period', 14),
        ('stoch_buy', 25),
        ('cci_period', 20),
        ('cci_buy', -80),
        ('min_signals', 3),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period)
        self.cci = bt.indicators.CommodityChannelIndex(
            self.data, period=self.p.cci_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # Tel oversold signalen
            signals = 0
            if self.data.close[0] <= self.bb.lines.bot[0]:
                signals += 1
            if self.rsi[0] < self.p.rsi_buy:
                signals += 1
            if self.stoch.lines.percK[0] < self.p.stoch_buy:
                signals += 1
            if self.cci[0] < self.p.cci_buy:
                signals += 1

            # Koop als genoeg signalen + bounce
            if (not in_cooldown and
                    signals >= self.p.min_signals and
                    self.data.close[0] > self.data.close[-1]):
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

            if self.data.close[0] >= self.bb.lines.mid[0]:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None
