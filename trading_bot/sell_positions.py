"""Verkoop alle open posities en reset bot state."""
import os
import json
from dotenv import load_dotenv
load_dotenv()

from kraken_client import KrakenClient

client = KrakenClient(
    api_key=os.getenv('KRAKEN_API_KEY'),
    private_key=os.getenv('KRAKEN_PRIVATE_KEY'),
)
state_file = '/Users/oussama/Cryptogem/trading_bot/bot_state.json'

with open(state_file, 'r') as f:
    state = json.load(f)

positions = state.get('positions', {})

if not positions:
    print("Geen open posities.")
else:
    for pair, pos in list(positions.items()):
        volume = pos['volume']
        entry = pos['entry_price']
        # Gebruik werkelijk saldo i.p.v. state volume (fees bij aankoop)
        asset = pair.split('/')[0]
        balance = client.get_balance()
        actual_volume = float(balance.get(asset, 0)) if balance else 0
        if actual_volume <= 0:
            print(f"  ⚠️ Geen {asset} saldo gevonden, skip")
            continue
        print(f"Verkopen: {pair} — {actual_volume:.4f} tokens (state: {volume:.4f}, entry ${entry})")

        order_id = client.place_market_sell(pair, actual_volume)
        if order_id:
            print(f"  ✅ Verkocht! Order ID: {order_id}")
            del state['positions'][pair]
        else:
            print(f"  ❌ Verkoop mislukt voor {pair}")

    # Save cleaned state
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)
    print("\nBot state opgeschoond.")

# Check saldo
balance = client.get_balance()
if balance:
    print(f"\nHuidig saldo:")
    for asset, amount in balance.items():
        val = float(amount)
        if val > 0.001:
            print(f"  {asset}: {val}")
