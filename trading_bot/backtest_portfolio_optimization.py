#!/usr/bin/env python3
"""
Portfolio & Sizing Optimalisatie Backtest
-----------------------------------------
Comprehensive test van portfolio-niveau optimalisaties:

A) Positie configuraties: 1x$2000, 2x$1000, 3x$700, 4x$500, 5x$400
B) Signaal ranking: RSI, volume, bounce depth, combo score
C) Coin filtering: volume, volatiliteit, spread
D) Risk management: Kelly criterion, equity curve trailing, max drawdown
E) Compounding: vaste sizing vs herbelleg winsten vs streak-based
F) Market regime: BTC als indicator, alleen traden in gunstige regimes

Budget: $2000 totaal | 0.26% fee | 60 dagen | Chronologisch
"""
import os
import sys
import json
import time
import math
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# Add parent to path for strategy imports
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import DualConfirmStrategy, Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026  # 0.26%
TOTAL_BUDGET = 2000   # $2000 totaal

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('portfolio_opt')


# ============================================================
# DATA LOADING
# ============================================================

def load_cache():
    """Load cached candle data."""
    if not CACHE_FILE.exists():
        print("ERROR: candle_cache_60d.json niet gevonden. Run eerst backtest_improved.py")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    coins = [k for k in cache if not k.startswith('_')]
    print(f"  Data geladen: {len(coins)} coins, {cache.get('_days', '?')} dagen")
    return cache


# ============================================================
# COIN PRE-FILTERING
# ============================================================

def calc_coin_metrics(cache):
    """Bereken metrics per coin voor filtering en ranking."""
    metrics = {}
    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 50:
            continue

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        avg_price = sum(closes) / len(closes) if closes else 0
        avg_dollar_volume = avg_volume * avg_price

        # ATR/price ratio = volatiliteit proxy
        atr = calc_atr(highs, lows, closes, 14)
        volatility = atr / avg_price if avg_price > 0 else 0

        # Spread proxy: avg (high-low)/close
        spreads = [(h - l) / c if c > 0 else 0 for h, l, c in zip(highs, lows, closes)]
        avg_spread = sum(spreads) / len(spreads) if spreads else 0

        metrics[pair] = {
            'avg_volume': avg_volume,
            'avg_dollar_volume': avg_dollar_volume,
            'volatility': volatility,
            'avg_spread': avg_spread,
            'avg_price': avg_price,
            'candle_count': len(candles),
        }

    return metrics


def filter_coins(cache, metrics, min_dollar_vol=0, max_volatility=999,
                 max_spread=999, min_candles=50):
    """Filter coins op basis van metrics. Retourneert set van toegestane pairs."""
    allowed = set()
    for pair, m in metrics.items():
        if m['candle_count'] < min_candles:
            continue
        if m['avg_dollar_volume'] < min_dollar_vol:
            continue
        if m['volatility'] > max_volatility:
            continue
        if m['avg_spread'] > max_spread:
            continue
        allowed.add(pair)
    return allowed


# ============================================================
# SIGNAL EXTRACTION WITH SCORING
# ============================================================

def extract_all_signals(cache, allowed_coins=None, atr_stop_mult=2.0):
    """
    Extract alle buy/sell signalen chronologisch met uitgebreide scoring.
    Retourneert events met score details voor ranking experimenten.
    """
    all_events = []
    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        if allowed_coins and pair not in allowed_coins:
            continue

        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 30:
            continue

        strat = DualConfirmStrategy(
            rsi_dc_max=35, rsi_bb_max=35, rsi_sell=70,
            atr_stop_mult=atr_stop_mult, cooldown_bars=4,
            max_stop_loss_pct=15.0
        )
        position = None

        for i in range(25, len(candles)):
            window = candles[:i + 1]
            current = candles[i]
            bar_time = current['time']

            signal = strat.analyze(window, position, pair)

            if signal.action == 'BUY' and position is None:
                # Bereken uitgebreide scoring
                closes = [c['close'] for c in window]
                highs_w = [c['high'] for c in window]
                lows_w = [c['low'] for c in window]
                rsi = signal.rsi

                # Volume ratio
                volumes = [c.get('volume', 0) for c in window[-20:]]
                avg_vol = sum(volumes) / len(volumes) if volumes else 1
                current_vol = current.get('volume', 0)
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

                # Bounce depth: hoe ver onder DC lower
                prev_highs = highs_w[:-1]
                prev_lows = lows_w[:-1]
                _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, 20)
                dc_depth = 0
                if prev_lowest and prev_lowest > 0:
                    dc_depth = (prev_lowest - current['low']) / prev_lowest * 100

                # BB depth
                bb_mid, bb_upper, bb_lower = calc_bollinger(closes, 20, 2.0)
                bb_depth = 0
                if bb_lower and bb_lower > 0:
                    bb_depth = (bb_lower - current['close']) / bb_lower * 100

                # ATR
                atr = calc_atr(highs_w, lows_w, closes, 14)

                # Candle body position (close vs high-low range)
                candle_range = current['high'] - current['low']
                body_pos = (current['close'] - current['low']) / candle_range if candle_range > 0 else 0.5

                # Combo bounce score
                combo_score = 50
                # RSI component (0-25)
                if rsi < 20: combo_score += 25
                elif rsi < 25: combo_score += 20
                elif rsi < 30: combo_score += 15
                elif rsi < 35: combo_score += 8
                # DC depth component (0-15)
                if dc_depth > 3: combo_score += 15
                elif dc_depth > 2: combo_score += 10
                elif dc_depth > 1: combo_score += 5
                # Volume component (0-10)
                if vol_ratio > 2.0: combo_score += 10
                elif vol_ratio > 1.5: combo_score += 7
                elif vol_ratio > 1.0: combo_score += 3
                else: combo_score -= 5
                # Body position (0-5)
                if body_pos > 0.7: combo_score += 5
                elif body_pos > 0.5: combo_score += 3

                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': 'BUY',
                    'price': signal.price,
                    'stop_price': signal.stop_price,
                    'target_price': signal.target_price,
                    'rsi': rsi,
                    'vol_ratio': vol_ratio,
                    'dc_depth': dc_depth,
                    'bb_depth': bb_depth,
                    'body_pos': body_pos,
                    'combo_score': min(100, max(0, combo_score)),
                    'atr': atr,
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


# ============================================================
# BTC REGIME DETECTION
# ============================================================

def build_btc_regime(btc_candles):
    """
    Bouw BTC regime map: time -> regime.
    Regimes:
      'bull':     BTC trending up strongly (>3% 24h)
      'sideways': BTC between -3% and +3% 24h
      'bear':     BTC trending down (<-3% 24h)

    Ook track SMA20 trend.
    """
    regime_map = {}
    if not btc_candles or len(btc_candles) < 30:
        return regime_map

    closes = [c['close'] for c in btc_candles]

    for i in range(6, len(btc_candles)):
        t = btc_candles[i]['time']
        btc_now = btc_candles[i]['close']

        # 24h change (6 x 4H candles)
        btc_24h_ago = btc_candles[i - 6]['close']
        change_24h = (btc_now - btc_24h_ago) / btc_24h_ago * 100

        # SMA20 trend
        if i >= 20:
            sma20 = sum(closes[i-19:i+1]) / 20
            above_sma = btc_now > sma20
        else:
            above_sma = True

        # 7d change (42 x 4H candles)
        change_7d = 0
        if i >= 42:
            btc_7d_ago = btc_candles[i - 42]['close']
            change_7d = (btc_now - btc_7d_ago) / btc_7d_ago * 100

        # BTC volatility (ATR 14)
        if i >= 14:
            highs = [c['high'] for c in btc_candles[i-13:i+1]]
            lows = [c['low'] for c in btc_candles[i-13:i+1]]
            cls = [c['close'] for c in btc_candles[i-13:i+1]]
            btc_atr = calc_atr(highs, lows, cls, 14)
            btc_vol = btc_atr / btc_now * 100 if btc_now > 0 else 0
        else:
            btc_vol = 2

        if change_24h > 3:
            regime = 'bull'
        elif change_24h < -3:
            regime = 'bear'
        else:
            regime = 'sideways'

        regime_map[t] = {
            'regime': regime,
            'change_24h': change_24h,
            'change_7d': change_7d,
            'above_sma20': above_sma,
            'btc_vol': btc_vol,
        }

    return regime_map


# ============================================================
# PORTFOLIO SIMULATION ENGINE
# ============================================================

def simulate_portfolio(events, config):
    """
    Universele portfolio simulatie engine.

    config dict:
      max_positions: int
      capital_per_trade: float
      commission: float
      ranking_method: None | 'rsi' | 'volume' | 'dc_depth' | 'combo_score'
      sizing_method: 'fixed' | 'dynamic' | 'kelly' | 'compound' | 'streak'
      btc_regime_map: dict | None
      btc_filter_mode: None | 'no_bull' | 'only_bear_sideways' | 'smart'
      equity_trailing: bool (stop trading if equity drops 10%)
      max_drawdown_pct: float (max drawdown before pause)
    """
    max_pos = config['max_positions']
    base_capital = config['capital_per_trade']
    commission = config['commission']
    ranking = config.get('ranking_method')
    sizing = config.get('sizing_method', 'fixed')
    btc_map = config.get('btc_regime_map')
    btc_filter = config.get('btc_filter_mode')
    equity_trailing = config.get('equity_trailing', False)
    max_dd_pct = config.get('max_drawdown_pct', 100)

    positions = {}
    closed_trades = []
    total_capital = max_pos * base_capital
    current_equity = total_capital
    peak_equity = total_capital
    trading_paused = False

    # Kelly criterion state
    kelly_wins = 0
    kelly_losses = 0
    kelly_avg_win = 0
    kelly_avg_loss = 0

    # Streak tracking
    streak = 0  # positive = winning streak, negative = losing

    # Group buy events by time for ranking
    buy_events_by_time = defaultdict(list)
    for e in events:
        if e['action'] == 'BUY':
            buy_events_by_time[e['time']].append(e)

    for event in events:
        if event['action'] in ('SELL_TARGET', 'SELL_STOP'):
            pair = event['pair']
            if pair not in positions:
                continue

            pos = positions[pair]
            entry_price = pos['entry_price']
            exit_price = event['price']
            volume = pos['volume']

            gross_pnl = (exit_price - entry_price) * volume
            entry_fee = entry_price * volume * commission
            exit_fee = exit_price * volume * commission
            net_pnl = gross_pnl - entry_fee - exit_fee

            current_equity += net_pnl
            if current_equity > peak_equity:
                peak_equity = current_equity

            # Update Kelly stats
            if net_pnl >= 0:
                kelly_wins += 1
                kelly_avg_win = (kelly_avg_win * (kelly_wins - 1) + net_pnl) / kelly_wins if kelly_wins > 0 else net_pnl
                streak = max(0, streak) + 1
            else:
                kelly_losses += 1
                kelly_avg_loss = (kelly_avg_loss * (kelly_losses - 1) + abs(net_pnl)) / kelly_losses if kelly_losses > 0 else abs(net_pnl)
                streak = min(0, streak) - 1

            # Check equity trailing / drawdown
            drawdown = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0
            if equity_trailing and drawdown >= 10:
                trading_paused = True
            if drawdown >= max_dd_pct:
                trading_paused = True
            # Resume if equity recovers to 95% of peak
            if trading_paused and drawdown < 5:
                trading_paused = False

            closed_trades.append({
                'pair': pair,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': net_pnl,
                'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                'exit_type': 'TARGET' if event['action'] == 'SELL_TARGET' else 'STOP',
                'capital_used': pos['capital_used'],
                'equity_at_close': current_equity,
            })
            del positions[pair]

        elif event['action'] == 'BUY':
            pair = event['pair']
            if pair in positions:
                continue
            if len(positions) >= max_pos:
                continue
            if trading_paused:
                continue

            # BTC regime filter
            if btc_filter and btc_map:
                regime_info = btc_map.get(event['time'])
                if regime_info:
                    regime = regime_info['regime']
                    if btc_filter == 'no_bull' and regime == 'bull':
                        continue
                    elif btc_filter == 'only_bear_sideways' and regime == 'bull':
                        continue
                    elif btc_filter == 'smart':
                        # Skip als BTC sterk stijgt (>5% 24h) - bounces minder betrouwbaar
                        if regime_info['change_24h'] > 5:
                            continue
                        # Skip als BTC crasht (>-8% 24h) - alles daalt
                        if regime_info['change_24h'] < -8:
                            continue

            # Ranking: als er meerdere BUY signalen tegelijk zijn
            if ranking:
                same_time = buy_events_by_time.get(event['time'], [])
                if len(same_time) > 1:
                    # Sort based on ranking method
                    if ranking == 'rsi':
                        same_time_sorted = sorted(same_time, key=lambda x: x.get('rsi', 50))
                    elif ranking == 'volume':
                        same_time_sorted = sorted(same_time, key=lambda x: x.get('vol_ratio', 1), reverse=True)
                    elif ranking == 'dc_depth':
                        same_time_sorted = sorted(same_time, key=lambda x: x.get('dc_depth', 0), reverse=True)
                    elif ranking == 'combo_score':
                        same_time_sorted = sorted(same_time, key=lambda x: x.get('combo_score', 50), reverse=True)
                    else:
                        same_time_sorted = same_time

                    # How many slots available?
                    slots_available = max_pos - len(positions)
                    best_pairs = [b['pair'] for b in same_time_sorted[:slots_available]]
                    if pair not in best_pairs:
                        continue

            # Determine position size
            if sizing == 'fixed':
                cap = base_capital
            elif sizing == 'dynamic':
                score = event.get('combo_score', 50)
                if score >= 85: cap = base_capital * 1.20
                elif score >= 75: cap = base_capital * 1.10
                elif score >= 65: cap = base_capital * 1.00
                elif score >= 55: cap = base_capital * 0.90
                else: cap = base_capital * 0.80
            elif sizing == 'kelly':
                total_trades = kelly_wins + kelly_losses
                if total_trades >= 5 and kelly_avg_loss > 0:
                    win_rate = kelly_wins / total_trades
                    win_loss_ratio = kelly_avg_win / kelly_avg_loss
                    kelly_f = win_rate - (1 - win_rate) / win_loss_ratio
                    kelly_f = max(0.05, min(0.5, kelly_f))  # Cap between 5% and 50%
                    # Half-Kelly for safety
                    cap = current_equity * kelly_f * 0.5
                    cap = max(base_capital * 0.5, min(base_capital * 1.5, cap))
                else:
                    cap = base_capital
            elif sizing == 'compound':
                # Reinvest: capital grows with equity
                equity_ratio = current_equity / total_capital
                cap = base_capital * equity_ratio
                cap = max(base_capital * 0.5, cap)  # Floor at 50% of base
            elif sizing == 'streak':
                # Increase after wins, decrease after losses
                if streak >= 3:
                    cap = base_capital * 1.30
                elif streak >= 2:
                    cap = base_capital * 1.15
                elif streak >= 1:
                    cap = base_capital * 1.05
                elif streak <= -3:
                    cap = base_capital * 0.60
                elif streak <= -2:
                    cap = base_capital * 0.75
                elif streak <= -1:
                    cap = base_capital * 0.85
                else:
                    cap = base_capital
            else:
                cap = base_capital

            volume = cap / event['price'] if event['price'] > 0 else 0
            if volume <= 0:
                continue

            positions[pair] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
                'capital_used': cap,
            }

    return closed_trades, current_equity


# ============================================================
# RESULTS CALCULATION
# ============================================================

def calc_results(trades, total_capital):
    """Calculate comprehensive results from trades."""
    if not trades:
        return None

    total = len(trades)
    wins = [t for t in trades if t['pnl'] >= 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    gross_wins = sum(t['pnl'] for t in wins)
    gross_losses = abs(sum(t['pnl'] for t in losses))

    wr = len(wins) / total * 100
    pf = gross_wins / gross_losses if gross_losses > 0 else 999
    roi = total_pnl / total_capital * 100
    avg_win = gross_wins / len(wins) if wins else 0
    avg_loss = -gross_losses / len(losses) if losses else 0

    # Max drawdown calculation
    equity_curve = [total_capital]
    for t in trades:
        equity_curve.append(equity_curve[-1] + t['pnl'])
    peak = total_capital
    max_dd = 0
    max_dd_pct = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd = dd

    # Sharpe-like metric (pnl per trade / stddev of pnl)
    pnls = [t['pnl'] for t in trades]
    avg_pnl = total_pnl / total
    variance = sum((p - avg_pnl) ** 2 for p in pnls) / total if total > 1 else 0
    std_pnl = variance ** 0.5
    sharpe_like = avg_pnl / std_pnl if std_pnl > 0 else 0

    # Composite score: weighted combination
    # High P&L + High PF + Low drawdown + Reasonable trade count
    # Normalized: P&L weight 40%, PF 20%, DD penalty 20%, WR 10%, Trade count 10%
    pf_capped = min(pf, 10)
    composite = (
        total_pnl * 0.004 +          # $250 = 1 point
        pf_capped * 10 +             # PF 2 = 20 points
        max(0, 30 - max_dd_pct) +    # DD penalty
        wr * 0.3 +                   # WR 60% = 18 points
        min(total, 50) * 0.2 +       # More trades = better (up to 50)
        sharpe_like * 20             # Risk-adjusted return
    )

    return {
        'trades': total,
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'pnl': total_pnl,
        'roi': roi,
        'pf': pf,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_dd': max_dd,
        'max_dd_pct': max_dd_pct,
        'sharpe_like': sharpe_like,
        'composite': composite,
        'final_equity': trades[-1].get('equity_at_close', total_capital + total_pnl) if trades else total_capital,
    }


def print_row(name, r, total_capital):
    """Print one result row."""
    if r is None:
        print(f"  {name:<42} | {'NO TRADES':>60}")
        return
    print(f"  {name:<42} | {r['trades']:>3}t | WR {r['wr']:>5.1f}% | "
          f"P&L ${r['pnl']:>+8.2f} | ROI {r['roi']:>+6.1f}% | PF {r['pf']:>5.2f} | "
          f"DD {r['max_dd_pct']:>4.1f}% | Score {r['composite']:>5.1f}")


# ============================================================
# TEST SECTIONS
# ============================================================

def test_position_configs(events, btc_regime_map):
    """A) Test alle positie configuraties met $2000 totaal budget."""
    print(f"\n{'='*120}")
    print(f"  A) POSITIE CONFIGURATIES — $2000 totaal budget")
    print(f"  Welke verdeling over posities werkt het best?")
    print(f"{'='*120}")
    print(f"  {'CONFIG':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    configs = [
        ('1x$2000 (all-in per trade)',    1, 2000),
        ('2x$1000 (balanced)',            2, 1000),
        ('3x$667  (diverse)',             3, 667),
        ('4x$500  (spread)',              4, 500),
        ('5x$400  (max diverse)',         5, 400),
    ]

    results = []
    for name, max_pos, cap in configs:
        config = {
            'max_positions': max_pos,
            'capital_per_trade': cap,
            'commission': KRAKEN_FEE,
        }
        trades, _ = simulate_portfolio(events, config)
        r = calc_results(trades, TOTAL_BUDGET)
        if r:
            r['name'] = name
        print_row(name, r, TOTAL_BUDGET)
        results.append((name, r))

    return results


def test_signal_ranking(events, btc_regime_map):
    """B) Test signaal ranking methodes."""
    print(f"\n{'='*120}")
    print(f"  B) SIGNAAL RANKING — Welke coin kiezen bij meerdere signalen?")
    print(f"  Test met 2x$1000 en 3x$667 configuraties")
    print(f"{'='*120}")
    print(f"  {'RANKING METHOD':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    ranking_methods = [
        ('No ranking (FCFS)',       None),
        ('Lowest RSI (oversold)',   'rsi'),
        ('Highest volume ratio',    'volume'),
        ('Deepest DC bounce',       'dc_depth'),
        ('Combo score (all)',       'combo_score'),
    ]

    results = []
    for pos_config in [(2, 1000, '2x$1000'), (3, 667, '3x$667')]:
        max_pos, cap, config_label = pos_config
        print(f"\n  --- {config_label} ---")

        for name, method in ranking_methods:
            config = {
                'max_positions': max_pos,
                'capital_per_trade': cap,
                'commission': KRAKEN_FEE,
                'ranking_method': method,
            }
            trades, _ = simulate_portfolio(events, config)
            r = calc_results(trades, TOTAL_BUDGET)
            label = f"[{config_label}] {name}"
            if r:
                r['name'] = label
            print_row(label, r, TOTAL_BUDGET)
            results.append((label, r))

    return results


def test_coin_filtering(cache, btc_regime_map):
    """C) Test coin filtering op volume, volatiliteit, spread."""
    print(f"\n{'='*120}")
    print(f"  C) COIN FILTERING — Welke coins filteren voor betere resultaten?")
    print(f"{'='*120}")
    print(f"  {'FILTER':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    metrics = calc_coin_metrics(cache)

    # Calculate percentiles for dollar volume
    dollar_vols = sorted([m['avg_dollar_volume'] for m in metrics.values()])
    p25_vol = dollar_vols[len(dollar_vols) // 4] if dollar_vols else 0
    p50_vol = dollar_vols[len(dollar_vols) // 2] if dollar_vols else 0
    p75_vol = dollar_vols[3 * len(dollar_vols) // 4] if dollar_vols else 0

    # Calculate percentiles for volatility
    vols = sorted([m['volatility'] for m in metrics.values()])
    p75_volatility = vols[3 * len(vols) // 4] if vols else 0
    p90_volatility = vols[int(len(vols) * 0.9)] if vols else 0

    filters = [
        ('No filter (all coins)',           {'min_dollar_vol': 0}),
        (f'Vol > P25 (${p25_vol:,.0f})',    {'min_dollar_vol': p25_vol}),
        (f'Vol > P50 (${p50_vol:,.0f})',    {'min_dollar_vol': p50_vol}),
        (f'Vol > P75 (${p75_vol:,.0f})',    {'min_dollar_vol': p75_vol}),
        (f'Low volatility (<P75)',          {'max_volatility': p75_volatility}),
        (f'Low volatility (<P90)',          {'max_volatility': p90_volatility}),
        (f'Vol>P25 + LowVol<P90',          {'min_dollar_vol': p25_vol, 'max_volatility': p90_volatility}),
        (f'Vol>P50 + LowVol<P90',          {'min_dollar_vol': p50_vol, 'max_volatility': p90_volatility}),
    ]

    results = []
    for name, filter_params in filters:
        allowed = filter_coins(cache, metrics, **filter_params)
        events = extract_all_signals(cache, allowed_coins=allowed)
        n_coins = len(allowed)

        config = {
            'max_positions': 2,
            'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
        }
        trades, _ = simulate_portfolio(events, config)
        r = calc_results(trades, TOTAL_BUDGET)
        label = f"{name} ({n_coins} coins)"
        if r:
            r['name'] = label
        print_row(label, r, TOTAL_BUDGET)
        results.append((label, r))

    return results


def test_risk_management(events, btc_regime_map):
    """D) Test risk management: Kelly, equity trailing, drawdown limiet."""
    print(f"\n{'='*120}")
    print(f"  D) RISK MANAGEMENT — Kelly criterion, equity trailing, drawdown limiet")
    print(f"{'='*120}")
    print(f"  {'RISK METHOD':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    risk_configs = [
        ('Baseline (fixed sizing)',         {'sizing_method': 'fixed'}),
        ('Kelly criterion (half-Kelly)',    {'sizing_method': 'kelly'}),
        ('Equity trailing (stop at -10%)',  {'sizing_method': 'fixed', 'equity_trailing': True}),
        ('Max DD 15% pause',               {'sizing_method': 'fixed', 'max_drawdown_pct': 15}),
        ('Max DD 10% pause',               {'sizing_method': 'fixed', 'max_drawdown_pct': 10}),
        ('Kelly + DD 15%',                 {'sizing_method': 'kelly', 'max_drawdown_pct': 15}),
        ('Kelly + Equity trailing',        {'sizing_method': 'kelly', 'equity_trailing': True}),
    ]

    results = []
    for pos_config in [(2, 1000, '2x$1000'), (3, 667, '3x$667')]:
        max_pos, cap, config_label = pos_config
        print(f"\n  --- {config_label} ---")

        for name, extra in risk_configs:
            config = {
                'max_positions': max_pos,
                'capital_per_trade': cap,
                'commission': KRAKEN_FEE,
                'ranking_method': 'combo_score',
                **extra,
            }
            trades, final_eq = simulate_portfolio(events, config)
            r = calc_results(trades, TOTAL_BUDGET)
            label = f"[{config_label}] {name}"
            if r:
                r['name'] = label
            print_row(label, r, TOTAL_BUDGET)
            results.append((label, r))

    return results


def test_compounding(events, btc_regime_map):
    """E) Test compounding methodes."""
    print(f"\n{'='*120}")
    print(f"  E) COMPOUNDING — Vaste sizing vs herbelleg winsten vs streak-based")
    print(f"{'='*120}")
    print(f"  {'SIZING METHOD':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    sizing_methods = [
        ('Fixed ($1000/trade)',         'fixed'),
        ('Dynamic (score-based)',       'dynamic'),
        ('Compound (reinvest)',         'compound'),
        ('Streak (win/loss adjust)',    'streak'),
        ('Kelly criterion',             'kelly'),
    ]

    results = []
    for pos_config in [(2, 1000, '2x$1000'), (3, 667, '3x$667')]:
        max_pos, cap, config_label = pos_config
        print(f"\n  --- {config_label} ---")

        for name, method in sizing_methods:
            config = {
                'max_positions': max_pos,
                'capital_per_trade': cap,
                'commission': KRAKEN_FEE,
                'ranking_method': 'combo_score',
                'sizing_method': method,
            }
            trades, final_eq = simulate_portfolio(events, config)
            r = calc_results(trades, TOTAL_BUDGET)
            label = f"[{config_label}] {name}"
            if r:
                r['name'] = label
                r['final_equity'] = final_eq
            print_row(label, r, TOTAL_BUDGET)
            results.append((label, r))

    return results


def test_market_regime(events, btc_regime_map):
    """F) Test market regime filters met BTC als indicator."""
    print(f"\n{'='*120}")
    print(f"  F) MARKET REGIME — BTC als indicator, wanneer NIET traden?")
    print(f"{'='*120}")
    print(f"  {'REGIME FILTER':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    regime_filters = [
        ('No filter (trade always)',         None),
        ('Skip BTC bull (>3% 24h)',          'no_bull'),
        ('Only bear+sideways',               'only_bear_sideways'),
        ('Smart (skip >5% and <-8%)',        'smart'),
    ]

    results = []
    for pos_config in [(2, 1000, '2x$1000'), (3, 667, '3x$667')]:
        max_pos, cap, config_label = pos_config
        print(f"\n  --- {config_label} ---")

        for name, filter_mode in regime_filters:
            config = {
                'max_positions': max_pos,
                'capital_per_trade': cap,
                'commission': KRAKEN_FEE,
                'ranking_method': 'combo_score',
                'btc_regime_map': btc_regime_map if filter_mode else None,
                'btc_filter_mode': filter_mode,
            }
            trades, _ = simulate_portfolio(events, config)
            r = calc_results(trades, TOTAL_BUDGET)
            label = f"[{config_label}] {name}"
            if r:
                r['name'] = label
            print_row(label, r, TOTAL_BUDGET)
            results.append((label, r))

    return results


def test_combined_best(events, cache, btc_regime_map):
    """Combineer de beste opties uit elke categorie."""
    print(f"\n{'='*120}")
    print(f"  G) GECOMBINEERDE CONFIGURATIES — Beste opties samenvoegen")
    print(f"{'='*120}")
    print(f"  {'COMBINED CONFIG':<42} | {'#':>3}  | {'WR':>7} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>5}  | {'SCORE':>6}")
    print(f"  {'-'*118}")

    metrics = calc_coin_metrics(cache)
    dollar_vols = sorted([m['avg_dollar_volume'] for m in metrics.values()])
    p25_vol = dollar_vols[len(dollar_vols) // 4] if dollar_vols else 0

    # Filtered events
    allowed_filtered = filter_coins(cache, metrics, min_dollar_vol=p25_vol)
    events_filtered = extract_all_signals(cache, allowed_coins=allowed_filtered)

    combined_configs = [
        # Baseline
        ('BASELINE: 2x$1000 fixed FCFS',
         events, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
         }),

        # Combo 1: Best position config + ranking
        ('2x$1000 + combo ranking',
         events, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
         }),

        # Combo 2: + coin filter
        ('2x$1000 + rank + vol filter',
         events_filtered, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
         }),

        # Combo 3: + BTC regime
        ('2x$1000 + rank + filter + BTC',
         events_filtered, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
         }),

        # Combo 4: + compounding
        ('2x$1000 + rank + BTC + compound',
         events_filtered, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'compound',
         }),

        # Combo 5: + Kelly + DD limiet
        ('2x$1000 + rank + BTC + kelly + DD15',
         events_filtered, {
            'max_positions': 2, 'capital_per_trade': 1000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'kelly',
            'max_drawdown_pct': 15,
         }),

        # Same but 3x$667
        ('BASELINE: 3x$667 fixed FCFS',
         events, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
         }),

        ('3x$667 + combo ranking',
         events, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
         }),

        ('3x$667 + rank + vol filter',
         events_filtered, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
         }),

        ('3x$667 + rank + filter + BTC',
         events_filtered, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
         }),

        ('3x$667 + rank + BTC + compound',
         events_filtered, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'compound',
         }),

        ('3x$667 + rank + BTC + kelly + DD15',
         events_filtered, {
            'max_positions': 3, 'capital_per_trade': 667,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'kelly',
            'max_drawdown_pct': 15,
         }),

        # 4x$500 variants
        ('4x$500 + rank + filter + BTC',
         events_filtered, {
            'max_positions': 4, 'capital_per_trade': 500,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
         }),

        ('4x$500 + rank + BTC + compound',
         events_filtered, {
            'max_positions': 4, 'capital_per_trade': 500,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'compound',
         }),

        # 5x$400 variants
        ('5x$400 + rank + filter + BTC',
         events_filtered, {
            'max_positions': 5, 'capital_per_trade': 400,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
         }),

        # 1x$2000 with everything
        ('1x$2000 + rank + filter + BTC',
         events_filtered, {
            'max_positions': 1, 'capital_per_trade': 2000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
         }),

        ('1x$2000 + rank + BTC + kelly + DD15',
         events_filtered, {
            'max_positions': 1, 'capital_per_trade': 2000,
            'commission': KRAKEN_FEE,
            'ranking_method': 'combo_score',
            'btc_regime_map': btc_regime_map,
            'btc_filter_mode': 'smart',
            'sizing_method': 'kelly',
            'max_drawdown_pct': 15,
         }),
    ]

    results = []
    for name, evts, config in combined_configs:
        trades, final_eq = simulate_portfolio(evts, config)
        r = calc_results(trades, TOTAL_BUDGET)
        if r:
            r['name'] = name
            r['final_equity'] = final_eq
        print_row(name, r, TOTAL_BUDGET)
        results.append((name, r))

    return results


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"\n{'#'*120}")
    print(f"  PORTFOLIO & SIZING OPTIMALISATIE — COMPREHENSIVE BACKTEST")
    print(f"  Budget: ${TOTAL_BUDGET} | Fee: {KRAKEN_FEE*100:.2f}% | Strategy: DualConfirm (DC+BB)")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'#'*120}")

    # Load data
    cache = load_cache()
    btc_candles = cache.get('BTC/USD', [])

    # Build BTC regime map
    btc_regime_map = build_btc_regime(btc_candles)
    regime_counts = defaultdict(int)
    for t, info in btc_regime_map.items():
        regime_counts[info['regime']] += 1
    total_bars = sum(regime_counts.values())
    print(f"\n  BTC Regime verdeling (60d):")
    for regime in ['bull', 'sideways', 'bear']:
        cnt = regime_counts.get(regime, 0)
        pct = cnt / total_bars * 100 if total_bars > 0 else 0
        print(f"    {regime:>10}: {cnt:>4} bars ({pct:>5.1f}%)")

    # Extract base signals (no coin filtering)
    print(f"\n  Extracting signals...")
    all_events = extract_all_signals(cache)
    buy_events = [e for e in all_events if e['action'] == 'BUY']
    sell_events = [e for e in all_events if e['action'] != 'BUY']
    print(f"  Total events: {len(all_events)} ({len(buy_events)} buys, {len(sell_events)} sells)")

    # Count simultaneous signals
    from collections import Counter
    buy_times = Counter(e['time'] for e in buy_events)
    multi_signals = {t: c for t, c in buy_times.items() if c > 1}
    print(f"  Times with multiple BUY signals: {len(multi_signals)}")
    if multi_signals:
        max_simultaneous = max(multi_signals.values())
        avg_simultaneous = sum(multi_signals.values()) / len(multi_signals)
        print(f"  Max simultaneous: {max_simultaneous}, Avg: {avg_simultaneous:.1f}")

    # Score distribution
    scores = [e.get('combo_score', 50) for e in buy_events]
    if scores:
        print(f"  Combo score distribution: min={min(scores):.0f}, avg={sum(scores)/len(scores):.0f}, max={max(scores):.0f}")

    # Run all test sections
    all_section_results = []

    results_a = test_position_configs(all_events, btc_regime_map)
    all_section_results.extend(results_a)

    results_b = test_signal_ranking(all_events, btc_regime_map)
    all_section_results.extend(results_b)

    results_c = test_coin_filtering(cache, btc_regime_map)
    all_section_results.extend(results_c)

    results_d = test_risk_management(all_events, btc_regime_map)
    all_section_results.extend(results_d)

    results_e = test_compounding(all_events, btc_regime_map)
    all_section_results.extend(results_e)

    results_f = test_market_regime(all_events, btc_regime_map)
    all_section_results.extend(results_f)

    results_g = test_combined_best(all_events, cache, btc_regime_map)
    all_section_results.extend(results_g)

    # ============================================================
    # GRAND FINALE: TOP 10 OVERALL
    # ============================================================
    print(f"\n{'#'*120}")
    print(f"  GRAND FINALE — TOP 10 PORTFOLIO CONFIGURATIES")
    print(f"  Gerankt op composite score (P&L 40% + PF 20% + DD-penalty 20% + WR 10% + Trades 10%)")
    print(f"{'#'*120}")

    # Filter valid results
    valid = [(name, r) for name, r in all_section_results if r is not None]
    # Sort by composite score
    valid.sort(key=lambda x: x[1].get('composite', 0), reverse=True)

    # De-duplicate by name (keep highest score)
    seen = set()
    unique = []
    for name, r in valid:
        if name not in seen:
            seen.add(name)
            unique.append((name, r))

    print(f"\n  {'RANK':<5} {'CONFIG':<48} | {'#':>3}t | {'WR':>6} | "
          f"{'P&L':>11} | {'ROI':>7} | {'PF':>5} | {'DD':>5} | {'SCORE':>6}")
    print(f"  {'-'*120}")

    for i, (name, r) in enumerate(unique[:10]):
        rank = f"#{i+1}"
        marker = " ***" if i == 0 else " **" if i == 1 else " *" if i == 2 else ""
        print(f"  {rank:<5} {name:<48} | {r['trades']:>3}  | {r['wr']:>5.1f}% | "
              f"${r['pnl']:>+9.2f} | {r['roi']:>+6.1f}% | {r['pf']:>5.2f} | "
              f"{r['max_dd_pct']:>4.1f}% | {r['composite']:>5.1f}{marker}")

    # ============================================================
    # TOP 3 SAMENVATTING
    # ============================================================
    print(f"\n{'#'*120}")
    print(f"  TOP 3 AANBEVELINGEN")
    print(f"{'#'*120}")

    for i, (name, r) in enumerate(unique[:3]):
        print(f"\n  {'='*80}")
        print(f"  #{i+1}: {name}")
        print(f"  {'='*80}")
        print(f"    Trades:       {r['trades']}")
        print(f"    Win Rate:     {r['wr']:.1f}%")
        print(f"    Total P&L:    ${r['pnl']:+.2f}")
        print(f"    ROI:          {r['roi']:+.1f}%")
        print(f"    Profit Factor:{r['pf']:.2f}")
        print(f"    Max Drawdown: {r['max_dd_pct']:.1f}% (${r['max_dd']:.2f})")
        print(f"    Avg Win:      ${r['avg_win']:+.2f}")
        print(f"    Avg Loss:     ${r['avg_loss']:+.2f}")
        print(f"    Sharpe-like:  {r['sharpe_like']:.3f}")
        print(f"    Composite:    {r['composite']:.1f}")

    # Key insights
    print(f"\n{'#'*120}")
    print(f"  KEY INSIGHTS")
    print(f"{'#'*120}")

    # Best per category
    categories = {
        'Position Config': results_a,
        'Signal Ranking': results_b,
        'Coin Filtering': results_c,
        'Risk Management': results_d,
        'Compounding': results_e,
        'Market Regime': results_f,
        'Combined': results_g,
    }

    for cat_name, cat_results in categories.items():
        valid_cat = [(n, r) for n, r in cat_results if r is not None]
        if valid_cat:
            best = max(valid_cat, key=lambda x: x[1].get('pnl', -9999))
            print(f"\n  Best {cat_name}:")
            print(f"    {best[0]}: P&L ${best[1]['pnl']:+.2f}, PF {best[1]['pf']:.2f}, WR {best[1]['wr']:.1f}%")

    print(f"\n{'#'*120}\n")


if __name__ == '__main__':
    main()
