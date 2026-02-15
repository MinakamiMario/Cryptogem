#!/usr/bin/env python3
"""
Backtest Stoploss Analyse
-------------------------
Vergelijkt de impact van de trailing stop op de strategie.
Beantwoordt: kost de stoploss meer dan hij oplevert?

Varianten:
  1. BASELINE:       Huidige strategie (ATR 2.0x trail + 15% hard cap)
  2. GEEN TRAIL:     Alleen target exits (DC mid, BB mid, RSI>70) + 15% hard cap
  3. RUIMERE TRAIL:  ATR 3.0x trailing stop
  4. EXTRA RUIM:     ATR 4.0x trailing stop
  5. ATR 5.0x:       Zeer ruime trailing stop
  6. TIME STOP:      Max 20 bars in trade, dan exit + 15% hard cap
  7. COMBO BEST:     Ruimere trail + time stop

Gebruik:
    python backtest_stoploss.py              # 60 dagen
    python backtest_stoploss.py --days 30    # Custom periode
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
logger = logging.getLogger('backtest_stoploss')


# ============================================================
# DATA FETCHING (hergebruik cache)
# ============================================================

def fetch_all_candles(days=60):
    """Fetch 4H candles voor alle coins. Cache resultaat."""
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
# STOPLOSS VARIANTEN
# ============================================================

class StoplossVariantStrategy:
    """
    DualConfirm strategie met configureerbare stoploss varianten.

    Modes:
      - 'baseline':    ATR trailing stop (standaard)
      - 'no_trail':    Geen trailing stop, alleen targets + hard cap
      - 'trail':       ATR trailing stop met custom multiplier
      - 'time_stop':   Maximaal X bars in trade
      - 'combo':       Trail + time stop
    """

    def __init__(self, donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_dc_max=35, rsi_bb_max=35, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0, cooldown_bars=4,
                 max_stop_loss_pct=15.0,
                 # Stoploss variant parameters
                 mode='baseline',           # baseline, no_trail, trail, time_stop, combo
                 max_bars_in_trade=20,       # Voor time_stop en combo
                 # Volume filter (winnaar van vorige test)
                 volume_filter=True,
                 cooldown_after_stop=8,
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

        # Stoploss mode
        self.mode = mode
        self.max_bars_in_trade = max_bars_in_trade

        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        """Analyze met configureerbare stoploss."""
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

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
            # === ENTRY (identiek voor alle varianten) ===
            active_cooldown = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
            in_cooldown = (self.bar_count - self.last_exit_bar) < active_cooldown

            if in_cooldown:
                return Signal('WAIT', pair, current['close'],
                              f'Cooldown', rsi=rsi, confidence=0)

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
                volume_ok = current_vol >= avg_vol * 0.5

            if donchian_ok and bb_ok and volume_ok:
                # Initial stop berekening
                if self.mode == 'no_trail':
                    # Alleen hard cap als stop
                    stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                else:
                    stop = current['close'] - atr * self.atr_stop_mult
                    max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                    if stop < max_stop:
                        stop = max_stop

                target = mid_channel
                if bb_mid and (target is None or bb_mid < target):
                    target = bb_mid

                return Signal(
                    'BUY', pair, current['close'],
                    f"DUAL: RSI={rsi:.1f}, mode={self.mode}",
                    stop_price=stop, target_price=target,
                    rsi=rsi, confidence=0.90
                )

            return Signal('WAIT', pair, current['close'],
                          f"Geen dual confirm", rsi=rsi, confidence=0)

        else:
            # === EXIT ===
            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100
            bars_in_trade = self.bar_count - position.entry_time  # entry_time = bar index

            # --- Exit 1: Hard max loss cap (alle varianten) ---
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal('SELL_STOP', pair, current['close'],
                              f"HARD STOP: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.95)

            # --- Exit 2: DC mid channel target ---
            if mid_channel and current['close'] >= mid_channel:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"DC target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9)

            # --- Exit 3: BB mid target ---
            if bb_mid and current['close'] >= bb_mid:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"BB target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9)

            # --- Exit 4: RSI overbought ---
            if rsi > self.rsi_sell:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"RSI exit: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.85)

            # --- Exit 5: TIME STOP (als mode = time_stop of combo) ---
            if self.mode in ('time_stop', 'combo'):
                if bars_in_trade >= self.max_bars_in_trade:
                    self.last_exit_bar = self.bar_count
                    self.last_exit_was_stop = False
                    return Signal('SELL_TARGET', pair, current['close'],
                                  f"TIME STOP ({bars_in_trade} bars): P&L={pnl_pct:+.1f}%",
                                  rsi=rsi, confidence=0.7)

            # --- Exit 6: TRAILING STOP (als mode != no_trail) ---
            if self.mode != 'no_trail':
                # Update trailing stop
                if current['close'] > position.highest_price:
                    position.highest_price = current['close']
                new_stop = position.highest_price - atr * self.atr_stop_mult
                max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
                if new_stop < max_stop:
                    new_stop = max_stop
                if new_stop > position.stop_price:
                    position.stop_price = new_stop

                if current['close'] < position.stop_price:
                    self.last_exit_bar = self.bar_count
                    self.last_exit_was_stop = True
                    return Signal('SELL_STOP', pair, current['close'],
                                  f"TRAIL STOP: P&L={pnl_pct:+.1f}%",
                                  rsi=rsi, confidence=0.95)

            # Holding
            return Signal('HOLD', pair, current['close'],
                          f"Holding: P&L={pnl_pct:+.1f}%",
                          stop_price=position.stop_price, rsi=rsi)


# ============================================================
# PORTFOLIO SIMULATION
# ============================================================

def extract_signals_with_bar_tracking(cache, strategy_kwargs):
    """
    Extract signalen met bar index tracking voor time stop.
    """
    all_events = []
    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 30:
            continue

        strat = StoplossVariantStrategy(**strategy_kwargs)
        position = None

        for i in range(25, len(candles)):
            window = candles[:i + 1]
            current = candles[i]
            bar_time = current['time']

            signal = strat.analyze(window, position, pair)

            if signal.action == 'BUY' and position is None:
                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': 'BUY',
                    'price': signal.price,
                    'stop_price': signal.stop_price,
                    'target_price': signal.target_price,
                    'rsi': signal.rsi,
                    'bar_idx': i,
                })
                position = Position(
                    pair=pair,
                    entry_price=signal.price,
                    volume=1,
                    stop_price=signal.stop_price,
                    highest_price=signal.price,
                    entry_time=i,  # Bar index als entry time!
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
                    'bars_held': i - position.entry_time,
                    'exit_reason': signal.reason,
                    'highest_price': position.highest_price,
                })
                position = None

            elif position is not None:
                if current['close'] > position.highest_price:
                    position.highest_price = current['close']

    all_events.sort(key=lambda x: x['time'])
    return all_events


def simulate_portfolio(events, max_positions, capital_per_trade, commission,
                       use_dynamic_sizing=False):
    """Portfolio simulatie."""
    positions = {}
    closed_trades = []

    for event in events:
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

                # Bereken max favorable excursion (MFE)
                highest = event.get('highest_price', exit_price)
                mfe_pct = (highest - entry_price) / entry_price * 100 if entry_price > 0 else 0

                closed_trades.append({
                    'pair': pair,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': net_pnl,
                    'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                    'exit_type': 'TARGET' if event['action'] == 'SELL_TARGET' else 'STOP',
                    'exit_reason': event.get('exit_reason', ''),
                    'bars_held': event.get('bars_held', 0),
                    'mfe_pct': mfe_pct,
                    'capital_used': pos['capital_used'],
                })
                del positions[pair]

        elif event['action'] == 'BUY':
            pair = event['pair']
            if pair in positions or len(positions) >= max_positions:
                continue

            cap = capital_per_trade
            if use_dynamic_sizing:
                score = event.get('score', 50)
                if score >= 90:
                    cap *= 1.20
                elif score >= 80:
                    cap *= 1.10
                elif score >= 70:
                    cap *= 1.00
                elif score >= 60:
                    cap *= 0.90
                else:
                    cap *= 0.80

            volume = cap / event['price']
            positions[pair] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
                'capital_used': cap,
            }

    return closed_trades


def analyze_exit_types(trades):
    """Analyseer exit types en hun impact."""
    by_type = {}
    for t in trades:
        exit_type = t['exit_type']
        if exit_type not in by_type:
            by_type[exit_type] = []
        by_type[exit_type].append(t)

    results = {}
    for exit_type, type_trades in by_type.items():
        total_pnl = sum(t['pnl'] for t in type_trades)
        avg_pnl = total_pnl / len(type_trades) if type_trades else 0
        wins = [t for t in type_trades if t['pnl'] >= 0]
        avg_bars = sum(t['bars_held'] for t in type_trades) / len(type_trades) if type_trades else 0
        avg_mfe = sum(t['mfe_pct'] for t in type_trades) / len(type_trades) if type_trades else 0

        results[exit_type] = {
            'count': len(type_trades),
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'wr': len(wins) / len(type_trades) * 100 if type_trades else 0,
            'avg_bars': avg_bars,
            'avg_mfe': avg_mfe,
        }

    return results


def print_results(name, trades, capital_per_trade, max_positions, show_detail=False):
    """Print resultaten."""
    total = len(trades)
    if total == 0:
        print(f"  {name:<40} | Geen trades")
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

    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    avg_bars = sum(t['bars_held'] for t in trades) / total if total else 0
    avg_mfe = sum(t.get('mfe_pct', 0) for t in trades) / total if total else 0

    # Stoploss-specifieke stats
    stop_trades = [t for t in trades if t['exit_type'] == 'STOP']
    target_trades = [t for t in trades if t['exit_type'] == 'TARGET']
    stop_pnl = sum(t['pnl'] for t in stop_trades)
    target_pnl = sum(t['pnl'] for t in target_trades)

    print(f"  {name:<40} | {total:>3} trades | WR {wr:>5.1f}% | "
          f"P&L ${total_pnl:>+8.2f} | PF {pf:>5.2f} | "
          f"Avg ${avg_pnl:>+7.2f} | Bars {avg_bars:>4.1f}")

    if show_detail:
        print(f"    {'':40} | TARGET: {len(target_trades):>3} trades, ${target_pnl:>+8.2f} | "
              f"STOP: {len(stop_trades):>3} trades, ${stop_pnl:>+8.2f} | "
              f"Avg MFE {avg_mfe:>+5.1f}%")

        # Trades die gestopt werden maar MFE > 0 hadden (gemiste winst)
        stopped_with_mfe = [t for t in stop_trades if t['mfe_pct'] > 2]
        if stopped_with_mfe:
            missed_profit = sum(t['mfe_pct'] - t['pnl_pct'] for t in stopped_with_mfe)
            avg_missed = missed_profit / len(stopped_with_mfe)
            print(f"    {'':40} | Stopped met MFE>2%: {len(stopped_with_mfe)} trades, "
                  f"avg missed {avg_missed:>+5.1f}%")

    return {
        'name': name, 'trades': total, 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': total_pnl, 'roi': roi, 'pf': pf,
        'avg_win': avg_win, 'avg_loss': avg_loss,
        'avg_bars': avg_bars, 'avg_mfe': avg_mfe,
        'stop_trades': len(stop_trades), 'stop_pnl': stop_pnl,
        'target_trades': len(target_trades), 'target_pnl': target_pnl,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=60)
    args = parser.parse_args()

    print(f"\n{'='*120}")
    print(f"  STOPLOSS IMPACT ANALYSE - {args.days} DAGEN")
    print(f"  Vraag: Kost de trailing stop meer dan hij oplevert?")
    print(f"  Base: DualConfirm + Volume filter + Smart cooldown | 0.26% fee")
    print(f"{'='*120}\n")

    # 1. Fetch data
    cache = fetch_all_candles(days=args.days)
    coin_count = len([k for k in cache if not k.startswith('_')])
    logger.info(f"Data geladen: {coin_count} coins, {args.days} dagen")

    # Shared strategy params
    base_params = {
        'rsi_dc_max': 35, 'rsi_bb_max': 35, 'rsi_sell': 70,
        'cooldown_bars': 4, 'cooldown_after_stop': 8,
        'max_stop_loss_pct': 15.0, 'volume_filter': True,
    }

    # Define stoploss varianten
    variants = [
        ("1. BASELINE (ATR 2.0x trail)",     {**base_params, 'atr_stop_mult': 2.0, 'mode': 'baseline'}),
        ("2. GEEN TRAIL (alleen targets)",    {**base_params, 'atr_stop_mult': 2.0, 'mode': 'no_trail'}),
        ("3. RUIMERE TRAIL (ATR 3.0x)",       {**base_params, 'atr_stop_mult': 3.0, 'mode': 'trail'}),
        ("4. EXTRA RUIM (ATR 4.0x)",          {**base_params, 'atr_stop_mult': 4.0, 'mode': 'trail'}),
        ("5. ZEER RUIM (ATR 5.0x)",           {**base_params, 'atr_stop_mult': 5.0, 'mode': 'trail'}),
        ("6. TIME STOP (max 20 bars, no trail)", {**base_params, 'atr_stop_mult': 2.0, 'mode': 'time_stop', 'max_bars_in_trade': 20}),
        ("7. TIME STOP (max 30 bars, no trail)", {**base_params, 'atr_stop_mult': 2.0, 'mode': 'time_stop', 'max_bars_in_trade': 30}),
        ("8. COMBO: ATR 3.0x + 30 bar max",  {**base_params, 'atr_stop_mult': 3.0, 'mode': 'combo', 'max_bars_in_trade': 30}),
        ("9. COMBO: ATR 4.0x + 30 bar max",  {**base_params, 'atr_stop_mult': 4.0, 'mode': 'combo', 'max_bars_in_trade': 30}),
    ]

    configs = [
        ('2x$1000', 2, 1000),
        ('3x$700', 3, 700),
    ]

    all_results = {}

    for config_name, max_pos, capital in configs:
        print(f"\n  {'─'*118}")
        print(f"  CONFIG: {config_name} (max {max_pos} posities, ${capital}/trade)")
        print(f"  {'─'*118}")
        print(f"  {'VARIANT':<40} | {'#':>3} TRADES | {'WR':>7} | "
              f"{'P&L':>12} | {'PF':>6} | {'AVG':>10} | {'BARS':>5}")
        print(f"  {'─'*118}")

        config_results = []

        for name, params in variants:
            events = extract_signals_with_bar_tracking(cache, params)
            trades = simulate_portfolio(events, max_pos, capital, KRAKEN_FEE)
            r = print_results(name, trades, capital, max_pos, show_detail=True)
            if r:
                r['config'] = config_name
                config_results.append(r)

        all_results[config_name] = config_results

    # ============================================================
    # SAMENVATTING & CONCLUSIE
    # ============================================================
    print(f"\n{'='*120}")
    print(f"  SAMENVATTING: STOPLOSS IMPACT")
    print(f"{'='*120}")

    for config_name, max_pos, capital in configs:
        results = all_results.get(config_name, [])
        if not results:
            continue

        baseline = results[0]  # ATR 2.0x
        no_trail = results[1] if len(results) > 1 else None  # Geen trail

        print(f"\n  {config_name}:")
        print(f"  {'─'*80}")

        # Sorteer op P&L
        sorted_results = sorted(results, key=lambda x: x.get('pnl', 0), reverse=True)

        for i, r in enumerate(sorted_results):
            marker = " ★" if r == sorted_results[0] else ""
            diff = r['pnl'] - baseline['pnl'] if baseline else 0
            diff_str = f"({'+' if diff >= 0 else ''}{diff:.0f})" if r != baseline else "(baseline)"

            print(f"    {i+1}. {r['name']:<40} | P&L ${r['pnl']:>+8.2f} {diff_str:<12} | "
                  f"PF {r['pf']:>5.2f} | WR {r['wr']:>5.1f}% | "
                  f"Stops: {r.get('stop_trades',0):>2}, ${r.get('stop_pnl',0):>+7.0f}{marker}")

        # Conclusie per config
        best = sorted_results[0]
        print(f"\n    → BESTE: {best['name']}")
        if no_trail:
            trail_impact = baseline['pnl'] - no_trail['pnl']
            print(f"    → Trail stop impact: ${trail_impact:>+.2f} "
                  f"({'helpt' if trail_impact > 0 else 'KOST GELD'})")
            print(f"    → Baseline stops: {baseline.get('stop_trades',0)} trades verloren ${abs(baseline.get('stop_pnl',0)):.0f}")

    # Overall conclusie
    print(f"\n{'='*120}")
    print(f"  CONCLUSIE")
    print(f"{'='*120}")

    for config_name, max_pos, capital in configs:
        results = all_results.get(config_name, [])
        if len(results) < 2:
            continue

        baseline = results[0]
        no_trail = results[1]
        best = max(results, key=lambda x: x.get('pnl', 0))

        trail_helps = baseline['pnl'] > no_trail['pnl']

        print(f"\n  {config_name}:")
        if trail_helps:
            print(f"    ✅ Trailing stop HELPT: +${baseline['pnl'] - no_trail['pnl']:.2f}")
            if best != baseline:
                print(f"    💡 Maar {best['name']} is nog beter: +${best['pnl'] - baseline['pnl']:.2f}")
        else:
            print(f"    ❌ Trailing stop KOST GELD: -${no_trail['pnl'] - baseline['pnl']:.2f}")
            print(f"    💡 Beste alternatief: {best['name']} (+${best['pnl'] - baseline['pnl']:.2f})")

        print(f"    📊 Baseline: {baseline['stop_trades']} stop exits kosten ${abs(baseline.get('stop_pnl',0)):.0f}")
        print(f"    📊 Avg MFE bij stops: trades werden gestopt maar hadden potentie")

    print(f"\n{'='*120}\n")


if __name__ == '__main__':
    main()
