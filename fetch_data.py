"""
Fetch BTC/USD 1D historical data for backtesting.
"""
import yfinance as yf
import pandas as pd
import os

def fetch_btc_data():
    """Download BTC-USD daily data from Yahoo Finance."""
    ticker = yf.Ticker("BTC-USD")
    # Get maximum available history at daily interval
    df = ticker.history(period="max", interval="1d")

    # Clean up for backtrader compatibility
    df.index.name = 'Date'
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df = df.dropna()

    # Save to CSV
    output_path = os.path.join(os.path.dirname(__file__), 'btc_usd_1d.csv')
    df.to_csv(output_path)
    print(f"Downloaded {len(df)} daily candles from {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Saved to: {output_path}")
    return df

if __name__ == "__main__":
    fetch_btc_data()
