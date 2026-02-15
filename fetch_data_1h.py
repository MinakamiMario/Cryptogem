"""
Fetch BTC/USD 1H historical data for backtesting.
Yahoo Finance limits 1h data to ~730 days.
We'll fetch in chunks to maximize coverage.
"""
import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta

def fetch_btc_1h():
    """Download BTC-USD 1H data - max available from Yahoo Finance."""
    ticker = yf.Ticker("BTC-USD")

    # Yahoo allows max ~730 days of 1h data
    # Fetch the maximum available
    df = ticker.history(period="730d", interval="1h")

    if df.empty:
        print("No data returned, trying shorter period...")
        df = ticker.history(period="2y", interval="1h")

    # Clean up
    df.index.name = 'Date'
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df = df.dropna()

    # Remove timezone info for backtrader compatibility
    df.index = df.index.tz_localize(None)

    output_path = os.path.join(os.path.dirname(__file__), 'btc_usd_1h.csv')
    df.to_csv(output_path)
    print(f"Downloaded {len(df)} hourly candles")
    print(f"From: {df.index[0]}")
    print(f"To:   {df.index[-1]}")
    print(f"Days covered: {(df.index[-1] - df.index[0]).days}")
    print(f"Saved to: {output_path}")
    return df

if __name__ == "__main__":
    fetch_btc_1h()
