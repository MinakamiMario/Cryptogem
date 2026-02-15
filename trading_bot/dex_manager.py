"""
DEX Manager - DEX Data & Trading Layer
---------------------------------------
GeckoTerminal API: 4H OHLCV candle data voor DEX tokens (gratis, 30 req/min)
DexScreener API: Liquidity checks, token discovery (gratis, 300 req/min)

Ondersteunde chains:
  - Solana (Jupiter/Raydium)
  - BSC (PancakeSwap)
  - Ethereum (Uniswap) - let op: hoge gas fees!

Candle output formaat (identiek aan KrakenClient):
  {'time': int, 'open': float, 'high': float, 'low': float,
   'close': float, 'volume': float, 'count': int}

Gebruik:
    dex = DexManager()

    # Candles ophalen
    candles = dex.get_ohlc('solana', 'TOKEN_ADDRESS', interval=240)

    # Liquidity check voor een token
    liq = dex.check_liquidity('solana', 'TOKEN_ADDRESS')
    if liq['safe']:
        print(f"Liquidity OK: ${liq['usd_liquidity']:,.0f}")

    # Trending/nieuwe tokens ontdekken
    trending = dex.get_trending_pools('solana')
"""
import time
import json
import logging
from typing import Optional, Dict, List, Tuple
from pathlib import Path

logger = logging.getLogger('trading_bot')

# Cache directory
CACHE_DIR = Path(__file__).parent / 'cache'
CACHE_DIR.mkdir(exist_ok=True)


# ==============================================================================
# GeckoTerminal API Client (candle data)
# ==============================================================================

class GeckoTerminalClient:
    """
    GeckoTerminal API client voor DEX OHLCV candle data.

    Gratis tier: 30 req/min, 180 dagen historie, 1000 candles per request.
    4H candles: timeframe=hour, aggregate=4
    """

    BASE_URL = "https://api.geckoterminal.com/api/v2"

    # Chain ID mapping
    CHAINS = {
        'solana': 'solana',
        'ethereum': 'eth',
        'eth': 'eth',
        'bsc': 'bsc',
        'bnb': 'bsc',
        'base': 'base',
        'arbitrum': 'arbitrum',
    }

    def __init__(self):
        self._last_request_time = 0
        self._min_interval = 2.1  # 30 req/min = 1 per 2 sec, met marge
        self._pool_cache: Dict[str, dict] = {}  # token_addr → pool info
        self._pool_cache_file = CACHE_DIR / 'gecko_pool_cache.json'
        self._load_pool_cache()

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _load_pool_cache(self):
        """Laad gecachte pool adressen."""
        if self._pool_cache_file.exists():
            try:
                with open(self._pool_cache_file, 'r') as f:
                    data = json.load(f)
                    # Filter stale entries (> 24 uur oud)
                    now = time.time()
                    self._pool_cache = {
                        k: v for k, v in data.items()
                        if now - v.get('cached_at', 0) < 86400
                    }
            except Exception:
                self._pool_cache = {}

    def _save_pool_cache(self):
        """Sla pool cache op."""
        try:
            with open(self._pool_cache_file, 'w') as f:
                json.dump(self._pool_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Pool cache opslaan gefaald: {e}")

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """HTTP GET request naar GeckoTerminal API."""
        import requests
        self._rate_limit()
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                logger.warning("GeckoTerminal rate limit bereikt, wacht 60s...")
                time.sleep(60)
                resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"GeckoTerminal API error {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"GeckoTerminal request error: {e}")
            return None

    def _get_chain_id(self, chain: str) -> str:
        """Vertaal chain naam naar GeckoTerminal network ID."""
        return self.CHAINS.get(chain.lower(), chain.lower())

    def find_best_pool(self, chain: str, token_address: str) -> Optional[dict]:
        """
        Vind de beste pool voor een token.
        Selecteert op basis van: stablecoin quote (USDC/USDT) → volume → liquidity.
        Cached resultaat voor 24 uur.

        Returns: {'pool_address': str, 'dex': str, 'liquidity_usd': float,
                  'base_symbol': str, 'quote_symbol': str}
        """
        cache_key = f"{chain}:{token_address}"
        if cache_key in self._pool_cache:
            return self._pool_cache[cache_key]

        network = self._get_chain_id(chain)
        data = self._get(f"/networks/{network}/tokens/{token_address}/pools",
                         params={'page': 1})

        if not data or 'data' not in data:
            return None

        pools = data['data']
        if not pools:
            return None

        # Preferred stablecoin quotes (voor betere prijsdata)
        STABLE_QUOTES = {'usdc', 'usdt', 'dai', 'busd', 'usd coin', 'tether'}

        # Score elk pool: prefer stablecoin quote + hoog volume
        best = None
        best_score = -1
        for pool in pools:
            attrs = pool.get('attributes', {})
            liq = float(attrs.get('reserve_in_usd', 0) or 0)

            # Volume ophalen (kan dict of scalar zijn)
            vol_data = attrs.get('volume_usd', {})
            if isinstance(vol_data, dict):
                vol_24h = float(vol_data.get('h24', 0) or 0)
            else:
                vol_24h = float(vol_data or 0)

            # Check of quote token een stablecoin is
            name = attrs.get('name', '')
            parts = name.split(' / ') if ' / ' in name else ['', '']
            quote_name = parts[1].lower() if len(parts) > 1 else ''
            is_stable = any(s in quote_name for s in STABLE_QUOTES)

            # Score: stablecoin bonus (1M) + volume (primary) + liquidity (secondary)
            score = (1_000_000 if is_stable else 0) + vol_24h + (liq * 0.01)

            if score > best_score:
                best_score = score
                best = {
                    'pool_address': attrs.get('address', ''),
                    'dex': name,
                    'liquidity_usd': liq,
                    'base_symbol': parts[0].strip() if parts[0] else '',
                    'quote_symbol': parts[1].strip() if len(parts) > 1 else '',
                    'volume_24h': vol_24h,
                    'cached_at': time.time(),
                }

        if best:
            self._pool_cache[cache_key] = best
            self._save_pool_cache()
            logger.info(f"Pool gevonden: {chain}:{token_address[:8]}... → "
                        f"{best['pool_address'][:8]}... (liq: ${best['liquidity_usd']:,.0f})")

        return best

    def get_ohlc(self, chain: str, token_address: str,
                 interval: int = 240, limit: int = 720) -> Optional[List[dict]]:
        """
        Haal OHLCV candles op voor een DEX token.

        Args:
            chain: 'solana', 'bsc', 'ethereum'
            token_address: contract address van de token
            interval: in minuten (240 = 4H)
            limit: max candles (max 1000)

        Returns: lijst van candle dicts in KrakenClient formaat
        """
        # Eerst pool adres vinden
        pool = self.find_best_pool(chain, token_address)
        if not pool:
            logger.warning(f"Geen pool gevonden voor {chain}:{token_address[:8]}...")
            return None

        return self.get_ohlc_by_pool(chain, pool['pool_address'], interval, limit)

    def get_ohlc_by_pool(self, chain: str, pool_address: str,
                         interval: int = 240, limit: int = 720) -> Optional[List[dict]]:
        """
        Haal OHLCV candles op via pool adres.
        """
        network = self._get_chain_id(chain)

        # Timeframe mapping
        if interval >= 1440:
            timeframe = 'day'
            aggregate = interval // 1440
        elif interval >= 60:
            timeframe = 'hour'
            aggregate = interval // 60
        else:
            timeframe = 'minute'
            aggregate = interval

        # GeckoTerminal max 1000 per request
        actual_limit = min(limit, 1000)

        data = self._get(
            f"/networks/{network}/pools/{pool_address}/ohlcv/{timeframe}",
            params={
                'aggregate': aggregate,
                'limit': actual_limit,
                'currency': 'usd',
            }
        )

        if not data or 'data' not in data:
            return None

        ohlcv_list = data['data'].get('attributes', {}).get('ohlcv_list', [])
        if not ohlcv_list:
            return None

        # Converteer naar KrakenClient candle formaat
        # GeckoTerminal: [timestamp, open, high, low, close, volume]
        # Meest recente eerst → sorteer op tijd ascending
        candles = []
        for c in reversed(ohlcv_list):
            candles.append({
                'time': int(c[0]),
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'volume': float(c[5]),
                'count': 0,  # Niet beschikbaar via GeckoTerminal
            })

        logger.info(f"GeckoTerminal: {len(candles)} candles opgehaald voor "
                     f"{chain}:{pool_address[:8]}...")
        return candles

    def get_trending_pools(self, chain: str, limit: int = 20) -> Optional[List[dict]]:
        """Haal trending pools op voor een chain."""
        network = self._get_chain_id(chain)
        data = self._get(f"/networks/{network}/trending_pools")
        if not data or 'data' not in data:
            return None

        pools = []
        for pool in data['data'][:limit]:
            attrs = pool.get('attributes', {})
            pools.append({
                'name': attrs.get('name', ''),
                'address': attrs.get('address', ''),
                'price_usd': float(attrs.get('base_token_price_usd', 0) or 0),
                'volume_24h': float(attrs.get('volume_usd', {}).get('h24', 0) or 0),
                'liquidity_usd': float(attrs.get('reserve_in_usd', 0) or 0),
                'price_change_24h': float(attrs.get('price_change_percentage', {}).get('h24', 0) or 0),
            })
        return pools

    def search_pools(self, query: str, chain: str = None) -> Optional[List[dict]]:
        """Zoek pools op naam of symbol."""
        params = {'query': query}
        if chain:
            params['network'] = self._get_chain_id(chain)

        data = self._get("/search/pools", params=params)
        if not data or 'data' not in data:
            return None

        results = []
        for pool in data['data'][:20]:
            attrs = pool.get('attributes', {})
            results.append({
                'name': attrs.get('name', ''),
                'address': attrs.get('address', ''),
                'network': attrs.get('network', {}).get('identifier', ''),
                'price_usd': float(attrs.get('base_token_price_usd', 0) or 0),
                'volume_24h': float(attrs.get('volume_usd', {}).get('h24', 0) or 0),
                'liquidity_usd': float(attrs.get('reserve_in_usd', 0) or 0),
            })
        return results


# ==============================================================================
# DexScreener API Client (liquidity + discovery)
# ==============================================================================

class DexScreenerClient:
    """
    DexScreener API client voor liquidity checks en token discovery.

    Gratis, geen API key nodig, 300 req/min.
    GEEN historical candle data! Alleen real-time data.
    """

    BASE_URL = "https://api.dexscreener.com"

    # Chain ID mapping (DexScreener formaat)
    CHAINS = {
        'solana': 'solana',
        'ethereum': 'ethereum',
        'eth': 'ethereum',
        'bsc': 'bsc',
        'bnb': 'bsc',
        'base': 'base',
        'arbitrum': 'arbitrum',
    }

    def __init__(self):
        self._last_request_time = 0
        self._min_interval = 0.25  # 300 req/min = 5 per sec

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get(self, endpoint: str) -> Optional[dict]:
        """HTTP GET request naar DexScreener API."""
        import requests
        self._rate_limit()
        url = f"{self.BASE_URL}{endpoint}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                logger.warning("DexScreener rate limit, wacht 10s...")
                time.sleep(10)
                resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"DexScreener API error {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"DexScreener request error: {e}")
            return None

    def check_liquidity(self, chain: str, token_address: str,
                        min_liquidity_usd: float = 50_000,
                        min_volume_24h: float = 10_000,
                        min_txns_24h: int = 100,
                        max_age_days: int = 30) -> dict:
        """
        Uitgebreide liquidity check voor een DEX token.

        Returns: {
            'safe': bool,           # Veilig om te traden?
            'usd_liquidity': float, # USD liquidity in pool
            'volume_24h': float,    # 24h handelsvolume
            'txns_24h': int,        # Aantal transacties 24h
            'buy_sell_ratio': float, # Buys/sells ratio
            'pair_age_days': float, # Leeftijd van het pair
            'price_usd': float,    # Huidige prijs
            'dex': str,            # DEX naam (raydium, uniswap, etc.)
            'reasons': list,       # Redenen voor afwijzing (als niet safe)
            'best_pair': str,      # Beste pair adres
        }
        """
        chain_id = self.CHAINS.get(chain.lower(), chain.lower())
        data = self._get(f"/tokens/v1/{chain_id}/{token_address}")

        result = {
            'safe': False,
            'usd_liquidity': 0,
            'volume_24h': 0,
            'txns_24h': 0,
            'buy_sell_ratio': 0,
            'pair_age_days': 0,
            'price_usd': 0,
            'dex': '',
            'reasons': [],
            'best_pair': '',
        }

        if not data:
            result['reasons'].append('Token niet gevonden op DexScreener')
            return result

        # Data is een lijst van pairs (tokens/v1 endpoint)
        pairs = data if isinstance(data, list) else data.get('pairs', [])
        if not pairs:
            result['reasons'].append('Geen trading pairs gevonden')
            return result

        # Vind het pair met hoogste liquidity
        best = None
        best_liq = 0
        for pair in pairs:
            liq = pair.get('liquidity', {}).get('usd', 0) or 0
            if liq > best_liq:
                best_liq = liq
                best = pair

        if not best:
            result['reasons'].append('Geen pair met liquidity gevonden')
            return result

        # Extract data
        liq_usd = best.get('liquidity', {}).get('usd', 0) or 0
        vol_24h = best.get('volume', {}).get('h24', 0) or 0
        txns = best.get('txns', {}).get('h24', {})
        buys = txns.get('buys', 0) or 0
        sells = txns.get('sells', 0) or 0
        total_txns = buys + sells
        buy_sell_ratio = buys / max(sells, 1)

        # Pair leeftijd
        created_at = best.get('pairCreatedAt', 0)
        age_days = (time.time() * 1000 - created_at) / (86400 * 1000) if created_at else 0

        result.update({
            'usd_liquidity': liq_usd,
            'volume_24h': vol_24h,
            'txns_24h': total_txns,
            'buy_sell_ratio': buy_sell_ratio,
            'pair_age_days': age_days,
            'price_usd': float(best.get('priceUsd', 0) or 0),
            'dex': best.get('dexId', ''),
            'best_pair': best.get('pairAddress', ''),
        })

        # Safety checks
        reasons = []

        if liq_usd < min_liquidity_usd:
            reasons.append(f"Liquidity te laag: ${liq_usd:,.0f} < ${min_liquidity_usd:,.0f}")

        if vol_24h < min_volume_24h:
            reasons.append(f"Volume te laag: ${vol_24h:,.0f} < ${min_volume_24h:,.0f}")

        if total_txns < min_txns_24h:
            reasons.append(f"Te weinig transacties: {total_txns} < {min_txns_24h}")

        if age_days < max_age_days:
            reasons.append(f"Pair te nieuw: {age_days:.0f} dagen < {max_age_days} dagen")

        # Extreme buy/sell ratio = mogelijke manipulatie
        if total_txns > 50 and (buy_sell_ratio > 10 or buy_sell_ratio < 0.1):
            reasons.append(f"Verdachte buy/sell ratio: {buy_sell_ratio:.2f}")

        result['reasons'] = reasons
        result['safe'] = len(reasons) == 0

        return result

    def get_token_info(self, token_address: str) -> Optional[List[dict]]:
        """
        Haal token info op (alle chains).
        DexScreener zoekt automatisch op alle chains.
        """
        data = self._get(f"/latest/dex/tokens/{token_address}")
        if not data or 'pairs' not in data:
            return None

        results = []
        for pair in data['pairs'][:10]:
            results.append({
                'chain': pair.get('chainId', ''),
                'dex': pair.get('dexId', ''),
                'pair_address': pair.get('pairAddress', ''),
                'base_symbol': pair.get('baseToken', {}).get('symbol', ''),
                'quote_symbol': pair.get('quoteToken', {}).get('symbol', ''),
                'price_usd': float(pair.get('priceUsd', 0) or 0),
                'liquidity_usd': pair.get('liquidity', {}).get('usd', 0) or 0,
                'volume_24h': pair.get('volume', {}).get('h24', 0) or 0,
                'price_change_24h': pair.get('priceChange', {}).get('h24', 0) or 0,
            })
        return results

    def search_tokens(self, query: str) -> Optional[List[dict]]:
        """Zoek tokens op naam of symbol."""
        data = self._get(f"/latest/dex/search?q={query}")
        if not data or 'pairs' not in data:
            return None

        results = []
        seen = set()
        for pair in data['pairs'][:20]:
            base = pair.get('baseToken', {})
            key = f"{pair.get('chainId')}:{base.get('address', '')}"
            if key in seen:
                continue
            seen.add(key)

            results.append({
                'chain': pair.get('chainId', ''),
                'address': base.get('address', ''),
                'symbol': base.get('symbol', ''),
                'name': base.get('name', ''),
                'price_usd': float(pair.get('priceUsd', 0) or 0),
                'liquidity_usd': pair.get('liquidity', {}).get('usd', 0) or 0,
                'volume_24h': pair.get('volume', {}).get('h24', 0) or 0,
            })
        return results

    def get_top_boosted(self) -> Optional[List[dict]]:
        """Haal top boosted tokens op (meest promoted)."""
        data = self._get("/token-boosts/top/v1")
        if not data:
            return None
        return data[:20] if isinstance(data, list) else []

    def discover_solana_tokens(self,
                                min_liquidity: float = 100_000,
                                min_volume_24h: float = 50_000,
                                min_mcap: float = 1_000_000,
                                min_age_days: float = 14,
                                min_txns_24h: int = 200,
                                max_tokens: int = 50) -> List[dict]:
        """
        Ontdek automatisch de top Solana tokens via DexScreener.

        Stappen:
        1. Haal trending/boosted tokens op
        2. Zoek bekende top Solana coins (hardcoded seed list)
        3. Multi-token lookup voor details
        4. Filter op veiligheid: liquidity, market cap, leeftijd, volume
        5. Sorteer op score (liq + volume + mcap)

        Args:
            min_liquidity: Minimum USD liquidity ($100K default)
            min_volume_24h: Minimum 24h volume ($50K default)
            min_mcap: Minimum market cap ($1M default)
            min_age_days: Minimum leeftijd pair (14 dagen default)
            min_txns_24h: Minimum transacties per 24h (200 default)
            max_tokens: Maximum tokens in resultaat

        Returns: Gesorteerde lijst van veilige Solana tokens
        """
        import time as _time

        # ─── Seed list: bekende top Solana tokens (contract addresses) ───
        SEED_TOKENS = {
            'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',
            'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 'BONK',
            'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 'WIF',
            '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 'RAY',
            'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': 'ORCA',
            'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': 'PYTH',
            'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': 'JTO',
            'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof': 'RNDR',
            'SHDWyBxihqiCj6YekG2GUr7wqKLeLAMK1gHZck9pL6y': 'SHDW',
            'MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey': 'MNDE',
            'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5': 'MEW',
            'WENWENvqqNya429ubCdR81ZmD69brwQaaBYY6p3LCpk': 'WEN',
            '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr': 'POPCAT',
            'A8C3xuqscfmyLrte3VwXxhSRfDGAqDN9TJjgJpXRMkne': 'KMNO',
            'Grass7B4RdKfBCjTKgSqnXkqjwiGvQyFbuSCUJr3XXjs': 'GRASS',
            '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ': 'W',
        }

        logger.info(f"Solana token discovery gestart (min liq=${min_liquidity:,.0f}, "
                     f"min mcap=${min_mcap:,.0f}, min age={min_age_days}d)")

        # ─── Stap 1: Verzamel token adressen ───
        token_addresses = set(SEED_TOKENS.keys())

        # Boosted tokens ophalen
        boosted = self.get_top_boosted()
        if boosted:
            for t in boosted:
                if t.get('chainId') == 'solana':
                    addr = t.get('tokenAddress', '')
                    if addr:
                        token_addresses.add(addr)

        # Token profiles ophalen
        profiles_data = self._get("/token-profiles/latest/v1")
        if profiles_data and isinstance(profiles_data, list):
            for t in profiles_data:
                if t.get('chainId') == 'solana':
                    addr = t.get('tokenAddress', '')
                    if addr:
                        token_addresses.add(addr)

        logger.info(f"Solana discovery: {len(token_addresses)} unieke adressen verzameld "
                     f"({len(SEED_TOKENS)} seed + trending/boosted)")

        # ─── Stap 2: Multi-token lookup (batches van 30) ───
        all_pairs = []
        addr_list = list(token_addresses)

        for i in range(0, len(addr_list), 30):
            batch = addr_list[i:i+30]
            multi = ','.join(batch)
            data = self._get(f"/tokens/v1/solana/{multi}")
            if data and isinstance(data, list):
                all_pairs.extend(data)
            # Rate limit respecteren
            if i + 30 < len(addr_list):
                _time.sleep(0.3)

        logger.info(f"DexScreener: {len(all_pairs)} pairs opgehaald voor "
                     f"{len(addr_list)} tokens")

        # ─── Stap 3: Dedupliceer & selecteer beste pair per token ───
        best_per_token = {}
        for pair in all_pairs:
            base = pair.get('baseToken', {})
            addr = base.get('address', '')
            symbol = base.get('symbol', '')
            liq = pair.get('liquidity', {}).get('usd', 0) or 0

            key = addr
            if key not in best_per_token or liq > (best_per_token[key].get('_liq', 0)):
                # Extract alle veiligheidsdata
                vol_24h = pair.get('volume', {}).get('h24', 0) or 0
                txns = pair.get('txns', {}).get('h24', {})
                buys = txns.get('buys', 0) or 0
                sells = txns.get('sells', 0) or 0
                total_txns = buys + sells
                buy_sell_ratio = buys / max(sells, 1)

                created_at = pair.get('pairCreatedAt', 0)
                age_days = (_time.time() * 1000 - created_at) / (86400 * 1000) if created_at else 0

                mcap = pair.get('marketCap', 0) or pair.get('fdv', 0) or 0
                price = float(pair.get('priceUsd', 0) or 0)

                best_per_token[key] = {
                    'symbol': symbol,
                    'name': base.get('name', symbol),
                    'address': addr,
                    'chain': 'solana',
                    'price_usd': price,
                    'liquidity_usd': liq,
                    'volume_24h': vol_24h,
                    'market_cap': mcap,
                    'txns_24h': total_txns,
                    'buys_24h': buys,
                    'sells_24h': sells,
                    'buy_sell_ratio': buy_sell_ratio,
                    'age_days': age_days,
                    'dex': pair.get('dexId', ''),
                    'pair_address': pair.get('pairAddress', ''),
                    'quote_symbol': pair.get('quoteToken', {}).get('symbol', ''),
                    '_liq': liq,  # voor dedup sorting
                }

        logger.info(f"Unieke tokens na dedup: {len(best_per_token)}")

        # ─── Stap 4: Safety filter ───
        safe_tokens = []
        rejected = {'liquidity': 0, 'volume': 0, 'mcap': 0, 'age': 0, 'txns': 0,
                     'ratio': 0}

        for addr, token in best_per_token.items():
            reasons = []

            if token['liquidity_usd'] < min_liquidity:
                reasons.append(f"liq ${token['liquidity_usd']:,.0f} < ${min_liquidity:,.0f}")
                rejected['liquidity'] += 1

            if token['volume_24h'] < min_volume_24h:
                reasons.append(f"vol ${token['volume_24h']:,.0f} < ${min_volume_24h:,.0f}")
                rejected['volume'] += 1

            if token['market_cap'] < min_mcap and token['market_cap'] > 0:
                reasons.append(f"mcap ${token['market_cap']:,.0f} < ${min_mcap:,.0f}")
                rejected['mcap'] += 1

            if token['age_days'] < min_age_days:
                reasons.append(f"age {token['age_days']:.0f}d < {min_age_days}d")
                rejected['age'] += 1

            if token['txns_24h'] < min_txns_24h:
                reasons.append(f"txns {token['txns_24h']} < {min_txns_24h}")
                rejected['txns'] += 1

            # Verdachte buy/sell ratio
            if token['txns_24h'] > 50:
                if token['buy_sell_ratio'] > 10 or token['buy_sell_ratio'] < 0.1:
                    reasons.append(f"verdachte ratio {token['buy_sell_ratio']:.1f}")
                    rejected['ratio'] += 1

            if not reasons:
                # Veiligheids-score berekenen
                score = (
                    min(token['liquidity_usd'] / 1_000_000, 5) * 20 +    # Max 100 punten liq
                    min(token['volume_24h'] / 500_000, 5) * 15 +          # Max 75 punten vol
                    min(token['market_cap'] / 10_000_000, 10) * 5 +       # Max 50 punten mcap
                    min(token['age_days'] / 365, 1) * 10 +                # Max 10 punten leeftijd
                    min(token['txns_24h'] / 5000, 1) * 5                  # Max 5 punten activiteit
                )
                token['safety_score'] = round(score, 1)
                # Verwijder interne velden
                token.pop('_liq', None)
                safe_tokens.append(token)
            else:
                logger.debug(f"Token {token['symbol']} afgewezen: {', '.join(reasons)}")

        # ─── Stap 5: RugCheck safety check ───
        # Gebruik RugCheck API om scams/rug pulls te detecteren
        from dex_manager import RugCheckClient
        rugcheck = RugCheckClient()

        rugcheck_passed = []
        rugcheck_failed = 0

        for token in safe_tokens:
            addr = token.get('address', '')
            if not addr:
                continue

            rug = rugcheck.check_token(addr)
            token['rugcheck_score'] = rug['score']
            token['rugcheck_safe'] = rug['safe']
            token['freeze_authority'] = rug['freeze_authority']
            token['mint_authority'] = rug['mint_authority']
            token['lp_locked_pct'] = rug['lp_locked_pct']
            token['top5_holder_pct'] = rug['top5_holder_pct']
            token['total_holders'] = rug['total_holders']
            token['rugcheck_dangers'] = rug['dangers']

            if rug['rugged']:
                logger.warning(f"Token {token['symbol']} is GERUGGED! Overgeslagen.")
                rugcheck_failed += 1
                continue

            if rug['freeze_authority'] and rug['score'] > 10000:
                logger.info(f"Token {token['symbol']} heeft freeze authority + hoge score, "
                            f"overgeslagen")
                rugcheck_failed += 1
                continue

            if rug['dangers'] >= 2 and rug['score'] > 50000:
                logger.info(f"Token {token['symbol']} heeft {rug['dangers']} dangers + "
                            f"score {rug['score']}, overgeslagen")
                rugcheck_failed += 1
                continue

            # RugCheck score meewegen in safety score
            # Bonus voor lage rugcheck score (veiliger)
            if rug['score'] <= 100:
                token['safety_score'] += 20  # Zeer veilig
            elif rug['score'] <= 1000:
                token['safety_score'] += 10
            elif rug['score'] > 50000:
                token['safety_score'] -= 10  # Penalty voor hoge score

            rugcheck_passed.append(token)

        logger.info(f"RugCheck: {len(rugcheck_passed)} passed, {rugcheck_failed} failed")

        # ─── Stap 6: Sorteer op score en limiteer ───
        rugcheck_passed.sort(key=lambda t: t['safety_score'], reverse=True)
        result = rugcheck_passed[:max_tokens]

        # Log samenvatting
        logger.info(f"Solana discovery compleet: {len(result)}/{len(best_per_token)} tokens "
                     f"passeren alle filters (DexScreener + RugCheck)")
        logger.info(f"  DexScreener afgewezen: liq={rejected['liquidity']}, "
                     f"vol={rejected['volume']}, mcap={rejected['mcap']}, "
                     f"age={rejected['age']}, txns={rejected['txns']}, "
                     f"ratio={rejected['ratio']}")
        logger.info(f"  RugCheck afgewezen: {rugcheck_failed}")

        return result


# ==============================================================================
# RugCheck API Client (Solana scam/rug pull detection)
# ==============================================================================

class RugCheckClient:
    """
    RugCheck.xyz API client voor Solana token safety checks.

    Gratis, geen API key nodig.
    Controleert: LP lock status, freeze/mint authority, holder concentration,
    rug pull risico, en overall safety score.

    Score systeem: lager = veiliger (WIF=1, JUP=101, RENDER=76107)
    """

    BASE_URL = "https://api.rugcheck.xyz/v1"

    def __init__(self):
        self._last_request_time = 0
        self._min_interval = 1.0  # Conservatief, geen officieel limiet bekend
        self._cache: Dict[str, dict] = {}

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def check_token(self, token_address: str) -> dict:
        """
        Volledige safety check voor een Solana token.

        Returns: {
            'safe': bool,           # Veilig om te traden?
            'score': int,           # RugCheck score (lager = veiliger)
            'rugged': bool,         # Al gerugged?
            'risks': list,          # Lijst van risico's
            'dangers': int,         # Aantal 'danger' risico's
            'warnings': int,        # Aantal 'warn' risico's
            'freeze_authority': bool,  # Kan tokens bevriezen?
            'mint_authority': bool,    # Kan tokens bijmaken?
            'lp_locked_pct': float,    # Beste LP lock percentage
            'top5_holder_pct': float,  # Top 5 holders % van supply
            'total_holders': int,      # Totaal aantal holders
            'reasons': list,           # Redenen voor afwijzing
        }
        """
        # Cache check
        if token_address in self._cache:
            return self._cache[token_address]

        import requests
        self._rate_limit()

        result = {
            'safe': False,
            'score': 999999,
            'rugged': False,
            'risks': [],
            'dangers': 0,
            'warnings': 0,
            'freeze_authority': False,
            'mint_authority': False,
            'lp_locked_pct': 0,
            'top5_holder_pct': 0,
            'total_holders': 0,
            'reasons': [],
        }

        try:
            resp = requests.get(
                f"{self.BASE_URL}/tokens/{token_address}/report",
                timeout=15
            )
            if resp.status_code != 200:
                result['reasons'].append(f"RugCheck API error: {resp.status_code}")
                return result

            data = resp.json()
        except Exception as e:
            result['reasons'].append(f"RugCheck request error: {e}")
            return result

        # Score & rugged status
        score = data.get('score', 999999)
        rugged = data.get('rugged', False)

        # Risico's tellen
        risks = data.get('risks', []) or []
        dangers = sum(1 for r in risks if r.get('level') == 'danger')
        warnings = sum(1 for r in risks if r.get('level') == 'warn')
        risk_list = [(r.get('level', '?'), r.get('name', '?')) for r in risks]

        # Freeze & Mint authority
        freeze_auth = data.get('freezeAuthority') is not None
        mint_auth = data.get('mintAuthority') is not None

        # LP Lock percentage (beste pool)
        markets = data.get('markets', []) or []
        best_lp_locked = 0
        for m in markets:
            lp = m.get('lp', {})
            if lp:
                lock_pct = lp.get('lpLockedPct', 0) or 0
                best_lp_locked = max(best_lp_locked, lock_pct)

        # Top holders
        holders = data.get('topHolders', []) or []
        # pct is al in percentage (24.77 = 24.77%)
        top5_pct = sum(h.get('pct', 0) for h in holders[:5])
        total_holders = data.get('totalHolders', 0) or 0

        # Safety evaluatie
        reasons = []

        if rugged:
            reasons.append("TOKEN IS GERUGGED")

        if freeze_auth:
            reasons.append("Freeze authority actief (kan tokens bevriezen)")

        if mint_auth and score > 10000:
            # Mint authority is soms OK bij grote tokens (GRASS heeft het)
            reasons.append("Mint authority actief (kan tokens bijmaken)")

        if dangers >= 2:
            reasons.append(f"{dangers} danger-level risico's")

        if top5_pct > 80:
            reasons.append(f"Top 5 holders bezitten {top5_pct:.0f}% van supply")

        if total_holders < 1000 and score > 1000:
            reasons.append(f"Weinig holders: {total_holders}")

        result.update({
            'safe': len(reasons) == 0,
            'score': score,
            'rugged': rugged,
            'risks': risk_list,
            'dangers': dangers,
            'warnings': warnings,
            'freeze_authority': freeze_auth,
            'mint_authority': mint_auth,
            'lp_locked_pct': best_lp_locked * 100,
            'top5_holder_pct': top5_pct,
            'total_holders': total_holders,
            'reasons': reasons,
        })

        # Cache resultaat
        self._cache[token_address] = result

        logger.info(f"RugCheck {token_address[:8]}...: score={score}, "
                     f"safe={result['safe']}, dangers={dangers}, "
                     f"holders={total_holders}")

        return result


# ==============================================================================
# DEX Manager (orchestrator)
# ==============================================================================

class DexManager:
    """
    Unified DEX manager die GeckoTerminal (candles) en DexScreener (liquidity)
    combineert tot een unified interface.

    Gebruik:
        dex = DexManager()

        # Candles ophalen (via GeckoTerminal)
        candles = dex.get_ohlc('solana', 'TOKEN_ADDRESS')

        # Liquidity check (via DexScreener)
        check = dex.check_liquidity('solana', 'TOKEN_ADDRESS')

        # Alles in een: candles + safety check
        result = dex.get_safe_ohlc('solana', 'TOKEN_ADDRESS')
    """

    # Minimum liquidity per chain (rekening houdend met gas costs)
    MIN_LIQUIDITY = {
        'solana': 25_000,       # Lage gas ($0.01), lagere drempel OK
        'bsc': 50_000,          # Lage gas ($0.50-2), matige drempel
        'ethereum': 200_000,    # Hoge gas ($10-50), hoge drempel nodig
    }

    # Gas kosten per chain (geschat in USD)
    GAS_COSTS = {
        'solana': 0.01,
        'bsc': 1.0,
        'ethereum': 30.0,  # Gemiddeld, kan $10-50 zijn
    }

    def __init__(self):
        self.gecko = GeckoTerminalClient()
        self.screener = DexScreenerClient()
        self.rugcheck = RugCheckClient()

    def get_ohlc(self, chain: str, token_address: str,
                 interval: int = 240, limit: int = 720) -> Optional[List[dict]]:
        """
        Haal OHLCV candles op voor een DEX token (via GeckoTerminal).
        Output in KrakenClient candle formaat.
        """
        return self.gecko.get_ohlc(chain, token_address, interval, limit)

    def check_liquidity(self, chain: str, token_address: str) -> dict:
        """
        Check liquidity van een DEX token (via DexScreener).
        Gebruikt chain-specifieke minimum drempels.
        """
        min_liq = self.MIN_LIQUIDITY.get(chain.lower(), 50_000)
        return self.screener.check_liquidity(
            chain, token_address,
            min_liquidity_usd=min_liq,
            min_volume_24h=10_000,
            min_txns_24h=100,
            max_age_days=30,
        )

    def get_safe_ohlc(self, chain: str, token_address: str,
                      interval: int = 240) -> Optional[dict]:
        """
        Haal candles op MET liquidity check.
        Returns None als token niet veilig genoeg is.

        Returns: {
            'candles': list,
            'liquidity': dict,
            'gas_cost': float,
            'chain': str,
        }
        """
        # Eerst liquidity check (sneller dan candles ophalen)
        liq = self.check_liquidity(chain, token_address)
        if not liq['safe']:
            logger.info(f"Token {token_address[:8]}... op {chain} afgewezen: "
                        f"{', '.join(liq['reasons'])}")
            return None

        # Candles ophalen
        candles = self.get_ohlc(chain, token_address, interval)
        if not candles or len(candles) < 30:
            logger.info(f"Niet genoeg candle data voor {token_address[:8]}... op {chain}")
            return None

        return {
            'candles': candles,
            'liquidity': liq,
            'gas_cost': self.GAS_COSTS.get(chain.lower(), 1.0),
            'chain': chain,
        }

    def estimate_slippage(self, chain: str, token_address: str,
                          trade_size_usd: float) -> float:
        """
        Schat slippage in voor een trade.
        Simpele benadering: trade_size / (2 * liquidity) * 100

        Returns: geschatte slippage in percentage.
        """
        liq = self.check_liquidity(chain, token_address)
        if liq['usd_liquidity'] <= 0:
            return 100.0  # Onhandelbaar

        # Simpele slippage schatting
        # Bij 2x trade size = liquidity → ~50% slippage
        slippage_pct = (trade_size_usd / (2 * liq['usd_liquidity'])) * 100
        return min(slippage_pct, 100.0)

    def is_trade_economical(self, chain: str, token_address: str,
                            trade_size_usd: float) -> Tuple[bool, str]:
        """
        Check of een trade economisch zinnig is (gas + slippage vs trade size).

        Returns: (economical: bool, reason: str)
        """
        gas = self.GAS_COSTS.get(chain.lower(), 1.0)
        slippage = self.estimate_slippage(chain, token_address, trade_size_usd)

        # Totale kosten = gas (entry + exit) + slippage
        total_cost_pct = ((gas * 2) / trade_size_usd * 100) + slippage

        if total_cost_pct > 5.0:
            return False, (f"Te duur: gas=${gas*2:.2f} + slippage={slippage:.1f}% "
                           f"= {total_cost_pct:.1f}% van ${trade_size_usd:.0f}")

        return True, f"OK: totale kosten {total_cost_pct:.2f}%"

    def get_chain_stats(self, chain: str) -> dict:
        """Haal statistieken op voor een chain."""
        return {
            'chain': chain,
            'gas_cost_usd': self.GAS_COSTS.get(chain.lower(), 0),
            'min_liquidity': self.MIN_LIQUIDITY.get(chain.lower(), 50_000),
            'recommended_min_trade': self.GAS_COSTS.get(chain.lower(), 0) * 100,
        }
