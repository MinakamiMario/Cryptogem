#!/usr/bin/env python3
"""
TIMEMAX EXIT DEEP ANALYSIS — Waarom falen deze trades en kunnen we ze redden?
=============================================================================
Draait V9B config (TP7%, SL15%, TimeMax 8 bars) en analyseert elke TimeMax
exit trade in detail:

Per trade:
  1. Pair naam
  2. P&L op moment van TimeMax exit
  3. Was de trade ooit groen? Max high P&L
  4. Max drawdown tijdens de trade
  5. RSI op moment van exit
  6. Wat GEBEURDE er NA de exit? (10 bars: raakt het +7% of -15%?)

Categorisering:
  A. "Bijna gewonnen" — ooit >+3% groen maar zakte terug
  B. "Nooit kans" — nooit boven +2%
  C. "Langzame bounce" — geleidelijk stijgend, had meer tijd nodig
  D. "Crash na entry" — zakte direct fors (max DD > -5% in eerste 3 bars)

Gebruik:
    python analyze_timemax_trades.py
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

# V9B Config
V9B_CFG = {
    'dc_period': 20,
    'bb_period': 20,
    'bb_dev': 2.0,
    'rsi_period': 14,
    'rsi_max': 40,
    'atr_period': 14,
    'vol_min_pct': 0.5,
    'vol_spike': True,
    'vol_spike_mult': 2.0,
    'vol_confirm': True,
    'vol_confirm_mult': 1.0,
    # V9B exits
    'profit_target_pct': 7.0,
    'fixed_stop_pct': 15.0,
    'time_max_bars': 8,
    # Cooldown
    'cooldown_bars': 4,
    'cooldown_stop': 8,
}


# ============================================================
# V9B STRATEGY — Profit Target + Fixed Stop + TimeMax
# ============================================================

class V9BStrategy:
    """V9B: TP7% SL15% TM8 — DualConfirm entry."""

    def __init__(self, cfg):
        self.donchian_period = cfg.get('dc_period', 20)
        self.bb_period = cfg.get('bb_period', 20)
        self.bb_dev = cfg.get('bb_dev', 2.0)
        self.rsi_period = cfg.get('rsi_period', 14)
        self.rsi_max = cfg.get('rsi_max', 40)
        self.atr_period = cfg.get('atr_period', 14)
        self.volume_min_pct = cfg.get('vol_min_pct', 0.5)
        self.use_volume_spike = cfg.get('vol_spike', False)
        self.volume_spike_mult = cfg.get('vol_spike_mult', 2.0)
        self.use_vol_confirm = cfg.get('vol_confirm', False)
        self.vol_confirm_mult = cfg.get('vol_confirm_mult', 1.0)

        self.profit_target_pct = cfg.get('profit_target_pct', 7.0)
        self.fixed_stop_pct = cfg.get('fixed_stop_pct', 15.0)
        self.time_max_bars = cfg.get('time_max_bars', 8)

        self.cooldown_bars = cfg.get('cooldown_bars', 4)
        self.cooldown_after_stop = cfg.get('cooldown_stop', 8)

        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def check_entry(self, candles):
        """Check entry conditions. Returns dict or None."""
        min_bars = max(self.donchian_period, self.bb_period,
                       self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return None

        self.bar_count = len(candles)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1],
                                          self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(
            closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, prev_lowest, bb_lower]):
            return None

        close = candles[-1]['close']
        low = candles[-1]['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # Cooldown
        cd = (self.cooldown_after_stop if self.last_exit_was_stop
              else self.cooldown_bars)
        if (self.bar_count - self.last_exit_bar) < cd:
            return None

        # Base volume
        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return None

        # Dual confirm
        dc_sig = (low <= prev_lowest and rsi < self.rsi_max
                  and close > prev_close)
        bb_sig = (close <= bb_lower and rsi < self.rsi_max
                  and close > prev_close)
        if not (dc_sig and bb_sig):
            return None

        # Volume spike
        if self.use_volume_spike and volumes:
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return None

        # Volume confirm
        if (self.use_vol_confirm and len(volumes) >= 2
                and volumes[-2] > 0):
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return None

        return {
            'price': close,
            'rsi': rsi,
            'vol_ratio': volumes[-1] / vol_avg if vol_avg > 0 else 0,
        }

    def check_exit(self, candles, entry_price, entry_bar):
        """Check exit. Returns dict with reason or None (hold)."""
        self.bar_count = len(candles)
        bars_in = self.bar_count - entry_bar

        closes = [c['close'] for c in candles]
        close = candles[-1]['close']
        pnl_pct = (close - entry_price) / entry_price * 100

        rsi = calc_rsi(closes, self.rsi_period)

        # 1. PROFIT TARGET
        if pnl_pct >= self.profit_target_pct:
            return {'reason': 'PROFIT TARGET', 'price': close,
                    'pnl_pct': pnl_pct, 'rsi': rsi, 'bars': bars_in}

        # 2. FIXED STOP
        if pnl_pct <= -self.fixed_stop_pct:
            return {'reason': 'FIXED STOP', 'price': close,
                    'pnl_pct': pnl_pct, 'rsi': rsi, 'bars': bars_in}

        # 3. TIME MAX
        if bars_in >= self.time_max_bars:
            return {'reason': 'TIME MAX', 'price': close,
                    'pnl_pct': pnl_pct, 'rsi': rsi, 'bars': bars_in}

        return None

    def record_exit(self, was_stop):
        self.last_exit_bar = self.bar_count
        self.last_exit_was_stop = was_stop


# ============================================================
# PORTFOLIO BACKTEST + TIMEMAX ANALYSIS
# ============================================================

def run_analysis():
    print("=" * 100)
    print("TIMEMAX EXIT DEEP ANALYSIS — V9B (TP7% SL15% TM8)")
    print("=" * 100)

    # Load data
    if not CACHE_FILE.exists():
        print(f"FOUT: Cache niet gevonden: {CACHE_FILE}")
        sys.exit(1)

    with open(CACHE_FILE) as f:
        data = json.load(f)

    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins, cache: {CACHE_FILE.name}")

    # Init strategies
    strategies = {p: V9BStrategy(V9B_CFG) for p in coins if p in data}
    coin_list = [c for c in coins if c in data]

    max_bars = max(len(data[p]) for p in coin_list)
    start_bar = 50
    pos_size = 2000
    max_pos = 1

    # State
    positions = {}  # pair -> {entry_price, entry_bar, entry_rsi}
    all_trades = []

    for bar in range(start_bar, max_bars):
        buys = []
        sells = []

        for pair in coin_list:
            candles = data.get(pair, [])
            if bar >= len(candles):
                continue

            window = candles[:bar + 1]

            if pair in positions:
                pos = positions[pair]
                sig = strategies[pair].check_exit(
                    window, pos['entry_price'], pos['entry_bar'])
                if sig:
                    sells.append((pair, sig))
            else:
                sig = strategies[pair].check_entry(window)
                if sig:
                    buys.append((pair, sig, candles[bar]))

        # Process sells
        for pair, sig in sells:
            pos = positions[pair]
            sp = sig['price']
            gross = (sp - pos['entry_price']) / pos['entry_price'] * pos_size
            fees = (pos_size * KRAKEN_FEE
                    + (pos_size + gross) * KRAKEN_FEE)
            net = gross - fees

            is_stop = sig['reason'] in ('FIXED STOP', 'TIME MAX') and net < 0
            strategies[pair].record_exit(is_stop)

            trade = {
                'pair': pair,
                'entry_price': pos['entry_price'],
                'entry_bar': pos['entry_bar'],
                'exit_price': sp,
                'exit_bar': bar,
                'pnl_usd': net,
                'pnl_pct': sig['pnl_pct'],
                'reason': sig['reason'],
                'bars_held': sig['bars'],
                'entry_rsi': pos.get('entry_rsi', 0),
                'exit_rsi': sig['rsi'],
            }
            all_trades.append(trade)
            del positions[pair]

        # Process buys (volume ranking)
        if len(positions) < max_pos and buys:
            def rank(item):
                p, s, c = item
                cd = data.get(p, [])
                vs = [x.get('volume', 0) for x in cd[max(0, bar - 20):bar + 1]]
                if vs and len(vs) > 1:
                    avg = sum(vs[:-1]) / max(1, len(vs) - 1)
                    if avg > 0:
                        return vs[-1] / avg
                return 0
            buys.sort(key=rank, reverse=True)

            for pair, sig, candle in buys:
                if len(positions) >= max_pos:
                    break
                positions[pair] = {
                    'entry_price': sig['price'],
                    'entry_bar': bar,
                    'entry_rsi': sig['rsi'],
                }

    # Close remaining
    for pair, pos in list(positions.items()):
        candles = data.get(pair, [])
        if candles:
            lp = candles[-1]['close']
            gross = (lp - pos['entry_price']) / pos['entry_price'] * pos_size
            fees = (pos_size * KRAKEN_FEE + (pos_size + gross) * KRAKEN_FEE)
            net = gross - fees
            pnl_pct = (lp - pos['entry_price']) / pos['entry_price'] * 100
            all_trades.append({
                'pair': pair,
                'entry_price': pos['entry_price'],
                'entry_bar': pos['entry_bar'],
                'exit_price': lp,
                'exit_bar': max_bars - 1,
                'pnl_usd': net,
                'pnl_pct': pnl_pct,
                'reason': 'END',
                'bars_held': max_bars - 1 - pos['entry_bar'],
                'entry_rsi': pos.get('entry_rsi', 0),
                'exit_rsi': 0,
            })

    # ============================================================
    # OVERALL SUMMARY
    # ============================================================
    print(f"\n{'=' * 100}")
    print("OVERALL V9B RESULTATEN")
    print(f"{'=' * 100}")
    print(f"Totaal trades: {len(all_trades)}")
    total_pnl = sum(t['pnl_usd'] for t in all_trades)
    wins = [t for t in all_trades if t['pnl_usd'] > 0]
    losses = [t for t in all_trades if t['pnl_usd'] <= 0]
    wr = len(wins) / len(all_trades) * 100 if all_trades else 0
    print(f"Win Rate: {wr:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"Totaal P&L: ${total_pnl:+.0f}")

    # Per exit reason
    reasons = {}
    for t in all_trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0, 'wins': 0})
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl_usd']
        if t['pnl_usd'] > 0:
            reasons[r]['wins'] += 1

    print(f"\nExit Reason Breakdown:")
    print(f"{'Reason':<18} {'#':>4} {'WR%':>6} {'P&L':>10} {'Avg':>10}")
    print(f"{'-' * 52}")
    for r, d in sorted(reasons.items(), key=lambda x: -x[1]['n']):
        wr_r = d['wins'] / d['n'] * 100 if d['n'] else 0
        avg_r = d['pnl'] / d['n'] if d['n'] else 0
        print(f"{r:<18} {d['n']:>4} {wr_r:>5.1f}% ${d['pnl']:>+9.0f} ${avg_r:>+9.0f}")

    # ============================================================
    # TIMEMAX DEEP ANALYSIS
    # ============================================================
    tm_trades = [t for t in all_trades if t['reason'] == 'TIME MAX']

    if not tm_trades:
        print("\nGeen TimeMax trades gevonden!")
        return

    print(f"\n{'=' * 100}")
    print(f"TIMEMAX EXIT DEEP ANALYSIS — {len(tm_trades)} trades")
    print(f"{'=' * 100}")

    # Detailed analysis per trade
    detailed = []

    for t in tm_trades:
        pair = t['pair']
        entry_price = t['entry_price']
        entry_bar = t['entry_bar']
        exit_bar = t['exit_bar']
        candles = data.get(pair, [])

        if not candles:
            continue

        # ---- Intra-trade analyse: bar-by-bar ----
        max_high_pnl_pct = 0.0   # Beste moment (high-based)
        max_close_pnl_pct = 0.0  # Beste close P&L
        min_low_pnl_pct = 0.0    # Ergste moment (low-based)
        min_close_pnl_pct = 0.0  # Ergste close P&L
        bar_pnls = []             # Close P&L per bar
        first_3_bars_min = 0.0    # Min P&L in eerste 3 bars

        for b in range(entry_bar, min(exit_bar + 1, len(candles))):
            c = candles[b]
            # High-based P&L (intrabar)
            high_pnl = (c['high'] - entry_price) / entry_price * 100
            if high_pnl > max_high_pnl_pct:
                max_high_pnl_pct = high_pnl
            # Low-based P&L (intrabar)
            low_pnl = (c['low'] - entry_price) / entry_price * 100
            if low_pnl < min_low_pnl_pct:
                min_low_pnl_pct = low_pnl
            # Close-based P&L
            close_pnl = (c['close'] - entry_price) / entry_price * 100
            bar_pnls.append(close_pnl)
            if close_pnl > max_close_pnl_pct:
                max_close_pnl_pct = close_pnl
            if close_pnl < min_close_pnl_pct:
                min_close_pnl_pct = close_pnl
            # First 3 bars check
            if b - entry_bar < 3:
                if low_pnl < first_3_bars_min:
                    first_3_bars_min = low_pnl

        # ---- RSI op exit moment ----
        exit_rsi = t['exit_rsi']
        if exit_rsi == 0 and exit_bar < len(candles):
            closes_for_rsi = [c['close'] for c in candles[:exit_bar + 1]]
            exit_rsi = calc_rsi(closes_for_rsi, 14)

        # ---- Wat gebeurt NA de exit? 10 bars vooruit ----
        post_exit_bars = []
        post_max_pnl = 0.0
        post_min_pnl = 0.0
        post_hits_tp = False  # Raakt het +7% na exit?
        post_hits_sl = False  # Raakt het -15% na exit?
        post_bars_to_tp = None
        post_bars_to_sl = None

        for b in range(exit_bar + 1, min(exit_bar + 11, len(candles))):
            c = candles[b]
            # P&L t.o.v. ENTRY price (alsof we vasthielden)
            high_pnl = (c['high'] - entry_price) / entry_price * 100
            low_pnl = (c['low'] - entry_price) / entry_price * 100
            close_pnl = (c['close'] - entry_price) / entry_price * 100

            post_exit_bars.append({
                'bar': b - exit_bar,
                'close_pnl': close_pnl,
                'high_pnl': high_pnl,
                'low_pnl': low_pnl,
            })

            if high_pnl > post_max_pnl:
                post_max_pnl = high_pnl
            if low_pnl < post_min_pnl:
                post_min_pnl = low_pnl

            if high_pnl >= 7.0 and not post_hits_tp:
                post_hits_tp = True
                post_bars_to_tp = b - exit_bar

            if low_pnl <= -15.0 and not post_hits_sl:
                post_hits_sl = True
                post_bars_to_sl = b - exit_bar

        # ---- P&L trend: stijgend of dalend? ----
        trend = "FLAT"
        if len(bar_pnls) >= 3:
            first_half = bar_pnls[:len(bar_pnls) // 2]
            second_half = bar_pnls[len(bar_pnls) // 2:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_second > avg_first + 0.5:
                trend = "RISING"
            elif avg_second < avg_first - 0.5:
                trend = "FALLING"

        # ---- Categorisering ----
        if max_high_pnl_pct >= 3.0:
            category = "A: BIJNA GEWONNEN"
        elif first_3_bars_min < -5.0:
            category = "D: CRASH NA ENTRY"
        elif trend == "RISING" and max_close_pnl_pct > 0:
            category = "C: LANGZAME BOUNCE"
        elif max_high_pnl_pct < 2.0:
            category = "B: NOOIT KANS"
        elif trend == "RISING":
            category = "C: LANGZAME BOUNCE"
        else:
            category = "B: NOOIT KANS"

        detail = {
            'pair': pair,
            'entry_price': entry_price,
            'exit_price': t['exit_price'],
            'pnl_usd': t['pnl_usd'],
            'pnl_pct': t['pnl_pct'],
            'bars_held': t['bars_held'],
            'entry_rsi': t['entry_rsi'],
            'exit_rsi': exit_rsi,
            'max_high_pnl_pct': max_high_pnl_pct,
            'max_close_pnl_pct': max_close_pnl_pct,
            'min_low_pnl_pct': min_low_pnl_pct,
            'min_close_pnl_pct': min_close_pnl_pct,
            'first_3_bars_min': first_3_bars_min,
            'trend': trend,
            'category': category,
            'bar_pnls': bar_pnls,
            # Post-exit
            'post_max_pnl': post_max_pnl,
            'post_min_pnl': post_min_pnl,
            'post_hits_tp': post_hits_tp,
            'post_hits_sl': post_hits_sl,
            'post_bars_to_tp': post_bars_to_tp,
            'post_bars_to_sl': post_bars_to_sl,
            'post_exit_bars': post_exit_bars,
            # Entry bar index for timestamp
            'entry_bar_idx': entry_bar,
            'exit_bar_idx': exit_bar,
        }
        detailed.append(detail)

    # ============================================================
    # PRINT DETAILED RESULTS
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"DETAIL PER TIMEMAX TRADE ({len(detailed)} trades)")
    print(f"{'=' * 100}")

    for i, d in enumerate(detailed):
        pair = d['pair']
        candles = data.get(pair, [])
        entry_ts = candles[d['entry_bar_idx']]['time'] if d['entry_bar_idx'] < len(candles) else 0
        exit_ts = candles[d['exit_bar_idx']]['time'] if d['exit_bar_idx'] < len(candles) else 0
        entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if entry_ts else '?'
        exit_dt = datetime.fromtimestamp(exit_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if exit_ts else '?'

        was_green = "JA" if d['max_high_pnl_pct'] > 0 else "NEE"

        print(f"\n--- Trade #{i + 1}: {pair} ---")
        print(f"  Categorie:     {d['category']}")
        print(f"  Entry:         ${d['entry_price']:.6f} ({entry_dt} UTC)")
        print(f"  Exit:          ${d['exit_price']:.6f} ({exit_dt} UTC)")
        print(f"  P&L:           ${d['pnl_usd']:+.0f} ({d['pnl_pct']:+.2f}%)")
        print(f"  Bars gehouden: {d['bars_held']}")
        print(f"  Entry RSI:     {d['entry_rsi']:.1f}")
        print(f"  Exit RSI:      {d['exit_rsi']:.1f}")
        print(f"  Ooit groen?    {was_green} (max high: {d['max_high_pnl_pct']:+.2f}%, max close: {d['max_close_pnl_pct']:+.2f}%)")
        print(f"  Max drawdown:  {d['min_low_pnl_pct']:+.2f}% (low-based), {d['min_close_pnl_pct']:+.2f}% (close-based)")
        print(f"  Eerste 3 bars: min {d['first_3_bars_min']:+.2f}%")
        print(f"  P&L trend:     {d['trend']}")

        # Bar-by-bar P&L
        if d['bar_pnls']:
            pnl_str = " | ".join([f"B{j}:{p:+.1f}%" for j, p in enumerate(d['bar_pnls'])])
            print(f"  Bar-by-bar:    {pnl_str}")

        # Post-exit analysis
        print(f"  --- NA EXIT (10 bars vooruit) ---")
        if d['post_exit_bars']:
            post_str = " | ".join(
                [f"B+{pb['bar']}:{pb['close_pnl']:+.1f}%" for pb in d['post_exit_bars']])
            print(f"  Post-exit:     {post_str}")
            print(f"  Post max:      {d['post_max_pnl']:+.2f}%  Post min: {d['post_min_pnl']:+.2f}%")
            if d['post_hits_tp']:
                print(f"  RAAKT +7% TP:  JA! Na {d['post_bars_to_tp']} bars — GEMISTE WINST!")
            else:
                print(f"  RAAKT +7% TP:  NEE (max was {d['post_max_pnl']:+.2f}%)")
            if d['post_hits_sl']:
                print(f"  RAAKT -15% SL: JA na {d['post_bars_to_sl']} bars — EXIT WAS GOED")
            else:
                print(f"  RAAKT -15% SL: NEE (min was {d['post_min_pnl']:+.2f}%)")
        else:
            print(f"  Post-exit:     Geen data (einde dataset)")

    # ============================================================
    # CATEGORIE SAMENVATTING
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"CATEGORIE SAMENVATTING")
    print(f"{'=' * 100}")

    categories = {}
    for d in detailed:
        cat = d['category']
        categories.setdefault(cat, {
            'count': 0, 'pnl': 0, 'trades': [],
            'post_tp_hits': 0, 'post_sl_hits': 0
        })
        categories[cat]['count'] += 1
        categories[cat]['pnl'] += d['pnl_usd']
        categories[cat]['trades'].append(d)
        if d['post_hits_tp']:
            categories[cat]['post_tp_hits'] += 1
        if d['post_hits_sl']:
            categories[cat]['post_sl_hits'] += 1

    for cat in sorted(categories.keys()):
        c = categories[cat]
        avg_pnl = c['pnl'] / c['count']
        pct_of_total = c['count'] / len(detailed) * 100
        print(f"\n{cat}:")
        print(f"  Aantal:          {c['count']} ({pct_of_total:.0f}% van TimeMax trades)")
        print(f"  Totaal P&L:      ${c['pnl']:+.0f}")
        print(f"  Gem. P&L:        ${avg_pnl:+.0f}")
        print(f"  Raakt TP na exit: {c['post_tp_hits']}/{c['count']}")
        print(f"  Raakt SL na exit: {c['post_sl_hits']}/{c['count']}")

        # Per trade in category
        for d in c['trades']:
            tp_marker = " ** GEMIST **" if d['post_hits_tp'] else ""
            print(f"    {d['pair']:<15} P&L: ${d['pnl_usd']:+5.0f} ({d['pnl_pct']:+5.2f}%) "
                  f"MaxHigh: {d['max_high_pnl_pct']:+5.2f}% "
                  f"MaxDD: {d['min_low_pnl_pct']:+5.2f}% "
                  f"PostMax: {d['post_max_pnl']:+5.2f}% "
                  f"ExitRSI: {d['exit_rsi']:.0f}"
                  f"{tp_marker}")

    # ============================================================
    # KEY INSIGHTS
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"KEY INSIGHTS")
    print(f"{'=' * 100}")

    total_tm_pnl = sum(d['pnl_usd'] for d in detailed)
    avg_tm_pnl = total_tm_pnl / len(detailed) if detailed else 0
    green_count = sum(1 for d in detailed if d['max_high_pnl_pct'] > 0)
    post_tp_count = sum(1 for d in detailed if d['post_hits_tp'])
    post_sl_count = sum(1 for d in detailed if d['post_hits_sl'])
    would_win = sum(1 for d in detailed if d['post_hits_tp'] and not d['post_hits_sl'])
    would_lose = sum(1 for d in detailed if d['post_hits_sl'] and not d['post_hits_tp'])
    both = sum(1 for d in detailed if d['post_hits_tp'] and d['post_hits_sl'])

    # How much P&L lost by TimeMax exit vs holding?
    tp_profit_per_trade = pos_size * 0.07 - (pos_size * KRAKEN_FEE * 2)  # ~$140 - $10.4 fees
    potential_recovery = post_tp_count * tp_profit_per_trade

    print(f"\n  TimeMax trades:        {len(detailed)}")
    print(f"  Totaal P&L:            ${total_tm_pnl:+.0f}")
    print(f"  Gem. P&L per trade:    ${avg_tm_pnl:+.0f}")
    print(f"  Ooit groen geweest:    {green_count}/{len(detailed)} ({green_count / len(detailed) * 100:.0f}%)")
    print(f"")
    print(f"  --- POST-EXIT ANALYSE ---")
    print(f"  Raakt +7% TP na exit:  {post_tp_count}/{len(detailed)} ({post_tp_count / len(detailed) * 100:.0f}%)")
    print(f"  Raakt -15% SL na exit: {post_sl_count}/{len(detailed)} ({post_sl_count / len(detailed) * 100:.0f}%)")
    print(f"  Raakt TP maar niet SL: {would_win} (gemiste wins)")
    print(f"  Raakt SL maar niet TP: {would_lose} (goede exits)")
    print(f"  Raakt beide:           {both} (ambigue)")
    print(f"  Raakt geen van beide:  {len(detailed) - post_tp_count - would_lose - both + (both if post_sl_count > 0 else 0)}")
    neither = sum(1 for d in detailed if not d['post_hits_tp'] and not d['post_hits_sl'])
    print(f"  Raakt geen van beide:  {neither} (drijft rond)")
    print(f"")
    print(f"  --- POTENTIELE VERBETERING ---")
    print(f"  Als we TM{V9B_CFG['time_max_bars']} -> TM18 (verdubbelen):")
    missed = sum(1 for d in detailed
                 if d['post_hits_tp'] and d['post_bars_to_tp'] and d['post_bars_to_tp'] <= 10)
    print(f"    Trades die TP raken in +10 bars: {missed}")
    print(f"    Potentiele extra winst: ~${missed * tp_profit_per_trade:.0f}")
    print(f"    Maar trades die -15% raken: {post_sl_count} (risico)")

    # Average RSI at exit
    avg_exit_rsi = sum(d['exit_rsi'] for d in detailed) / len(detailed)
    print(f"\n  Gem. RSI bij TimeMax exit: {avg_exit_rsi:.1f}")

    # RSI distribution
    rsi_ranges = {'<30': 0, '30-40': 0, '40-50': 0, '50-60': 0, '>60': 0}
    for d in detailed:
        rsi = d['exit_rsi']
        if rsi < 30:
            rsi_ranges['<30'] += 1
        elif rsi < 40:
            rsi_ranges['30-40'] += 1
        elif rsi < 50:
            rsi_ranges['40-50'] += 1
        elif rsi < 60:
            rsi_ranges['50-60'] += 1
        else:
            rsi_ranges['>60'] += 1
    print(f"  RSI distributie bij exit:")
    for k, v in rsi_ranges.items():
        print(f"    RSI {k}: {v} trades ({v / len(detailed) * 100:.0f}%)")

    # P&L distribution
    pnl_ranges = {'< -5%': 0, '-5% to -2%': 0, '-2% to 0%': 0,
                  '0% to +2%': 0, '+2% to +5%': 0, '> +5%': 0}
    for d in detailed:
        p = d['pnl_pct']
        if p < -5:
            pnl_ranges['< -5%'] += 1
        elif p < -2:
            pnl_ranges['-5% to -2%'] += 1
        elif p < 0:
            pnl_ranges['-2% to 0%'] += 1
        elif p < 2:
            pnl_ranges['0% to +2%'] += 1
        elif p < 5:
            pnl_ranges['+2% to +5%'] += 1
        else:
            pnl_ranges['> +5%'] += 1

    print(f"\n  P&L distributie bij TimeMax exit:")
    for k, v in pnl_ranges.items():
        print(f"    {k}: {v} trades ({v / len(detailed) * 100:.0f}%)")

    # Max high P&L distribution — how close did they get to +7%?
    print(f"\n  Hoe dicht bij +7% TP kwamen TimeMax trades?")
    tp_ranges = {'< +1%': 0, '+1% to +3%': 0, '+3% to +5%': 0,
                 '+5% to +7%': 0, '>= +7%': 0}
    for d in detailed:
        mh = d['max_high_pnl_pct']
        if mh < 1:
            tp_ranges['< +1%'] += 1
        elif mh < 3:
            tp_ranges['+1% to +3%'] += 1
        elif mh < 5:
            tp_ranges['+3% to +5%'] += 1
        elif mh < 7:
            tp_ranges['+5% to +7%'] += 1
        else:
            tp_ranges['>= +7%'] += 1

    for k, v in tp_ranges.items():
        print(f"    Max High {k}: {v} trades ({v / len(detailed) * 100:.0f}%)")

    # ============================================================
    # SCENARIO SIMULATIE
    # ============================================================
    print(f"\n{'=' * 100}")
    print(f"SCENARIO SIMULATIE: WAT ALS WE TIMEMAX AANPASSEN?")
    print(f"{'=' * 100}")

    # Scenario 1: TM = 12
    # Scenario 2: TM = 16
    # Scenario 3: TM = onbeperkt (alleen TP/SL)
    # For each: calculate how trades would have ended

    for tm_scenario in [12, 16, 24, 999]:
        tm_label = f"TM{tm_scenario}" if tm_scenario < 100 else "Geen TM (alleen TP/SL)"
        wins_s = 0
        losses_s = 0
        pnl_s = 0
        exits_s = {'PROFIT TARGET': 0, 'FIXED STOP': 0, 'TIME MAX': 0, 'STILL_OPEN': 0}

        for d in detailed:
            pair = d['pair']
            entry_price = d['entry_price']
            entry_bar = d['entry_bar_idx']
            candles = data.get(pair, [])

            # Simuleer: wat als we langer vasthielden?
            extra_bars = tm_scenario - V9B_CFG['time_max_bars']
            max_look = min(entry_bar + tm_scenario, len(candles))

            result_reason = 'STILL_OPEN'
            result_pnl_pct = 0
            result_bar = max_look - 1

            for b in range(entry_bar, max_look):
                c = candles[b]
                high_pnl = (c['high'] - entry_price) / entry_price * 100
                low_pnl = (c['low'] - entry_price) / entry_price * 100
                close_pnl = (c['close'] - entry_price) / entry_price * 100

                # Check TP first (within bar)
                if high_pnl >= 7.0:
                    result_reason = 'PROFIT TARGET'
                    result_pnl_pct = 7.0  # Exit at TP
                    result_bar = b
                    break

                # Check SL
                if low_pnl <= -15.0:
                    result_reason = 'FIXED STOP'
                    result_pnl_pct = -15.0
                    result_bar = b
                    break

                # TimeMax
                if b - entry_bar >= tm_scenario and tm_scenario < 100:
                    result_reason = 'TIME MAX'
                    result_pnl_pct = close_pnl
                    result_bar = b
                    break

                # Last bar
                if b == max_look - 1:
                    result_pnl_pct = close_pnl

            # Calculate P&L
            gross = result_pnl_pct / 100 * pos_size
            fees = pos_size * KRAKEN_FEE + (pos_size + gross) * KRAKEN_FEE
            net = gross - fees

            pnl_s += net
            exits_s[result_reason] += 1
            if net > 0:
                wins_s += 1
            else:
                losses_s += 1

        wr_s = wins_s / len(detailed) * 100 if detailed else 0

        print(f"\n  Scenario: {tm_label}")
        print(f"    WR: {wr_s:.1f}% ({wins_s}W/{losses_s}L)")
        print(f"    Totaal P&L: ${pnl_s:+.0f} (was ${total_tm_pnl:+.0f})")
        print(f"    Verschil: ${pnl_s - total_tm_pnl:+.0f}")
        print(f"    Exits: ", end="")
        for k, v in exits_s.items():
            if v > 0:
                print(f"{k}={v}  ", end="")
        print()

    print(f"\n{'=' * 100}")
    print("ANALYSE COMPLEET")
    print(f"{'=' * 100}")


if __name__ == '__main__':
    run_analysis()
