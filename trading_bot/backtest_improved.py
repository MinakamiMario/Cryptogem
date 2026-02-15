#!/usr/bin/env python3
"""
Backtest Improved Strategy - 60 dagen portfolio-realistisch
-----------------------------------------------------------
Test 4 verbeteringen t.o.v. baseline dual confirm:
  1. Signaal ranking (bounce strength + volume)
  2. Dynamische positie sizing
  3. Marktregime filter (BTC trend)
  4. Slimmere cooldown (langer na stop loss)

Alle tests portfolio-realistisch: max posities, chronologisch, 0.26% fee.

Gebruik:
    python backtest_improved.py              # Volledige test
    python backtest_improved.py --days 30    # Custom periode
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from strategy import DualConfirmStrategy, Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026  # 0.26%

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('backtest_improved')


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_all_candles(days=60):
    """Fetch 4H candles voor alle coins. Cache resultaat."""
    # Check cache (max 4 uur oud)
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        cache_age = time.time() - cache.get('_timestamp', 0)
        if cache_age < 14400 and cache.get('_days', 0) >= days:
            coin_count = len([k for k in cache if not k.startswith('_')])
            logger.info(f"Cache geladen: {coin_count} coins, {cache.get('_days')}d (age={cache_age/3600:.1f}h)")
            return cache

    from kraken_client import KrakenClient
    api_key = os.getenv('KRAKEN_API_KEY', '')
    private_key = os.getenv('KRAKEN_PRIVATE_KEY', '')
    client = KrakenClient(api_key, private_key)

    coins_str = os.getenv('COINS', '')
    coins = [c.strip() for c in coins_str.split(',') if c.strip()]

    since = int((datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp())
    cache = {'_timestamp': time.time(), '_days': days}
    fetched = 0
    errors = 0

    logger.info(f"Fetching {days}d candles voor {len(coins)} coins...")

    for i, pair in enumerate(coins):
        try:
            candles = client.get_ohlc(pair, interval=240, since=since)
            if candles and len(candles) >= 30:
                cache[pair] = candles
                fetched += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  {i+1}/{len(coins)} ({fetched} OK, {errors} errors)")
        except Exception as e:
            errors += 1

    logger.info(f"Fetch compleet: {fetched} coins, {errors} errors")

    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

    return cache


# ============================================================
# IMPROVED STRATEGY
# ============================================================

class ImprovedDualConfirmStrategy:
    """
    Verbeterde Dual Confirm met:
    1. Signaal ranking (bounce strength score)
    2. Dynamische positie sizing
    3. Marktregime filter (BTC trend)
    4. Slimmere cooldown
    """

    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_dc_max=35, rsi_bb_max=35, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, cooldown_bars=4,
                 max_stop_loss_pct=15.0,
                 # Nieuwe parameters
                 cooldown_after_stop=8,      # Langere cooldown na stop loss
                 volume_filter=True,         # Volume boven gemiddelde vereist
                 ):
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
        self.volume_filter = volume_filter

        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def calc_signal_score(self, candles, rsi, prev_lowest, bb_lower):
        """
        Bereken signaal kwaliteit score (0-100).
        Hogere score = betere setup.
        """
        current = candles[-1]
        score = 50  # Base score

        # 1. RSI depth: lager = sterker oversold (-10 tot +20)
        if rsi < 20:
            score += 20
        elif rsi < 25:
            score += 15
        elif rsi < 30:
            score += 10
        elif rsi < 35:
            score += 5

        # 2. Bounce strength: hoe ver onder DC lower (-5 tot +15)
        if prev_lowest and prev_lowest > 0:
            depth_pct = (prev_lowest - current['low']) / prev_lowest * 100
            if depth_pct > 3:
                score += 15
            elif depth_pct > 2:
                score += 10
            elif depth_pct > 1:
                score += 5

        # 3. BB depth: hoe ver onder BB lower (-5 tot +10)
        if bb_lower and bb_lower > 0:
            bb_depth = (bb_lower - current['close']) / bb_lower * 100
            if bb_depth > 2:
                score += 10
            elif bb_depth > 1:
                score += 5

        # 4. Volume spike: boven gemiddelde = betrouwbaarder (-5 tot +10)
        volumes = [c.get('volume', 0) for c in candles[-20:]]
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        current_vol = current.get('volume', 0)
        if avg_vol > 0:
            vol_ratio = current_vol / avg_vol
            if vol_ratio > 2.0:
                score += 10
            elif vol_ratio > 1.5:
                score += 7
            elif vol_ratio > 1.0:
                score += 3
            else:
                score -= 5  # Onder gemiddeld volume = minder betrouwbaar

        # 5. Bounce bevestiging: close vs low spread (+0 tot +5)
        candle_range = current['high'] - current['low']
        if candle_range > 0:
            close_position = (current['close'] - current['low']) / candle_range
            if close_position > 0.7:  # Close dicht bij high = sterke bounce
                score += 5
            elif close_position > 0.5:
                score += 3

        return max(0, min(100, score))

    def calc_position_size(self, signal_score, base_capital):
        """
        Dynamische positie sizing op basis van signaal score.
        Score 50 = 80% van base capital
        Score 70 = 100% van base capital
        Score 90+ = 120% van base capital
        """
        if signal_score >= 90:
            multiplier = 1.20
        elif signal_score >= 80:
            multiplier = 1.10
        elif signal_score >= 70:
            multiplier = 1.00
        elif signal_score >= 60:
            multiplier = 0.90
        else:
            multiplier = 0.80

        return base_capital * multiplier

    def analyze(self, candles, position, pair):
        """Analyze met verbeterde logica."""
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0), 50

        self.bar_count = len(candles)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)

        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        current = candles[-1]
        prev = candles[-2]

        if position is None:
            # Smart cooldown
            active_cooldown = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
            in_cooldown = (self.bar_count - self.last_exit_bar) < active_cooldown

            if in_cooldown:
                return Signal('WAIT', pair, current['close'],
                              f'Cooldown ({self.bar_count - self.last_exit_bar}/{active_cooldown})',
                              rsi=rsi, confidence=0), 0

            donchian_ok = (
                prev_lowest is not None and
                current['low'] <= prev_lowest and
                rsi < self.rsi_dc_max and
                current['close'] > prev['close']
            )

            bb_ok = (
                bb_lower is not None and
                current['close'] <= bb_lower and
                rsi < self.rsi_bb_max and
                current['close'] > prev['close']
            )

            # Volume filter
            volume_ok = True
            if self.volume_filter:
                volumes = [c.get('volume', 0) for c in candles[-20:]]
                avg_vol = sum(volumes) / len(volumes) if volumes else 0
                current_vol = current.get('volume', 0)
                volume_ok = current_vol >= avg_vol * 0.5  # Minimaal 50% van gemiddelde

            if donchian_ok and bb_ok and volume_ok:
                signal_score = self.calc_signal_score(candles, rsi, prev_lowest, bb_lower)

                stop = current['close'] - atr * self.atr_stop_mult
                max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                if stop < max_stop:
                    stop = max_stop

                target = mid_channel
                if bb_mid and (target is None or bb_mid < target):
                    target = bb_mid

                return Signal(
                    'BUY', pair, current['close'],
                    f"DUAL+IMPROVED: score={signal_score}, RSI={rsi:.1f}",
                    stop_price=stop, target_price=target,
                    rsi=rsi, confidence=signal_score / 100
                ), signal_score

            return Signal('WAIT', pair, current['close'],
                          f"Geen dual confirm",
                          rsi=rsi, confidence=0), 0
        else:
            # EXIT logica (identiek aan baseline)
            if current['close'] > position.highest_price:
                position.highest_price = current['close']
            new_stop = position.highest_price - atr * self.atr_stop_mult
            max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < max_stop:
                new_stop = max_stop
            if new_stop > position.stop_price:
                position.stop_price = new_stop

            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100

            # Hard stop
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal('SELL_STOP', pair, current['close'],
                              f"Hard stop: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.95), 0

            # DC mid target
            if mid_channel and current['close'] >= mid_channel:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"DC target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9), 0

            # BB mid target
            if bb_mid and current['close'] >= bb_mid:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"BB target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9), 0

            # RSI overbought
            if rsi > self.rsi_sell:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"RSI exit: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.85), 0

            # Trailing stop
            if current['close'] < position.stop_price:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal('SELL_STOP', pair, current['close'],
                              f"Trail stop: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.95), 0

            return Signal('HOLD', pair, current['close'],
                          f"Holding: P&L={pnl_pct:+.1f}%",
                          stop_price=position.stop_price, rsi=rsi), 0


# ============================================================
# PORTFOLIO SIMULATION
# ============================================================

def extract_all_signals(cache, strategy_class, strategy_kwargs, use_scoring=False):
    """Extract alle signalen chronologisch uit alle coins."""
    all_events = []
    strategies = {}

    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 30:
            continue

        strat = strategy_class(**strategy_kwargs)
        strategies[pair] = strat
        position = None

        for i in range(25, len(candles)):
            window = candles[:i + 1]
            current = candles[i]
            bar_time = current['time']

            if use_scoring:
                signal, score = strat.analyze(window, position, pair)
            else:
                signal = strat.analyze(window, position, pair)
                score = 50  # Default

            if signal.action == 'BUY' and position is None:
                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': 'BUY',
                    'price': signal.price,
                    'stop_price': signal.stop_price,
                    'target_price': signal.target_price,
                    'rsi': signal.rsi,
                    'score': score,
                    'bar_idx': i,
                })
                position = Position(
                    pair=pair,
                    entry_price=signal.price,
                    volume=1,
                    stop_price=signal.stop_price,
                    highest_price=signal.price,
                    entry_time=bar_time,
                )

            elif signal.action in ('SELL_TARGET', 'SELL_STOP') and position is not None:
                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': signal.action,
                    'price': signal.price,
                    'rsi': signal.rsi,
                    'entry_price': position.entry_price,
                    'bar_idx': i,
                })
                position = None

            elif position is not None:
                if current['close'] > position.highest_price:
                    position.highest_price = current['close']

    all_events.sort(key=lambda x: x['time'])
    return all_events


def simulate_portfolio(events, max_positions, capital_per_trade, commission,
                       use_ranking=False, use_dynamic_sizing=False,
                       btc_candles=None, btc_regime_filter=False):
    """
    Portfolio simulatie met verbeteringen.
    """
    positions = {}
    closed_trades = []
    total_capital = max_positions * capital_per_trade

    # BTC regime data voorbereiden
    btc_bearish_times = set()
    if btc_regime_filter and btc_candles:
        for i in range(6, len(btc_candles)):
            # BTC 24u change (6 x 4H candles)
            btc_now = btc_candles[i]['close']
            btc_24h_ago = btc_candles[i - 6]['close']
            btc_change = (btc_now - btc_24h_ago) / btc_24h_ago * 100
            # Als BTC >5% stijgt in 24u → markt is in sterke uptrend, bounces minder betrouwbaar
            if btc_change > 5:
                btc_bearish_times.add(btc_candles[i]['time'])

    # Group BUY events per timestamp voor ranking
    buy_events_by_time = {}
    sell_events = []

    for event in events:
        if event['action'] == 'BUY':
            t = event['time']
            if t not in buy_events_by_time:
                buy_events_by_time[t] = []
            buy_events_by_time[t].append(event)
        else:
            sell_events.append(event)

    # Process sells eerst (bevrijden slots)
    all_events_ordered = []
    for event in events:
        all_events_ordered.append(event)

    for event in all_events_ordered:
        if event['action'] in ('SELL_TARGET', 'SELL_STOP'):
            pair = event['pair']
            if pair in positions:
                pos = positions[pair]
                entry_price = pos['entry_price']
                exit_price = event['price']
                volume = pos['volume']

                gross_pnl = (exit_price - entry_price) * volume
                entry_fee = entry_price * volume * commission
                exit_fee = exit_price * volume * commission
                net_pnl = gross_pnl - entry_fee - exit_fee

                closed_trades.append({
                    'pair': pair,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': net_pnl,
                    'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                    'exit_type': 'TARGET' if event['action'] == 'SELL_TARGET' else 'STOP',
                    'capital_used': pos['capital_used'],
                })
                del positions[pair]

        elif event['action'] == 'BUY':
            pair = event['pair']
            if pair in positions:
                continue
            if len(positions) >= max_positions:
                # Ranking: als er meerdere BUY signalen zijn op dezelfde bar
                if use_ranking:
                    same_time_buys = buy_events_by_time.get(event['time'], [])
                    if len(same_time_buys) > 1:
                        # Sorteer op score (hoogste eerst)
                        same_time_buys.sort(key=lambda x: x.get('score', 50), reverse=True)
                        # Skip als dit niet de beste is
                        best_pairs = [b['pair'] for b in same_time_buys[:max_positions]]
                        if pair not in best_pairs:
                            continue
                continue

            # BTC regime filter
            if btc_regime_filter and event['time'] in btc_bearish_times:
                continue

            # Bepaal capital
            if use_dynamic_sizing:
                score = event.get('score', 50)
                if score >= 90:
                    cap = capital_per_trade * 1.20
                elif score >= 80:
                    cap = capital_per_trade * 1.10
                elif score >= 70:
                    cap = capital_per_trade * 1.00
                elif score >= 60:
                    cap = capital_per_trade * 0.90
                else:
                    cap = capital_per_trade * 0.80
            else:
                cap = capital_per_trade

            volume = cap / event['price']
            positions[pair] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
                'capital_used': cap,
            }

    return closed_trades


def print_results(name, trades, capital_per_trade, max_positions):
    """Print resultaten van een simulatie."""
    total = len(trades)
    if total == 0:
        print(f"  {name:<35} | Geen trades")
        return {}

    wins = [t for t in trades if t['pnl'] >= 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    gross_wins = sum(t['pnl'] for t in wins)
    gross_losses = abs(sum(t['pnl'] for t in losses))

    wr = len(wins) / total * 100
    pf = gross_wins / gross_losses if gross_losses > 0 else 999
    avg_pnl = total_pnl / total
    total_capital = capital_per_trade * max_positions
    roi = total_pnl / total_capital * 100

    biggest_win = max(t['pnl'] for t in trades) if trades else 0
    biggest_loss = min(t['pnl'] for t in trades) if trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0

    print(f"  {name:<35} | {total:>3} trades | WR {wr:>5.1f}% | "
          f"P&L ${total_pnl:>+8.2f} | ROI {roi:>+6.1f}% | PF {pf:>5.2f} | "
          f"Avg W ${avg_win:>+7.2f} | Avg L ${avg_loss:>+7.2f}")

    return {
        'name': name, 'trades': total, 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': total_pnl, 'roi': roi, 'pf': pf,
        'avg_win': avg_win, 'avg_loss': avg_loss,
        'biggest_win': biggest_win, 'biggest_loss': biggest_loss,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=60)
    args = parser.parse_args()

    print(f"\n{'='*110}")
    print(f"  BACKTEST IMPROVED STRATEGY - {args.days} DAGEN")
    print(f"  Portfolio-realistisch | 0.26% fee | Chronologisch | Max posities")
    print(f"{'='*110}\n")

    # 1. Fetch data
    cache = fetch_all_candles(days=args.days)
    coin_count = len([k for k in cache if not k.startswith('_')])
    logger.info(f"Data geladen: {coin_count} coins, {args.days} dagen")

    # BTC candles voor regime filter
    btc_candles = cache.get('BTC/USD', [])

    # 2. Baseline: huidige strategie
    print(f"  {'STRATEGIE':<35} | {'#':>3} TRADES | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'AVG WIN':>10} | {'AVG LOSS':>10}")
    print(f"  {'-'*108}")

    configs = [
        ('2x$1000', 2, 1000),
        ('3x$700', 3, 700),
    ]

    all_results = []

    for config_name, max_pos, capital in configs:
        print(f"\n  --- Config: {config_name} ---")

        # A) BASELINE
        baseline_events = extract_all_signals(
            cache, DualConfirmStrategy,
            {'rsi_dc_max': 35, 'rsi_bb_max': 35, 'rsi_sell': 70,
             'atr_stop_mult': 2.0, 'cooldown_bars': 4, 'max_stop_loss_pct': 15.0},
            use_scoring=False
        )
        baseline_trades = simulate_portfolio(
            baseline_events, max_pos, capital, KRAKEN_FEE
        )
        r = print_results(f"Baseline (DC+BB)", baseline_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # B) + SMART COOLDOWN (8 bars na stop loss)
        smart_cool_events = extract_all_signals(
            cache, ImprovedDualConfirmStrategy,
            {'rsi_dc_max': 35, 'rsi_bb_max': 35, 'rsi_sell': 70,
             'atr_stop_mult': 2.0, 'cooldown_bars': 4, 'cooldown_after_stop': 8,
             'max_stop_loss_pct': 15.0, 'volume_filter': False},
            use_scoring=True
        )
        smart_cool_trades = simulate_portfolio(
            smart_cool_events, max_pos, capital, KRAKEN_FEE
        )
        r = print_results(f"+ Smart Cooldown (8 na stop)", smart_cool_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # C) + VOLUME FILTER
        vol_events = extract_all_signals(
            cache, ImprovedDualConfirmStrategy,
            {'rsi_dc_max': 35, 'rsi_bb_max': 35, 'rsi_sell': 70,
             'atr_stop_mult': 2.0, 'cooldown_bars': 4, 'cooldown_after_stop': 8,
             'max_stop_loss_pct': 15.0, 'volume_filter': True},
            use_scoring=True
        )
        vol_trades = simulate_portfolio(
            vol_events, max_pos, capital, KRAKEN_FEE
        )
        r = print_results(f"+ Volume Filter (>50% avg)", vol_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # D) + SIGNAAL RANKING
        rank_trades = simulate_portfolio(
            vol_events, max_pos, capital, KRAKEN_FEE,
            use_ranking=True
        )
        r = print_results(f"+ Signaal Ranking (score)", rank_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # E) + DYNAMIC SIZING
        dyn_trades = simulate_portfolio(
            vol_events, max_pos, capital, KRAKEN_FEE,
            use_ranking=True, use_dynamic_sizing=True
        )
        r = print_results(f"+ Dynamic Sizing (score-based)", dyn_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # F) + BTC REGIME FILTER
        btc_trades = simulate_portfolio(
            vol_events, max_pos, capital, KRAKEN_FEE,
            use_ranking=True, use_dynamic_sizing=True,
            btc_candles=btc_candles, btc_regime_filter=True
        )
        r = print_results(f"+ BTC Regime Filter (>5% skip)", btc_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

        # G) ALLES SAMEN
        all_improved_trades = simulate_portfolio(
            vol_events, max_pos, capital, KRAKEN_FEE,
            use_ranking=True, use_dynamic_sizing=True,
            btc_candles=btc_candles, btc_regime_filter=True
        )
        r = print_results(f"ALLES GECOMBINEERD", all_improved_trades, capital, max_pos)
        if r:
            r['config'] = config_name
            all_results.append(r)

    # Samenvatting
    print(f"\n{'='*110}")
    print(f"  SAMENVATTING BESTE RESULTATEN")
    print(f"{'='*110}")

    for config_name, _, _ in configs:
        config_results = [r for r in all_results if r.get('config') == config_name]
        if config_results:
            best = max(config_results, key=lambda x: x.get('pnl', 0))
            baseline = next((r for r in config_results if 'Baseline' in r.get('name', '')), None)
            if baseline and best:
                improvement = best['pnl'] - baseline['pnl']
                print(f"\n  {config_name}:")
                print(f"    Baseline:  P&L ${baseline['pnl']:>+8.2f} | WR {baseline['wr']:.1f}% | PF {baseline['pf']:.2f}")
                print(f"    Best:      P&L ${best['pnl']:>+8.2f} | WR {best['wr']:.1f}% | PF {best['pf']:.2f} | {best['name']}")
                print(f"    Verschil:  ${improvement:>+8.2f} ({'+' if improvement > 0 else ''}{improvement/max(abs(baseline['pnl']),1)*100:.0f}%)")

    print(f"\n{'='*110}\n")


if __name__ == '__main__':
    main()
