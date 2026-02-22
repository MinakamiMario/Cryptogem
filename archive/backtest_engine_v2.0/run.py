#!/usr/bin/env python3
"""
Cryptogem Backtest Engine v2.0 - CLI Runner
=============================================
Usage:
    python run.py backtest                    # Backtest all strategies on BTC 1H
    python run.py backtest --coin ETH         # Backtest on ETH
    python run.py backtest --timeframe 1d     # Backtest on 1D
    python run.py backtest --strategy v55     # Backtest single strategy

    python run.py paper                       # Paper trade all strategies (1 year)
    python run.py paper --days 30             # Paper trade last 30 days
    python run.py paper --capital 500         # Start with EUR 500
    python run.py paper --strategy v69        # Paper trade single strategy

    python run.py compare                     # Compare 1H vs 1D strategies
    python run.py fetch                       # Fetch/update data for all coins
    python run.py fetch --coin SOL            # Fetch data for SOL only
    python run.py list                        # List available data files
"""
import argparse
import sys
from datetime import datetime, timedelta

from engine.backtest import run_backtest, run_paper_trade
from engine.data_loader import fetch_and_save, list_available_data, TICKERS
from engine.report import print_results, print_paper_trades, print_comparison
from strategies import VWAPTrend1H, VWAPChaikin1H, KeltnerOptimizedStops, KeltnerMicroBreakout


# Strategy registry
STRATEGIES_1H = {
    'v55': ('V55: VWAP Trend (Best Return)', VWAPTrend1H),
    'v69': ('V69: VWAP+Chaikin (Best Risk)', VWAPChaikin1H),
}

STRATEGIES_1D = {
    'v13': ('V13: Keltner Optimized', KeltnerOptimizedStops),
    'v21': ('V21: Keltner Micro-Breakout', KeltnerMicroBreakout),
}


def cmd_backtest(args):
    """Run backtests."""
    coin = args.coin.upper()
    tf = args.timeframe

    if tf == '1h':
        strats = STRATEGIES_1H
    else:
        strats = STRATEGIES_1D

    if args.strategy:
        key = args.strategy.lower()
        if key not in strats:
            print(f"  Onbekende strategie: {key}")
            print(f"  Beschikbaar ({tf}): {', '.join(strats.keys())}")
            return
        strats = {key: strats[key]}

    print(f"\n{'='*80}")
    print(f"  BACKTEST: {coin} {tf.upper()}")
    print(f"  Startkapitaal: $10,000 | Commissie: 0.1%")
    print(f"{'='*80}")

    results = []
    for key, (name, cls) in strats.items():
        print(f"  >>> {name}...")
        r = run_backtest(cls, coin=coin, timeframe=tf)
        results.append(r)

    print_results(results, title=f"RESULTATEN {coin} {tf.upper()}")


def cmd_paper(args):
    """Run paper trade simulations."""
    coin = args.coin.upper()
    capital = args.capital
    days = args.days

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # Select strategies based on timeframe
    all_strats = {}
    all_strats.update({k: (v[0], v[1], '1h') for k, v in STRATEGIES_1H.items()})
    all_strats.update({k: (v[0], v[1], '1d') for k, v in STRATEGIES_1D.items()})

    if args.strategy:
        key = args.strategy.lower()
        if key not in all_strats:
            print(f"  Onbekende strategie: {key}")
            print(f"  Beschikbaar: {', '.join(all_strats.keys())}")
            return
        strats_to_run = {key: all_strats[key]}
    else:
        strats_to_run = all_strats

    print(f"\n{'='*80}")
    print(f"  PAPER TRADE SIMULATIE: {coin}")
    print(f"  Periode: {start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')} ({days} dagen)")
    print(f"  Startkapitaal: EUR {capital:,.2f}")
    print(f"{'='*80}")

    paper_results = []
    for key, (name, cls, tf) in strats_to_run.items():
        print(f"  >>> {name} ({tf})...")
        r = run_paper_trade(cls, coin=coin, timeframe=tf,
                            start_date=start_date, end_date=end_date,
                            paper_cash=capital)
        paper_results.append(r)
        print_paper_trades(r, title=name)

    if len(paper_results) > 1:
        print_comparison(paper_results, paper_cash=capital)


def cmd_compare(args):
    """Compare 1H vs 1D strategies."""
    coin = args.coin.upper()
    capital = args.capital
    days = args.days

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    print(f"\n{'='*80}")
    print(f"  VERGELIJKING 1H vs 1D: {coin}")
    print(f"  Periode: {start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}")
    print(f"  Startkapitaal: EUR {capital:,.2f}")
    print(f"{'='*80}")

    paper_results = []

    for key, (name, cls) in STRATEGIES_1H.items():
        print(f"  >>> {name} (1H)...")
        r = run_paper_trade(cls, coin=coin, timeframe='1h',
                            start_date=start_date, end_date=end_date,
                            paper_cash=capital)
        paper_results.append(r)

    for key, (name, cls) in STRATEGIES_1D.items():
        print(f"  >>> {name} (1D)...")
        r = run_paper_trade(cls, coin=coin, timeframe='1d',
                            start_date=start_date, end_date=end_date,
                            paper_cash=capital)
        paper_results.append(r)

    for r in paper_results:
        print_paper_trades(r)

    print_comparison(paper_results, paper_cash=capital)


def cmd_fetch(args):
    """Fetch/update market data."""
    coins = [args.coin.upper()] if args.coin else list(TICKERS.keys())
    timeframes = [args.timeframe] if args.timeframe else ['1h', '1d']

    print(f"\n{'='*60}")
    print(f"  DATA FETCHER")
    print(f"{'='*60}")

    for coin in coins:
        for tf in timeframes:
            period = '730d' if tf == '1h' else 'max'
            try:
                fetch_and_save(coin, tf, period)
            except Exception as e:
                print(f"  FOUT: {coin} {tf}: {e}")

    print(f"\n  Klaar!\n")


def cmd_list(args):
    """List available data files."""
    files = list_available_data()

    print(f"\n{'='*60}")
    print(f"  BESCHIKBARE DATA")
    print(f"{'='*60}")

    if not files:
        print("  Geen data gevonden. Gebruik: python run.py fetch")
    else:
        for f in files:
            print(f"  {f['file']:<20} {f['candles']:>6} candles  "
                  f"{f['start'].strftime('%Y-%m-%d')} tot {f['end'].strftime('%Y-%m-%d')}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Cryptogem Backtest Engine v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  python run.py backtest                    Backtest alle strategieen op BTC 1H
  python run.py backtest --coin ETH         Backtest op ETH
  python run.py paper --days 30             Paper trade laatste 30 dagen
  python run.py paper --capital 500         Start met EUR 500
  python run.py compare                     Vergelijk 1H vs 1D
  python run.py fetch                       Download data voor alle coins
  python run.py list                        Toon beschikbare data
        """)

    subparsers = parser.add_subparsers(dest='command', help='Commando')

    # Backtest
    p_bt = subparsers.add_parser('backtest', help='Run backtests')
    p_bt.add_argument('--coin', default='BTC', help='Coin (BTC/ETH/SOL/BNB)')
    p_bt.add_argument('--timeframe', default='1h', help='Timeframe (1h/1d)')
    p_bt.add_argument('--strategy', help='Specifieke strategie (v55/v69/v13/v21)')

    # Paper trade
    p_pt = subparsers.add_parser('paper', help='Paper trade simulatie')
    p_pt.add_argument('--coin', default='BTC', help='Coin (BTC/ETH/SOL/BNB)')
    p_pt.add_argument('--days', type=int, default=365, help='Aantal dagen terug (default: 365)')
    p_pt.add_argument('--capital', type=float, default=1000.0, help='Startkapitaal in EUR (default: 1000)')
    p_pt.add_argument('--strategy', help='Specifieke strategie')

    # Compare
    p_cmp = subparsers.add_parser('compare', help='Vergelijk 1H vs 1D')
    p_cmp.add_argument('--coin', default='BTC', help='Coin (BTC/ETH/SOL/BNB)')
    p_cmp.add_argument('--days', type=int, default=365, help='Aantal dagen terug')
    p_cmp.add_argument('--capital', type=float, default=1000.0, help='Startkapitaal in EUR')

    # Fetch
    p_fetch = subparsers.add_parser('fetch', help='Download marktdata')
    p_fetch.add_argument('--coin', help='Specifieke coin (anders alle)')
    p_fetch.add_argument('--timeframe', help='Specifiek timeframe (anders alle)')

    # List
    subparsers.add_parser('list', help='Toon beschikbare data')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        'backtest': cmd_backtest,
        'paper': cmd_paper,
        'compare': cmd_compare,
        'fetch': cmd_fetch,
        'list': cmd_list,
    }

    commands[args.command](args)


if __name__ == '__main__':
    main()
