"""
Extended indicator enrichment for Sprint 5 hypothesis screening.

Adds microstructure-level indicators (opens, vwap, count, body_pct, atr_ratio)
to the base indicator dict WITHOUT modifying harness.py or indicators.py.
"""


def extend_indicators(data: dict, coins: list, indicators: dict) -> None:
    """
    Enrich base indicators in-place with microstructure fields.

    Args:
        data: candle_cache format {coin: [candle_dicts]}
        coins: list of coin symbols
        indicators: dict from precompute_base_indicators() -- modified in-place
    """
    for coin in coins:
        if coin not in indicators or coin not in data:
            continue

        ind = indicators[coin]
        candles = data[coin]
        n = ind['n']

        # Opens
        opens = [c.get('open', 0.0) for c in candles[:n]]
        ind['opens'] = opens

        # VWAPs -- may not exist in all exchange data
        vwaps = [c.get('vwap') for c in candles[:n]]
        ind['vwaps'] = vwaps

        # Counts -- may not exist in all exchange data
        counts = [c.get('count') for c in candles[:n]]
        ind['counts'] = counts

        # Feature availability flags
        vwap_valid = sum(1 for v in vwaps if v is not None)
        count_valid = sum(1 for v in counts if v is not None)
        ind['has_vwap'] = vwap_valid >= n * 0.5
        ind['has_count'] = count_valid >= n * 0.5

        # body_pct: abs(close - open) / ATR * 100
        closes = ind['closes']
        atr = ind.get('atr', [None] * n)
        body_pct = [None] * n
        for bar in range(n):
            if atr[bar] is not None and atr[bar] > 0:
                body_pct[bar] = abs(closes[bar] - opens[bar]) / atr[bar] * 100
            elif atr[bar] is not None:
                body_pct[bar] = 0.0
        ind['body_pct'] = body_pct

        # atr_ratio: ATR / SMA(ATR, 50)
        atr_ratio = [None] * n
        # Collect non-None ATR values progressively
        for bar in range(n):
            if atr[bar] is None:
                continue
            # Collect last 50 non-None ATR values up to this bar
            atr_window = []
            for j in range(max(0, bar - 49), bar + 1):
                if atr[j] is not None:
                    atr_window.append(atr[j])
            if len(atr_window) >= 10:  # need at least 10 values
                mean_atr = sum(atr_window) / len(atr_window)
                atr_ratio[bar] = atr[bar] / mean_atr if mean_atr > 0 else 1.0
            else:
                atr_ratio[bar] = 1.0  # neutral when insufficient history
        ind['atr_ratio'] = atr_ratio


def get_feature_coverage(indicators: dict, coins: list) -> dict:
    """
    Report VWAP and count field availability across coins.

    Returns dict with coverage statistics.
    """
    vwap_avail = 0
    count_avail = 0
    total = 0

    for coin in coins:
        if coin not in indicators:
            continue
        total += 1
        if indicators[coin].get('has_vwap', False):
            vwap_avail += 1
        if indicators[coin].get('has_count', False):
            count_avail += 1

    return {
        'vwap_available': vwap_avail,
        'vwap_missing': total - vwap_avail,
        'vwap_pct': vwap_avail / total * 100 if total > 0 else 0.0,
        'count_available': count_avail,
        'count_missing': total - count_avail,
        'count_pct': count_avail / total * 100 if total > 0 else 0.0,
        'total_coins': total,
    }
