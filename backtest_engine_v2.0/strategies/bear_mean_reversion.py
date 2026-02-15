"""
Bear Market Mean Reversion - Cycle Trading
--------------------------------------------
In een bear market beweegt BTC in cycles: daling → bounce → daling.
Deze strategie koopt bij oversold bounces en verkoopt bij mean reversion.

Idee: Koop wanneer RSI oversold is EN prijs bounced van Bollinger lower band.
Verkoop wanneer prijs terug naar mid-band of RSI overbought.

Varianten:
- BearMeanReversion: Bollinger bounce + RSI oversold
- BearRSICycle: Pure RSI cycle trading
- BearKeltnerBounce: Keltner lower band bounce
- BearStochBounce: Stochastic oversold bounce
- BearVWAPBounce: VWAP + RSI divergence

Long only. No leverage.
"""
import backtrader as bt


class BearMeanReversion(bt.Strategy):
    """
    Bollinger Band bounce + RSI oversold.
    Koop: prijs < lower BB + RSI < 30 + prijs stijgend.
    Verkoop: prijs > mid BB of RSI > 70 of trailing stop.
    """
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('rsi_period', 14),
        ('rsi_buy', 30),
        ('rsi_sell', 70),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def next(self):
        if self.order:
            return

        if not self.position:
            # Koop: prijs raakt lower BB + RSI oversold + prijs begint te stijgen
            if (self.data.close[0] <= self.bb.lines.bot[0] and
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

            # Verkoop: mid-band bereikt, RSI overbought, of stop
            if self.data.close[0] >= self.bb.lines.mid[0]:
                self.order = self.sell(size=self.position.size)
            elif self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearRSICycle(bt.Strategy):
    """
    Pure RSI cycle trading.
    Koop: RSI < 25 en stijgend (bounce).
    Verkoop: RSI > 65 of trailing stop.
    Snellere RSI (9) voor kortere cycles.
    """
    params = (
        ('rsi_period', 9),
        ('rsi_buy', 25),
        ('rsi_sell', 65),
        ('ema_period', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
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
            # RSI oversold en stijgend = bounce begint
            if (not in_cooldown and
                    self.rsi[0] < self.p.rsi_buy and
                    self.rsi[0] > self.rsi[-1] and
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

            if self.rsi[0] > self.p.rsi_sell:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearKeltnerBounce(bt.Strategy):
    """
    Keltner Channel lower band bounce.
    Koop: prijs < lower Keltner + momentum omhoog.
    Verkoop: prijs > mid Keltner of stop.
    """
    params = (
        ('kc_period', 20),
        ('kc_atr_mult', 2.0),
        ('rsi_period', 14),
        ('rsi_max', 40),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.kc_mid = bt.indicators.EMA(self.data.close, period=self.p.kc_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0

    def kc_lower(self):
        return self.kc_mid[0] - self.atr[0] * self.p.kc_atr_mult

    def next(self):
        if self.order:
            return

        if not self.position:
            if (self.data.close[0] <= self.kc_lower() and
                    self.rsi[0] < self.p.rsi_max and
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

            if self.data.close[0] >= self.kc_mid[0]:
                self.order = self.sell(size=self.position.size)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearStochBounce(bt.Strategy):
    """
    Stochastic oversold bounce.
    Koop: Stoch %K < 20 en %K kruist boven %D (bullish cross).
    Verkoop: Stoch > 80, of trailing stop.
    """
    params = (
        ('stoch_period', 14),
        ('stoch_slow', 3),
        ('stoch_buy', 20),
        ('stoch_sell', 80),
        ('ema_period', 50),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.stoch_period, period_dfast=self.p.stoch_slow)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
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
            # Stoch bullish cross in oversold zone
            if (not in_cooldown and
                    self.stoch.lines.percK[0] < self.p.stoch_buy and
                    self.stoch.lines.percK[0] > self.stoch.lines.percD[0] and
                    self.stoch.lines.percK[-1] <= self.stoch.lines.percD[-1]):
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


class BearVWAPBounce(bt.Strategy):
    """
    VWAP bounce in bear market.
    Koop: prijs onder VWMA + RSI oversold + prijs begint te stijgen.
    Verkoop: prijs boven VWMA of RSI overbought.
    Tegenovergestelde van V55 - we kopen ONDER de VWMA in plaats van erboven.
    """
    params = (
        ('vwma_period', 20),
        ('rsi_period', 14),
        ('rsi_buy', 35),
        ('rsi_sell', 65),
        ('atr_period', 14),
        ('atr_stop_mult', 2.5),
        ('cooldown_bars', 4),
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
            # Koop onder VWMA als RSI oversold en prijs stijgt
            if (not in_cooldown and
                    self.data.close[0] < vwma and
                    self.rsi[0] < self.p.rsi_buy and
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

            # Verkoop als terug boven VWMA of RSI overbought
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


class BearEMADip(bt.Strategy):
    """
    EMA Dip Buy - koop dips naar EMA in dalende trend.
    Koop: prijs daalt naar EMA21 en bounced + RSI < 40.
    Verkoop: +3% target of trailing stop.
    Snelle in-en-uit trades.
    """
    params = (
        ('fast_ema', 10),
        ('slow_ema', 21),
        ('rsi_period', 9),
        ('rsi_buy', 40),
        ('target_pct', 3.0),
        ('atr_period', 14),
        ('atr_stop_mult', 1.5),
        ('cooldown_bars', 3),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.fast_ema)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.slow_ema)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.entry_price = 0
        self.stop_price = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # Prijs raakt EMA21 van boven, RSI laag, en bounced
            if (not in_cooldown and
                    self.data.low[0] <= self.ema_slow[0] and
                    self.data.close[0] > self.ema_slow[0] and
                    self.rsi[0] < self.p.rsi_buy and
                    self.data.close[0] > self.data.close[-1]):
                size = (self.broker.getcash() * self.p.risk_pct) / self.data.close[0]
                self.order = self.buy(size=size)
                self.entry_price = self.data.close[0]
                self.stop_price = self.data.close[0] - self.atr[0] * self.p.atr_stop_mult
        else:
            # Target of stop
            target = self.entry_price * (1 + self.p.target_pct / 100)
            if self.data.close[0] >= target:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearDonchianBounce(bt.Strategy):
    """
    Donchian Channel lower band bounce.
    Koop: prijs raakt 20-period low en bounced.
    Verkoop: prijs raakt mid-channel of trailing stop.
    """
    params = (
        ('donchian_period', 20),
        ('rsi_period', 14),
        ('rsi_max', 35),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
        self.highest_high = bt.indicators.Highest(self.data.high, period=self.p.donchian_period)
        self.lowest_low = bt.indicators.Lowest(self.data.low, period=self.p.donchian_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.order = None
        self.stop_price = 0
        self.highest = 0
        self.last_exit_bar = -999

    def next(self):
        if self.order:
            return

        mid_channel = (self.highest_high[0] + self.lowest_low[0]) / 2
        in_cooldown = (len(self) - self.last_exit_bar) < self.p.cooldown_bars

        if not self.position:
            # Prijs bij lower Donchian + RSI laag + bounce
            if (not in_cooldown and
                    self.data.low[0] <= self.lowest_low[-1] and
                    self.rsi[0] < self.p.rsi_max and
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

            if self.data.close[0] >= mid_channel:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)
            elif self.data.close[0] < self.stop_price:
                self.order = self.sell(size=self.position.size)
                self.last_exit_bar = len(self)

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BearCCIBounce(bt.Strategy):
    """
    CCI (Commodity Channel Index) oversold bounce.
    Koop: CCI < -100 en stijgend (extreme oversold bounce).
    Verkoop: CCI > 100 of trailing stop.
    """
    params = (
        ('cci_period', 20),
        ('cci_buy', -100),
        ('cci_sell', 100),
        ('atr_period', 14),
        ('atr_stop_mult', 2.0),
        ('cooldown_bars', 4),
        ('risk_pct', 0.95),
    )

    def __init__(self):
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
            if (not in_cooldown and
                    self.cci[0] < self.p.cci_buy and
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
