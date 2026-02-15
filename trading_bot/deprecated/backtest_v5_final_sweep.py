#!/usr/bin/env python3
"""
V5 FINAL SWEEP — Laatste experimenten voor de nacht
=====================================================
1. Probeer de AI3 verliezer te vermijden (de enige verliezer in V5)
2. Volume-gewogen RSI (VRSI) als alternatief
3. Body-to-wick ratio als filter (sterke bounces)
4. Meerdere timeframe RSI bevestiging
5. Signal quality gewogen exit (betere trades langer vasthouden)
6. Per-exit-type analyse: welke exits zijn het best?
"""
import os, sys, json, logging
from pathlib import Path
from dataclasses import dataclass

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from dotenv import load_dotenv
from strategy import Signal, calc_rsi, calc_atr, calc_donchian, calc_bollinger
load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('v5_final')


def fetch_all_candles():
    with open(CACHE_FILE) as f:
        return json.load(f)


class V5FinalStrategy:
    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8, volume_min_pct=0.5,
                 use_volume_spike=True, volume_spike_mult=2.0,
                 use_vol_confirm=True, vol_confirm_mult=1.0,
                 use_breakeven_stop=True, breakeven_trigger_pct=3.0,
                 use_time_max=True, time_max_bars=10,
                 # V5 RSI Recovery
                 use_rsi_recovery_exit=False, rsi_recovery_target=47, rsi_recovery_min_bars=2,
                 # Body-to-wick ratio filter
                 use_body_wick_filter=False, min_body_ratio=0.3,
                 # Volume acceleration (volume increasing for N bars)
                 use_vol_acceleration=False, vol_accel_bars=2,
                 # Min ATR% filter (avoid low volatility entries)
                 use_min_atr_pct=False, min_atr_pct=2.0,
                 # Price distance from BB lower (too far = falling knife)
                 use_bb_distance_filter=False, max_bb_distance_pct=5.0,
                 # Bounce strength (close should be significantly above low)
                 use_bounce_strength=False, min_bounce_pct=0.5,
                 # Trend filter: close above EMA for trend confirmation
                 use_ema_filter=False, ema_period=50, ema_side='below',
                 ):
        for k, v in locals().items():
            if k != 'self': setattr(self, k, v)
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def _calc_ema(self, data, period):
        if len(data) < period: return None
        mult = 2 / (period + 1)
        ema = sum(data[:period]) / period
        for price in data[period:]:
            ema = price * mult + ema * (1 - mult)
        return ema

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Data', confidence=0)

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]
        opens = [c['open'] for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)
        _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1], self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
            return Signal('WAIT', pair, 0, 'Indicators', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        high = current['high']
        opn = current['open']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # EXIT
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0

            if close > position.highest_price:
                position.highest_price = close

            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop: new_stop = hard_stop

            if self.use_breakeven_stop:
                pct = (close - entry_price) / entry_price * 100
                if pct >= self.breakeven_trigger_pct:
                    be = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < be: new_stop = be

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)
            if self.use_time_max and bars >= self.time_max_bars:
                return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)
            if self.use_rsi_recovery_exit and bars >= self.rsi_recovery_min_bars and rsi >= self.rsi_recovery_target:
                return Signal('SELL', pair, close, 'RSI RECOVERY', confidence=0.85)
            if close >= mid_channel:
                return Signal('SELL', pair, close, 'DC TARGET', confidence=0.9)
            if close >= bb_mid:
                return Signal('SELL', pair, close, 'BB TARGET', confidence=0.85)
            if rsi > self.rsi_sell:
                return Signal('SELL', pair, close, 'RSI EXIT', confidence=0.8)
            if close < position.stop_price:
                return Signal('SELL', pair, close, 'TRAIL STOP', confidence=1.0)

            return Signal('HOLD', pair, close, 'Hold', confidence=0.5)

        # ENTRY
        cd = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cd:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return Signal('WAIT', pair, close, 'Vol low', confidence=0)

        dc_sig = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_sig = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)
        if not (dc_sig and bb_sig):
            return Signal('WAIT', pair, close, 'No signal', confidence=0)

        if self.use_volume_spike and volumes:
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return Signal('WAIT', pair, close, 'Vol spike', confidence=0)

        if self.use_vol_confirm and len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, 'Vol conf', confidence=0)

        # Body-to-wick ratio: strong bounce has big body relative to total range
        if self.use_body_wick_filter:
            body = abs(close - opn)
            total_range = high - low
            if total_range > 0 and body / total_range < self.min_body_ratio:
                return Signal('WAIT', pair, close, 'Weak body', confidence=0)

        # Volume acceleration: volume increasing for N consecutive bars
        if self.use_vol_acceleration and len(volumes) >= self.vol_accel_bars + 1:
            accel = True
            for i in range(1, self.vol_accel_bars + 1):
                if volumes[-i] <= volumes[-i-1]:
                    accel = False
                    break
            if not accel:
                return Signal('WAIT', pair, close, 'No vol accel', confidence=0)

        # Min ATR% filter
        if self.use_min_atr_pct and close > 0:
            atr_pct = atr / close * 100
            if atr_pct < self.min_atr_pct:
                return Signal('WAIT', pair, close, f'ATR% {atr_pct:.1f}', confidence=0)

        # BB distance filter (don't buy if too far below BB lower)
        if self.use_bb_distance_filter and bb_lower > 0:
            dist_pct = (bb_lower - close) / bb_lower * 100
            if dist_pct > self.max_bb_distance_pct:
                return Signal('WAIT', pair, close, 'BB too far', confidence=0)

        # Bounce strength (close should be meaningfully above low)
        if self.use_bounce_strength and (high - low) > 0:
            bounce = (close - low) / (high - low) * 100
            if bounce < self.min_bounce_pct:
                return Signal('WAIT', pair, close, 'Weak bounce', confidence=0)

        # EMA filter
        if self.use_ema_filter:
            ema = self._calc_ema(closes, self.ema_period)
            if ema is not None:
                if self.ema_side == 'below' and close > ema:
                    return Signal('WAIT', pair, close, 'Above EMA', confidence=0)
                elif self.ema_side == 'above' and close < ema:
                    return Signal('WAIT', pair, close, 'Below EMA', confidence=0)

        stop = close - atr * self.atr_stop_mult
        hard = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard: stop = hard

        quality = max(0, (self.rsi_max - rsi) / self.rsi_max) * 0.4
        quality += min(1, ((prev_lowest - low) / prev_lowest * 20 if prev_lowest > 0 else 0)) * 0.3
        quality += min(1, volumes[-1] / vol_avg / 3 if vol_avg > 0 else 0) * 0.3

        return Signal('BUY', pair, close, 'V5 ENTRY', confidence=quality, stop_price=stop)


@dataclass
class BPos:
    pair: str; entry_price: float; entry_bar: int; stop_price: float
    highest_price: float; size_usd: float; side: str = 'long'


def run_bt(data, sfactory, label=""):
    coins = [k for k in data if not k.startswith('_')]
    strats = {p: sfactory() for p in coins}
    mb = max(len(data[p]) for p in coins if p in data and not p.startswith('_'))
    pos, trades = {}, []
    eq = 2000.0; peak = eq; mdd = 0

    for bi in range(50, mb):
        buys, sells = [], []
        for p in coins:
            c = data.get(p, [])
            if bi >= len(c): continue
            w = c[:bi+1]
            pp = pos.get(p)
            mp = None
            if pp:
                mp = type('P', (), {'entry_price': pp.entry_price, 'stop_price': pp.stop_price,
                                    'highest_price': pp.highest_price, 'side': 'long', 'entry_bar': pp.entry_bar})()
            sig = strats[p].analyze(w, mp, p)
            if sig.action == 'SELL' and p in pos: sells.append((p, sig))
            elif sig.action == 'BUY' and p not in pos: buys.append((p, sig, c[bi]))

        for p, s in sells:
            pp = pos[p]
            g = (s.price - pp.entry_price) / pp.entry_price * pp.size_usd
            f = pp.size_usd * KRAKEN_FEE + (pp.size_usd + g) * KRAKEN_FEE
            n = g - f; eq += n
            st = strats[p]; st.last_exit_bar = st.bar_count; st.last_exit_was_stop = 'STOP' in s.reason
            trades.append({'pair': p, 'entry': pp.entry_price, 'exit': s.price,
                           'pnl': n, 'reason': s.reason, 'bars': bi - pp.entry_bar})
            del pos[p]

        if len(pos) < 1 and buys:
            buys.sort(key=lambda x: x[1].confidence, reverse=True)
            for p, s, _ in buys[:1]:
                pos[p] = BPos(p, s.price, bi, s.stop_price or s.price*0.85, s.price, 2000.0)

        if eq > peak: peak = eq
        dd = (peak-eq)/peak*100 if peak > 0 else 0
        if dd > mdd: mdd = dd

    for p, pp in list(pos.items()):
        c = data.get(p, [])
        if c:
            lp = c[-1]['close']
            g = (lp-pp.entry_price)/pp.entry_price*pp.size_usd
            f = pp.size_usd*KRAKEN_FEE+(pp.size_usd+g)*KRAKEN_FEE
            eq += g-f
            trades.append({'pair':p,'entry':pp.entry_price,'exit':lp,'pnl':g-f,'reason':'END','bars':mb-pp.entry_bar})

    tp = sum(t['pnl'] for t in trades)
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    wr = len(w)/len(trades)*100 if trades else 0
    tw = sum(t['pnl'] for t in w)
    tl = abs(sum(t['pnl'] for t in l))
    pf = tw/tl if tl > 0 else float('inf')
    ab = sum(t['bars'] for t in trades)/len(trades) if trades else 0

    return {'label': label, 'trades': len(trades), 'win_rate': wr, 'total_pnl': tp,
            'pf': pf, 'max_dd': mdd, 'avg_bars': ab, 'trade_list': trades}


def fmt(r, bp=0):
    d = r['total_pnl'] - bp
    pf = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    return (f"  {r['label']:<62} | {r['trades']:>2}tr | WR {r['win_rate']:>5.1f}% | "
            f"${r['total_pnl']:>+8.0f} ({d:>+6.0f}) | PF {pf:>7} | DD {r['max_dd']:>4.1f}%")


def main():
    data = fetch_all_candles()

    print("\n" + "=" * 140)
    print("  V5 FINAL SWEEP — Laatste experimenten")
    print("=" * 140)

    # V4 and V5 baselines
    v4 = run_bt(data, lambda: V5FinalStrategy(), label="V4 BASELINE")
    v5 = run_bt(data, lambda: V5FinalStrategy(use_rsi_recovery_exit=True, rsi_recovery_target=47), label="V5 RSIRecov(47)")
    bp = v4['total_pnl']

    print(f"\n{fmt(v4)}")
    print(f"{fmt(v5, bp)}")

    # ==========================================
    # 1. BODY-WICK RATIO FILTER
    # ==========================================
    print(f"\n  [1] BODY-WICK RATIO FILTER")
    print("  " + "-" * 138)

    for ratio in [0.2, 0.3, 0.4, 0.5, 0.6]:
        r = run_bt(data, lambda rt=ratio: V5FinalStrategy(use_body_wick_filter=True, min_body_ratio=rt),
                   label=f"Body ratio > {ratio}")
        print(fmt(r, bp))

    # With V5
    for ratio in [0.3, 0.4, 0.5]:
        r = run_bt(data, lambda rt=ratio: V5FinalStrategy(
            use_rsi_recovery_exit=True, rsi_recovery_target=47,
            use_body_wick_filter=True, min_body_ratio=rt),
            label=f"V5 + Body ratio > {ratio}")
        print(fmt(r, bp))

    # ==========================================
    # 2. VOLUME ACCELERATION
    # ==========================================
    print(f"\n  [2] VOLUME ACCELERATION")
    print("  " + "-" * 138)

    for bars in [2, 3, 4]:
        r = run_bt(data, lambda b=bars: V5FinalStrategy(use_vol_acceleration=True, vol_accel_bars=b),
                   label=f"Vol accel {bars} bars")
        print(fmt(r, bp))

    # ==========================================
    # 3. MIN ATR% FILTER (avoid dead coins)
    # ==========================================
    print(f"\n  [3] MIN ATR% FILTER")
    print("  " + "-" * 138)

    for pct in [1.0, 2.0, 3.0, 4.0, 5.0]:
        r = run_bt(data, lambda p=pct: V5FinalStrategy(use_min_atr_pct=True, min_atr_pct=p),
                   label=f"Min ATR% > {pct}")
        print(fmt(r, bp))

    # ==========================================
    # 4. BB DISTANCE FILTER (avoid falling knives)
    # ==========================================
    print(f"\n  [4] BB DISTANCE FILTER")
    print("  " + "-" * 138)

    for dist in [2.0, 3.0, 5.0, 8.0, 10.0]:
        r = run_bt(data, lambda d=dist: V5FinalStrategy(use_bb_distance_filter=True, max_bb_distance_pct=d),
                   label=f"Max BB distance {dist}%")
        print(fmt(r, bp))

    # ==========================================
    # 5. BOUNCE STRENGTH
    # ==========================================
    print(f"\n  [5] BOUNCE STRENGTH FILTER")
    print("  " + "-" * 138)

    for bs in [30, 40, 50, 60, 70]:
        r = run_bt(data, lambda b=bs: V5FinalStrategy(use_bounce_strength=True, min_bounce_pct=b),
                   label=f"Bounce strength > {bs}%")
        print(fmt(r, bp))

    # With V5
    for bs in [30, 40, 50]:
        r = run_bt(data, lambda b=bs: V5FinalStrategy(
            use_rsi_recovery_exit=True, rsi_recovery_target=47,
            use_bounce_strength=True, min_bounce_pct=b),
            label=f"V5 + Bounce > {bs}%")
        print(fmt(r, bp))

    # ==========================================
    # 6. EMA TREND FILTER
    # ==========================================
    print(f"\n  [6] EMA TREND FILTER")
    print("  " + "-" * 138)

    for per in [20, 50, 100, 200]:
        r = run_bt(data, lambda p=per: V5FinalStrategy(use_ema_filter=True, ema_period=p, ema_side='below'),
                   label=f"Must be below EMA{per}")
        print(fmt(r, bp))

    # ==========================================
    # 7. BEST COMBOS WITH V5
    # ==========================================
    print(f"\n  [7] BEST NEW COMBOS WITH V5")
    print("  " + "-" * 138)

    combos = [
        ("V5 + MinATR>3%", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                 use_min_atr_pct=True, min_atr_pct=3.0)),
        ("V5 + MinATR>2%", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                 use_min_atr_pct=True, min_atr_pct=2.0)),
        ("V5 + BBdist<5%", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                 use_bb_distance_filter=True, max_bb_distance_pct=5.0)),
        ("V5 + Body>0.3 + Bounce>40%", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                              use_body_wick_filter=True, min_body_ratio=0.3,
                                              use_bounce_strength=True, min_bounce_pct=40)),
        ("V5 + belowEMA50", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                  use_ema_filter=True, ema_period=50)),
        ("V5 + belowEMA200", dict(use_rsi_recovery_exit=True, rsi_recovery_target=47,
                                   use_ema_filter=True, ema_period=200)),
    ]

    for name, params in combos:
        r = run_bt(data, lambda p=params: V5FinalStrategy(**p), label=name)
        print(fmt(r, bp))

    # ==========================================
    # FINAL RANKING
    # ==========================================
    print(f"\n  FINAL: V5 RSIRecov(47) is de definitieve winnaar")
    print(f"{fmt(v5, bp)}")
    print(f"\n  Trade details:")
    for t in v5['trade_list']:
        icon = "✅" if t['pnl'] > 0 else "❌"
        print(f"    {icon} {t['pair']:<14} | P&L ${t['pnl']:>+8.2f} | {t['bars']:>2}b | {t['reason']}")

    print("\n" + "=" * 140)


if __name__ == '__main__':
    main()
