#!/usr/bin/env python3
"""
V5 PRECISION SWEEP — Fijntuning RSI Recovery + nog ongeteste ideeën
====================================================================
1. RSI Recovery target precision sweep (42-47, stap 1)
2. Trailing stop optimalisatie: step-trail (lock profits in steps)
3. Profit target % exit (als trade al X% in winst, exit meteen)
4. BB deviation sweep (2.0 vs 1.5, 2.5, 3.0)
5. Cooldown variaties na stop loss
6. Volume spike relaxen als andere signals sterk zijn
7. Best combo finalization
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
logger = logging.getLogger('v5_precision')

def fetch_all_candles():
    with open(CACHE_FILE) as f:
        return json.load(f)


class V5Strategy:
    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8, volume_min_pct=0.5,
                 use_volume_spike=True, volume_spike_mult=2.0,
                 use_vol_confirm=True, vol_confirm_mult=1.0,
                 use_breakeven_stop=True, breakeven_trigger_pct=3.0,
                 use_time_max=True, time_max_bars=10,
                 # RSI Recovery exit
                 use_rsi_recovery_exit=False, rsi_recovery_target=45, rsi_recovery_min_bars=2,
                 # Step-trail: lock X% profit in steps
                 use_step_trail=False, step_trail_step_pct=5.0, step_trail_lock_pct=2.0,
                 # Profit target exit
                 use_profit_target=False, profit_target_pct=20.0,
                 # BB squeeze entry filter
                 use_bb_squeeze=False, bb_squeeze_threshold=0.02,
                 ):
        for k, v in locals().items():
            if k != 'self':
                setattr(self, k, v)
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Data', confidence=0)

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
            return Signal('WAIT', pair, 0, 'Indicators', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # EXIT
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0
            profit_pct = (close - entry_price) / entry_price * 100

            if close > position.highest_price:
                position.highest_price = close

            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even stop
            if self.use_breakeven_stop and profit_pct >= self.breakeven_trigger_pct:
                be = entry_price * (1 + KRAKEN_FEE * 2)
                if new_stop < be:
                    new_stop = be

            # Step-trail: lock profits in steps
            if self.use_step_trail:
                highest_pct = (position.highest_price - entry_price) / entry_price * 100
                steps_reached = int(highest_pct / self.step_trail_step_pct)
                if steps_reached > 0:
                    locked = entry_price * (1 + (steps_reached * self.step_trail_lock_pct) / 100)
                    if new_stop < locked:
                        new_stop = locked

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            # Hard stop
            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)

            # Profit target
            if self.use_profit_target and profit_pct >= self.profit_target_pct:
                return Signal('SELL', pair, close, 'PROFIT TARGET', confidence=1.0)

            # Time max
            if self.use_time_max and bars >= self.time_max_bars:
                return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)

            # RSI recovery
            if self.use_rsi_recovery_exit and bars >= self.rsi_recovery_min_bars:
                if rsi >= self.rsi_recovery_target:
                    return Signal('SELL', pair, close, 'RSI RECOVERY', confidence=0.85)

            # Target exits
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

        # BB squeeze filter
        if self.use_bb_squeeze:
            bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0
            if bb_width > self.bb_squeeze_threshold:
                return Signal('WAIT', pair, close, 'BB wide', confidence=0)

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
            f"${r['total_pnl']:>+8.0f} ({d:>+6.0f}) | PF {pf:>7} | DD {r['max_dd']:>4.1f}% | "
            f"AvgB {r['avg_bars']:>4.1f}")


def main():
    data = fetch_all_candles()

    print("\n" + "=" * 140)
    print("  V5 PRECISION SWEEP — Fijntuning RSI Recovery + nieuwe exit-ideeën")
    print("=" * 140)

    base = run_bt(data, lambda: V5Strategy(), label="V4 BASELINE")
    bp = base['total_pnl']
    print(f"\n{fmt(base)}")

    # ==========================================
    # 1. RSI RECOVERY PRECISION (42-47 per 1)
    # ==========================================
    print(f"\n  [1] RSI RECOVERY PRECISION SWEEP (target 42-47)")
    print("  " + "-" * 138)

    for tgt in range(42, 48):
        for mb in [1, 2, 3]:
            r = run_bt(data, lambda t=tgt, m=mb: V5Strategy(
                use_rsi_recovery_exit=True, rsi_recovery_target=t, rsi_recovery_min_bars=m),
                label=f"RSI Recovery tgt={tgt} min={mb}b")
            print(fmt(r, bp))

    # ==========================================
    # 2. STEP-TRAIL EXIT
    # ==========================================
    print(f"\n  [2] STEP-TRAIL EXIT (lock profits in steps)")
    print("  " + "-" * 138)

    step_tests = [
        ("StepTrail 5%/2% lock", dict(use_step_trail=True, step_trail_step_pct=5, step_trail_lock_pct=2)),
        ("StepTrail 10%/5% lock", dict(use_step_trail=True, step_trail_step_pct=10, step_trail_lock_pct=5)),
        ("StepTrail 3%/1% lock", dict(use_step_trail=True, step_trail_step_pct=3, step_trail_lock_pct=1)),
        ("StepTrail 5%/3% lock", dict(use_step_trail=True, step_trail_step_pct=5, step_trail_lock_pct=3)),
        # With RSI Recovery
        ("RSIRecov(45,2) + StepTrail(5/2)", dict(use_rsi_recovery_exit=True, rsi_recovery_target=45,
                                                   rsi_recovery_min_bars=2, use_step_trail=True,
                                                   step_trail_step_pct=5, step_trail_lock_pct=2)),
    ]
    for name, params in step_tests:
        r = run_bt(data, lambda p=params: V5Strategy(**p), label=name)
        print(fmt(r, bp))

    # ==========================================
    # 3. PROFIT TARGET EXIT
    # ==========================================
    print(f"\n  [3] PROFIT TARGET EXIT (exit at X% profit)")
    print("  " + "-" * 138)

    for pt in [5, 10, 15, 20, 30, 50, 100]:
        r = run_bt(data, lambda p=pt: V5Strategy(use_profit_target=True, profit_target_pct=p),
                   label=f"Profit target {pt}%")
        print(fmt(r, bp))

    # With RSI Recovery
    for pt in [10, 20, 50, 100]:
        r = run_bt(data, lambda p=pt: V5Strategy(use_profit_target=True, profit_target_pct=p,
                   use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2),
                   label=f"RSIRecov(45,2) + ProfitTgt {pt}%")
        print(fmt(r, bp))

    # ==========================================
    # 4. BB DEVIATION SWEEP
    # ==========================================
    print(f"\n  [4] BB DEVIATION SWEEP")
    print("  " + "-" * 138)

    for dev in [1.0, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0]:
        r = run_bt(data, lambda d=dev: V5Strategy(bb_dev=d), label=f"BB dev={dev}")
        print(fmt(r, bp))

    # ==========================================
    # 5. COOLDOWN VARIATIONS
    # ==========================================
    print(f"\n  [5] COOLDOWN VARIATIONS")
    print("  " + "-" * 138)

    for cd in [2, 4, 6, 8]:
        for cds in [4, 8, 12]:
            r = run_bt(data, lambda c=cd, s=cds: V5Strategy(cooldown_bars=c, cooldown_after_stop=s),
                       label=f"Cooldown normal={cd}b stop={cds}b")
            print(fmt(r, bp))

    # ==========================================
    # 6. RSI SELL THRESHOLD (when to take RSI-based profit)
    # ==========================================
    print(f"\n  [6] RSI SELL THRESHOLD")
    print("  " + "-" * 138)

    for rs in [50, 55, 60, 65, 70, 75, 80]:
        r = run_bt(data, lambda s=rs: V5Strategy(rsi_sell=s), label=f"RSI sell={rs}")
        print(fmt(r, bp))

    # ==========================================
    # 7. BB SQUEEZE FILTER (enter only in tight BB = upcoming breakout)
    # ==========================================
    print(f"\n  [7] BB SQUEEZE FILTER")
    print("  " + "-" * 138)

    for sq in [0.01, 0.02, 0.03, 0.04, 0.05, 0.08, 0.10]:
        r = run_bt(data, lambda s=sq: V5Strategy(use_bb_squeeze=True, bb_squeeze_threshold=s),
                   label=f"BB squeeze < {sq:.2f}")
        print(fmt(r, bp))

    # ==========================================
    # 8. FINAL V5 CANDIDATES
    # ==========================================
    print(f"\n  [8] FINAL V5 CANDIDATES")
    print("  " + "=" * 138)

    finals = [
        ("V4 BASELINE", {}),
        ("V5-SIMPLE: + RSIRecov(45,2b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2)),
        ("V5-SIMPLE: + RSIRecov(47,2b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=47, rsi_recovery_min_bars=2)),
        ("V5-SIMPLE: + RSIRecov(46,2b)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=46, rsi_recovery_min_bars=2)),
        ("V5+StepTrail: RSIRecov(45,2)+Step(5/2)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2,
            use_step_trail=True, step_trail_step_pct=5, step_trail_lock_pct=2)),
        ("V5+ProfTgt: RSIRecov(45,2)+ProfTgt(100%)", dict(
            use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2,
            use_profit_target=True, profit_target_pct=100)),
    ]

    final_results = []
    for name, params in finals:
        r = run_bt(data, lambda p=params: V5Strategy(**p), label=name)
        final_results.append(r)
        print(fmt(r, bp))

    # Trade details for top 3
    top3 = sorted(final_results, key=lambda x: x['total_pnl'], reverse=True)[:3]
    for r in top3:
        print(f"\n  {r['label']}: {r['trades']}tr | WR {r['win_rate']:.1f}% | P&L ${r['total_pnl']:+,.2f} | PF {r['pf']:.2f}")
        for t in r['trade_list']:
            icon = "✅" if t['pnl'] > 0 else "❌"
            print(f"    {icon} {t['pair']:<14} | P&L ${t['pnl']:>+8.2f} | {t['bars']:>2}b | {t['reason']}")

    print("\n" + "=" * 140)


if __name__ == '__main__':
    main()
