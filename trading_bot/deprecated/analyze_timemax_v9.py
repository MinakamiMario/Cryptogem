#!/usr/bin/env python3
"""
V9 TimeMax Optimale Analyse
============================
Vindt alle 185 DualConfirm entries en analyseert voor diverse TimeMax waarden:
- Hoeveel raken TP7% / SL15% / TimeMax exit
- Gemiddelde P&L van TimeMax exits
- EV per trade
- Wat gebeurt er met TM-exits als ze langer mogen lopen

Gebruik: python analyze_timemax_v9.py
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026
POS_SIZE = 2000
TP_PCT = 7.0
SL_PCT = 15.0

# V4 DualConfirm entry parameters
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
RSI_MAX = 40
VOL_SPIKE_MULT = 2.0
VOL_CONFIRM_MULT = 1.0
MIN_BARS_NEEDED = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, 14) + 5

# TimeMax waarden om te testen
TM_VALUES = [4, 6, 8, 10, 12, 15, 20, 30, 50]

# Voor de "langer laten lopen" analyse
EXTENDED_BARS = [20, 30, 50, 100]


def load_cache():
    print(f"Loading cache: {CACHE_FILE}")
    with open(CACHE_FILE) as f:
        raw = json.load(f)
    # Filter metadata keys (beginnen met _)
    data = {k: v for k, v in raw.items() if isinstance(v, list)}
    print(f"  {len(data)} coins geladen")
    # Controleer structuur
    sample_key = list(data.keys())[0]
    sample = data[sample_key]
    n = len(sample)
    print(f"  Sample: {sample_key} heeft {n} candles")
    if n > 0:
        c = sample[0]
        print(f"  Keys: {list(c.keys())}")
    return data


def find_entries(data):
    """Vind alle DualConfirm + VolSpike + VolConfirm entries."""
    entries = []

    for pair, candles in data.items():
        if len(candles) < MIN_BARS_NEEDED:
            continue

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        for bar in range(MIN_BARS_NEEDED, len(candles)):
            # Indicators op window tot en met bar
            window_closes = closes[:bar + 1]
            window_highs = highs[:bar + 1]
            window_lows = lows[:bar + 1]
            window_volumes = volumes[:bar + 1]

            rsi = calc_rsi(window_closes, RSI_PERIOD)

            # Donchian op vorige bars (excl huidige)
            _, prev_lowest, _ = calc_donchian(window_highs[:-1], window_lows[:-1], DC_PERIOD)

            # Bollinger
            _, _, bb_lower = calc_bollinger(window_closes, BB_PERIOD, BB_DEV)

            if prev_lowest is None or bb_lower is None:
                continue

            current = candles[bar]
            prev = candles[bar - 1]

            close = current['close']
            low = current['low']
            prev_close = prev['close']

            # DualConfirm check
            dc_ok = (low <= prev_lowest and rsi < RSI_MAX and close > prev_close)
            bb_ok = (close <= bb_lower and rsi < RSI_MAX and close > prev_close)

            if not (dc_ok and bb_ok):
                continue

            # Volume spike check (>2x avg20)
            vol_window = window_volumes[-20:]
            if len(vol_window) < 2:
                continue
            vol_avg = sum(vol_window) / len(vol_window)
            if vol_avg <= 0:
                continue
            cur_vol = window_volumes[-1]
            if cur_vol < vol_avg * VOL_SPIKE_MULT:
                continue

            # Volume confirm (current vol > prev vol)
            prev_vol = window_volumes[-2]
            if prev_vol <= 0:
                continue
            if cur_vol / prev_vol < VOL_CONFIRM_MULT:
                continue

            # Base volume filter (>50% avg)
            if cur_vol < vol_avg * 0.5:
                continue

            # ENTRY FOUND
            entry_price = close
            # Bewaar alle bars na entry voor simulatie
            remaining = candles[bar + 1:]

            entries.append({
                'pair': pair,
                'bar': bar,
                'entry_price': entry_price,
                'rsi': rsi,
                'vol_ratio': cur_vol / vol_avg,
                'remaining': remaining,  # alle candles na entry
            })

    return entries


def simulate_trade(entry, max_bars):
    """
    Simuleer een trade met TP7%, SL15%, TimeMax.
    Retourneert: (exit_type, pnl_pct, bars_held, exit_price)
    exit_type: 'TP', 'SL', 'TM', 'OPEN' (als max_bars niet bereikt en geen exit)
    """
    ep = entry['entry_price']
    tp_price = ep * (1 + TP_PCT / 100)
    sl_price = ep * (1 - SL_PCT / 100)
    remaining = entry['remaining']

    for i, candle in enumerate(remaining):
        bar_num = i + 1  # 1-indexed (bar 1 = eerste bar na entry)

        # Check SL first (intrabar: low)
        if candle['low'] <= sl_price:
            pnl_pct = -SL_PCT
            return 'SL', pnl_pct, bar_num, sl_price

        # Check TP (intrabar: high)
        if candle['high'] >= tp_price:
            pnl_pct = TP_PCT
            return 'TP', pnl_pct, bar_num, tp_price

        # Check TimeMax (op close)
        if bar_num >= max_bars:
            pnl_pct = (candle['close'] - ep) / ep * 100
            return 'TM', pnl_pct, bar_num, candle['close']

    # Nooit exit bereikt (data op)
    if remaining:
        last = remaining[-1]
        pnl_pct = (last['close'] - ep) / ep * 100
        return 'OPEN', pnl_pct, len(remaining), last['close']
    return 'OPEN', 0.0, 0, ep


def simulate_no_timemax(entry, max_bars_look):
    """
    Simuleer een trade met ALLEEN TP7% en SL15%, tot max_bars_look bars.
    Voor analyse van wat TM-exits zouden doen als ze langer mochten lopen.
    """
    ep = entry['entry_price']
    tp_price = ep * (1 + TP_PCT / 100)
    sl_price = ep * (1 - SL_PCT / 100)
    remaining = entry['remaining']

    for i, candle in enumerate(remaining):
        bar_num = i + 1
        if bar_num > max_bars_look:
            break

        if candle['low'] <= sl_price:
            return 'SL', -SL_PCT, bar_num

        if candle['high'] >= tp_price:
            return 'TP', TP_PCT, bar_num

    # Nog open na max_bars_look
    if remaining and max_bars_look <= len(remaining):
        last = remaining[min(max_bars_look - 1, len(remaining) - 1)]
        pnl_pct = (last['close'] - ep) / ep * 100
        return 'OPEN', pnl_pct, min(max_bars_look, len(remaining))
    elif remaining:
        last = remaining[-1]
        pnl_pct = (last['close'] - ep) / ep * 100
        return 'OPEN', pnl_pct, len(remaining)
    return 'OPEN', 0.0, 0


def calc_net_pnl(pnl_pct, pos_size=POS_SIZE):
    """Bereken netto P&L in $ inclusief dubbele Kraken fee."""
    gross = pnl_pct / 100 * pos_size
    fee_entry = pos_size * KRAKEN_FEE
    fee_exit = (pos_size + gross) * KRAKEN_FEE
    return gross - fee_entry - fee_exit


def main():
    data = load_cache()
    print("\n=== STAP 1: Entries zoeken (DualConfirm + VolSpike + VolConfirm) ===")
    entries = find_entries(data)
    print(f"  Gevonden: {len(entries)} entries")

    # Toon top coins
    pair_counts = {}
    for e in entries:
        pair_counts[e['pair']] = pair_counts.get(e['pair'], 0) + 1
    top_pairs = sorted(pair_counts.items(), key=lambda x: -x[1])[:10]
    print(f"  Top coins: {', '.join(f'{p}({n})' for p,n in top_pairs)}")

    # ================================================================
    # STAP 2: TimeMax sweep
    # ================================================================
    print("\n" + "=" * 100)
    print("=== STAP 2: TimeMax Sweep — TP7% / SL15% / TM exit ===")
    print("=" * 100)

    header = (f"{'TM':>4} | {'Trades':>6} | {'TP':>4} {'%':>5} | {'SL':>4} {'%':>5} | "
              f"{'TM':>4} {'%':>5} | {'TM avg%':>7} | {'TM avg$':>7} | "
              f"{'Tot P&L':>8} | {'EV/t $':>7} | {'WR%':>5} | {'PF':>6}")
    print(header)
    print("-" * 100)

    results = {}

    for tm in TM_VALUES:
        tp_count = 0
        sl_count = 0
        tm_count = 0
        open_count = 0
        total_net = 0.0
        tm_pnls = []
        tp_pnls = []
        sl_pnls = []

        trade_details = []

        for entry in entries:
            exit_type, pnl_pct, bars, exit_price = simulate_trade(entry, tm)
            net = calc_net_pnl(pnl_pct)

            trade_details.append({
                'pair': entry['pair'],
                'exit_type': exit_type,
                'pnl_pct': pnl_pct,
                'net': net,
                'bars': bars,
                'entry': entry,
            })

            if exit_type == 'TP':
                tp_count += 1
                tp_pnls.append(net)
            elif exit_type == 'SL':
                sl_count += 1
                sl_pnls.append(net)
            elif exit_type == 'TM':
                tm_count += 1
                tm_pnls.append(net)
            else:
                open_count += 1

            total_net += net

        total_trades = tp_count + sl_count + tm_count
        if total_trades == 0:
            continue

        tp_pct = tp_count / total_trades * 100
        sl_pct_r = sl_count / total_trades * 100
        tm_pct = tm_count / total_trades * 100
        tm_avg_pct = sum(d['pnl_pct'] for d in trade_details if d['exit_type'] == 'TM') / tm_count if tm_count > 0 else 0
        tm_avg_net = sum(tm_pnls) / tm_count if tm_count > 0 else 0
        ev_per_trade = total_net / total_trades
        wins = tp_count + len([p for p in tm_pnls if p > 0])
        wr = wins / total_trades * 100
        gross_wins = sum(p for p in tp_pnls + tm_pnls + sl_pnls if p > 0)
        gross_losses = abs(sum(p for p in tp_pnls + tm_pnls + sl_pnls if p < 0))
        pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')

        results[tm] = {
            'total': total_trades,
            'tp': tp_count, 'sl': sl_count, 'tm': tm_count,
            'open': open_count,
            'total_net': total_net, 'ev': ev_per_trade,
            'wr': wr, 'pf': pf,
            'tm_avg_pct': tm_avg_pct, 'tm_avg_net': tm_avg_net,
            'trades': trade_details,
        }

        pf_str = f"{pf:.1f}" if pf < 1000 else "INF"
        print(f"{tm:>4} | {total_trades:>6} | {tp_count:>4} {tp_pct:>4.0f}% | "
              f"{sl_count:>4} {sl_pct_r:>4.0f}% | {tm_count:>4} {tm_pct:>4.0f}% | "
              f"{tm_avg_pct:>+6.1f}% | {tm_avg_net:>+7.0f} | "
              f"{total_net:>+8.0f} | {ev_per_trade:>+7.1f} | "
              f"{wr:>4.0f}% | {pf_str:>6}")

    # Open count voor langste TM
    if TM_VALUES:
        longest = max(TM_VALUES)
        r = results.get(longest, {})
        if r.get('open', 0) > 0:
            print(f"\n  (Bij TM{longest}: {r['open']} trades nog OPEN = data op voordat exit bereikt)")

    # ================================================================
    # STAP 3: Breakdown per exit type voor key TM values
    # ================================================================
    print("\n" + "=" * 100)
    print("=== STAP 3: Gedetailleerde P&L per exit type ===")
    print("=" * 100)

    for tm in [8, 10, 12, 15, 20]:
        if tm not in results:
            continue
        r = results[tm]
        trades = r['trades']

        tp_trades = [t for t in trades if t['exit_type'] == 'TP']
        sl_trades = [t for t in trades if t['exit_type'] == 'SL']
        tm_trades = [t for t in trades if t['exit_type'] == 'TM']

        print(f"\n--- TM={tm} ({r['total']} trades, EV=${r['ev']:+.1f}/trade) ---")

        if tp_trades:
            avg_bars = sum(t['bars'] for t in tp_trades) / len(tp_trades)
            avg_net = sum(t['net'] for t in tp_trades) / len(tp_trades)
            print(f"  TP7%:     {len(tp_trades):>3} trades, avg ${avg_net:+.0f}/trade, avg {avg_bars:.1f} bars")

        if sl_trades:
            avg_bars = sum(t['bars'] for t in sl_trades) / len(sl_trades)
            avg_net = sum(t['net'] for t in sl_trades) / len(sl_trades)
            print(f"  SL15%:    {len(sl_trades):>3} trades, avg ${avg_net:+.0f}/trade, avg {avg_bars:.1f} bars")

        if tm_trades:
            avg_bars = sum(t['bars'] for t in tm_trades) / len(tm_trades)
            avg_net = sum(t['net'] for t in tm_trades) / len(tm_trades)
            pos = len([t for t in tm_trades if t['net'] > 0])
            neg = len([t for t in tm_trades if t['net'] <= 0])
            print(f"  TimeMax:  {len(tm_trades):>3} trades, avg ${avg_net:+.0f}/trade, avg {avg_bars:.1f} bars "
                  f"({pos} wins, {neg} losses)")

            # Distributie van TM exits
            pnl_pcts = sorted([t['pnl_pct'] for t in tm_trades])
            print(f"    TM P&L distributie: min={min(pnl_pcts):+.1f}%, "
                  f"25%={pnl_pcts[len(pnl_pcts)//4]:+.1f}%, "
                  f"med={pnl_pcts[len(pnl_pcts)//2]:+.1f}%, "
                  f"75%={pnl_pcts[3*len(pnl_pcts)//4]:+.1f}%, "
                  f"max={max(pnl_pcts):+.1f}%")

        print(f"  TOTAAL:   P&L ${r['total_net']:+.0f}, WR {r['wr']:.0f}%")

    # ================================================================
    # STAP 4: Wat gebeurt met TM exits als ze LANGER lopen?
    # ================================================================
    print("\n" + "=" * 100)
    print("=== STAP 4: TM-exits bij TM8 — wat als ze langer mochten lopen? ===")
    print("=" * 100)

    # Gebruik TM8 als baseline
    if 8 not in results:
        print("  FOUT: TM8 niet gevonden in resultaten")
        return

    tm8_trades = [t for t in results[8]['trades'] if t['exit_type'] == 'TM']
    print(f"\n  {len(tm8_trades)} trades zijn TM-exit bij TM8")
    print(f"  (gemiddeld P&L op moment van TM-exit: {results[8]['tm_avg_pct']:+.1f}%)\n")

    header2 = (f"{'ExtBars':>7} | {'→TP7%':>6} | {'→SL15%':>7} | {'StillOpen':>9} | "
               f"{'TP wins$':>8} | {'SL loss$':>8} | {'Open avg%':>9} | {'Net vs TM8':>10}")
    print(header2)
    print("-" * 90)

    # Baseline: wat was hun P&L bij TM8?
    tm8_baseline_net = sum(t['net'] for t in tm8_trades)

    for ext in EXTENDED_BARS:
        tp_later = 0
        sl_later = 0
        still_open = 0
        tp_net = 0.0
        sl_net = 0.0
        open_pnls = []

        for t in tm8_trades:
            entry = t['entry']
            # Simuleer ZONDER TimeMax, tot ext bars
            exit_type, pnl_pct, bars = simulate_no_timemax(entry, ext)

            if exit_type == 'TP':
                tp_later += 1
                tp_net += calc_net_pnl(pnl_pct)
            elif exit_type == 'SL':
                sl_later += 1
                sl_net += calc_net_pnl(pnl_pct)
            else:
                still_open += 1
                open_pnls.append(pnl_pct)

        open_avg = sum(open_pnls) / len(open_pnls) if open_pnls else 0
        # Net resultaat als we deze trades ext bars hadden laten lopen
        # ipv TM8 exit
        alt_net = tp_net + sl_net + sum(calc_net_pnl(p) for p in open_pnls)
        diff = alt_net - tm8_baseline_net

        print(f"{ext:>7} | {tp_later:>6} | {sl_later:>7} | {still_open:>9} | "
              f"{tp_net:>+8.0f} | {sl_net:>+8.0f} | {open_avg:>+8.1f}% | "
              f"{diff:>+10.0f}")

    # ================================================================
    # STAP 5: Per-trade detail van TM8 exits
    # ================================================================
    print("\n" + "=" * 100)
    print("=== STAP 5: Individuele TM8-exits — per trade detail ===")
    print("=" * 100)

    print(f"\n{'Pair':<16} | {'EntryPx':>10} | {'TM8 P&L%':>8} | {'TM8 $':>7} | "
          f"{'→20bar':>8} | {'→50bar':>8} | {'→100bar':>8}")
    print("-" * 90)

    for t in sorted(tm8_trades, key=lambda x: x['net']):
        entry = t['entry']
        pair_short = t['pair'][:15]

        # Wat gebeurt bij 20, 50, 100 bars?
        outcomes = {}
        for ext in [20, 50, 100]:
            exit_type, pnl_pct, bars = simulate_no_timemax(entry, ext)
            outcomes[ext] = f"{exit_type}{pnl_pct:+.1f}%"

        print(f"{pair_short:<16} | {entry['entry_price']:>10.4f} | {t['pnl_pct']:>+7.1f}% | "
              f"{t['net']:>+7.0f} | {outcomes[20]:>8} | {outcomes[50]:>8} | {outcomes[100]:>8}")

    # ================================================================
    # STAP 6: Optimum samenvatting
    # ================================================================
    print("\n" + "=" * 100)
    print("=== STAP 6: OPTIMUM SAMENVATTING ===")
    print("=" * 100)

    best_ev = max(results.items(), key=lambda x: x[1]['ev'])
    best_pnl = max(results.items(), key=lambda x: x[1]['total_net'])
    best_wr = max(results.items(), key=lambda x: x[1]['wr'])

    print(f"\n  Beste EV/trade:  TM{best_ev[0]} → ${best_ev[1]['ev']:+.1f}/trade "
          f"({best_ev[1]['total']} trades, P&L ${best_ev[1]['total_net']:+.0f})")
    print(f"  Beste Total P&L: TM{best_pnl[0]} → ${best_pnl[1]['total_net']:+.0f} "
          f"({best_pnl[1]['total']} trades, EV ${best_pnl[1]['ev']:+.1f})")
    print(f"  Beste WR:        TM{best_wr[0]} → {best_wr[1]['wr']:.0f}% "
          f"({best_wr[1]['total']} trades)")

    # Marginal analysis: EV verschil tussen opeenvolgende TM waarden
    print(f"\n  --- Marginale analyse ---")
    print(f"  {'TM':>4} → {'TM+':>4} | {'ΔTrades':>8} | {'ΔEV/t':>8} | {'ΔP&L':>8} | {'Extra TM→TP':>11}")
    print(f"  " + "-" * 60)

    sorted_tms = sorted(results.keys())
    for i in range(len(sorted_tms) - 1):
        tm1 = sorted_tms[i]
        tm2 = sorted_tms[i + 1]
        r1 = results[tm1]
        r2 = results[tm2]
        d_trades = r2['total'] - r1['total']
        d_ev = r2['ev'] - r1['ev']
        d_pnl = r2['total_net'] - r1['total_net']
        # Hoeveel meer TP trades?
        d_tp = r2['tp'] - r1['tp']
        print(f"  {tm1:>4} → {tm2:>4} | {d_trades:>+8} | {d_ev:>+8.1f} | {d_pnl:>+8.0f} | {d_tp:>+11}")

    # Zonder ZEUS/toptrader analyse
    print("\n  --- Zonder top-1 coin (outlier check) ---")
    # Vind de coin met hoogste P&L
    for tm in [8, 10, 12, 15, 20]:
        if tm not in results:
            continue
        r = results[tm]
        pair_pnl = {}
        for t in r['trades']:
            pair_pnl[t['pair']] = pair_pnl.get(t['pair'], 0) + t['net']
        if not pair_pnl:
            continue
        top_coin = max(pair_pnl.items(), key=lambda x: x[1])
        total_ex = r['total_net'] - top_coin[1]
        trades_ex = r['total'] - len([t for t in r['trades'] if t['pair'] == top_coin[0]])
        ev_ex = total_ex / trades_ex if trades_ex > 0 else 0
        print(f"  TM{tm:>2}: Total ${r['total_net']:+.0f} → zonder {top_coin[0]}({top_coin[1]:+.0f}) = "
              f"${total_ex:+.0f}, EV ${ev_ex:+.1f}/trade ({trades_ex} trades)")

    print("\n=== ANALYSE COMPLEET ===")


if __name__ == '__main__':
    main()
