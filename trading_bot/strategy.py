"""
Live Strategy Signal Generator
------------------------------
Berekent buy/sell signalen op basis van OHLC data van Kraken.
Identieke logica als de backtest strategieën.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger('trading_bot')


@dataclass
class Signal:
    """Trading signaal."""
    action: str  # 'BUY', 'SELL_TARGET', 'SELL_STOP', 'HOLD', 'WAIT'
    pair: str
    price: float
    reason: str
    stop_price: float = 0.0
    target_price: float = 0.0
    rsi: float = 0.0
    confidence: float = 0.0


@dataclass
class Position:
    """Open positie tracking."""
    pair: str
    entry_price: float
    volume: float
    stop_price: float
    highest_price: float
    entry_time: int
    order_id: str = ''


def calc_rsi(closes: list, period: int = 14) -> float:
    """Bereken RSI op basis van close prijzen."""
    if len(closes) < period + 1:
        return 50.0  # Neutraal als niet genoeg data

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # Gebruik de laatste 'period' veranderingen
    recent_gains = gains[-(period):]
    recent_losses = losses[-(period):]

    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    """Bereken ATR (Average True Range)."""
    if len(highs) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)

    recent_trs = trs[-(period):]
    return sum(recent_trs) / len(recent_trs)


def calc_donchian(highs: list, lows: list, period: int = 20) -> tuple:
    """Bereken Donchian Channel: (highest_high, lowest_low, mid_channel)."""
    if len(highs) < period:
        return None, None, None

    hh = max(highs[-period:])
    ll = min(lows[-period:])
    mid = (hh + ll) / 2
    return hh, ll, mid


def calc_bollinger(closes: list, period: int = 20, dev: float = 2.0) -> tuple:
    """Bereken Bollinger Bands: (mid, upper, lower)."""
    if len(closes) < period:
        return None, None, None

    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((x - mid) ** 2 for x in recent) / period
    std = variance ** 0.5
    upper = mid + dev * std
    lower = mid - dev * std
    return mid, upper, lower


class DonchianBounceStrategy:
    """
    Bear Donchian Bounce - Live versie.
    Identiek aan backtest BearDonchianBounce.

    Entry: low <= prev Donchian lower + RSI < 35 + close > prev close
    Exit: close >= mid channel OF trailing stop
    """

    def __init__(self, donchian_period=20, rsi_period=14, rsi_max=35,
                 atr_period=14, atr_stop_mult=2.0, cooldown_bars=4,
                 max_stop_loss_pct=15.0):
        self.donchian_period = donchian_period
        self.rsi_period = rsi_period
        self.rsi_max = rsi_max
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.cooldown_bars = cooldown_bars
        self.max_stop_loss_pct = max_stop_loss_pct
        self.last_exit_bar = -999
        self.bar_count = 0

    def analyze(self, candles: list, position: Optional[Position], pair: str) -> Signal:
        """
        Analyseer candle data en genereer signaal.
        candles: lijst van dicts met open, high, low, close, volume
        position: huidige open positie (of None)
        """
        if len(candles) < max(self.donchian_period, self.rsi_period, self.atr_period) + 5:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)

        # Extract price arrays
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        # Indicators
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        # Donchian op VORIGE bars (excl huidige)
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)

        # Donchian inclusief huidige bar (voor mid channel target)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)

        current = candles[-1]
        prev = candles[-2]

        if position is None:
            # === CHECK ENTRY ===
            in_cooldown = (self.bar_count - self.last_exit_bar) < self.cooldown_bars

            if in_cooldown:
                return Signal('WAIT', pair, current['close'],
                              f'Cooldown ({self.bar_count - self.last_exit_bar}/{self.cooldown_bars})',
                              rsi=rsi, confidence=0)

            price_at_lower = current['low'] <= prev_lowest if prev_lowest else False
            rsi_oversold = rsi < self.rsi_max
            price_bouncing = current['close'] > prev['close']

            if price_at_lower and rsi_oversold and price_bouncing:
                stop = current['close'] - atr * self.atr_stop_mult
                # Max stop loss cap: stop mag nooit verder dan max_stop_loss_pct% onder entry
                max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                if stop < max_stop:
                    stop = max_stop
                return Signal(
                    'BUY', pair, current['close'],
                    f"Donchian bounce: low={current['low']:.4f} <= DC_low={prev_lowest:.4f}, "
                    f"RSI={rsi:.1f} < {self.rsi_max}, bounce confirmed",
                    stop_price=stop,
                    target_price=mid_channel,
                    rsi=rsi,
                    confidence=0.85
                )

            dc_str = f"{prev_lowest:.4f}" if prev_lowest else "?"
            return Signal('WAIT', pair, current['close'],
                          f"Geen signaal: low={current['low']:.4f} vs DC={dc_str}, RSI={rsi:.1f}",
                          rsi=rsi, confidence=0)

        else:
            # === CHECK EXIT ===
            # Update trailing stop
            if current['close'] > position.highest_price:
                position.highest_price = current['close']
            new_stop = position.highest_price - atr * self.atr_stop_mult
            # Max stop loss cap: stop mag nooit verder dan max_stop_loss_pct% onder entry
            max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < max_stop:
                new_stop = max_stop
            if new_stop > position.stop_price:
                position.stop_price = new_stop

            # Exit 1: Mid channel target bereikt
            if mid_channel and current['close'] >= mid_channel:
                pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100
                self.last_exit_bar = self.bar_count
                return Signal(
                    'SELL_TARGET', pair, current['close'],
                    f"Mid channel target bereikt: {current['close']:.4f} >= {mid_channel:.4f} "
                    f"(entry={position.entry_price:.4f}, P&L={pnl_pct:+.1f}%)",
                    rsi=rsi,
                    confidence=0.9
                )

            # Exit 2: Hard max loss cap (15%)
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100
                self.last_exit_bar = self.bar_count
                return Signal(
                    'SELL_STOP', pair, current['close'],
                    f"Max loss cap geraakt: {current['close']:.4f} < {hard_stop:.4f} "
                    f"(entry={position.entry_price:.4f}, P&L={pnl_pct:+.1f}%, max={self.max_stop_loss_pct}%)",
                    rsi=rsi,
                    confidence=0.95
                )

            # Exit 3: Trailing stop geraakt
            if current['close'] < position.stop_price:
                pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100
                self.last_exit_bar = self.bar_count
                return Signal(
                    'SELL_STOP', pair, current['close'],
                    f"Trailing stop geraakt: {current['close']:.4f} < {position.stop_price:.4f} "
                    f"(entry={position.entry_price:.4f}, P&L={pnl_pct:+.1f}%)",
                    rsi=rsi,
                    confidence=0.95
                )

            # Holding
            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100
            return Signal(
                'HOLD', pair, current['close'],
                f"Holding: entry={position.entry_price:.4f}, P&L={pnl_pct:+.1f}%, "
                f"stop={position.stop_price:.4f}, target={mid_channel:.4f}",
                stop_price=position.stop_price,
                target_price=mid_channel,
                rsi=rsi,
                confidence=0
            )


class MeanReversionStrategy:
    """
    Bear Mean Reversion (BB) - Live versie.
    Entry: close <= BB lower + RSI < 30 + close > prev close
    Exit: close >= BB mid OR RSI > 70 OR trailing stop
    """

    def __init__(self, bb_period=20, bb_dev=2.0, rsi_period=14,
                 rsi_buy=30, rsi_sell=70, atr_period=14, atr_stop_mult=3.0,
                 max_stop_loss_pct=15.0):
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.max_stop_loss_pct = max_stop_loss_pct

    def analyze(self, candles: list, position: Optional[Position], pair: str) -> Signal:
        if len(candles) < max(self.bb_period, self.rsi_period, self.atr_period) + 5:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        current = candles[-1]
        prev = candles[-2]

        if position is None:
            if bb_lower and current['close'] <= bb_lower and rsi < self.rsi_buy and current['close'] > prev['close']:
                stop = current['close'] - atr * self.atr_stop_mult
                # Max stop loss cap
                max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                if stop < max_stop:
                    stop = max_stop
                return Signal(
                    'BUY', pair, current['close'],
                    f"BB bounce: close={current['close']:.4f} <= BB_low={bb_lower:.4f}, RSI={rsi:.1f}",
                    stop_price=stop, target_price=bb_mid, rsi=rsi, confidence=0.85
                )
            bb_str = f"{bb_lower:.4f}" if bb_lower else "?"
            return Signal('WAIT', pair, current['close'],
                          f"Geen signaal: close={current['close']:.4f} vs BB_low={bb_str}, RSI={rsi:.1f}",
                          rsi=rsi, confidence=0)
        else:
            if current['close'] > position.highest_price:
                position.highest_price = current['close']
            new_stop = position.highest_price - atr * self.atr_stop_mult
            # Max stop loss cap
            max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < max_stop:
                new_stop = max_stop
            if new_stop > position.stop_price:
                position.stop_price = new_stop

            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100

            # Hard max loss cap
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                return Signal('SELL_STOP', pair, current['close'],
                              f"Max loss cap: {current['close']:.4f} < {hard_stop:.4f} (P&L={pnl_pct:+.1f}%, max={self.max_stop_loss_pct}%)",
                              rsi=rsi, confidence=0.95)

            if bb_mid and current['close'] >= bb_mid:
                return Signal('SELL_TARGET', pair, current['close'],
                              f"BB mid target: {current['close']:.4f} >= {bb_mid:.4f} (P&L={pnl_pct:+.1f}%)",
                              rsi=rsi, confidence=0.9)

            if rsi > self.rsi_sell:
                return Signal('SELL_TARGET', pair, current['close'],
                              f"RSI overbought: RSI={rsi:.1f} > {self.rsi_sell} (P&L={pnl_pct:+.1f}%)",
                              rsi=rsi, confidence=0.85)

            if current['close'] < position.stop_price:
                return Signal('SELL_STOP', pair, current['close'],
                              f"Stop loss: {current['close']:.4f} < {position.stop_price:.4f} (P&L={pnl_pct:+.1f}%)",
                              rsi=rsi, confidence=0.95)

            return Signal('HOLD', pair, current['close'],
                          f"Holding: P&L={pnl_pct:+.1f}%, stop={position.stop_price:.4f}",
                          stop_price=position.stop_price, target_price=bb_mid, rsi=rsi)


class DualConfirmStrategy:
    """
    Bear Bounce Dual Confirm OPTIMIZED V4 - Donchian + Bollinger Bands tegelijk.

    V4 Optimalisaties (60d, 285 coins, 0.26% fee):
      - Entry: Volume spike >2.0x + volume bar-to-bar confirm (stijgend volume)
      - Exit: Break-even stop +3%, ATR trailing 2.0x, time max 10 bars (40h)
      - Portfolio: 1x$2000 all-in

    Entry: ALLE moeten waar zijn:
      1. Donchian: low <= prev DC lower + RSI < 40 + close > prev close
      2. BB: close <= BB lower + RSI < 40 + close > prev close
      3. Volume: current volume >= 2.0x avg(20)
      4. Volume confirm: current volume > prev bar volume (V4)

    Exit (eerste die triggert):
      1. HARD STOP: close < entry × (1 - 15%)
      2. TIME MAX: trade open >= 10 bars (40h) → force close (V4)
      3. TARGET: close >= DC mid channel OF close >= BB mid
      4. RSI EXIT: RSI > 70
      5. TRAILING STOP: close < trailing stop (ATR × 2.0)
         - Break-even: na +3% winst → stop naar entry + fee buffer

    Backtest 60d resultaten (V4):
      1x$2000: P&L +$4,566, WR 83.3%, PF 78.29, DD 1.9% (12 trades)
    """

    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_dc_max=40, rsi_bb_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, cooldown_bars=4,
                 cooldown_after_stop=8,
                 max_stop_loss_pct=15.0,
                 # V2 optimalisaties
                 volume_spike_filter=True, volume_spike_mult=2.0,
                 breakeven_stop=True, breakeven_trigger_pct=3.0,
                 volume_min_pct=0.5,
                 # V3: Time max exit
                 time_max_bars=10,
                 # V4: Volume bar-to-bar confirmation
                 vol_confirm=True, vol_confirm_mult=1.0):
        self.donchian_period = donchian_period
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.rsi_period = rsi_period
        self.rsi_dc_max = rsi_dc_max
        self.rsi_bb_max = rsi_bb_max
        self.rsi_sell = rsi_sell
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.cooldown_bars = cooldown_bars
        self.cooldown_after_stop = cooldown_after_stop
        self.max_stop_loss_pct = max_stop_loss_pct
        # V2: Volume spike filter (Agent 1 winnaar)
        self.volume_spike_filter = volume_spike_filter
        self.volume_spike_mult = volume_spike_mult
        # V2: Break-even stop (Agent 2 winnaar)
        self.breakeven_stop = breakeven_stop
        self.breakeven_trigger_pct = breakeven_trigger_pct
        # V2: Base volume filter
        self.volume_min_pct = volume_min_pct
        # V3: Time max exit (force exit stale trades)
        self.time_max_bars = time_max_bars
        # V4: Volume bar-to-bar confirmation
        self.vol_confirm = vol_confirm
        self.vol_confirm_mult = vol_confirm_mult
        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles: list, position: Optional[Position], pair: str) -> Signal:
        """
        Analyseer candle data en genereer signaal.
        Dual confirm: Donchian bounce + BB bounce moeten BEIDE triggeren.
        V2: + volume spike filter + break-even stop.
        """
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        # Indicators
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        # Donchian op VORIGE bars (excl huidige)
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)

        # Donchian inclusief huidige bar (voor mid channel target)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)

        # Bollinger Bands
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        current = candles[-1]
        prev = candles[-2]

        if position is None:
            # === CHECK ENTRY (dual confirm + V2 filters) ===
            # Smart cooldown: langere cooldown na stop loss
            cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
            in_cooldown = (self.bar_count - self.last_exit_bar) < cooldown_needed
            if in_cooldown:
                return Signal('WAIT', pair, current['close'],
                              f'Cooldown ({self.bar_count - self.last_exit_bar}/{cooldown_needed})',
                              rsi=rsi, confidence=0)

            # Base volume filter (min 50% van gemiddeld)
            if volumes:
                vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
                if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                    return Signal('WAIT', pair, current['close'],
                                  f'Volume te laag: {volumes[-1]:.0f} < {vol_avg * self.volume_min_pct:.0f}',
                                  rsi=rsi, confidence=0)

            # Signal 1: Donchian bounce
            donchian_ok = (
                prev_lowest is not None and
                current['low'] <= prev_lowest and
                rsi < self.rsi_dc_max and
                current['close'] > prev['close']
            )

            # Signal 2: BB bounce
            bb_ok = (
                bb_lower is not None and
                current['close'] <= bb_lower and
                rsi < self.rsi_bb_max and
                current['close'] > prev['close']
            )

            if not (donchian_ok and bb_ok):
                dc_str = f"{prev_lowest:.4f}" if prev_lowest else "?"
                bb_str = f"{bb_lower:.4f}" if bb_lower else "?"
                dc_flag = "DC:OK" if donchian_ok else "DC:NO"
                bb_flag = "BB:OK" if bb_ok else "BB:NO"
                return Signal('WAIT', pair, current['close'],
                              f"Geen dual confirm: {dc_flag} {bb_flag} | "
                              f"low={current['low']:.4f} DC={dc_str} BB={bb_str} RSI={rsi:.1f}",
                              rsi=rsi, confidence=0)

            # V2: Volume spike filter (Agent 1 winnaar: >2.0x avg volume)
            if self.volume_spike_filter and volumes:
                vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
                if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                    return Signal('WAIT', pair, current['close'],
                                  f"Volume spike te laag: {volumes[-1]:.0f} < {vol_avg * self.volume_spike_mult:.0f} "
                                  f"({self.volume_spike_mult}x avg)",
                                  rsi=rsi, confidence=0)

            # V4: Volume bar-to-bar confirmation (stijgend volume op bounce)
            if self.vol_confirm and len(volumes) >= 2 and volumes[-2] > 0:
                vol_bar_ratio = volumes[-1] / volumes[-2]
                if vol_bar_ratio < self.vol_confirm_mult:
                    return Signal('WAIT', pair, current['close'],
                                  f"Vol confirm te laag: {vol_bar_ratio:.2f}x < {self.vol_confirm_mult}x prev bar",
                                  rsi=rsi, confidence=0)

            # All checks passed → BUY
            stop = current['close'] - atr * self.atr_stop_mult
            # Max stop loss cap
            max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
            if stop < max_stop:
                stop = max_stop

            # Best target = closest (DC mid or BB mid)
            target = mid_channel
            if bb_mid and (target is None or bb_mid < target):
                target = bb_mid

            # Calculate signal quality score
            rsi_score = max(0, (self.rsi_dc_max - rsi) / self.rsi_dc_max)
            vol_ratio = volumes[-1] / vol_avg if volumes and vol_avg > 0 else 1
            vol_score = min(1, vol_ratio / 3)
            quality = rsi_score * 0.5 + vol_score * 0.5

            return Signal(
                'BUY', pair, current['close'],
                f"DUAL CONFIRM V4: DC low={prev_lowest:.4f}, BB low={bb_lower:.4f}, "
                f"RSI={rsi:.1f}, vol={vol_ratio:.1f}x, bounce OK",
                stop_price=stop,
                target_price=target,
                rsi=rsi,
                confidence=max(0.80, quality)
            )

        else:
            # === CHECK EXIT (enhanced with V2 break-even stop) ===
            # Update trailing stop
            if current['close'] > position.highest_price:
                position.highest_price = current['close']
            new_stop = position.highest_price - atr * self.atr_stop_mult
            # Max stop loss cap
            max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < max_stop:
                new_stop = max_stop

            # V2: Break-even stop (Agent 2 winnaar)
            # Na +3% winst → stop mag niet lager dan entry + fee buffer
            if self.breakeven_stop:
                profit_pct = (current['close'] - position.entry_price) / position.entry_price * 100
                if profit_pct >= self.breakeven_trigger_pct:
                    breakeven_level = position.entry_price * 1.006  # +0.6% fee buffer
                    if new_stop < breakeven_level:
                        new_stop = breakeven_level

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100

            # Exit 1: Hard max loss cap
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal(
                    'SELL_STOP', pair, current['close'],
                    f"Max loss cap: {current['close']:.4f} < {hard_stop:.4f} "
                    f"(P&L={pnl_pct:+.1f}%, max={self.max_stop_loss_pct}%)",
                    rsi=rsi, confidence=0.95
                )

            # Exit 2: V3 Time max (force exit stale trades after 16 bars = 64h)
            if self.time_max_bars > 0 and position.entry_time > 0:
                # Bereken bars in trade via timestamps (4H = 14400 sec per bar)
                time_in_trade = candles[-1].get('time', 0) - position.entry_time
                bars_in_trade = time_in_trade / 14400 if time_in_trade > 0 else 0
                if bars_in_trade >= self.time_max_bars:
                    self.last_exit_bar = self.bar_count
                    self.last_exit_was_stop = bars_in_trade >= self.time_max_bars and pnl_pct < 0
                    return Signal(
                        'SELL_STOP' if pnl_pct < 0 else 'SELL_TARGET', pair, current['close'],
                        f"Time max: {bars_in_trade:.0f} bars >= {self.time_max_bars} "
                        f"(P&L={pnl_pct:+.1f}%)",
                        rsi=rsi, confidence=0.85
                    )

            # Exit 3: DC mid channel target
            if mid_channel and current['close'] >= mid_channel:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal(
                    'SELL_TARGET', pair, current['close'],
                    f"DC mid target: {current['close']:.4f} >= {mid_channel:.4f} "
                    f"(P&L={pnl_pct:+.1f}%)",
                    rsi=rsi, confidence=0.9
                )

            # Exit 3: BB mid target
            if bb_mid and current['close'] >= bb_mid:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal(
                    'SELL_TARGET', pair, current['close'],
                    f"BB mid target: {current['close']:.4f} >= {bb_mid:.4f} "
                    f"(P&L={pnl_pct:+.1f}%)",
                    rsi=rsi, confidence=0.9
                )

            # Exit 4: RSI overbought
            if rsi > self.rsi_sell:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal(
                    'SELL_TARGET', pair, current['close'],
                    f"RSI overbought: RSI={rsi:.1f} > {self.rsi_sell} "
                    f"(P&L={pnl_pct:+.1f}%)",
                    rsi=rsi, confidence=0.85
                )

            # Exit 5: Trailing stop
            if current['close'] < position.stop_price:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal(
                    'SELL_STOP', pair, current['close'],
                    f"Trailing stop: {current['close']:.4f} < {position.stop_price:.4f} "
                    f"(P&L={pnl_pct:+.1f}%)",
                    rsi=rsi, confidence=0.95
                )

            # Holding
            # Show closest target
            target = mid_channel
            if bb_mid and (target is None or bb_mid < target):
                target = bb_mid
            target_str = f"{target:.4f}" if target else "?"

            return Signal(
                'HOLD', pair, current['close'],
                f"Holding: P&L={pnl_pct:+.1f}%, stop={position.stop_price:.4f}, target={target_str}",
                stop_price=position.stop_price,
                target_price=target,
                rsi=rsi,
                confidence=0
            )
