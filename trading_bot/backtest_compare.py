"""
Portfolio Vergelijking: 3×$600 vs 6×$300
========================================
Simuleert BEIDE scenario's chronologisch over alle coins tegelijk.
Meet het effect van max_positions op gemiste signalen en totale winst.
Gebruikt gecachte candle data uit backtest_results als beschikbaar.
"""
import krakenex
import time
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Strategy parameters (identiek aan live bot)
DONCHIAN_PERIOD = 20
RSI_PERIOD = 14
RSI_MAX = 35
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
COOLDOWN_BARS = 4
MAX_STOP_LOSS_PCT = 15.0

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / period

def calc_donchian(highs, lows, period=20):
    if len(highs) < period:
        return None, None, None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    mid = (hh + ll) / 2
    return hh, ll, mid


def extract_all_signals(all_candles):
    """
    Extract alle entry en exit signalen per coin, chronologisch.
    Returns lijst van events: {time, pair, type, price, stop, ...}
    """
    all_events = []

    for pair, candles in all_candles.items():
        if len(candles) < max(DONCHIAN_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5:
            continue

        last_exit_bar = -999
        position = None

        for i in range(max(DONCHIAN_PERIOD, RSI_PERIOD, ATR_PERIOD) + 2, len(candles)):
            window = candles[:i+1]
            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]

            rsi = calc_rsi(closes, RSI_PERIOD)
            atr = calc_atr(highs, lows, closes, ATR_PERIOD)

            prev_highs = highs[:-1]
            prev_lows = lows[:-1]
            _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, DONCHIAN_PERIOD)
            _, _, mid_channel = calc_donchian(highs, lows, DONCHIAN_PERIOD)

            current = window[-1]
            prev_candle = window[-2]

            if position is None:
                in_cooldown = (i - last_exit_bar) < COOLDOWN_BARS
                if in_cooldown or prev_lowest is None:
                    continue

                price_at_lower = current['low'] <= prev_lowest
                rsi_oversold = rsi < RSI_MAX
                price_bouncing = current['close'] > prev_candle['close']

                if price_at_lower and rsi_oversold and price_bouncing:
                    stop = current['close'] - atr * ATR_STOP_MULT
                    max_stop = current['close'] * (1 - MAX_STOP_LOSS_PCT / 100)
                    if stop < max_stop:
                        stop = max_stop

                    all_events.append({
                        'time': current['time'],
                        'pair': pair,
                        'type': 'ENTRY',
                        'price': current['close'],
                        'stop': stop,
                        'target': mid_channel,
                        'rsi': rsi,
                        'atr': atr,
                        'bar_idx': i,
                    })
                    # Track position voor exit detectie
                    position = {
                        'entry_price': current['close'],
                        'stop_price': stop,
                        'highest_price': current['close'],
                        'entry_bar': i,
                    }
            else:
                if current['close'] > position['highest_price']:
                    position['highest_price'] = current['close']
                new_stop = position['highest_price'] - atr * ATR_STOP_MULT
                max_stop = position['entry_price'] * (1 - MAX_STOP_LOSS_PCT / 100)
                if new_stop < max_stop:
                    new_stop = max_stop
                if new_stop > position['stop_price']:
                    position['stop_price'] = new_stop

                exit_type = None
                hard_stop = position['entry_price'] * (1 - MAX_STOP_LOSS_PCT / 100)
                if current['close'] < hard_stop:
                    exit_type = 'STOP'
                elif mid_channel and current['close'] >= mid_channel:
                    exit_type = 'TARGET'
                elif current['close'] < position['stop_price']:
                    exit_type = 'STOP'

                if exit_type:
                    pnl_pct = (current['close'] - position['entry_price']) / position['entry_price'] * 100
                    all_events.append({
                        'time': current['time'],
                        'pair': pair,
                        'type': 'EXIT',
                        'exit_type': exit_type,
                        'price': current['close'],
                        'entry_price': position['entry_price'],
                        'pnl_pct': pnl_pct,
                        'bar_idx': i,
                    })
                    last_exit_bar = i
                    position = None

        # Sluit open positie aan einde
        if position:
            last = candles[-1]
            pnl_pct = (last['close'] - position['entry_price']) / position['entry_price'] * 100
            all_events.append({
                'time': last['time'],
                'pair': pair,
                'type': 'EXIT',
                'exit_type': 'OPEN',
                'price': last['close'],
                'entry_price': position['entry_price'],
                'pnl_pct': pnl_pct,
                'bar_idx': len(candles) - 1,
            })

    # Sorteer chronologisch
    all_events.sort(key=lambda x: (x['time'], x['type'] == 'ENTRY'))
    return all_events


def simulate_portfolio(events, capital_per_trade, max_positions):
    """
    Simuleer portfolio met max posities limiet.
    Returns dict met resultaten.
    """
    positions = {}  # pair -> {entry_price, volume, ...}
    trades = []
    skipped = []
    total_capital = capital_per_trade * max_positions  # Totaal beschikbaar

    for event in events:
        if event['type'] == 'ENTRY':
            if len(positions) >= max_positions:
                skipped.append(event)
                continue
            if event['pair'] in positions:
                # Al een positie in deze coin
                continue

            volume = capital_per_trade / event['price']
            positions[event['pair']] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
            }

        elif event['type'] == 'EXIT':
            if event['pair'] not in positions:
                continue

            pos = positions[event['pair']]
            pnl_usd = pos['volume'] * (event['price'] - pos['entry_price'])
            pnl_pct = (event['price'] - pos['entry_price']) / pos['entry_price'] * 100

            trades.append({
                'pair': event['pair'],
                'entry_price': pos['entry_price'],
                'exit_price': event['price'],
                'pnl_usd': pnl_usd,
                'pnl_pct': pnl_pct,
                'exit_type': event.get('exit_type', '?'),
            })
            del positions[event['pair']]

    if not trades:
        return {
            'capital_per_trade': capital_per_trade,
            'max_positions': max_positions,
            'total_capital': total_capital,
            'trades': 0,
            'skipped': len(skipped),
            'total_pnl_usd': 0,
            'win_rate': 0,
            'avg_pnl_pct': 0,
            'avg_pnl_usd': 0,
            'max_loss_usd': 0,
            'max_win_usd': 0,
            'profit_factor': 0,
            'max_drawdown_usd': 0,
            'roi': 0,
        }

    wins = [t for t in trades if t['pnl_usd'] > 0]
    losses = [t for t in trades if t['pnl_usd'] <= 0]
    total_pnl = sum(t['pnl_usd'] for t in trades)

    gross_profit = sum(t['pnl_usd'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_usd'] for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999

    # Max drawdown (equity curve)
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl_usd']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Worst single trade
    worst = min(t['pnl_usd'] for t in trades)
    best = max(t['pnl_usd'] for t in trades)

    return {
        'capital_per_trade': capital_per_trade,
        'max_positions': max_positions,
        'total_capital': total_capital,
        'trades': len(trades),
        'skipped': len(skipped),
        'total_pnl_usd': round(total_pnl, 2),
        'win_rate': round(len(wins) / len(trades) * 100, 1),
        'avg_pnl_pct': round(sum(t['pnl_pct'] for t in trades) / len(trades), 2),
        'avg_pnl_usd': round(total_pnl / len(trades), 2),
        'max_loss_usd': round(worst, 2),
        'max_win_usd': round(best, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor < 999 else 999,
        'max_drawdown_usd': round(max_dd, 2),
        'roi': round(total_pnl / total_capital * 100, 2),
        'trades_list': trades,
        'skipped_list': skipped,
    }


# ===== MAIN =====
PAIR_MAP = {
    'ZG/USD': '0GUSD', 'XRP/USD': 'XXRPZUSD', 'XLM/USD': 'XXLMZUSD',
    'ETC/USD': 'XETCZUSD', 'LTC/USD': 'XLTCZUSD', 'BTC/USD': 'XXBTZUSD',
    'ETH/USD': 'XETHZUSD',
}

coins = os.getenv('COINS', '').split(',')
api = krakenex.API()
since = int((datetime.now() - timedelta(days=60)).timestamp())

# Cache file voor candle data (zodat we niet 2x hoeven te fetchen)
CACHE_FILE = '/Users/oussama/Cryptogem/trading_bot/candle_cache.json'

# Check of we cached data hebben (max 4 uur oud)
use_cache = False
if os.path.exists(CACHE_FILE):
    cache_age = time.time() - os.path.getmtime(CACHE_FILE)
    if cache_age < 14400:  # 4 uur
        use_cache = True

all_candles = {}
errors = []

if use_cache:
    print("📦 Laden van gecachte candle data...")
    with open(CACHE_FILE, 'r') as f:
        all_candles = json.load(f)
    print(f"   {len(all_candles)} coins geladen uit cache")
else:
    print(f"📡 Ophalen van candle data voor {len(coins)} coins...")
    for idx, pair in enumerate(coins):
        pair = pair.strip()
        if not pair:
            continue

        kraken_pair = PAIR_MAP.get(pair, pair.replace('/', ''))
        time.sleep(0.8)

        try:
            result = api.query_public('OHLC', {'pair': kraken_pair, 'interval': 240, 'since': since})
            if result.get('error') and len(result['error']) > 0:
                errors.append(f"{pair}: {result['error']}")
                continue

            data = result.get('result', {})
            candles = []
            for key, vals in data.items():
                if key != 'last':
                    for c in vals:
                        candles.append({
                            'time': int(c[0]),
                            'open': float(c[1]),
                            'high': float(c[2]),
                            'low': float(c[3]),
                            'close': float(c[4]),
                            'vwap': float(c[5]),
                            'volume': float(c[6]),
                            'count': int(c[7]),
                        })
                    break

            if len(candles) >= 30:
                all_candles[pair] = candles

            if (idx + 1) % 25 == 0:
                print(f"  [{idx+1}/{len(coins)}] Verwerkt...")

        except Exception as e:
            errors.append(f"{pair}: {str(e)}")

    # Cache opslaan
    with open(CACHE_FILE, 'w') as f:
        json.dump(all_candles, f)
    print(f"   {len(all_candles)} coins opgehaald, {len(errors)} errors")

print(f"\n{'=' * 80}")
print(f"SIGNALEN EXTRACTIE")
print(f"{'=' * 80}")

events = extract_all_signals(all_candles)
entry_events = [e for e in events if e['type'] == 'ENTRY']
exit_events = [e for e in events if e['type'] == 'EXIT']
print(f"Totaal events:     {len(events)}")
print(f"Entry signalen:    {len(entry_events)}")
print(f"Exit signalen:     {len(exit_events)}")

# ===== SIMULATIE =====
print(f"\n{'=' * 80}")
print(f"PORTFOLIO SIMULATIE")
print(f"{'=' * 80}")

scenarios = [
    (600, 3, "3 × $600"),
    (300, 6, "6 × $300"),
    (400, 5, "5 × $400"),  # Bonus: tussenoptie
]

results = {}
for capital, max_pos, label in scenarios:
    r = simulate_portfolio(events, capital, max_pos)
    results[label] = r

# ===== OUTPUT =====
print(f"\n{'=' * 80}")
print(f"{'VERGELIJKING':^80}")
print(f"{'=' * 80}")
print(f"{'Metric':<30} {'3 × $600':>16} {'6 × $300':>16} {'5 × $400':>16}")
print(f"{'-' * 80}")

r1 = results["3 × $600"]
r2 = results["6 × $300"]
r3 = results["5 × $400"]

metrics = [
    ("Totaal kapitaal", f"${r1['total_capital']}", f"${r2['total_capital']}", f"${r3['total_capital']}"),
    ("Kapitaal per trade", f"${r1['capital_per_trade']}", f"${r2['capital_per_trade']}", f"${r3['capital_per_trade']}"),
    ("Max posities", f"{r1['max_positions']}", f"{r2['max_positions']}", f"{r3['max_positions']}"),
    ("", "", "", ""),
    ("Trades uitgevoerd", f"{r1['trades']}", f"{r2['trades']}", f"{r3['trades']}"),
    ("Signalen GEMIST", f"{r1['skipped']} ❌", f"{r2['skipped']} {'✅' if r2['skipped'] < r1['skipped'] else '⚠️'}", f"{r3['skipped']}"),
    ("Win rate", f"{r1['win_rate']}%", f"{r2['win_rate']}%", f"{r3['win_rate']}%"),
    ("", "", "", ""),
    ("Totaal P&L", f"${r1['total_pnl_usd']:.2f}", f"${r2['total_pnl_usd']:.2f}", f"${r3['total_pnl_usd']:.2f}"),
    ("ROI", f"{r1['roi']}%", f"{r2['roi']}%", f"{r3['roi']}%"),
    ("Gem. P&L/trade (%)", f"{r1['avg_pnl_pct']}%", f"{r2['avg_pnl_pct']}%", f"{r3['avg_pnl_pct']}%"),
    ("Gem. P&L/trade ($)", f"${r1['avg_pnl_usd']}", f"${r2['avg_pnl_usd']}", f"${r3['avg_pnl_usd']}"),
    ("", "", "", ""),
    ("Worst trade ($)", f"${r1['max_loss_usd']}", f"${r2['max_loss_usd']}", f"${r3['max_loss_usd']}"),
    ("Best trade ($)", f"${r1['max_win_usd']}", f"${r2['max_win_usd']}", f"${r3['max_win_usd']}"),
    ("Profit Factor", f"{r1['profit_factor']}", f"{r2['profit_factor']}", f"{r3['profit_factor']}"),
    ("Max Drawdown ($)", f"${r1['max_drawdown_usd']}", f"${r2['max_drawdown_usd']}", f"${r3['max_drawdown_usd']}"),
]

for label, v1, v2, v3 in metrics:
    if label == "":
        print(f"{'-' * 80}")
    else:
        print(f"{label:<30} {v1:>16} {v2:>16} {v3:>16}")

# Analyse
print(f"\n{'=' * 80}")
print(f"ANALYSE")
print(f"{'=' * 80}")

extra_trades = r2['trades'] - r1['trades']
extra_pnl = r2['total_pnl_usd'] - r1['total_pnl_usd']
fewer_skipped = r1['skipped'] - r2['skipped']

print(f"\n6×$300 vs 3×$600:")
print(f"  → {extra_trades:+d} extra trades uitgevoerd")
print(f"  → {fewer_skipped} minder signalen gemist")
print(f"  → ${extra_pnl:+.2f} verschil in P&L")
print(f"  → Max verlies per trade: ${r1['capital_per_trade'] * MAX_STOP_LOSS_PCT / 100:.0f} vs ${r2['capital_per_trade'] * MAX_STOP_LOSS_PCT / 100:.0f}")

# Risico analyse
print(f"\n📊 Risico vergelijking:")
print(f"  3×$600: max ${3 * 600 * MAX_STOP_LOSS_PCT / 100:.0f} verlies als ALLE posities stoppen (=${3 * MAX_STOP_LOSS_PCT:.0f}% van kapitaal)")
print(f"  6×$300: max ${6 * 300 * MAX_STOP_LOSS_PCT / 100:.0f} verlies als ALLE posities stoppen (=${6 * MAX_STOP_LOSS_PCT:.0f}% van kapitaal)")
print(f"  → Zelfde worst case (${max(3,6) * 300 * MAX_STOP_LOSS_PCT / 100:.0f}), maar 6×$300 verdeelt risico over meer coins")

# Aanbeveling
print(f"\n{'=' * 80}")
print(f"AANBEVELING")
print(f"{'=' * 80}")

if r2['total_pnl_usd'] > r1['total_pnl_usd'] and r2['skipped'] < r1['skipped']:
    print(f"✅ 6 × $300 is BETER:")
    print(f"   • Meer trades = meer kansen gepakt")
    print(f"   • Minder signalen gemist ({r2['skipped']} vs {r1['skipped']})")
    print(f"   • ${r2['total_pnl_usd'] - r1['total_pnl_usd']:.2f} meer winst")
    print(f"   • Beter gediversifieerd (6 coins i.p.v. 3)")
    print(f"   • Kleiner verlies per trade (max ${300 * MAX_STOP_LOSS_PCT / 100:.0f} vs ${600 * MAX_STOP_LOSS_PCT / 100:.0f})")
elif r1['total_pnl_usd'] > r2['total_pnl_usd']:
    print(f"✅ 3 × $600 is BETER:")
    print(f"   • Hogere absolute winst")
    print(f"   • Grotere winst per trade")
else:
    print(f"⚖️ Beide scenario's zijn vergelijkbaar")
    print(f"   6×$300 is veiliger (diversificatie), 3×$600 simpeler")

# Bewaar resultaten
summary = {
    'scenarios': {label: {k: v for k, v in r.items() if k not in ('trades_list', 'skipped_list')}
                  for label, r in results.items()},
    'recommendation': '6x300' if r2['total_pnl_usd'] > r1['total_pnl_usd'] else '3x600',
    'timestamp': datetime.now().isoformat(),
}
with open('/Users/oussama/Cryptogem/trading_bot/compare_results.json', 'w') as f:
    json.dump(summary, f, indent=2)
print(f"\nResultaten opgeslagen in compare_results.json")
