"""
Exchange Manager - Multi-Exchange Abstraction Layer
----------------------------------------------------
Unified interface voor Kraken (native) + MEXC (CCXT).
Behoudt volledige backward compatibility met bestaande bot.

Candle output formaat (identiek aan KrakenClient):
  {'time': int, 'open': float, 'high': float, 'low': float,
   'close': float, 'volume': float, 'count': int}

Gebruik:
    manager = ExchangeManager()
    manager.add_exchange('kraken', api_key=..., private_key=...)
    manager.add_exchange('mexc', api_key=..., secret=...)

    # Candles ophalen (unified formaat)
    candles = manager.get_ohlc('kraken', 'BTC/USD', interval=240)
    candles = manager.get_ohlc('mexc', 'BTC/USDT', interval=240)

    # Orders plaatsen
    order_id = manager.place_market_buy('kraken', 'FET/USD', volume=100)
    order_id = manager.place_market_buy('mexc', 'FET/USDT', volume=100)

    # Alle beschikbare coins ophalen
    coins = manager.get_tradeable_coins('mexc')  # ['BTC/USDT', 'ETH/USDT', ...]
"""
import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, List

logger = logging.getLogger('trading_bot')


# ==============================================================================
# Abstract Base Class
# ==============================================================================

class ExchangeClient(ABC):
    """Abstract base class voor exchange clients."""

    def __init__(self, name: str, fee_pct: float = 0.0):
        self.name = name
        self.fee_pct = fee_pct
        self._last_request_time = 0
        self._min_interval = 1.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    @abstractmethod
    def test_connection(self) -> bool:
        pass

    @abstractmethod
    def get_ohlc(self, pair: str, interval: int = 240) -> Optional[List[dict]]:
        """Haal OHLC candles op. interval in minuten (240 = 4H)."""
        pass

    @abstractmethod
    def get_ticker(self, pair: str) -> Optional[dict]:
        pass

    @abstractmethod
    def get_balance(self) -> Optional[dict]:
        pass

    @abstractmethod
    def place_market_buy(self, pair: str, volume: float) -> Optional[str]:
        pass

    @abstractmethod
    def place_market_sell(self, pair: str, volume: float) -> Optional[str]:
        pass

    @abstractmethod
    def get_tradeable_pairs(self) -> List[str]:
        """Haal alle handelbare paren op in 'BASE/QUOTE' formaat."""
        pass

    def get_market_info(self, pair: str) -> Optional[dict]:
        """Min order size, precision. Override per exchange."""
        return None

    def get_quote_currency(self) -> str:
        """Welke quote currency deze exchange primair gebruikt."""
        return 'USD'


# ==============================================================================
# Kraken Client (wrapper rond bestaande KrakenClient)
# ==============================================================================

class KrakenExchangeClient(ExchangeClient):
    """
    Kraken exchange client - wraps bestaande kraken_client.py.
    Behoudt alle bestaande functionaliteit inclusief USDC→USD conversie.
    """

    def __init__(self, api_key: str = '', private_key: str = ''):
        super().__init__('kraken', fee_pct=0.26)
        self._min_interval = 1.0

        from kraken_client import KrakenClient
        self._client = KrakenClient(api_key, private_key)

    def test_connection(self) -> bool:
        return self._client.test_connection()

    def get_ohlc(self, pair: str, interval: int = 240) -> Optional[List[dict]]:
        return self._client.get_ohlc(pair, interval=interval)

    def get_ticker(self, pair: str) -> Optional[dict]:
        return self._client.get_ticker(pair)

    def get_balance(self) -> Optional[dict]:
        return self._client.get_balance()

    def place_market_buy(self, pair: str, volume: float) -> Optional[str]:
        return self._client.place_market_buy(pair, volume)

    def place_market_sell(self, pair: str, volume: float) -> Optional[str]:
        return self._client.place_market_sell(pair, volume)

    def get_tradeable_pairs(self) -> List[str]:
        """
        Alle Kraken USD pairs - dynamisch via AssetPairs API.
        Cached voor 1 uur. Fallback naar hardcoded PAIR_MAP.
        """
        return self._client.get_all_tradeable_pairs()

    def get_quote_currency(self) -> str:
        return 'USD'

    # Kraken-specifiek: USDC→USD conversie
    def ensure_usd_available(self, needed: float) -> bool:
        return self._client.ensure_usd_available(needed)


# ==============================================================================
# MEXC Client (via CCXT)
# ==============================================================================

class MEXCExchangeClient(ExchangeClient):
    """
    MEXC exchange client via CCXT library.
    0% maker fees! 1,900+ coins beschikbaar.

    MEXC gebruikt USDT als quote currency (niet USD).
    """

    def __init__(self, api_key: str = '', secret: str = ''):
        super().__init__('mexc', fee_pct=0.0)  # 0% maker fees!
        self._min_interval = 0.2  # MEXC rate limit = 20 req/sec

        try:
            import ccxt
            self._exchange = ccxt.mexc({
                'apiKey': api_key,
                'secret': secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                },
            })
            # Laad markten bij init
            self._markets = None
            self._pairs_cache = None
            self._pairs_cache_time = 0
        except ImportError:
            raise ImportError(
                "CCXT library niet gevonden. Installeer met: pip install ccxt"
            )

    def _ensure_markets(self):
        """Laad markten (lazy, met cache)."""
        if self._markets is None:
            try:
                self._exchange.load_markets()
                self._markets = self._exchange.markets
                logger.info(f"MEXC markten geladen: {len(self._markets)} pairs")
            except Exception as e:
                logger.error(f"MEXC markten laden gefaald: {e}")
                self._markets = {}

    def test_connection(self) -> bool:
        try:
            self._rate_limit()
            status = self._exchange.fetch_status()
            if status and status.get('status') == 'ok':
                logger.info("MEXC verbinding OK")
                return True
            # Sommige exchanges retourneren geen status, probeer balance
            self._rate_limit()
            balance = self._exchange.fetch_balance()
            if balance is not None:
                logger.info("MEXC verbinding OK (via balance check)")
                return True
            return False
        except Exception as e:
            logger.error(f"MEXC verbinding gefaald: {e}")
            return False

    def get_ohlc(self, pair: str, interval: int = 240) -> Optional[List[dict]]:
        """
        Haal OHLC candles op via CCXT.
        interval: in minuten (240 = 4H)
        Output: zelfde formaat als KrakenClient.
        """
        self._rate_limit()
        try:
            # CCXT timeframe mapping
            tf_map = {
                1: '1m', 5: '5m', 15: '15m', 30: '30m',
                60: '1h', 240: '4h', 1440: '1d',
            }
            timeframe = tf_map.get(interval, '4h')

            # Haal 720 candles op (= 120 dagen bij 4H)
            ohlcv = self._exchange.fetch_ohlcv(pair, timeframe, limit=720)
            if not ohlcv:
                return None

            candles = []
            for c in ohlcv:
                candles.append({
                    'time': int(c[0] / 1000),  # CCXT geeft ms, wij willen sec
                    'open': float(c[1]),
                    'high': float(c[2]),
                    'low': float(c[3]),
                    'close': float(c[4]),
                    'volume': float(c[5]),
                    'count': 0,  # CCXT heeft geen trade count
                })
            return candles

        except Exception as e:
            logger.error(f"MEXC OHLC error voor {pair}: {e}")
            return None

    def get_ticker(self, pair: str) -> Optional[dict]:
        self._rate_limit()
        try:
            ticker = self._exchange.fetch_ticker(pair)
            if ticker:
                return {
                    'ask': float(ticker.get('ask', 0) or 0),
                    'bid': float(ticker.get('bid', 0) or 0),
                    'last': float(ticker.get('last', 0) or 0),
                    'volume_24h': float(ticker.get('baseVolume', 0) or 0),
                    'quote_volume_24h': float(ticker.get('quoteVolume', 0) or 0),
                    'high_24h': float(ticker.get('high', 0) or 0),
                    'low_24h': float(ticker.get('low', 0) or 0),
                }
        except Exception as e:
            logger.error(f"MEXC ticker error voor {pair}: {e}")
        return None

    def get_market_info(self, pair: str) -> Optional[dict]:
        """Min order size, precision uit CCXT markets."""
        self._ensure_markets()
        market = (self._markets or {}).get(pair)
        if not market:
            return None
        limits = market.get('limits', {})
        precision = market.get('precision', {})
        return {
            'min_amount': float((limits.get('amount', {}) or {}).get('min', 0) or 0),
            'min_cost': float((limits.get('cost', {}) or {}).get('min', 0) or 0),
            'amount_precision': precision.get('amount', 8),
            'price_precision': precision.get('price', 8),
        }

    def get_balance(self) -> Optional[dict]:
        self._rate_limit()
        try:
            balance = self._exchange.fetch_balance()
            if balance:
                result = {}
                for asset, data in balance.get('total', {}).items():
                    if data and float(data) > 0:
                        result[asset] = float(data)
                return result
        except Exception as e:
            logger.error(f"MEXC balance error: {e}")
        return None

    def place_market_buy(self, pair: str, volume: float) -> Optional[str]:
        self._rate_limit()
        try:
            order = self._exchange.create_market_buy_order(pair, volume)
            if order:
                order_id = order.get('id', '')
                logger.info(f"MEXC BUY: {pair} vol={volume} order={order_id}")
                return order_id
        except Exception as e:
            logger.error(f"MEXC buy error voor {pair}: {e}")
        return None

    def place_market_sell(self, pair: str, volume: float) -> Optional[str]:
        self._rate_limit()
        try:
            order = self._exchange.create_market_sell_order(pair, volume)
            if order:
                order_id = order.get('id', '')
                logger.info(f"MEXC SELL: {pair} vol={volume} order={order_id}")
                return order_id
        except Exception as e:
            logger.error(f"MEXC sell error voor {pair}: {e}")
        return None

    def place_limit_buy(self, pair: str, volume: float, price: float) -> Optional[dict]:
        """
        Place a limit buy order on MEXC.

        Returns full order dict with 'id', 'status', 'price', 'amount', 'filled',
        or None on error.
        """
        self._rate_limit()
        try:
            order = self._exchange.create_limit_buy_order(pair, volume, price)
            if order:
                logger.info(
                    f"MEXC LIMIT BUY: {pair} vol={volume} price={price} "
                    f"order={order.get('id', '')}"
                )
                return order
        except Exception as e:
            logger.error(f"MEXC limit buy error voor {pair}: {e}")
        return None

    def cancel_order(self, order_id: str, pair: str) -> bool:
        """Cancel an open order on MEXC. Returns True if cancelled successfully."""
        self._rate_limit()
        try:
            self._exchange.cancel_order(order_id, pair)
            logger.info(f"MEXC CANCEL: order={order_id} pair={pair}")
            return True
        except Exception as e:
            logger.error(f"MEXC cancel error voor {order_id}: {e}")
            return False

    def fetch_order(self, order_id: str, pair: str) -> Optional[dict]:
        """Fetch order status from MEXC. Returns CCXT order dict."""
        self._rate_limit()
        try:
            order = self._exchange.fetch_order(order_id, pair)
            return order
        except Exception as e:
            logger.error(f"MEXC fetch_order error voor {order_id}: {e}")
            return None

    def fetch_orderbook(self, pair: str, limit: int = 5) -> Optional[dict]:
        """Fetch orderbook for a pair. Returns {'bids': [...], 'asks': [...]}."""
        self._rate_limit()
        try:
            ob = self._exchange.fetch_order_book(pair, limit=limit)
            return ob
        except Exception as e:
            logger.error(f"MEXC orderbook error voor {pair}: {e}")
            return None

    def get_tradeable_pairs(self) -> List[str]:
        """
        Haal alle USDT spot pairs op van MEXC.
        Cached voor 1 uur.
        """
        now = time.time()
        if self._pairs_cache and (now - self._pairs_cache_time) < 3600:
            return self._pairs_cache

        self._ensure_markets()
        pairs = []
        for symbol, market in (self._markets or {}).items():
            if (market.get('spot', False) and
                market.get('active', False) and
                market.get('quote', '') == 'USDT'):
                pairs.append(symbol)

        self._pairs_cache = sorted(pairs)
        self._pairs_cache_time = now
        logger.info(f"MEXC tradeable pairs: {len(pairs)} USDT spot pairs")
        return self._pairs_cache

    def get_quote_currency(self) -> str:
        return 'USDT'


# ==============================================================================
# Exchange Manager (orchestrator)
# ==============================================================================

class ExchangeManager:
    """
    Unified exchange manager die meerdere exchanges beheert.

    Gebruik:
        manager = ExchangeManager()
        manager.add_exchange('kraken', api_key='...', private_key='...')
        manager.add_exchange('mexc', api_key='...', secret='...')

        # Candles ophalen
        candles = manager.get_ohlc('kraken', 'BTC/USD')
        candles = manager.get_ohlc('mexc', 'BTC/USDT')

        # Alle coins van alle exchanges
        all_coins = manager.get_all_tradeable_coins()
    """

    def __init__(self):
        self.exchanges: Dict[str, ExchangeClient] = {}

    def add_exchange(self, name: str, **kwargs) -> ExchangeClient:
        """
        Voeg een exchange toe.

        Supported exchanges:
        - 'kraken': kwargs = {api_key, private_key}
        - 'mexc': kwargs = {api_key, secret}
        """
        name = name.lower()

        if name == 'kraken':
            client = KrakenExchangeClient(
                api_key=kwargs.get('api_key', ''),
                private_key=kwargs.get('private_key', ''),
            )
        elif name == 'mexc':
            client = MEXCExchangeClient(
                api_key=kwargs.get('api_key', ''),
                secret=kwargs.get('secret', ''),
            )
        else:
            raise ValueError(f"Onbekende exchange: {name}. Ondersteund: kraken, mexc")

        self.exchanges[name] = client
        logger.info(f"Exchange toegevoegd: {name} (fee: {client.fee_pct}%)")
        return client

    def get_exchange(self, name: str) -> Optional[ExchangeClient]:
        return self.exchanges.get(name.lower())

    def get_ohlc(self, exchange: str, pair: str, interval: int = 240) -> Optional[List[dict]]:
        """Haal candles op van specifieke exchange."""
        client = self.exchanges.get(exchange.lower())
        if not client:
            logger.error(f"Exchange niet gevonden: {exchange}")
            return None
        return client.get_ohlc(pair, interval=interval)

    def get_ticker(self, exchange: str, pair: str) -> Optional[dict]:
        client = self.exchanges.get(exchange.lower())
        if not client:
            return None
        return client.get_ticker(pair)

    def get_balance(self, exchange: str) -> Optional[dict]:
        client = self.exchanges.get(exchange.lower())
        if not client:
            return None
        return client.get_balance()

    def place_market_buy(self, exchange: str, pair: str, volume: float) -> Optional[str]:
        client = self.exchanges.get(exchange.lower())
        if not client:
            return None
        return client.place_market_buy(pair, volume)

    def place_market_sell(self, exchange: str, pair: str, volume: float) -> Optional[str]:
        client = self.exchanges.get(exchange.lower())
        if not client:
            return None
        return client.place_market_sell(pair, volume)

    def get_tradeable_coins(self, exchange: str) -> List[str]:
        client = self.exchanges.get(exchange.lower())
        if not client:
            return []
        return client.get_tradeable_pairs()

    def get_all_tradeable_coins(self) -> Dict[str, List[str]]:
        """Haal alle tradeable coins op van alle exchanges."""
        result = {}
        for name, client in self.exchanges.items():
            result[name] = client.get_tradeable_pairs()
        return result

    def get_fee(self, exchange: str) -> float:
        """Haal fee percentage op voor exchange."""
        client = self.exchanges.get(exchange.lower())
        return client.fee_pct if client else 0.0

    def test_all_connections(self) -> Dict[str, bool]:
        """Test alle exchange verbindingen."""
        results = {}
        for name, client in self.exchanges.items():
            try:
                results[name] = client.test_connection()
            except Exception as e:
                logger.error(f"Connection test error voor {name}: {e}")
                results[name] = False
        return results

    @classmethod
    def from_env(cls) -> 'ExchangeManager':
        """
        Maak ExchangeManager aan vanuit environment variabelen.

        Verwacht in .env:
            KRAKEN_API_KEY=...
            KRAKEN_PRIVATE_KEY=...
            MEXC_API_KEY=...         (optioneel)
            MEXC_SECRET=...          (optioneel)
        """
        manager = cls()

        # Kraken (altijd laden als keys beschikbaar)
        kraken_key = os.getenv('KRAKEN_API_KEY', '')
        kraken_secret = os.getenv('KRAKEN_PRIVATE_KEY', '')
        if kraken_key and kraken_secret:
            manager.add_exchange('kraken',
                                 api_key=kraken_key,
                                 private_key=kraken_secret)
            logger.info("Kraken geladen vanuit .env")

        # MEXC (optioneel)
        mexc_key = os.getenv('MEXC_API_KEY', '')
        mexc_secret = os.getenv('MEXC_SECRET', '')
        if mexc_key and mexc_secret:
            manager.add_exchange('mexc',
                                 api_key=mexc_key,
                                 secret=mexc_secret)
            logger.info("MEXC geladen vanuit .env")

        return manager
