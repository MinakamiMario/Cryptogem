#!/usr/bin/env python3
"""
V5 KAPITAAL SIMULATIE — $2000 vs $3000 vs $4000
=================================================
60 dagen simulatie met V5 (RSI Recovery t=45) bij verschillende kapitalen.
1x all-in per trade.

Gebruik:
    python backtest_v5_capital_sim.py
"""
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
logger = logging.getLogger('v5_capital_sim')


def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        logger.info(f"Cache geladen: {len([k for k in cache if not k.startswith('_')])} coins")
        return cache
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


class V5Strategy:
    def __init__(self, rsi_recovery_target=45):
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
        self.rsi_recovery_min_bars = 2
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

        # ENTRY
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)
        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * 0.5:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)
        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)
        if volumes and vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
            return Signal('WAIT', pair, close, 'Volume spike <2x', confidence=0)
        if len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, 'Vol confirm <1x', confidence=0)
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop
        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = min(1, (volumes[-1] / vol_avg / 3)) if volumes and vol_avg > 0 else 0
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3
        return Signal('BUY', pair, close, 'DUAL CONFIRM V5', confidence=quality, stop_price=stop)


@dataclass
class BacktestPosition:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float
    side: str = 'long'


def run_sim(all_candles, capital, label=""):
    coins = [k for k in all_candles if not k.startswith('_')]
    strategies = {pair: V5Strategy(rsi_recovery_target=45) for pair in coins}
    max_bars = max(len(all_candles[p]) for p in coins)

    position = None
    trades = []
    equity = capital
    initial_equity = capital
    peak_equity = capital
    max_dd_pct = 0
    max_dd_usd = 0
    equity_curve = []

    for bar_idx in range(50, max_bars):
        buy_signals = []
        sell_signal = None

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue
            window = candles[:bar_idx + 1]

            if position and position.pair == pair:
                mock_pos = type('Pos', (), {
                    'entry_price': position.entry_price,
                    'stop_price': position.stop_price,
                    'highest_price': position.highest_price,
                    'side': 'long', 'entry_bar': position.entry_bar,
                })()
                sig = strategies[pair].analyze(window, mock_pos, pair)
                if sig.action == 'SELL':
                    sell_signal = (pair, sig)
                    # Update position stop from mock
                    position.stop_price = mock_pos.stop_price
                    position.highest_price = mock_pos.highest_price
            elif not position:
                sig = strategies[pair].analyze(window, None, pair)
                if sig.action == 'BUY':
                    buy_signals.append((pair, sig, candles[bar_idx]))

        # SELL
        if sell_signal:
            pair, sig = sell_signal
            gross_pnl = (sig.price - position.entry_price) / position.entry_price * position.size_usd
            fee = position.size_usd * KRAKEN_FEE + (position.size_usd + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee
            equity += net_pnl
            strategies[pair].last_exit_bar = strategies[pair].bar_count
            strategies[pair].last_exit_was_stop = 'STOP' in sig.reason
            trades.append({
                'pair': pair, 'entry': position.entry_price, 'exit': sig.price,
                'pnl': net_pnl, 'pnl_pct': (sig.price - position.entry_price) / position.entry_price * 100,
                'reason': sig.reason, 'bars': bar_idx - position.entry_bar, 'size': position.size_usd,
            })
            position = None

        # BUY
        if not position and buy_signals:
            # Rank by volume
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
            position = BacktestPosition(
                pair=pair, entry_price=sig.price, entry_bar=bar_idx,
                stop_price=sig.stop_price or sig.price * 0.85,
                highest_price=sig.price, size_usd=equity,  # ALL-IN met huidige equity
            )

        # Track
        if equity > peak_equity:
            peak_equity = equity
        dd = peak_equity - equity
        dd_pct = dd / peak_equity * 100 if peak_equity > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd
        equity_curve.append(equity)

    # Close remaining
    if position:
        candles = all_candles.get(position.pair, [])
        if candles:
            last = candles[-1]['close']
            gross = (last - position.entry_price) / position.entry_price * position.size_usd
            fee = position.size_usd * KRAKEN_FEE + (position.size_usd + gross) * KRAKEN_FEE
            net = gross - fee
            equity += net
            trades.append({
                'pair': position.pair, 'entry': position.entry_price, 'exit': last,
                'pnl': net, 'pnl_pct': (last - position.entry_price) / position.entry_price * 100,
                'reason': 'END', 'bars': max_bars - position.entry_bar, 'size': position.size_usd,
            })

    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    return {
        'label': label, 'capital': initial_equity, 'final_equity': equity,
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': wr, 'total_pnl': total_pnl, 'roi': total_pnl / initial_equity * 100,
        'pf': pf, 'max_dd_pct': max_dd_pct, 'max_dd_usd': max_dd_usd,
        'avg_win': tw / len(wins) if wins else 0,
        'avg_loss': tl / len(losses) * -1 if losses else 0,
        'best': max(trades, key=lambda t: t['pnl']) if trades else None,
        'worst': min(trades, key=lambda t: t['pnl']) if trades else None,
        'trade_list': trades, 'equity_curve': equity_curve,
    }


def main():
    data = fetch_all_candles()

    print()
    print("=" * 130)
    print("  V5 KAPITAAL SIMULATIE — $2000 vs $3000 vs $4000 (60 dagen, compound all-in)")
    print("  Strategie: V5 DualConfirm + RSI Recovery (t=45)")
    print("  Mode: 1x ALL-IN per trade met compound (herbelegt winst)")
    print("  Fee: 0.26% | 285 coins | Volume ranking")
    print("=" * 130)

    capitals = [2000, 3000, 4000]
    results = []

    for cap in capitals:
        label = f"V5 ${cap:,} all-in"
        r = run_sim(data, cap, label)
        results.append(r)
        logger.info(f"  {label}: P&L ${r['total_pnl']:+,.0f}, eindkapitaal ${r['final_equity']:,.0f}, "
                     f"WR {r['win_rate']:.1f}%, PF {r['pf']:.2f}")

    # OVERZICHT
    print()
    print("=" * 130)
    print("  RESULTATEN OVERZICHT")
    print("=" * 130)
    print(f"  {'CONFIG':<25} | {'START':>8} | {'EIND':>10} | {'#TR':>4} | {'WR':>6} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>7} | {'DD%':>6} | {'DD$':>8} | {'AvgW':>10} | {'AvgL':>10}")
    print("  " + "-" * 128)

    for r in results:
        print(f"  {r['label']:<25} | ${r['capital']:>5,} | ${r['final_equity']:>8,.0f} | "
              f"{r['trades']:>4} | {r['win_rate']:>5.1f}% | "
              f"${r['total_pnl']:>+10,.0f} | {r['roi']:>+6.1f}% | {r['pf']:>6.2f} | "
              f"{r['max_dd_pct']:>5.1f}% | ${r['max_dd_usd']:>6,.0f} | "
              f"${r['avg_win']:>+8,.0f} | ${r['avg_loss']:>+8,.0f}")

    # DETAIL per kapitaal
    for r in results:
        print()
        print(f"  {'=' * 90}")
        print(f"  {r['label']} — TRADE DETAIL")
        print(f"  {'=' * 90}")
        print(f"  Start: ${r['capital']:,} → Eind: ${r['final_equity']:,.2f} ({r['roi']:+.1f}%)")
        print()

        running_equity = r['capital']
        for i, t in enumerate(r['trade_list']):
            icon = "✅" if t['pnl'] > 0 else "❌"
            running_equity_before = running_equity
            running_equity += t['pnl']
            print(f"  {icon} {i+1:>2}. {t['pair']:<14} | "
                  f"inzet ${t['size']:>8,.0f} | "
                  f"P&L ${t['pnl']:>+10,.2f} ({t['pnl_pct']:>+6.2f}%) | "
                  f"{t['bars']:>3} bars | {t['reason']:<14} | "
                  f"saldo ${running_equity:>10,.2f}")

    # EQUITY CURVE vergelijking (begin en eind)
    print()
    print("=" * 130)
    print("  SAMENVATTING")
    print("=" * 130)
    for r in results:
        growth = r['final_equity'] / r['capital']
        print(f"  ${r['capital']:>5,} → ${r['final_equity']:>10,.2f}  |  ×{growth:.2f}  |  "
              f"+${r['total_pnl']:>10,.2f}  |  ROI {r['roi']:+.1f}%  |  DD {r['max_dd_pct']:.1f}%")

    print()
    print(f"  Alle 3 hebben dezelfde trades (zelfde signalen), maar hogere inzet = hogere absolute P&L")
    print(f"  ROI en PF zijn identiek — alleen de absolute bedragen schalen lineair mee")
    print()
    print("=" * 130)


if __name__ == '__main__':
    main()
