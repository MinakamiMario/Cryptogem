#!/usr/bin/env python3
"""
V5 DEEP DIVE — RSI Recovery Exit tuning + ADX anomaly + best combos
=====================================================================
Diepere analyse van de top V5 vondsten:

  1. RSI Recovery Exit sweep (targets 40-55, min bars 1-5)
  2. ADX discrepancy check (waarom anders dan vorige ronde?)
  3. DC=15 BB=20 investigation (waarom beter?)
  4. Triple combo: RSI Recovery + DC=15 + best tweaks
  5. Robustness: hoe gevoelig is elke verbetering?
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
logger = logging.getLogger('v5_deep')


def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


class V5Strategy:
    """V5 strategy met alle tweakbare parameters."""

    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8, volume_min_pct=0.5,
                 use_volume_spike=True, volume_spike_mult=2.0,
                 use_vol_confirm=True, vol_confirm_mult=1.0,
                 use_breakeven_stop=True, breakeven_trigger_pct=3.0,
                 use_time_max=True, time_max_bars=10,
                 use_adx=False, adx_threshold=20,
                 use_rsi_recovery_exit=False, rsi_recovery_target=50,
                 rsi_recovery_min_bars=3,
                 use_dynamic_time_max=False, dynamic_time_max_rsi_threshold=40,
                 dynamic_time_max_extension=4):
        self.donchian_period = donchian_period
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.rsi_period = rsi_period
        self.rsi_max = rsi_max
        self.rsi_sell = rsi_sell
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.max_stop_loss_pct = max_stop_loss_pct
        self.cooldown_bars = cooldown_bars
        self.cooldown_after_stop = cooldown_after_stop
        self.volume_min_pct = volume_min_pct
        self.use_volume_spike = use_volume_spike
        self.volume_spike_mult = volume_spike_mult
        self.use_vol_confirm = use_vol_confirm
        self.vol_confirm_mult = vol_confirm_mult
        self.use_breakeven_stop = use_breakeven_stop
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.use_time_max = use_time_max
        self.time_max_bars = time_max_bars
        self.use_adx = use_adx
        self.adx_threshold = adx_threshold
        self.use_rsi_recovery_exit = use_rsi_recovery_exit
        self.rsi_recovery_target = rsi_recovery_target
        self.rsi_recovery_min_bars = rsi_recovery_min_bars
        self.use_dynamic_time_max = use_dynamic_time_max
        self.dynamic_time_max_rsi_threshold = dynamic_time_max_rsi_threshold
        self.dynamic_time_max_extension = dynamic_time_max_extension
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def _calc_adx(self, highs, lows, closes, period=14):
        if len(highs) < period * 2:
            return None
        plus_dm, minus_dm, tr_list = [], [], []
        for i in range(1, len(highs)):
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            plus_dm.append(max(up, 0) if up > down else 0)
            minus_dm.append(max(down, 0) if down > up else 0)
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            tr_list.append(tr)
        if len(tr_list) < period:
            return None
        s_tr = sum(tr_list[:period])
        s_plus = sum(plus_dm[:period])
        s_minus = sum(minus_dm[:period])
        dx_vals = []
        for i in range(period, len(tr_list)):
            s_tr = s_tr - s_tr/period + tr_list[i]
            s_plus = s_plus - s_plus/period + plus_dm[i]
            s_minus = s_minus - s_minus/period + minus_dm[i]
            if s_tr == 0: continue
            p_di = 100*s_plus/s_tr
            m_di = 100*s_minus/s_tr
            di_sum = p_di + m_di
            dx_vals.append(100*abs(p_di-m_di)/di_sum if di_sum > 0 else 0)
        if len(dx_vals) < period:
            return None
        adx = sum(dx_vals[:period])/period
        for i in range(period, len(dx_vals)):
            adx = (adx*(period-1)+dx_vals[i])/period
        return adx

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)
        _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1], self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
            return Signal('WAIT', pair, 0, 'Indicators niet klaar', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # EXIT
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars_in_trade = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0

            if close > position.highest_price:
                position.highest_price = close

            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            if self.use_breakeven_stop:
                profit_pct = (close - entry_price) / entry_price * 100
                if profit_pct >= self.breakeven_trigger_pct:
                    be_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < be_level:
                        new_stop = be_level

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)

            # Time max (with dynamic extension)
            if self.use_time_max:
                eff_max = self.time_max_bars
                if self.use_dynamic_time_max and rsi > self.dynamic_time_max_rsi_threshold:
                    eff_max = self.time_max_bars + self.dynamic_time_max_extension
                if bars_in_trade >= eff_max:
                    return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)

            # RSI recovery exit (BEFORE DC/BB targets)
            if self.use_rsi_recovery_exit and bars_in_trade >= self.rsi_recovery_min_bars:
                if rsi >= self.rsi_recovery_target:
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

        # ENTRY
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)

        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)
        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)

        if self.use_volume_spike and volumes:
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return Signal('WAIT', pair, close, 'Volume spike', confidence=0)

        if self.use_vol_confirm and len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, 'Vol confirm', confidence=0)

        if self.use_adx:
            adx = self._calc_adx(highs, lows, closes)
            if adx is not None and adx < self.adx_threshold:
                return Signal('WAIT', pair, close, f'ADX {adx:.1f}', confidence=0)

        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = min(1, volumes[-1] / vol_avg / 3) if vol_avg > 0 else 0
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return Signal('BUY', pair, close, 'V5 ENTRY', confidence=quality, stop_price=stop)


@dataclass
class BacktestPosition:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float
    side: str = 'long'


def run_backtest(all_candles, strategy_factory, max_positions=1, position_size=2000, label=""):
    coins = [k for k in all_candles if not k.startswith('_')]
    strategies = {pair: strategy_factory() for pair in coins}
    max_bars = max(len(all_candles[p]) for p in coins if p in all_candles and not p.startswith('_'))

    positions = {}
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0

    for bar_idx in range(50, max_bars):
        buy_signals, sell_signals = [], []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles): continue
            window = candles[:bar_idx + 1]
            pos = positions.get(pair)

            mock_pos = None
            if pos:
                mock_pos = type('P', (), {
                    'entry_price': pos.entry_price, 'stop_price': pos.stop_price,
                    'highest_price': pos.highest_price, 'side': 'long', 'entry_bar': pos.entry_bar
                })()

            signal = strategies[pair].analyze(window, mock_pos, pair)
            if signal.action == 'SELL' and pair in positions:
                sell_signals.append((pair, signal))
            elif signal.action == 'BUY' and pair not in positions:
                buy_signals.append((pair, signal, candles[bar_idx]))

        for pair, signal in sell_signals:
            pos = positions[pair]
            gross = (signal.price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fee
            equity += net
            s = strategies[pair]
            s.last_exit_bar = s.bar_count
            s.last_exit_was_stop = 'STOP' in signal.reason
            trades.append({'pair': pair, 'entry': pos.entry_price, 'exit': signal.price,
                           'pnl': net, 'reason': signal.reason, 'bars': bar_idx - pos.entry_bar})
            del positions[pair]

        if len(positions) < max_positions and buy_signals:
            buy_signals.sort(key=lambda x: x[1].confidence, reverse=True)
            for pair, signal, _ in buy_signals:
                if len(positions) >= max_positions: break
                positions[pair] = BacktestPosition(
                    pair=pair, entry_price=signal.price, entry_bar=bar_idx,
                    stop_price=signal.stop_price or signal.price*0.85,
                    highest_price=signal.price, size_usd=position_size)

        if equity > peak_equity: peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_dd: max_dd = dd

    for pair, pos in list(positions.items()):
        candles = all_candles.get(pair, [])
        if candles:
            lp = candles[-1]['close']
            gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            equity += gross - fee
            trades.append({'pair': pair, 'entry': pos.entry_price, 'exit': lp,
                           'pnl': gross-fee, 'reason': 'END', 'bars': max_bars - pos.entry_bar})

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins)/len(trades)*100 if trades else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')
    avg_bars = sum(t['bars'] for t in trades) / len(trades) if trades else 0

    return {
        'label': label, 'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': wr, 'total_pnl': total_pnl, 'pf': pf, 'max_dd': max_dd,
        'avg_bars': avg_bars, 'trade_list': trades,
    }


def fmt(r, base_pnl=0):
    diff = r['total_pnl'] - base_pnl
    pf = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    return (f"  {r['label']:<60} | {r['trades']:>3}tr | WR {r['win_rate']:>5.1f}% | "
            f"${r['total_pnl']:>+8.0f} ({diff:>+6.0f}) | PF {pf:>7} | DD {r['max_dd']:>4.1f}% | "
            f"AvgB {r['avg_bars']:>4.1f}")


def main():
    data = fetch_all_candles()

    print()
    print("=" * 140)
    print("  V5 DEEP DIVE — RSI Recovery tuning, ADX anomaly, period combos")
    print("=" * 140)

    # Baseline V4
    base = run_backtest(data, lambda: V5Strategy(), label="V4 BASELINE")
    print(f"\n  BASELINE: {fmt(base)}")
    bp = base['total_pnl']

    # ==========================================
    # 1. RSI RECOVERY EXIT SWEEP
    # ==========================================
    print(f"\n  [1] RSI RECOVERY EXIT SWEEP")
    print("  " + "-" * 138)

    rsi_rec_results = []
    for target in [35, 38, 40, 42, 45, 48, 50, 55, 60]:
        for min_b in [1, 2, 3, 4, 5]:
            def f(t=target, m=min_b):
                return V5Strategy(use_rsi_recovery_exit=True, rsi_recovery_target=t, rsi_recovery_min_bars=m)
            r = run_backtest(data, f, label=f"RSI Recovery tgt={target} min={min_b}b")
            rsi_rec_results.append(r)

    # Print only the best per target
    by_target = {}
    for r in rsi_rec_results:
        tgt = r['label'].split('tgt=')[1].split(' ')[0]
        if tgt not in by_target or r['total_pnl'] > by_target[tgt]['total_pnl']:
            by_target[tgt] = r

    for tgt in sorted(by_target.keys(), key=int):
        print(fmt(by_target[tgt], bp))

    # Find overall best RSI recovery
    best_rsi = max(rsi_rec_results, key=lambda x: x['total_pnl'])
    print(f"\n  BEST RSI RECOVERY: {best_rsi['label']}")
    print(f"  {fmt(best_rsi, bp)}")

    # Show top 5
    top5_rsi = sorted(rsi_rec_results, key=lambda x: x['total_pnl'], reverse=True)[:5]
    print(f"\n  TOP 5 RSI Recovery configs:")
    for r in top5_rsi:
        print(fmt(r, bp))

    # ==========================================
    # 2. ADX INVESTIGATION — check with RSI<35 baseline
    # ==========================================
    print(f"\n  [2] ADX INVESTIGATION (V4 met RSI<40 vs RSI<35)")
    print("  " + "-" * 138)

    # Test ADX with RSI<35 (like in the previous test round)
    adx_tests = [
        ("ADX>15 RSI<35", dict(use_adx=True, adx_threshold=15, rsi_max=35)),
        ("ADX>20 RSI<35", dict(use_adx=True, adx_threshold=20, rsi_max=35)),
        ("ADX>25 RSI<35", dict(use_adx=True, adx_threshold=25, rsi_max=35)),
        ("ADX>15 RSI<40", dict(use_adx=True, adx_threshold=15, rsi_max=40)),
        ("ADX>20 RSI<40", dict(use_adx=True, adx_threshold=20, rsi_max=40)),
        ("ADX>25 RSI<40", dict(use_adx=True, adx_threshold=25, rsi_max=40)),
        # Without VolConfirm (maybe that's the difference)
        ("ADX>20 RSI<35 NO-VolConf", dict(use_adx=True, adx_threshold=20, rsi_max=35, use_vol_confirm=False)),
        ("ADX>20 RSI<40 NO-VolConf", dict(use_adx=True, adx_threshold=20, rsi_max=40, use_vol_confirm=False)),
        # Without TimeMax
        ("ADX>20 RSI<35 NO-TimeMax", dict(use_adx=True, adx_threshold=20, rsi_max=35, use_time_max=False)),
    ]

    for name, params in adx_tests:
        def f(p=params):
            return V5Strategy(**p)
        r = run_backtest(data, f, label=name)
        print(fmt(r, bp))

    # ==========================================
    # 3. DONCHIAN PERIOD DEEP DIVE (DC=10/15 are promising)
    # ==========================================
    print(f"\n  [3] DONCHIAN PERIOD DEEP DIVE")
    print("  " + "-" * 138)

    for dc in [8, 10, 12, 15, 18, 20]:
        def f(d=dc):
            return V5Strategy(donchian_period=d)
        r = run_backtest(data, f, label=f"DC={dc} (BB=20 default)")
        print(fmt(r, bp))

    # ==========================================
    # 4. RSI RECOVERY + DC PERIOD COMBOS
    # ==========================================
    print(f"\n  [4] RSI RECOVERY + DC PERIOD COMBOS")
    print("  " + "-" * 138)

    combo_results = []
    best_rsi_tgt = int(best_rsi['label'].split('tgt=')[1].split(' ')[0])
    best_rsi_min = int(best_rsi['label'].split('min=')[1].split('b')[0])

    combos = [
        (f"RSIRecov({best_rsi_tgt},{best_rsi_min}b) + DC=10", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=best_rsi_tgt,
            rsi_recovery_min_bars=best_rsi_min, donchian_period=10)),
        (f"RSIRecov({best_rsi_tgt},{best_rsi_min}b) + DC=15", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=best_rsi_tgt,
            rsi_recovery_min_bars=best_rsi_min, donchian_period=15)),
        (f"RSIRecov(45,2b) + DC=15", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, donchian_period=15)),
        (f"RSIRecov(45,2b) + DC=10", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, donchian_period=10)),
        (f"RSIRecov(45,2b) + DynTimeMax(40,+4b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, use_dynamic_time_max=True,
            dynamic_time_max_rsi_threshold=40, dynamic_time_max_extension=4)),
        (f"RSIRecov(45,2b) + DC=15 + DynTime", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, donchian_period=15,
            use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=40,
            dynamic_time_max_extension=4)),
        # ADX + RSI Recovery
        (f"RSIRecov(45,2b) + ADX>20", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, use_adx=True, adx_threshold=20)),
        (f"RSIRecov(45,2b) + ADX>15", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, use_adx=True, adx_threshold=15)),
        # RSI<35 variants
        (f"RSIRecov(45,2b) + RSI<35", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, rsi_max=35)),
        (f"RSIRecov(45,2b) + RSI<35 + DC=15", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, rsi_max=35, donchian_period=15)),
    ]

    for name, params in combos:
        def f(p=params):
            return V5Strategy(**p)
        r = run_backtest(data, f, label=name)
        combo_results.append(r)
        print(fmt(r, bp))

    # ==========================================
    # 5. ROBUSTNESS CHECK — vary one param at a time from best config
    # ==========================================
    print(f"\n  [5] ROBUSTNESS OF TOP CONFIGS")
    print("  " + "-" * 138)

    # RSI Recovery is the winner — how robust is it?
    print(f"\n  RSI Recovery robustness (target=45 is winner):")
    for tgt in [40, 42, 43, 44, 45, 46, 47, 48, 50]:
        def f(t=tgt):
            return V5Strategy(use_rsi_recovery_exit=True, rsi_recovery_target=t, rsi_recovery_min_bars=2)
        r = run_backtest(data, f, label=f"RSI Recovery tgt={tgt} (min=2b)")
        print(fmt(r, bp))

    print(f"\n  RSI Recovery robustness (min_bars sweep, target=45):")
    for mb in [1, 2, 3, 4, 5, 6]:
        def f(m=mb):
            return V5Strategy(use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=m)
        r = run_backtest(data, f, label=f"RSI Recovery min_bars={mb} (tgt=45)")
        print(fmt(r, bp))

    # ==========================================
    # 6. ULTIMATE BEST CANDIDATES
    # ==========================================
    print(f"\n  [6] ULTIMATE V5 CANDIDATES")
    print("  " + "-" * 138)

    ultimate = [
        ("V5-A: V4 + RSIRecov(45,2b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2)),
        ("V5-B: V4 + DC=15", dict(donchian_period=15)),
        ("V5-C: V4 + RSIRecov(45,2b) + DC=15", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, donchian_period=15)),
        ("V5-D: V4 + DynTimeMax(40,+4b)", dict(
            use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=40,
            dynamic_time_max_extension=4)),
        ("V5-E: V4 + RSIRecov(45,2b) + DynTime(40,+4b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45,
            rsi_recovery_min_bars=2, use_dynamic_time_max=True,
            dynamic_time_max_rsi_threshold=40, dynamic_time_max_extension=4)),
    ]

    ult_results = [base]
    for name, params in ultimate:
        def f(p=params):
            return V5Strategy(**p)
        r = run_backtest(data, f, label=name)
        ult_results.append(r)
        print(fmt(r, bp))

    # Trade details for each
    print(f"\n  TRADE DETAILS PER V5 CANDIDATE:")
    print("  " + "=" * 138)

    for r in ult_results:
        print(f"\n  {r['label']}: {r['trades']}tr | WR {r['win_rate']:.1f}% | P&L ${r['total_pnl']:+,.2f} | PF {r['pf']:.2f} | DD {r['max_dd']:.1f}%")
        for t in r['trade_list']:
            icon = "✅" if t['pnl'] > 0 else "❌"
            print(f"    {icon} {t['pair']:<14} | ${t['entry']:.4f} → ${t['exit']:.4f} | "
                  f"P&L ${t['pnl']:>+8.2f} | {t['bars']:>2}b | {t['reason']}")

    print()
    print("=" * 140)
    print("  CONCLUSIE")
    print("=" * 140)

    all_sorted = sorted(ult_results, key=lambda x: x['total_pnl'], reverse=True)
    for i, r in enumerate(all_sorted):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1}"
        diff = r['total_pnl'] - bp
        pf = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
        print(f"  {medal} {r['label']:<55} | P&L ${r['total_pnl']:>+8.0f} ({diff:>+6.0f}) | "
              f"PF {pf:>7} | WR {r['win_rate']:>5.1f}% | DD {r['max_dd']:>4.1f}%")

    print()
    print("=" * 140)


if __name__ == '__main__':
    main()
