#!/usr/bin/env python3
"""
V6 EXPERIMENT — Prijsstructuur Filters
========================================
Test of we watervallen (mid-crash entries) kunnen filteren
zonder goede trades te verliezen.

Filters getest:
  A. SIMPLE: Bearish marubozu + consecutive red bars
  B. DECELERATION: ATR-normalized decline + bar analysis
  C. WICK: Minimum lower wick requirement op entry bar
  D. MOMENTUM: Decline rate over 3 bars + body/wick ratio
  E. COMBOS: Beste combinaties

Gebruik:
    python backtest_v6_price_structure.py
"""
import os
import sys
import json
import logging
from pathlib import Path
from dataclasses import dataclass

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('v6_price_structure')


def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        logger.info(f"Cache geladen: {len([k for k in cache if not k.startswith('_')])} coins")
        return cache
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


class V6Strategy:
    """V5 DualConfirm + prijsstructuur filters."""

    def __init__(self,
                 # V5 standard
                 rsi_recovery_target=45,
                 rsi_recovery_min_bars=2,
                 # V6 PRICE STRUCTURE FILTERS
                 # A: Marubozu filter — reject als entry bar een grote bearish body is zonder wick
                 use_marubozu_filter=False,
                 marubozu_body_pct=80,        # body > X% van total range = marubozu
                 marubozu_min_consec_red=3,    # min X opeenvolgende rode candles
                 # B: Lower wick minimum — entry bar moet bewijs van kopers tonen
                 use_wick_filter=False,
                 min_lower_wick_pct=20,        # lower wick moet > X% van total range zijn
                 # C: Decline rate — reject als prijs te snel daalt
                 use_decline_filter=False,
                 decline_lookback=3,           # check over X bars
                 decline_atr_mult=2.0,         # decline > X * ATR = te snel
                 # D: Deceleration combo — decline + bar analyse
                 use_decel_filter=False,
                 decel_decline_atr=2.0,        # decline threshold (ATR mult)
                 decel_body_pct=80,            # body > X% = geen kopers
                 decel_wick_pct=20,            # lower wick < X% = geen kopers
                 ):
        # V5 base
        self.donchian_period = 20
        self.bb_period = 20
        self.bb_dev = 2.0
        self.rsi_period = 14
        self.rsi_max = 40
        self.rsi_sell = 70
        self.atr_period = 14
        self.atr_stop_mult = 2.0
        self.max_stop_loss_pct = 15.0
        self.cooldown_bars = 4
        self.cooldown_after_stop = 8
        self.volume_spike_mult = 2.0
        self.vol_confirm_mult = 1.0
        self.breakeven_trigger_pct = 3.0
        self.time_max_bars = 10
        self.rsi_recovery_target = rsi_recovery_target
        self.rsi_recovery_min_bars = rsi_recovery_min_bars

        # V6 filters
        self.use_marubozu_filter = use_marubozu_filter
        self.marubozu_body_pct = marubozu_body_pct
        self.marubozu_min_consec_red = marubozu_min_consec_red
        self.use_wick_filter = use_wick_filter
        self.min_lower_wick_pct = min_lower_wick_pct
        self.use_decline_filter = use_decline_filter
        self.decline_lookback = decline_lookback
        self.decline_atr_mult = decline_atr_mult
        self.use_decel_filter = use_decel_filter
        self.decel_decline_atr = decel_decline_atr
        self.decel_body_pct = decel_body_pct
        self.decel_wick_pct = decel_wick_pct

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        opens = [c['open'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
            return Signal('WAIT', pair, 0, 'Indicators niet klaar', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        high = current['high']
        open_price = current['open']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # ==========================================
        # EXIT LOGICA (V5 identiek)
        # ==========================================
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars_in_trade = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0
            if close > position.highest_price:
                position.highest_price = close
            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop
            profit_pct = (close - entry_price) / entry_price * 100
            if profit_pct >= self.breakeven_trigger_pct:
                be_level = entry_price * (1 + KRAKEN_FEE * 2)
                if new_stop < be_level:
                    new_stop = be_level
            if new_stop > position.stop_price:
                position.stop_price = new_stop

            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)
            if bars_in_trade >= self.time_max_bars:
                return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)
            if bars_in_trade >= self.rsi_recovery_min_bars and rsi >= self.rsi_recovery_target:
                return Signal('SELL', pair, close, 'RSI RECOVERY', confidence=0.85)
            if close >= mid_channel:
                return Signal('SELL', pair, close, 'DC TARGET', confidence=0.9)
            if close >= bb_mid:
                return Signal('SELL', pair, close, 'BB TARGET', confidence=0.85)
            if rsi > self.rsi_sell:
                return Signal('SELL', pair, close, 'RSI EXIT', confidence=0.8)
            if close < position.stop_price:
                return Signal('SELL', pair, close, 'TRAIL STOP', confidence=1.0)
            return Signal('HOLD', pair, close, 'In positie', confidence=0.5)

        # ==========================================
        # ENTRY LOGICA
        # ==========================================
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * 0.5:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)

        # DUAL CONFIRM
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)
        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)

        # Volume spike
        if volumes and vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
            return Signal('WAIT', pair, close, 'Volume spike <2x', confidence=0)

        # Volume bar-to-bar confirm
        if len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, 'Vol confirm <1x', confidence=0)

        # ==========================================
        # V6 PRIJSSTRUCTUUR FILTERS
        # ==========================================
        bar_range = high - low
        if bar_range <= 0:
            bar_range = 0.0001  # prevent div by zero

        body = abs(close - open_price)
        lower_wick = min(close, open_price) - low
        is_bearish = close < open_price

        body_pct = body / bar_range * 100
        lower_wick_pct = lower_wick / bar_range * 100

        # Filter A: Marubozu + consecutive red bars
        if self.use_marubozu_filter:
            # Check consecutive red bars
            consec_red = 0
            for i in range(len(candles) - 1, max(0, len(candles) - 10), -1):
                c = candles[i]
                if c['close'] < c['open']:
                    consec_red += 1
                else:
                    break

            if (is_bearish and body_pct > self.marubozu_body_pct
                    and consec_red >= self.marubozu_min_consec_red):
                return Signal('WAIT', pair, close,
                             f'MARUBOZU FILTER: body {body_pct:.0f}% + {consec_red} red bars', confidence=0)

        # Filter B: Minimum lower wick (bewijs van kopers)
        if self.use_wick_filter:
            if lower_wick_pct < self.min_lower_wick_pct:
                return Signal('WAIT', pair, close,
                             f'WICK FILTER: lower wick {lower_wick_pct:.0f}% < {self.min_lower_wick_pct}%', confidence=0)

        # Filter C: Decline rate (te snelle daling)
        if self.use_decline_filter and atr > 0:
            lookback = min(self.decline_lookback, len(candles) - 1)
            if lookback > 0:
                decline = candles[-lookback - 1]['close'] - close
                decline_atr = decline / atr
                if decline_atr > self.decline_atr_mult:
                    return Signal('WAIT', pair, close,
                                 f'DECLINE FILTER: {decline_atr:.1f}x ATR decline > {self.decline_atr_mult}x', confidence=0)

        # Filter D: Deceleration combo (decline + geen kopers op entry bar)
        if self.use_decel_filter and atr > 0:
            lookback = min(3, len(candles) - 1)
            if lookback > 0:
                decline = candles[-lookback - 1]['close'] - close
                decline_atr = decline / atr

                # Alleen rejecten als: snelle daling EN geen kopers zichtbaar
                if (decline_atr > self.decel_decline_atr
                        and is_bearish
                        and body_pct > self.decel_body_pct
                        and lower_wick_pct < self.decel_wick_pct):
                    return Signal('WAIT', pair, close,
                                 f'DECEL FILTER: {decline_atr:.1f}x ATR + body {body_pct:.0f}% + wick {lower_wick_pct:.0f}%',
                                 confidence=0)

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = min(1, (volumes[-1] / vol_avg / 3)) if volumes and vol_avg > 0 else 0
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return Signal('BUY', pair, close, 'DUAL CONFIRM V6', confidence=quality, stop_price=stop)


# ============================================================
# PORTFOLIO BACKTEST ENGINE
# ============================================================

@dataclass
class BacktestPosition:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float
    side: str = 'long'


def run_backtest(all_candles, strategy_factory, label=""):
    coins = [k for k in all_candles if not k.startswith('_')]
    strategies = {pair: strategy_factory() for pair in coins}
    max_bars = max(len(all_candles[p]) for p in coins)

    positions = {}
    trades = []
    filtered_signals = []  # Track welke signalen gefilterd werden
    equity = 2000
    initial_equity = 2000
    peak_equity = 2000
    max_dd = 0

    for bar_idx in range(50, max_bars):
        buy_signals = []
        sell_signals = []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue
            window = candles[:bar_idx + 1]
            pos = positions.get(pair)

            mock_pos = None
            if pos:
                mock_pos = type('Pos', (), {
                    'entry_price': pos.entry_price, 'stop_price': pos.stop_price,
                    'highest_price': pos.highest_price, 'side': 'long',
                    'entry_bar': pos.entry_bar,
                })()

            sig = strategies[pair].analyze(window, mock_pos, pair)

            if sig.action == 'SELL' and pair in positions:
                sell_signals.append((pair, sig))
            elif sig.action == 'BUY' and pair not in positions:
                buy_signals.append((pair, sig, candles[bar_idx]))
            elif sig.action == 'WAIT' and 'FILTER' in sig.reason and pair not in positions:
                # Track gefilterde signalen
                filtered_signals.append({
                    'pair': pair, 'bar_idx': bar_idx,
                    'price': sig.price, 'reason': sig.reason,
                })

        # SELL
        for pair, sig in sell_signals:
            pos = positions[pair]
            gross = (sig.price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fee
            equity += net
            strategies[pair].last_exit_bar = strategies[pair].bar_count
            strategies[pair].last_exit_was_stop = 'STOP' in sig.reason
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': sig.price,
                'pnl': net, 'pnl_pct': (sig.price - pos.entry_price) / pos.entry_price * 100,
                'reason': sig.reason, 'bars': bar_idx - pos.entry_bar,
            })
            del positions[pair]

        # BUY
        if len(positions) < 1 and buy_signals:
            def rank(item):
                p, s, c = item
                cd = all_candles.get(p, [])
                vols = [x.get('volume', 0) for x in cd[max(0, bar_idx-20):bar_idx+1]]
                if vols and len(vols) > 1:
                    avg = sum(vols[:-1]) / max(1, len(vols)-1)
                    return vols[-1] / avg if avg > 0 else 0
                return 0
            buy_signals.sort(key=rank, reverse=True)
            pair, sig, _ = buy_signals[0]
            positions[pair] = BacktestPosition(
                pair=pair, entry_price=sig.price, entry_bar=bar_idx,
                stop_price=sig.stop_price or sig.price * 0.85,
                highest_price=sig.price, size_usd=2000,
            )

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100
        if dd > max_dd:
            max_dd = dd

    # Close remaining
    for pair, pos in list(positions.items()):
        candles = all_candles.get(pair, [])
        if candles:
            last = candles[-1]['close']
            gross = (last - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fee
            equity += net
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': last,
                'pnl': net, 'pnl_pct': (last - pos.entry_price) / pos.entry_price * 100,
                'reason': 'END', 'bars': max_bars - pos.entry_bar,
            })

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    return {
        'label': label,
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': wr, 'total_pnl': total_pnl, 'roi': total_pnl / initial_equity * 100,
        'pf': pf, 'max_dd': max_dd,
        'avg_bars': sum(t['bars'] for t in trades) / len(trades) if trades else 0,
        'trade_list': trades,
        'filtered_count': len(filtered_signals),
        'filtered_signals': filtered_signals,
    }


def main():
    data = fetch_all_candles()

    print()
    print("=" * 140)
    print("  V6 PRIJSSTRUCTUUR EXPERIMENT — Waterval-detectie filters")
    print("  Base: V5 DualConfirm + RSI Recovery (t=45) | 1x$2000 | 0.26% fee | 60d | 285 coins")
    print("=" * 140)

    configs = [
        # Baseline V5
        {'label': 'V5 BASELINE (geen filter)',
         'marubozu': False, 'wick': False, 'decline': False, 'decel': False},

        # === A: MARUBOZU FILTER ===
        {'label': 'A1: Marubozu 80% + 3 red',
         'marubozu': True, 'maru_body': 80, 'maru_red': 3,
         'wick': False, 'decline': False, 'decel': False},
        {'label': 'A2: Marubozu 70% + 3 red',
         'marubozu': True, 'maru_body': 70, 'maru_red': 3,
         'wick': False, 'decline': False, 'decel': False},
        {'label': 'A3: Marubozu 80% + 2 red',
         'marubozu': True, 'maru_body': 80, 'maru_red': 2,
         'wick': False, 'decline': False, 'decel': False},
        {'label': 'A4: Marubozu 70% + 2 red',
         'marubozu': True, 'maru_body': 70, 'maru_red': 2,
         'wick': False, 'decline': False, 'decel': False},

        # === B: WICK FILTER ===
        {'label': 'B1: Min wick 20%',
         'marubozu': False, 'wick': True, 'wick_pct': 20,
         'decline': False, 'decel': False},
        {'label': 'B2: Min wick 15%',
         'marubozu': False, 'wick': True, 'wick_pct': 15,
         'decline': False, 'decel': False},
        {'label': 'B3: Min wick 10%',
         'marubozu': False, 'wick': True, 'wick_pct': 10,
         'decline': False, 'decel': False},
        {'label': 'B4: Min wick 30%',
         'marubozu': False, 'wick': True, 'wick_pct': 30,
         'decline': False, 'decel': False},

        # === C: DECLINE RATE ===
        {'label': 'C1: Decline >2.0 ATR / 3 bars',
         'marubozu': False, 'wick': False,
         'decline': True, 'dec_look': 3, 'dec_atr': 2.0, 'decel': False},
        {'label': 'C2: Decline >2.5 ATR / 3 bars',
         'marubozu': False, 'wick': False,
         'decline': True, 'dec_look': 3, 'dec_atr': 2.5, 'decel': False},
        {'label': 'C3: Decline >3.0 ATR / 3 bars',
         'marubozu': False, 'wick': False,
         'decline': True, 'dec_look': 3, 'dec_atr': 3.0, 'decel': False},
        {'label': 'C4: Decline >2.0 ATR / 5 bars',
         'marubozu': False, 'wick': False,
         'decline': True, 'dec_look': 5, 'dec_atr': 2.0, 'decel': False},

        # === D: DECELERATION COMBO ===
        {'label': 'D1: Decel 2.0 ATR + body 80% + wick 20%',
         'marubozu': False, 'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 2.0, 'decel_body': 80, 'decel_wick': 20},
        {'label': 'D2: Decel 1.5 ATR + body 80% + wick 20%',
         'marubozu': False, 'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 1.5, 'decel_body': 80, 'decel_wick': 20},
        {'label': 'D3: Decel 2.0 ATR + body 70% + wick 25%',
         'marubozu': False, 'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 2.0, 'decel_body': 70, 'decel_wick': 25},
        {'label': 'D4: Decel 1.5 ATR + body 70% + wick 25%',
         'marubozu': False, 'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 1.5, 'decel_body': 70, 'decel_wick': 25},
        {'label': 'D5: Decel 2.5 ATR + body 80% + wick 15%',
         'marubozu': False, 'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 2.5, 'decel_body': 80, 'decel_wick': 15},

        # === E: COMBOS ===
        {'label': 'E1: Marubozu 80%/3red + Wick 15%',
         'marubozu': True, 'maru_body': 80, 'maru_red': 3,
         'wick': True, 'wick_pct': 15, 'decline': False, 'decel': False},
        {'label': 'E2: Decel 2.0/80/20 + Wick 15%',
         'marubozu': False, 'wick': True, 'wick_pct': 15,
         'decline': False, 'decel': True, 'decel_atr': 2.0, 'decel_body': 80, 'decel_wick': 20},
        {'label': 'E3: Marubozu 80%/3red + Decel 2.0/80/20',
         'marubozu': True, 'maru_body': 80, 'maru_red': 3,
         'wick': False, 'decline': False,
         'decel': True, 'decel_atr': 2.0, 'decel_body': 80, 'decel_wick': 20},
    ]

    results = []

    for i, cfg in enumerate(configs):
        def make_strategy(c=cfg):
            return V6Strategy(
                use_marubozu_filter=c.get('marubozu', False),
                marubozu_body_pct=c.get('maru_body', 80),
                marubozu_min_consec_red=c.get('maru_red', 3),
                use_wick_filter=c.get('wick', False),
                min_lower_wick_pct=c.get('wick_pct', 20),
                use_decline_filter=c.get('decline', False),
                decline_lookback=c.get('dec_look', 3),
                decline_atr_mult=c.get('dec_atr', 2.0),
                use_decel_filter=c.get('decel', False),
                decel_decline_atr=c.get('decel_atr', 2.0),
                decel_body_pct=c.get('decel_body', 80),
                decel_wick_pct=c.get('decel_wick', 20),
            )

        r = run_backtest(data, make_strategy, label=cfg['label'])
        results.append(r)
        logger.info(f"  [{i+1}/{len(configs)}] {cfg['label']}: "
                     f"P&L ${r['total_pnl']:+,.0f}, WR {r['win_rate']:.1f}%, "
                     f"PF {r['pf']:.2f}, {r['trades']}tr, filtered {r['filtered_count']}")

    # ==========================================
    # RESULTATEN
    # ==========================================
    baseline = results[0]

    print()
    print("=" * 155)
    print("  RESULTATEN")
    print("=" * 155)
    print(f"  {'CONFIG':<45} | {'#TR':>4} | {'WR':>6} | {'P&L':>12} | {'vs V5':>8} | "
          f"{'PF':>7} | {'DD%':>6} | {'Bars':>5} | {'FILT':>4} | {'W':>3} | {'L':>3}")
    print("  " + "-" * 153)

    for r in results:
        diff = r['total_pnl'] - baseline['total_pnl']
        better = "✅" if diff > 0 else "🟡" if diff == 0 else "❌"
        print(f"  {r['label']:<45} | {r['trades']:>4} | {r['win_rate']:>5.1f}% | "
              f"${r['total_pnl']:>+9,.0f} | ${diff:>+6,.0f}{better} | "
              f"{r['pf']:>6.2f} | {r['max_dd']:>5.1f}% | {r['avg_bars']:>4.1f} | "
              f"{r['filtered_count']:>4} | {r['wins']:>3} | {r['losses']:>3}")

    # ==========================================
    # TRADE DETAIL vergelijking: V5 vs beste V6
    # ==========================================
    # Vind de beste V6 (hoogste P&L die ook minder verlies heeft)
    v5_losses = baseline['losses']
    better_configs = [r for r in results[1:] if r['losses'] < v5_losses or r['total_pnl'] > baseline['total_pnl']]

    if better_configs:
        best_v6 = max(better_configs, key=lambda x: x['total_pnl'])
    else:
        best_v6 = max(results[1:], key=lambda x: x['total_pnl'])

    print()
    print("=" * 155)
    print(f"  TRADE VERGELIJKING: V5 Baseline vs {best_v6['label']}")
    print("=" * 155)

    print(f"\n  V5 BASELINE ({baseline['trades']} trades, WR {baseline['win_rate']:.1f}%, "
          f"P&L ${baseline['total_pnl']:+,.2f}):")
    for j, t in enumerate(baseline['trade_list']):
        icon = "✅" if t['pnl'] > 0 else "❌"
        print(f"    {icon} {j+1:>2}. {t['pair']:<14} | ${t['entry']:.6f} → ${t['exit']:.6f} | "
              f"P&L ${t['pnl']:>+8.2f} ({t['pnl_pct']:>+6.2f}%) | {t['bars']:>3}b | {t['reason']}")

    print(f"\n  {best_v6['label']} ({best_v6['trades']} trades, WR {best_v6['win_rate']:.1f}%, "
          f"P&L ${best_v6['total_pnl']:+,.2f}):")
    for j, t in enumerate(best_v6['trade_list']):
        icon = "✅" if t['pnl'] > 0 else "❌"
        print(f"    {icon} {j+1:>2}. {t['pair']:<14} | ${t['entry']:.6f} → ${t['exit']:.6f} | "
              f"P&L ${t['pnl']:>+8.2f} ({t['pnl_pct']:>+6.2f}%) | {t['bars']:>3}b | {t['reason']}")

    # ==========================================
    # GEFILTERDE SIGNALEN ANALYSE
    # ==========================================
    if best_v6['filtered_signals']:
        print()
        print("=" * 155)
        print(f"  GEFILTERDE SIGNALEN door {best_v6['label']}")
        print("=" * 155)
        for fs in best_v6['filtered_signals'][:30]:
            print(f"    ✋ {fs['pair']:<14} @ ${fs['price']:.6f} | {fs['reason']}")
        if len(best_v6['filtered_signals']) > 30:
            print(f"    ... en {len(best_v6['filtered_signals']) - 30} meer")

    # ==========================================
    # RANKING
    # ==========================================
    print()
    print("=" * 155)
    print("  RANKING OP P&L (top 10)")
    print("=" * 155)

    sorted_r = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
    for i, r in enumerate(sorted_r[:10]):
        diff = r['total_pnl'] - baseline['total_pnl']
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
        print(f"  {medal:<4} {r['label']:<45} | P&L ${r['total_pnl']:>+9,.0f} ({diff:>+6,.0f}) | "
              f"WR {r['win_rate']:>5.1f}% | PF {r['pf']:>6.2f} | DD {r['max_dd']:>5.1f}% | "
              f"{r['trades']}tr | filt {r['filtered_count']}")

    # ==========================================
    # CONCLUSIE
    # ==========================================
    print()
    print("=" * 155)
    print("  CONCLUSIE")
    print("=" * 155)

    improved = [r for r in results[1:] if r['total_pnl'] > baseline['total_pnl']]
    same = [r for r in results[1:] if abs(r['total_pnl'] - baseline['total_pnl']) < 1]
    worse = [r for r in results[1:] if r['total_pnl'] < baseline['total_pnl'] - 1]

    print(f"\n  Van {len(results)-1} filters:")
    print(f"    ✅ Verbeterd:    {len(improved)}")
    print(f"    🟡 Geen effect:  {len(same)}")
    print(f"    ❌ Verslechterd: {len(worse)}")

    if improved:
        best = max(improved, key=lambda x: x['total_pnl'])
        diff = best['total_pnl'] - baseline['total_pnl']
        print(f"\n  BESTE FILTER: {best['label']}")
        print(f"    P&L: ${best['total_pnl']:+,.2f} (${diff:+,.2f} vs V5)")
        print(f"    WR:  {best['win_rate']:.1f}% | PF: {best['pf']:.2f} | DD: {best['max_dd']:.1f}%")
        print(f"    Trades: {best['trades']} | Filtered: {best['filtered_count']} signalen")

    print()
    print("=" * 155)


if __name__ == '__main__':
    main()
