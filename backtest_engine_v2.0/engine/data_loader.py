"""
Data fetcher and loader for multiple coins and timeframes.
Supports: BTC, ETH, SOL, BNB (via Yahoo Finance)
"""
import os
import pandas as pd
import backtrader as bt

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

# Yahoo Finance tickers
TICKERS = {
    'BTC': 'BTC-USD',
    'ETH': 'ETH-USD',
    'SOL': 'SOL-USD',
    'BNB': 'BNB-USD',
}


def get_data_path(coin, timeframe):
    """Get path for a coin/timeframe CSV file."""
    return os.path.join(DATA_DIR, f'{coin}_{timeframe}.csv')


def fetch_and_save(coin='BTC', timeframe='1h', period='730d'):
    """
    Fetch data from Yahoo Finance and save to CSV.

    Args:
        coin: 'BTC', 'ETH', 'SOL', 'BNB'
        timeframe: '1h', '1d'
        period: '730d', 'max', etc.
    """
    import yfinance as yf

    ticker = TICKERS.get(coin.upper())
    if not ticker:
        raise ValueError(f"Unknown coin: {coin}. Supported: {list(TICKERS.keys())}")

    # Yahoo Finance interval mapping
    interval_map = {'1h': '1h', '1d': '1d'}
    interval = interval_map.get(timeframe)
    if not interval:
        raise ValueError(f"Unknown timeframe: {timeframe}. Supported: 1h, 1d")

    print(f"  Fetching {ticker} {interval} data (period={period})...")
    data = yf.download(ticker, period=period, interval=interval)

    if data.empty:
        raise ValueError(f"No data received for {ticker}")

    # Flatten multi-level columns if needed
    if hasattr(data.columns, 'levels') and len(data.columns.levels) > 1:
        data.columns = data.columns.get_level_values(0)

    # Keep only OHLCV
    data = data[['Open', 'High', 'Low', 'Close', 'Volume']]
    data.index.name = 'Date'

    # Remove timezone info
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = get_data_path(coin.upper(), timeframe)
    data.to_csv(filepath)
    print(f"  Saved {len(data)} candles to {filepath}")
    return filepath


def load_data(coin='BTC', timeframe='1h'):
    """
    Load data from CSV and return a Backtrader data feed.

    Args:
        coin: 'BTC', 'ETH', 'SOL', 'BNB'
        timeframe: '1h', '1d'

    Returns:
        bt.feeds.PandasData feed
    """
    filepath = get_data_path(coin.upper(), timeframe)

    if not os.path.exists(filepath):
        print(f"  Data file not found: {filepath}")
        print(f"  Fetching data...")
        period = '730d' if timeframe == '1h' else 'max'
        fetch_and_save(coin, timeframe, period)

    df = pd.read_csv(filepath, index_col='Date', parse_dates=True)

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    if timeframe == '1h':
        tf = bt.TimeFrame.Minutes
        compression = 60
    else:
        tf = bt.TimeFrame.Days
        compression = 1

    return bt.feeds.PandasData(dataname=df, timeframe=tf, compression=compression)


def load_df(coin='BTC', timeframe='1h'):
    """Load raw DataFrame (for analysis/reporting)."""
    filepath = get_data_path(coin.upper(), timeframe)
    df = pd.read_csv(filepath, index_col='Date', parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def list_available_data():
    """List all available data files."""
    if not os.path.exists(DATA_DIR):
        return []
    files = []
    for f in sorted(os.listdir(DATA_DIR)):
        if f.endswith('.csv'):
            filepath = os.path.join(DATA_DIR, f)
            df = pd.read_csv(filepath, index_col='Date', parse_dates=True)
            files.append({
                'file': f,
                'candles': len(df),
                'start': df.index[0],
                'end': df.index[-1],
            })
    return files
