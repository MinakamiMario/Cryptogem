"""
Coin Scanner - Unified Multi-Exchange Coin Discovery & Scanning
----------------------------------------------------------------
Combineert exchange_manager, dex_manager en halal_filter tot
een unified scanner die alle coins van alle bronnen ophaalt,
filtert op halal, liquidity controleert, en candle data levert.

Dit is de "brein" van de multi-exchange uitbreiding.

Gebruik:
    scanner = CoinScanner()

    # Scan alle bronnen en krijg tradeable coins
    coins = scanner.scan_all()
    # Returns: [
    #   {'symbol': 'FET', 'pair': 'FET/USD', 'source': 'kraken', ...},
    #   {'symbol': 'NEWTOKEN', 'pair': 'NEWTOKEN/USDT', 'source': 'mexc', ...},
    #   {'symbol': 'DEXTER', 'chain': 'solana', 'source': 'dex', ...},
    # ]

    # Candles ophalen voor een coin
    candles = scanner.get_candles(coin_info)
"""
import os
import json
import time
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger('trading_bot')

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache'
CACHE_DIR.mkdir(exist_ok=True)


class CoinScanner:
    """
    Unified coin scanner die alle exchanges + DEXes + halal filter combineert.

    Architecture:
    ┌────────────────────────────────────────────┐
    │  CoinScanner                               │
    │  ┌──────────────┐ ┌──────────────┐         │
    │  │ExchangeManager│ │ DexManager   │         │
    │  │ Kraken + MEXC │ │ Gecko+Screen │         │
    │  └──────┬───────┘ └──────┬───────┘         │
    │         └───────┬────────┘                  │
    │                 ▼                           │
    │         ┌──────────────┐                    │
    │         │ HalalFilter  │                    │
    │         │ 3-laags check│                    │
    │         └──────┬───────┘                    │
    │                ▼                            │
    │         Tradeable Coins                     │
    └────────────────────────────────────────────┘
    """

    def __init__(self,
                 enable_kraken: bool = True,
                 enable_mexc: bool = True,
                 enable_dex: bool = True,
                 enable_halal: bool = True,
                 dex_chains: List[str] = None):
        """
        Args:
            enable_kraken: Kraken exchange inschakelen
            enable_mexc: MEXC exchange inschakelen
            enable_dex: DEX scanning inschakelen
            enable_halal: Halal filtering inschakelen
            dex_chains: Welke DEX chains scannen (default: solana, bsc)
        """
        from exchange_manager import ExchangeManager
        from dex_manager import DexManager
        from halal_filter import HalalFilter

        self.enable_halal = enable_halal
        self.enable_dex = enable_dex
        self.dex_chains = dex_chains or ['solana', 'bsc']  # Ethereum te duur

        # Initialiseer componenten
        self.exchange_manager = ExchangeManager()
        self.dex_manager = DexManager() if enable_dex else None
        self.halal_filter = HalalFilter() if enable_halal else None

        # Exchange setup vanuit .env
        if enable_kraken:
            kraken_key = os.getenv('KRAKEN_API_KEY', '')
            kraken_secret = os.getenv('KRAKEN_PRIVATE_KEY', '')
            if kraken_key and kraken_secret:
                self.exchange_manager.add_exchange('kraken',
                                                    api_key=kraken_key,
                                                    private_key=kraken_secret)

        if enable_mexc:
            mexc_key = os.getenv('MEXC_API_KEY', '')
            mexc_secret = os.getenv('MEXC_SECRET', '')
            if mexc_key and mexc_secret:
                self.exchange_manager.add_exchange('mexc',
                                                    api_key=mexc_key,
                                                    secret=mexc_secret)

        # Coin database cache
        self._coin_db_file = CACHE_DIR / 'coin_database.json'
        self._coin_db: Dict[str, dict] = {}
        self._load_coin_db()

        # DEX watchlist (handmatig beheerde DEX tokens om te scannen)
        self._dex_watchlist_file = BASE_DIR / 'dex_watchlist.json'
        self._dex_watchlist: List[dict] = self._load_json(self._dex_watchlist_file, [])

    def _load_json(self, path: Path, default):
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def _save_json(self, path: Path, data):
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Opslaan gefaald {path}: {e}")

    def _load_coin_db(self):
        if self._coin_db_file.exists():
            try:
                with open(self._coin_db_file, 'r') as f:
                    data = json.load(f)
                    # Filter stale entries (> 24 uur)
                    now = time.time()
                    self._coin_db = {
                        k: v for k, v in data.items()
                        if now - v.get('cached_at', 0) < 86400
                    }
            except Exception:
                self._coin_db = {}

    def _save_coin_db(self):
        self._save_json(self._coin_db_file, self._coin_db)

    # =========================================================================
    # CEX Scanning
    # =========================================================================

    def scan_cex(self, exchange: str) -> List[dict]:
        """
        Scan een CEX exchange voor tradeable coins.

        Returns: lijst van coin info dicts:
        [
            {
                'symbol': 'FET',
                'pair': 'FET/USD',
                'source': 'kraken',
                'source_type': 'cex',
                'fee_pct': 0.26,
                'quote': 'USD',
            },
            ...
        ]
        """
        client = self.exchange_manager.get_exchange(exchange)
        if not client:
            logger.warning(f"Exchange niet gevonden: {exchange}")
            return []

        pairs = client.get_tradeable_pairs()
        coins = []

        for pair in pairs:
            parts = pair.split('/')
            if len(parts) != 2:
                continue

            symbol = parts[0]
            quote = parts[1]

            coin = {
                'symbol': symbol,
                'pair': pair,
                'source': exchange,
                'source_type': 'cex',
                'fee_pct': client.fee_pct,
                'quote': quote,
            }
            coins.append(coin)

        logger.info(f"CEX scan {exchange}: {len(coins)} coins gevonden")
        return coins

    def scan_all_cex(self) -> List[dict]:
        """Scan alle CEX exchanges."""
        all_coins = []
        for name in self.exchange_manager.exchanges:
            coins = self.scan_cex(name)
            all_coins.extend(coins)
        return all_coins

    # =========================================================================
    # DEX Scanning
    # =========================================================================

    def scan_dex_watchlist(self) -> List[dict]:
        """
        Scan DEX tokens van de watchlist.
        Watchlist formaat: [
            {'symbol': 'TOKEN', 'chain': 'solana', 'address': '...'},
            ...
        ]
        """
        if not self.dex_manager or not self._dex_watchlist:
            return []

        coins = []
        for token in self._dex_watchlist:
            chain = token.get('chain', 'solana')
            address = token.get('address', '')
            symbol = token.get('symbol', '')

            if not address:
                continue

            # Liquidity check
            liq = self.dex_manager.check_liquidity(chain, address)

            coin = {
                'symbol': symbol,
                'pair': f"{symbol}/USD",
                'source': f'dex_{chain}',
                'source_type': 'dex',
                'chain': chain,
                'address': address,
                'fee_pct': 0.3,  # Typische DEX fee
                'gas_cost': self.dex_manager.GAS_COSTS.get(chain, 1.0),
                'quote': 'USD',
                'liquidity_usd': liq.get('usd_liquidity', 0),
                'liquidity_safe': liq.get('safe', False),
            }
            coins.append(coin)

        logger.info(f"DEX watchlist scan: {len(coins)} tokens")
        return coins

    def scan_dex_trending(self, chain: str, min_liquidity: float = 50_000) -> List[dict]:
        """
        Scan trending tokens op een DEX chain.
        """
        if not self.dex_manager:
            return []

        trending = self.dex_manager.gecko.get_trending_pools(chain)
        if not trending:
            return []

        coins = []
        for pool in trending:
            if pool.get('liquidity_usd', 0) < min_liquidity:
                continue

            name = pool.get('name', '')
            symbol = name.split(' / ')[0] if ' / ' in name else name

            coin = {
                'symbol': symbol,
                'pair': f"{symbol}/USD",
                'source': f'dex_{chain}_trending',
                'source_type': 'dex',
                'chain': chain,
                'pool_address': pool.get('address', ''),
                'fee_pct': 0.3,
                'gas_cost': self.dex_manager.GAS_COSTS.get(chain, 1.0),
                'quote': 'USD',
                'liquidity_usd': pool.get('liquidity_usd', 0),
                'volume_24h': pool.get('volume_24h', 0),
            }
            coins.append(coin)

        logger.info(f"DEX trending scan {chain}: {len(coins)} tokens "
                     f"(min liq ${min_liquidity:,.0f})")
        return coins

    def scan_solana_auto(self,
                         min_liquidity: float = 100_000,
                         min_volume_24h: float = 50_000,
                         min_mcap: float = 1_000_000,
                         min_age_days: float = 14,
                         max_tokens: int = 50) -> List[dict]:
        """
        Automatische Solana token discovery via DexScreener.

        Vindt automatisch de top Solana coins, gefilterd op:
        - Liquidity >= $100K (bescherming tegen rug pulls)
        - Volume >= $50K/24h (actief gehandeld)
        - Market cap >= $1M (geen micro-cap scams)
        - Leeftijd >= 14 dagen (bewezen overleving)
        - Transacties >= 200/24h (echte activiteit)
        - Geen verdachte buy/sell ratio

        Returns: lijst van coin info dicts klaar voor de bot
        """
        if not self.dex_manager:
            logger.warning("DexManager niet beschikbaar voor Solana scan")
            return []

        # Gebruik DexScreener discovery
        tokens = self.dex_manager.screener.discover_solana_tokens(
            min_liquidity=min_liquidity,
            min_volume_24h=min_volume_24h,
            min_mcap=min_mcap,
            min_age_days=min_age_days,
            min_txns_24h=200,
            max_tokens=max_tokens,
        )

        # Converteer naar coin_scanner formaat
        coins = []
        for token in tokens:
            coin = {
                'symbol': token['symbol'],
                'pair': f"{token['symbol']}/USD",
                'source': 'dex_solana',
                'source_type': 'dex',
                'chain': 'solana',
                'address': token['address'],
                'fee_pct': 0.3,  # ~0.3% DEX fee
                'gas_cost': 0.01,  # Solana gas
                'quote': 'USD',
                'liquidity_usd': token['liquidity_usd'],
                'volume_24h': token['volume_24h'],
                'market_cap': token.get('market_cap', 0),
                'age_days': token.get('age_days', 0),
                'safety_score': token.get('safety_score', 0),
                'txns_24h': token.get('txns_24h', 0),
                'liquidity_safe': True,  # Al gefilterd
                'dex': token.get('dex', ''),
                'pair_address': token.get('pair_address', ''),
            }
            coins.append(coin)

        logger.info(f"Solana auto-scan: {len(coins)} veilige tokens gevonden")
        return coins

    # =========================================================================
    # DEX Watchlist Management
    # =========================================================================

    def add_to_dex_watchlist(self, symbol: str, chain: str, address: str):
        """Voeg token toe aan DEX watchlist."""
        # Check of al aanwezig
        for token in self._dex_watchlist:
            if token.get('address', '').lower() == address.lower():
                return

        self._dex_watchlist.append({
            'symbol': symbol.upper(),
            'chain': chain.lower(),
            'address': address,
            'added_at': time.strftime('%Y-%m-%d %H:%M'),
        })
        self._save_json(self._dex_watchlist_file, self._dex_watchlist)
        logger.info(f"DEX watchlist: {symbol} ({chain}) toegevoegd")

    def remove_from_dex_watchlist(self, address: str):
        """Verwijder token van DEX watchlist."""
        self._dex_watchlist = [
            t for t in self._dex_watchlist
            if t.get('address', '').lower() != address.lower()
        ]
        self._save_json(self._dex_watchlist_file, self._dex_watchlist)

    # =========================================================================
    # Unified Scanning
    # =========================================================================

    def scan_all(self, include_trending: bool = False,
                 include_solana_auto: bool = True) -> List[dict]:
        """
        Scan ALLE bronnen en return een gefilterde lijst van tradeable coins.

        Pipeline:
        1. Scan alle CEX exchanges (Kraken, MEXC)
        2. Scan DEX watchlist
        3. Automatische Solana token discovery (via DexScreener)
        4. Optioneel: scan DEX trending
        5. Deduplicatie (prefer CEX boven DEX, prefer lagere fees)
        6. Halal filter
        7. Return gesorteerde lijst
        """
        all_coins = []
        solana_count = 0

        # 1. CEX scanning
        cex_coins = self.scan_all_cex()
        all_coins.extend(cex_coins)

        # 2. DEX watchlist
        if self.enable_dex:
            dex_coins = self.scan_dex_watchlist()
            all_coins.extend(dex_coins)

        # 3. Automatische Solana discovery
        if include_solana_auto and self.enable_dex and 'solana' in self.dex_chains:
            solana_coins = self.scan_solana_auto()
            all_coins.extend(solana_coins)
            solana_count = len(solana_coins)

        # 4. DEX trending (optioneel, bovenop auto-scan)
        if include_trending and self.enable_dex:
            for chain in self.dex_chains:
                trending = self.scan_dex_trending(chain)
                all_coins.extend(trending)

        # 5. Deduplicatie
        all_coins = self._deduplicate(all_coins)

        # 6. Halal filter
        if self.enable_halal and self.halal_filter:
            all_coins = self._apply_halal_filter(all_coins)

        # 7. Sorteer op source priority
        source_priority = {'kraken': 0, 'mexc': 1, 'dex_solana': 2, 'dex_bsc': 3}
        all_coins.sort(key=lambda c: source_priority.get(c['source'], 99))

        logger.info(f"Scan complete: {len(all_coins)} tradeable coins "
                     f"(CEX: {len(cex_coins)}, Solana auto: {solana_count}, "
                     f"DEX watchlist: {len(self._dex_watchlist)})")

        return all_coins

    def _deduplicate(self, coins: List[dict]) -> List[dict]:
        """
        Dedupliceer coins die op meerdere exchanges staan.
        Prefer: lagere fee → hogere liquidity → CEX boven DEX
        """
        seen = {}
        for coin in coins:
            symbol = coin['symbol']
            if symbol in seen:
                existing = seen[symbol]
                # Prefer lagere fees
                if coin['fee_pct'] < existing['fee_pct']:
                    # Bewaar bestaande als alternatief
                    coin['alternatives'] = existing.get('alternatives', []) + [{
                        'source': existing['source'],
                        'pair': existing['pair'],
                        'fee_pct': existing['fee_pct'],
                    }]
                    seen[symbol] = coin
                else:
                    # Voeg als alternatief toe
                    existing.setdefault('alternatives', []).append({
                        'source': coin['source'],
                        'pair': coin['pair'],
                        'fee_pct': coin['fee_pct'],
                    })
            else:
                seen[symbol] = coin

        return list(seen.values())

    def _apply_halal_filter(self, coins: List[dict]) -> List[dict]:
        """Pas halal filter toe op coin lijst."""
        symbols = [c['symbol'] for c in coins]

        # Batch check (zonder API calls - alleen cache/whitelist)
        results = self.halal_filter.batch_check(symbols, use_api=False)

        filtered = []
        removed = 0
        for coin in coins:
            result = results.get(coin['symbol'], {})
            halal_status = result.get('halal')

            if halal_status is False:
                removed += 1
                logger.debug(f"Halal filter: {coin['symbol']} afgewezen - "
                             f"{result.get('reason', 'onbekend')}")
                continue

            # True of None (unknown) → toestaan
            coin['halal_status'] = halal_status
            coin['halal_reason'] = result.get('reason', '')
            filtered.append(coin)

        if removed > 0:
            logger.info(f"Halal filter: {removed} coins afgewezen, "
                         f"{len(filtered)} over")

        return filtered

    # =========================================================================
    # Candle Data Ophalen
    # =========================================================================

    def get_candles(self, coin: dict, interval: int = 240) -> Optional[List[dict]]:
        """
        Haal candle data op voor een coin, ongeacht de bron.

        Args:
            coin: Coin info dict (uit scan_all())
            interval: Candle interval in minuten (240 = 4H)

        Returns: Lijst van candle dicts in KrakenClient formaat
        """
        source_type = coin.get('source_type', 'cex')

        if source_type == 'cex':
            return self.exchange_manager.get_ohlc(
                coin['source'], coin['pair'], interval=interval
            )
        elif source_type == 'dex':
            chain = coin.get('chain', 'solana')
            address = coin.get('address', '')
            pool_address = coin.get('pool_address', '')

            if pool_address:
                return self.dex_manager.gecko.get_ohlc_by_pool(
                    chain, pool_address, interval
                )
            elif address:
                return self.dex_manager.get_ohlc(
                    chain, address, interval
                )

        logger.warning(f"Geen candle bron voor {coin.get('symbol')}")
        return None

    # =========================================================================
    # Order Execution
    # =========================================================================

    def place_buy(self, coin: dict, volume: float) -> Optional[str]:
        """
        Plaats een buy order voor een coin, ongeacht de bron.
        DEX orders worden nog niet ondersteund (TODO).
        """
        source_type = coin.get('source_type', 'cex')

        if source_type == 'cex':
            return self.exchange_manager.place_market_buy(
                coin['source'], coin['pair'], volume
            )
        elif source_type == 'dex':
            logger.warning(f"DEX orders nog niet ondersteund voor {coin['symbol']}")
            # TODO: Jupiter/PancakeSwap SDK integratie
            return None

        return None

    def place_sell(self, coin: dict, volume: float) -> Optional[str]:
        """Plaats een sell order."""
        source_type = coin.get('source_type', 'cex')

        if source_type == 'cex':
            return self.exchange_manager.place_market_sell(
                coin['source'], coin['pair'], volume
            )
        elif source_type == 'dex':
            logger.warning(f"DEX orders nog niet ondersteund voor {coin['symbol']}")
            return None

        return None

    # =========================================================================
    # Statistics & Info
    # =========================================================================

    def get_stats(self) -> dict:
        """Haal uitgebreide statistieken op."""
        stats = {
            'exchanges': {},
            'dex_chains': self.dex_chains,
            'dex_watchlist': len(self._dex_watchlist),
            'halal_enabled': self.enable_halal,
        }

        for name, client in self.exchange_manager.exchanges.items():
            pairs = client.get_tradeable_pairs()
            stats['exchanges'][name] = {
                'pairs': len(pairs),
                'fee_pct': client.fee_pct,
                'quote': client.get_quote_currency(),
            }

        if self.halal_filter:
            stats['halal'] = self.halal_filter.get_stats()

        return stats

    def print_overview(self):
        """Print een mooi overzicht van alle bronnen."""
        stats = self.get_stats()

        print(f"\n{'='*60}")
        print(f"  COIN SCANNER OVERZICHT")
        print(f"{'='*60}")

        total_coins = 0
        for name, info in stats['exchanges'].items():
            emoji = '🟢' if info['pairs'] > 0 else '🔴'
            print(f"  {emoji} {name.upper():10s} | {info['pairs']:>5d} pairs | "
                  f"fee: {info['fee_pct']}% | quote: {info['quote']}")
            total_coins += info['pairs']

        if stats['dex_watchlist'] > 0:
            print(f"  🟡 DEX         | {stats['dex_watchlist']:>5d} tokens | "
                  f"chains: {', '.join(stats['dex_chains'])}")
            total_coins += stats['dex_watchlist']

        print(f"  {'─'*56}")
        print(f"  TOTAAL:     {total_coins:>5d} coins")

        if stats.get('halal'):
            h = stats['halal']
            print(f"\n  HALAL FILTER:")
            print(f"    Whitelist: {h['hardcoded_whitelist']} + "
                  f"{h['custom_whitelist']} custom")
            print(f"    Blacklist categories: {h['blacklist_categories']}")
            print(f"    Cached coins: {h['cached_coins']}")
            print(f"    Review queue: {h['review_queue']}")

        print(f"{'='*60}\n")
