"""Shared helper for ms_018 overfitting analysis scripts."""
import json, sys, importlib
sys.path.insert(0, '/Users/oussama/Cryptogem')

from strategies.ms.hypotheses import signal_structure_shift_pullback
from strategies.ms.indicators import precompute_ms_indicators

engine = importlib.import_module('strategies.4h.sprint3.engine')
run_backtest = engine.run_backtest
data_resolver = importlib.import_module('strategies.4h.data_resolver')

PARAMS = {
    'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
    'max_stop_pct': 15.0, 'time_max_bars': 15,
    'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
}

MEXC_FEE = 0.001  # 10 bps


def load_data():
    """Load dataset, return (data_dict, coins_list)."""
    dataset_path = data_resolver.resolve_dataset('4h_default')
    with open(dataset_path) as f:
        raw = json.load(f)
    data = {k: v for k, v in raw.items() if not k.startswith('_') and isinstance(v, list)}
    coins = [c for c in data if len(data[c]) >= 360]
    return data, coins


def bt_coin(data, coin, start=None, end=None, max_pos=1):
    """Run ms_018 backtest on single coin, optionally sliced."""
    bars = data[coin]
    if start is not None or end is not None:
        bars = bars[start:end]
    single = {coin: bars}
    indicators = precompute_ms_indicators(single, [coin])
    res = run_backtest(single, [coin], signal_structure_shift_pullback, PARAMS, indicators,
                       fee=MEXC_FEE, initial_capital=10000, max_pos=max_pos)
    return res


def coin_symbol(coin):
    """Extract symbol from pair name (e.g. 'ETH/USD' -> 'ETH')."""
    return coin.split('/')[0]


def load_halal():
    """Load current halal whitelist symbols."""
    symbols = set()
    with open('/Users/oussama/Cryptogem/trading_bot/halal_coins.txt') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                symbols.add(line.replace('/USDT', ''))
    return symbols
