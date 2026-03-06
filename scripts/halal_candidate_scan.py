#!/usr/bin/env python3
"""Scan ms_018 backtest universe for profitable halal candidates not yet whitelisted.

Filters: PnL > 0, trades >= 4, daily_volume > $3K.
Categorizes by likely halal/haram status based on symbol name.
"""
import sys
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
sys.path.insert(0, '/Users/oussama/Cryptogem')

from _ms018_helper import load_data, bt_coin, coin_symbol, load_halal

# ---------------------------------------------------------------------------
# Classification lists
# ---------------------------------------------------------------------------

DEFI_LENDING = {
    'AAVE', 'COMP', 'MKR', 'DAI', 'SUSHI', 'UNI', 'CAKE', 'SNX', 'YFI',
    'CRV', 'BAL', 'LQTY', 'RPL', 'MORPHO', 'PENDLE', 'JUP', 'RAY', 'ORCA',
    'OSMO',
}

MEME_GAMBLING = {
    'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'MEME', 'TURBO',
    'MYRO', 'BRETT', 'NEIRO', 'PNUT', 'ACT', 'GOAT', 'POPCAT', 'MOG',
    'COQ', 'BOME', 'TRUMP', 'MELANIA',
}

PRIVACY = {'XMR', 'ZEC', 'DASH', 'SCRT'}

KNOWN_HARAM = DEFI_LENDING | MEME_GAMBLING | PRIVACY

LIKELY_HALAL_SYMBOLS = {
    # Layer 1/2
    'BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'AVAX', 'ATOM', 'ALGO', 'NEAR',
    'APT', 'SUI', 'SEI', 'INJ', 'TIA', 'TON', 'FTM', 'SONIC', 'KAVA',
    'EGLD', 'HBAR', 'NEO', 'QTUM', 'ZIL', 'ONE', 'ROSE', 'CELO', 'MINA',
    'KAS', 'XRP', 'XLM', 'IOTA', 'ICX', 'WAVES', 'EOS', 'TRX', 'FLOW',
    'ICP', 'MATIC', 'POL', 'OP', 'ARB', 'STRK', 'METIS', 'MANTA',
    'ZK', 'BOBA', 'SKL', 'CTSI', 'LRC', 'IMX', 'CELR', 'ZRO',
    # Storage / Compute / AI
    'FIL', 'AR', 'RENDER', 'RNDR', 'AKT', 'TAO', 'AIOZ', 'THETA', 'TFUEL',
    'SC', 'STORJ', 'NKN', 'OCEAN', 'FET', 'AGIX', 'WLD', 'PRIME', 'ARKM',
    'GRASS', 'IO', 'VIRTUAL', 'GPU', 'PHB', 'GLM',
    # Gaming / Metaverse
    'AXS', 'SAND', 'MANA', 'GALA', 'ENJ', 'ILV', 'RONIN', 'RON',
    'PIXEL', 'PORTAL', 'BEAM', 'YGG', 'SUPER', 'ALICE', 'GODS',
    'WEMIX', 'PYR', 'MAGIC', 'GMT', 'STEPN',
    # DePIN / Real World
    'HNT', 'IOTX', 'DIMO', 'MOBILE', 'ONDO', 'RWA', 'LINK', 'API3',
    'PYTH', 'BAND', 'TRB', 'DIA',
    # Enterprise / Supply chain / Identity
    'VET', 'QNT', 'XDC', 'CSPR', 'ENS', 'GRT', 'ANKR', 'SSV',
    'LIT', 'NMR', 'EDU', 'ACE', 'MASK', 'ID',
    # Cross-chain / Interop
    'WORM', 'AXL', 'ZRO', 'STX', 'RUNE',
}


def classify(sym: str) -> str:
    if sym in KNOWN_HARAM:
        if sym in DEFI_LENDING:
            return 'KNOWN HARAM (DeFi lending/interest)'
        elif sym in MEME_GAMBLING:
            return 'KNOWN HARAM (meme/gambling)'
        else:
            return 'KNOWN HARAM (privacy)'
    if sym in LIKELY_HALAL_SYMBOLS:
        return 'LIKELY HALAL'
    return 'NEEDS REVIEW'


def avg_daily_volume_usd(candles: list[dict]) -> float:
    """Estimate avg daily USD volume from 4H candles (6 candles/day)."""
    if not candles:
        return 0.0
    total_vol_usd = 0.0
    for c in candles:
        mid = (c['high'] + c['low']) / 2
        total_vol_usd += c['volume'] * mid
    n_days = len(candles) / 6.0  # 4H candles → 6 per day
    return total_vol_usd / n_days if n_days > 0 else 0.0


def main():
    print('Loading data...')
    data, coins = load_data()
    halal_set = load_halal()
    print(f'Dataset: {len(coins)} coins with >=360 bars')
    print(f'Current halal whitelist: {len(halal_set)} symbols')
    print()

    # Run backtests and collect candidates
    candidates = []
    skipped_halal = 0
    skipped_filter = 0

    for i, coin in enumerate(coins):
        sym = coin_symbol(coin)
        if i % 50 == 0:
            print(f'  Scanning {i+1}/{len(coins)}...', flush=True)

        # Skip already-whitelisted
        if sym in halal_set:
            skipped_halal += 1
            continue

        res = bt_coin(data, coin)
        vol = avg_daily_volume_usd(data[coin])

        if res.pnl <= 0 or res.trades < 4 or vol < 3000:
            skipped_filter += 1
            continue

        category = classify(sym)
        candidates.append({
            'coin': coin,
            'sym': sym,
            'pnl': res.pnl,
            'pf': res.pf,
            'trades': res.trades,
            'wr': res.wr,
            'dd': res.dd,
            'vol': vol,
            'category': category,
        })

    # Sort by PnL descending
    candidates.sort(key=lambda x: x['pnl'], reverse=True)

    # Group by category
    groups = {}
    for c in candidates:
        cat = c['category']
        groups.setdefault(cat, []).append(c)

    # Print results
    print('=' * 90)
    print(f'HALAL CANDIDATE SCAN — ms_018 (shift_pb) on {len(coins)} coins')
    print(f'Filters: PnL > 0, trades >= 4, daily_volume > $3K')
    print(f'Excluded: {skipped_halal} already whitelisted, {skipped_filter} filtered out')
    print(f'Candidates found: {len(candidates)}')
    print('=' * 90)

    # Print order: LIKELY HALAL first, NEEDS REVIEW, then KNOWN HARAM
    order = ['LIKELY HALAL', 'NEEDS REVIEW',
             'KNOWN HARAM (DeFi lending/interest)',
             'KNOWN HARAM (meme/gambling)',
             'KNOWN HARAM (privacy)']

    for cat in order:
        items = groups.get(cat, [])
        if not items:
            continue
        print(f'\n{"─" * 90}')
        print(f'  {cat} ({len(items)} coins)')
        print(f'{"─" * 90}')
        print(f'  {"Symbol":<12} {"PnL":>10} {"PF":>6} {"WR%":>6} {"Trades":>7} {"DD%":>7} {"Vol/day":>12}')
        print(f'  {"─"*12} {"─"*10} {"─"*6} {"─"*6} {"─"*7} {"─"*7} {"─"*12}')
        for c in items:
            print(f'  {c["sym"]:<12} ${c["pnl"]:>9,.0f} {c["pf"]:>5.2f} {c["wr"]:>5.1f} {c["trades"]:>7} {c["dd"]:>6.1f}% ${c["vol"]:>10,.0f}')

    # Summary
    print(f'\n{"=" * 90}')
    print('SUMMARY')
    print(f'{"=" * 90}')
    total_halal = len(groups.get('LIKELY HALAL', []))
    total_review = len(groups.get('NEEDS REVIEW', []))
    total_haram = sum(len(groups.get(k, [])) for k in order if 'HARAM' in k)
    print(f'  LIKELY HALAL:   {total_halal:>4} coins')
    print(f'  NEEDS REVIEW:   {total_review:>4} coins')
    print(f'  KNOWN HARAM:    {total_haram:>4} coins')
    print(f'  TOTAL:          {len(candidates):>4} coins')

    if total_halal > 0:
        halal_pnl = sum(c['pnl'] for c in groups.get('LIKELY HALAL', []))
        print(f'\n  LIKELY HALAL total PnL: ${halal_pnl:,.0f}')
    if total_review > 0:
        review_pnl = sum(c['pnl'] for c in groups.get('NEEDS REVIEW', []))
        print(f'  NEEDS REVIEW total PnL: ${review_pnl:,.0f}')


if __name__ == '__main__':
    main()
