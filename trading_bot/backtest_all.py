"""
Backtest alle halal coins over afgelopen 2 maanden met BearDonchianBounce strategie.
Gebruikt live Kraken data (4H candles).
"""
import krakenex
import time
import json
from datetime import datetime, timedelta

# Strategy parameters (zelfde als live bot)
DONCHIAN_PERIOD = 20
RSI_PERIOD = 14
RSI_MAX = 35
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
COOLDOWN_BARS = 4
MAX_STOP_LOSS_PCT = 15.0  # Max 15% verlies per trade
CAPITAL_PER_TRADE = 600

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
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
    recent_trs = trs[-period:]
    return sum(recent_trs) / len(recent_trs)

def calc_donchian(highs, lows, period=20):
    if len(highs) < period:
        return None, None, None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    mid = (hh + ll) / 2
    return hh, ll, mid

def backtest_coin(candles, pair):
    """Run backtest on candle data. Returns dict with results."""
    if len(candles) < max(DONCHIAN_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5:
        return None
    
    trades = []
    position = None
    last_exit_bar = -999
    
    # Buy & hold tracking
    first_close = candles[0]['close']
    last_close = candles[-1]['close']
    buy_hold_return = (last_close - first_close) / first_close * 100
    
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
        prev = window[-2]
        
        if position is None:
            # Check entry
            in_cooldown = (i - last_exit_bar) < COOLDOWN_BARS
            if in_cooldown:
                continue
            
            if prev_lowest is None:
                continue
                
            price_at_lower = current['low'] <= prev_lowest
            rsi_oversold = rsi < RSI_MAX
            price_bouncing = current['close'] > prev['close']
            
            if price_at_lower and rsi_oversold and price_bouncing:
                stop = current['close'] - atr * ATR_STOP_MULT
                # Max stop loss cap: nooit meer dan MAX_STOP_LOSS_PCT% onder entry
                max_stop = current['close'] * (1 - MAX_STOP_LOSS_PCT / 100)
                if stop < max_stop:
                    stop = max_stop
                volume = CAPITAL_PER_TRADE / current['close']
                position = {
                    'entry_price': current['close'],
                    'volume': volume,
                    'stop_price': stop,
                    'highest_price': current['close'],
                    'entry_bar': i,
                    'entry_time': current['time'],
                }
        else:
            # Check exit
            if current['close'] > position['highest_price']:
                position['highest_price'] = current['close']
            new_stop = position['highest_price'] - atr * ATR_STOP_MULT
            # Max stop loss cap
            max_stop = position['entry_price'] * (1 - MAX_STOP_LOSS_PCT / 100)
            if new_stop < max_stop:
                new_stop = max_stop
            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            exit_type = None
            # Hard max loss cap check eerst
            hard_stop = position['entry_price'] * (1 - MAX_STOP_LOSS_PCT / 100)
            if current['close'] < hard_stop:
                exit_type = 'STOP'
            elif mid_channel and current['close'] >= mid_channel:
                exit_type = 'TARGET'
            elif current['close'] < position['stop_price']:
                exit_type = 'STOP'
            
            if exit_type:
                pnl_pct = (current['close'] - position['entry_price']) / position['entry_price'] * 100
                pnl_usd = position['volume'] * (current['close'] - position['entry_price'])
                trades.append({
                    'entry_price': position['entry_price'],
                    'exit_price': current['close'],
                    'pnl_pct': pnl_pct,
                    'pnl_usd': pnl_usd,
                    'type': exit_type,
                    'bars_held': i - position['entry_bar'],
                })
                last_exit_bar = i
                position = None
    
    # Close any open position at end
    if position:
        pnl_pct = (candles[-1]['close'] - position['entry_price']) / position['entry_price'] * 100
        pnl_usd = position['volume'] * (candles[-1]['close'] - position['entry_price'])
        trades.append({
            'entry_price': position['entry_price'],
            'exit_price': candles[-1]['close'],
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'type': 'OPEN',
            'bars_held': len(candles) - position['entry_bar'],
        })
    
    if not trades:
        return {
            'pair': pair,
            'trades': 0,
            'total_return': 0,
            'total_pnl_usd': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'max_dd': 0,
            'buy_hold': buy_hold_return,
            'alpha': -buy_hold_return,
            'profit_factor': 0,
        }
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses_t = [t for t in trades if t['pnl_pct'] <= 0]
    total_pnl = sum(t['pnl_pct'] for t in trades)
    total_pnl_usd = sum(t['pnl_usd'] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    gross_profit = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
    gross_loss = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Max drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl_pct']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    
    alpha = total_pnl - buy_hold_return
    
    return {
        'pair': pair,
        'trades': len(trades),
        'total_return': round(total_pnl, 2),
        'total_pnl_usd': round(total_pnl_usd, 2),
        'win_rate': round(win_rate, 1),
        'avg_pnl': round(total_pnl / len(trades), 2),
        'max_dd': round(max_dd, 2),
        'buy_hold': round(buy_hold_return, 2),
        'alpha': round(alpha, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999,
    }


# ===== MAIN =====
api = krakenex.API()

# Load coins from .env
import os
from dotenv import load_dotenv
load_dotenv()
coins = os.getenv('COINS', '').split(',')

# Pair map
PAIR_MAP = {
    'ZG/USD': '0GUSD', 'XRP/USD': 'XXRPZUSD', 'XLM/USD': 'XXLMZUSD',
    'ETC/USD': 'XETCZUSD', 'LTC/USD': 'XLTCZUSD', 'BTC/USD': 'XXBTZUSD',
    'ETH/USD': 'XETHZUSD',
}

# 2 months ago
since = int((datetime.now() - timedelta(days=60)).timestamp())

results = []
errors = []
total = len(coins)

print(f"Backtesting {total} coins over afgelopen 2 maanden (4H Donchian Bounce)")
print(f"Capital per trade: ${CAPITAL_PER_TRADE}")
print(f"Max stop loss: {MAX_STOP_LOSS_PCT}% (=${CAPITAL_PER_TRADE * MAX_STOP_LOSS_PCT / 100:.0f} per trade)")
print("=" * 80)

for idx, pair in enumerate(coins):
    pair = pair.strip()
    if not pair:
        continue
    
    kraken_pair = PAIR_MAP.get(pair, pair.replace('/', ''))
    
    # Rate limiting
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
        
        if len(candles) < 30:
            errors.append(f"{pair}: te weinig data ({len(candles)} candles)")
            continue
        
        bt = backtest_coin(candles, pair)
        if bt:
            results.append(bt)
            status = "✅" if bt['alpha'] > 0 else "⚠️" if bt['trades'] > 0 else "⏳"
            if (idx + 1) % 25 == 0:
                print(f"  [{idx+1}/{total}] Verwerkt...")
    
    except Exception as e:
        errors.append(f"{pair}: {str(e)}")

print(f"\n{'=' * 80}")
print(f"RESULTATEN: {len(results)} coins gebacktest")
print(f"Errors: {len(errors)}")
if errors:
    for e in errors[:10]:
        print(f"  ❌ {e}")

# Sort by alpha
results.sort(key=lambda x: x['alpha'], reverse=True)

# Summary stats
with_trades = [r for r in results if r['trades'] > 0]
positive_alpha = [r for r in results if r['alpha'] > 0 and r['trades'] > 0]
negative_alpha = [r for r in results if r['alpha'] < 0 and r['trades'] > 0]

print(f"\n{'=' * 80}")
print(f"SAMENVATTING")
print(f"{'=' * 80}")
print(f"Totaal coins:          {len(results)}")
print(f"Coins met trades:      {len(with_trades)}")
print(f"Coins zonder trades:   {len(results) - len(with_trades)}")
print(f"Positieve alpha:       {len(positive_alpha)}")
print(f"Negatieve alpha:       {len(negative_alpha)}")

if with_trades:
    total_pnl = sum(r['total_pnl_usd'] for r in with_trades)
    total_trades = sum(r['trades'] for r in with_trades)
    avg_wr = sum(r['win_rate'] for r in with_trades) / len(with_trades)
    print(f"\nTotaal trades:         {total_trades}")
    print(f"Totaal P&L:            ${total_pnl:.2f}")
    print(f"Gem. win rate:         {avg_wr:.1f}%")

print(f"\n{'=' * 80}")
print(f"TOP 30 COINS (gesorteerd op alpha)")
print(f"{'=' * 80}")
print(f"{'Pair':<18} {'Trades':>6} {'Return':>8} {'P&L($)':>8} {'WR%':>6} {'PF':>6} {'DD%':>6} {'B&H%':>8} {'Alpha%':>8}")
print("-" * 80)

for r in results[:30]:
    if r['trades'] > 0:
        pf_str = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "∞"
        print(f"{r['pair']:<18} {r['trades']:>6} {r['total_return']:>7.1f}% {r['total_pnl_usd']:>8.2f} {r['win_rate']:>5.1f}% {pf_str:>6} {r['max_dd']:>5.1f}% {r['buy_hold']:>7.1f}% {r['alpha']:>7.1f}%")

print(f"\n{'=' * 80}")
print(f"BOTTOM 10 (slechtste alpha)")
print(f"{'=' * 80}")
for r in results[-10:]:
    if r['trades'] > 0:
        pf_str = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "∞"
        print(f"{r['pair']:<18} {r['trades']:>6} {r['total_return']:>7.1f}% {r['total_pnl_usd']:>8.2f} {r['win_rate']:>5.1f}% {pf_str:>6} {r['max_dd']:>5.1f}% {r['buy_hold']:>7.1f}% {r['alpha']:>7.1f}%")

# Overall portfolio simulation
if with_trades:
    print(f"\n{'=' * 80}")
    print(f"PORTFOLIO SIMULATIE (als alle coins tegelijk getraded)")
    print(f"{'=' * 80}")
    total_invested = sum(r['trades'] for r in with_trades) * CAPITAL_PER_TRADE
    total_profit = sum(r['total_pnl_usd'] for r in with_trades)
    roi = total_profit / total_invested * 100 if total_invested > 0 else 0
    print(f"Totaal geïnvesteerd:   ${total_invested:.0f} ({sum(r['trades'] for r in with_trades)} trades × ${CAPITAL_PER_TRADE})")
    print(f"Totaal winst/verlies:  ${total_profit:.2f}")
    print(f"ROI:                   {roi:.2f}%")
    print(f"Gem. winst per trade:  ${total_profit/sum(r['trades'] for r in with_trades):.2f}")

# Save results
with open('/Users/oussama/Cryptogem/trading_bot/backtest_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResultaten opgeslagen in backtest_results.json")
