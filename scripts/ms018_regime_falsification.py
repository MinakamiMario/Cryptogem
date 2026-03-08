#!/usr/bin/env python3
"""MS-018 FINAL Falsification Test — Regime-Filtered Blind Portfolio.

Pre-registered: dit is de LAATSTE test voor MS-018.
- PF > 1.0 onder bear-regime → conditioneel edge, heropenen discussie
- PF < 1.0 onder bear-regime → definitief dood, geen verdere tests

Regime definitie: BTC close < 200-bar SMA (= bear/sideways)
We testen ook RSI<50 als alternatief regime-filter.
"""
import json, sys, time, importlib
import statistics

sys.path.insert(0, '/Users/oussama/Cryptogem')

from strategies.ms.hypotheses import signal_structure_shift_pullback
from strategies.ms.indicators import precompute_ms_indicators

engine = importlib.import_module('strategies.4h.sprint3.engine')
run_backtest = engine.run_backtest

MEXC_FEE = 0.001
DATASET = '/Users/oussama/CryptogemData/derived/candle_cache/mexc/4h/candle_cache_4h_mexc_v2.json'

DEFAULT_PARAMS = {
    'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
    'max_stop_pct': 15.0, 'time_max_bars': 15,
    'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
}

print("Loading MEXC 4H dataset...", flush=True)
t0 = time.time()
with open(DATASET) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items()
        if not k.startswith('_') and isinstance(v, list) and len(v) >= 360}
print(f"  Loaded {len(data)} coins in {time.time()-t0:.1f}s", flush=True)

# ─── BTC regime berekenen ───────────────────────────────────
# Find BTC proxy — dataset uses USD suffix, may have WBTC instead of BTC
btc_key = None
for candidate in ['BTC/USD', 'BTC/USDT', 'WBTC/USD', 'WBTC/USDT']:
    if candidate in data:
        btc_key = candidate
        break
# Fallback: any key containing BTC
if not btc_key:
    for k in data:
        if 'BTC' in k.upper():
            btc_key = k
            break

if not btc_key:
    print("ERROR: Geen BTC proxy gevonden in dataset")
    sys.exit(1)

btc_bars = data[btc_key]
print(f"  BTC key: {btc_key}, {len(btc_bars)} bars", flush=True)

# Bereken BTC SMA-200 en RSI-14 per bar index
def calc_sma(bars, period):
    """Returns dict: bar_index → SMA value (None als niet genoeg data)."""
    closes = [b[4] if isinstance(b, list) else b['close'] for b in bars]
    sma = {}
    for i in range(len(closes)):
        if i < period - 1:
            sma[i] = None
        else:
            sma[i] = sum(closes[i-period+1:i+1]) / period
    return sma, closes

def calc_rsi(bars, period=14):
    """Returns dict: bar_index → RSI value."""
    closes = [b[4] if isinstance(b, list) else b['close'] for b in bars]
    rsi = {}
    if len(closes) < period + 1:
        return rsi

    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i-1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period, len(closes)):
        if i > period:
            delta = closes[i] - closes[i-1]
            avg_gain = (avg_gain * (period - 1) + max(delta, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-delta, 0)) / period

        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))

    return rsi

print("  Computing BTC regime indicators...", flush=True)
btc_sma200, btc_closes = calc_sma(btc_bars, 200)
btc_rsi14 = calc_rsi(btc_bars, 14)

# Regime classificatie per bar
# We gebruiken timestamps om regimes te matchen met andere coins
def get_bar_ts(bar):
    """Extract timestamp from bar (list or dict format)."""
    if isinstance(bar, list):
        return bar[0]
    return bar.get('time', bar.get('timestamp', bar.get('ts', 0)))

btc_regime_by_ts = {}  # ts → {'sma_bear': bool, 'rsi_bear': bool}
for i, bar in enumerate(btc_bars):
    ts = get_bar_ts(bar)
    sma_val = btc_sma200.get(i)
    rsi_val = btc_rsi14.get(i)
    close = btc_closes[i]

    btc_regime_by_ts[ts] = {
        'sma_bear': close < sma_val if sma_val is not None else None,
        'rsi_bear': rsi_val < 50 if rsi_val is not None else None,
    }

# Stats
total_bars_with_sma = sum(1 for v in btc_regime_by_ts.values() if v['sma_bear'] is not None)
bear_bars_sma = sum(1 for v in btc_regime_by_ts.values() if v['sma_bear'] is True)
bear_bars_rsi = sum(1 for v in btc_regime_by_ts.values() if v['rsi_bear'] is True)

print(f"\n  BTC Regime Stats:")
print(f"    Total bars met SMA200: {total_bars_with_sma}")
print(f"    Bear (close < SMA200): {bear_bars_sma} ({100*bear_bars_sma/max(total_bars_with_sma,1):.0f}%)")
print(f"    Bear (RSI14 < 50):     {bear_bars_rsi} ({100*bear_bars_rsi/max(len(btc_regime_by_ts),1):.0f}%)")
print(flush=True)


# ─── Regime-filtered dataset bouwen ────────────────────────
def filter_bars_by_regime(coin_data, regime_key):
    """Filter bars: keep only bars where BTC regime matches.

    Returns new dict with filtered bar lists per coin.
    Bars worden NIET verwijderd maar gemarkeerd — de engine
    moet alle bars zien voor indicator berekening.
    We bouwen een set van 'allowed' timestamps.
    """
    allowed_ts = set()
    for ts, regime in btc_regime_by_ts.items():
        if regime.get(regime_key) is True:
            allowed_ts.add(ts)
    return allowed_ts


def bt_with_regime(coins, regime_key, label):
    """Backtest all coins, maar alleen trades openen op regime-bars.

    Aangezien de engine geen regime-filter heeft, doen we per-coin
    backtest en filteren we trades achteraf op entry timestamp.
    """
    print(f"\n{'='*70}")
    print(f"REGIME TEST: {label}")
    print(f"{'='*70}", flush=True)

    allowed_ts = filter_bars_by_regime(data, regime_key)
    print(f"  Allowed bars: {len(allowed_ts)}", flush=True)

    # Per-coin backtest, filter trades by regime
    total_trades = 0
    regime_trades = 0
    gross_profit = 0.0
    gross_loss = 0.0
    total_pnl = 0.0
    coins_profitable = 0
    coins_losing = 0
    coins_active = 0
    per_coin_pnl = []

    all_coins = list(coins.keys())

    for idx, coin in enumerate(all_coins):
        single = {coin: coins[coin]}
        try:
            indicators = precompute_ms_indicators(single, [coin])
            res = run_backtest(single, [coin], signal_structure_shift_pullback,
                              DEFAULT_PARAMS, indicators, fee=MEXC_FEE,
                              initial_capital=10000, max_pos=1)
        except Exception:
            continue

        if not hasattr(res, 'trade_list') or not res.trade_list:
            continue

        # Filter trades: alleen die waarvan entry_bar timestamp in regime zit
        coin_pnl = 0.0
        coin_trades = 0
        for trade in res.trade_list:
            total_trades += 1
            # trade is typically a dict or namedtuple
            entry_bar_idx = None
            if isinstance(trade, dict):
                entry_bar_idx = trade.get('entry_bar', trade.get('entry_idx'))
            elif hasattr(trade, 'entry_bar'):
                entry_bar_idx = trade.entry_bar
            elif hasattr(trade, 'entry_idx'):
                entry_bar_idx = trade.entry_idx

            # Get timestamp of entry bar
            if entry_bar_idx is not None and entry_bar_idx < len(coins[coin]):
                entry_ts = get_bar_ts(coins[coin][entry_bar_idx])
            else:
                continue

            if entry_ts not in allowed_ts:
                continue

            # Trade is in regime
            regime_trades += 1
            coin_trades += 1

            if isinstance(trade, dict):
                pnl = trade.get('pnl', 0)
            else:
                pnl = getattr(trade, 'pnl', 0)

            coin_pnl += pnl
            if pnl > 0:
                gross_profit += pnl
            else:
                gross_loss += abs(pnl)

        if coin_trades >= 1:
            coins_active += 1
            total_pnl += coin_pnl
            per_coin_pnl.append(coin_pnl)
            if coin_pnl > 0:
                coins_profitable += 1
            else:
                coins_losing += 1

        if (idx + 1) % 50 == 0:
            print(f"    ... {idx+1}/{len(all_coins)} coins", flush=True)

    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    print(f"\n  Results:")
    print(f"    Total trades (all regimes): {total_trades}")
    print(f"    Regime trades:              {regime_trades} ({100*regime_trades/max(total_trades,1):.0f}%)")
    print(f"    Coins active:               {coins_active}")
    print(f"    Coins profitable:           {coins_profitable} ({100*coins_profitable/max(coins_active,1):.0f}%)")
    print(f"    Coins losing:               {coins_losing} ({100*coins_losing/max(coins_active,1):.0f}%)")
    print(f"    Gross profit:               ${gross_profit:+,.0f}")
    print(f"    Gross loss:                 ${gross_loss:+,.0f}")
    print(f"    Net PnL:                    ${total_pnl:+,.0f}")
    print(f"    PF:                         {pf:.2f}")

    if per_coin_pnl:
        per_coin_pnl.sort()
        print(f"\n  Per-coin PnL distribution (regime trades only):")
        print(f"    Min:    ${per_coin_pnl[0]:+,.0f}")
        print(f"    Median: ${per_coin_pnl[len(per_coin_pnl)//2]:+,.0f}")
        print(f"    Mean:   ${statistics.mean(per_coin_pnl):+,.0f}")
        print(f"    Max:    ${per_coin_pnl[-1]:+,.0f}")

    print(flush=True)
    return pf, regime_trades, coins_profitable, coins_active, total_pnl


# ─── Run tests ──────────────────────────────────────────────

# Test A: BTC < SMA200 (classic bear regime)
pf_sma, trades_sma, win_sma, active_sma, pnl_sma = bt_with_regime(
    data, 'sma_bear', 'BTC < SMA200 (bear/sideways)')

# Test B: BTC RSI14 < 50 (momentum bear)
pf_rsi, trades_rsi, win_rsi, active_rsi, pnl_rsi = bt_with_regime(
    data, 'rsi_bear', 'BTC RSI14 < 50 (momentum bear)')

# ─── Reference: ongefiltered (from Test 1) ──────────────────
print(f"\n{'='*70}")
print("REFERENCE: Unfiltered (Test 1 result)")
print(f"{'='*70}")
print(f"  PF: 0.78, PnL: -$10,000, Trades: 128")

# ─── FINAL VERDICT ──────────────────────────────────────────
print(f"\n{'='*70}")
print("FINAL VERDICT — MS-018 REGIME FALSIFICATION")
print(f"{'='*70}")

print(f"\n  {'Test':<35} {'PF':>6} {'Trades':>8} {'PnL':>12} {'Verdict':>10}")
print(f"  {'-'*35} {'-'*6} {'-'*8} {'-'*12} {'-'*10}")
print(f"  {'Unfiltered (baseline)':<35} {'0.78':>6} {'128':>8} {'$-10,000':>12} {'FAIL':>10}")
print(f"  {'BTC < SMA200 (bear)':<35} {pf_sma:>6.2f} {trades_sma:>8} {f'${pnl_sma:+,.0f}':>12} {'PASS' if pf_sma > 1.0 else 'FAIL':>10}")
print(f"  {'BTC RSI14 < 50':<35} {pf_rsi:>6.2f} {trades_rsi:>8} {f'${pnl_rsi:+,.0f}':>12} {'PASS' if pf_rsi > 1.0 else 'FAIL':>10}")

if pf_sma > 1.0 or pf_rsi > 1.0:
    print(f"\n  🟡 CONDITIONEEL EDGE GEVONDEN — regime-filter maakt verschil")
    print(f"     Heropenen discussie: ms_018 + regime-detectie als conditionele strategie")
else:
    print(f"\n  🔴 DEFINITIEF DOOD — ook onder bear-regime geen edge")
    print(f"     MS-018 is hiermee afgesloten. Geen verdere tests.")

print(f"\n  Totale runtime: {time.time()-t0:.0f}s")
print(flush=True)
