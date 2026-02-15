"""
Halal Filter - 3-Laags Halal Screening Systeem
-----------------------------------------------
Runtime halal check voor crypto tokens bij entry signaal.
Gebruikt CoinGecko API categories als primaire databron.

3-Laags Systeem:
  Laag 1: Categorie Blacklist (automatisch via CoinGecko)
  Laag 2: Hardcoded Whitelist (override voor bekende halal coins)
  Laag 3: Review Queue (onbekende coins loggen voor handmatige review)

Gebruik:
    halal = HalalFilter()

    # Check bij entry signaal
    result = halal.check('FET')
    if result['halal']:
        print("Halal - mag traden!")
    else:
        print(f"Haram: {result['reason']}")

    # Handmatig toevoegen aan whitelist/blacklist
    halal.add_to_whitelist('NEWCOIN', 'Handmatig goedgekeurd')
    halal.add_to_blacklist('BADCOIN', 'Rente-gebaseerd protocol')
"""
import json
import time
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger('trading_bot')

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache'
CACHE_DIR.mkdir(exist_ok=True)


class HalalFilter:
    """
    3-Laags Halal Screening Systeem.

    Flow bij check:
    1. Whitelist check → als gevonden: HALAL (skip verdere checks)
    2. Blacklist check → als gevonden: HARAM
    3. CoinGecko category check → als haram categorie: HARAM
    4. Niet gevonden / geen categorie → UNKNOWN (gelogd voor review)
    """

    # =========================================================================
    # LAAG 1: Categorie Blacklist (CoinGecko categories)
    # =========================================================================
    BLACKLIST_CATEGORIES = {
        # Riba (rente/interest)
        'lending-borrowing-earning': 'Lending/borrowing = riba (rente)',
        'liquid-staking-governance': 'Liquid staking = rente-achtig rendement',
        'liquid-staking-derivatives': 'Staking derivatives = rente-achtig',
        'yield-farming': 'Yield farming = rente-gebaseerd',
        'yield-aggregator': 'Yield aggregator = rente-gebaseerd',
        'ohm-fork': 'OHM forks = rebasing/rente-mechanisme',
        'rebase-tokens': 'Rebase tokens = inflatoir rente-mechanisme',

        # Gharar (overmatige onzekerheid/gokken)
        'gambling': 'Gokken = haram',
        'prediction-markets': 'Prediction markets = gokken',

        # Speculatief/derivaten
        'leveraged-tokens': 'Leveraged tokens = speculatief + rente',
        'derivatives': 'Derivaten = speculatief',
        'synthetic-assets': 'Synthetische assets = geen echte waarde',
        'options': 'Options = speculatief',
        'perpetuals': 'Perpetuals = leverage + rente',

        # Verzekering (gharar)
        'insurance': 'Verzekering = gharar (overmatige onzekerheid)',
        'decentralized-insurance': 'DeFi verzekering = gharar',

        # Meme tokens (optioneel, hoog risico / geen fundamentele waarde)
        'meme-token': 'Meme token = geen fundamentele waarde',

        # Staking specifiek (rente)
        'liquid-restaking-tokens': 'Restaking = rente-achtig',

        # Privacy coins die vaak voor haram doeleinden gebruikt worden
        # (niet per definitie haram, maar grijs gebied)
        # Niet in blacklist - laat kraken_client.py PAIR_MAP dit afhandelen
    }

    # =========================================================================
    # HARDCODED COIN BLACKLIST (bekende haram coins, geen API nodig)
    # =========================================================================
    BLACKLIST_COINS = {
        # Lending / Borrowing platforms (riba)
        'AAVE': 'Aave - lending/borrowing platform (riba)',
        'COMP': 'Compound - lending/borrowing platform (riba)',
        'MKR': 'MakerDAO - lending/stablecoin met rente (riba)',
        'DAI': 'DAI - door rente-gedekte stablecoin',
        'CREAM': 'Cream Finance - lending (riba)',
        'VENUS': 'Venus - BSC lending (riba)',
        'BENQI': 'BENQI - Avalanche lending (riba)',
        'MORPHO': 'Morpho - lending optimizer (riba)',
        'RADIANT': 'Radiant Capital - lending (riba)',
        'SPARK': 'Spark Protocol - lending (riba)',
        'FRAX': 'Frax - algoritmische stablecoin met rente',
        'LQTY': 'Liquity - borrowing protocol (riba)',
        'LUSD': 'LUSD - door rente-gedekte stablecoin',

        # Liquid Staking (rente-achtig)
        'LDO': 'Lido - liquid staking (rente-achtig)',
        'RPL': 'Rocket Pool - liquid staking (rente-achtig)',
        'SWISE': 'StakeWise - liquid staking (rente-achtig)',
        'ANKR_STAKE': 'Ankr Staking - liquid staking',
        'CBETH': 'Coinbase Staked ETH - liquid staking',
        'STETH': 'Lido Staked ETH - liquid staking',
        'RETH': 'Rocket Pool ETH - liquid staking',
        'MSOL': 'Marinade Staked SOL - liquid staking',

        # Yield / Farming (rente)
        'YFI': 'Yearn Finance - yield aggregator (riba)',
        'CVX': 'Convex Finance - yield booster (riba)',
        'CRV': 'Curve - stablecoin yield (riba)',
        'PENDLE': 'Pendle - yield trading (riba)',
        'BIFI': 'Beefy Finance - yield optimizer (riba)',
        'ALPHA': 'Alpha Finance - leveraged yield (riba)',
        'SPELL': 'Abracadabra - yield/lending (riba)',

        # Gambling / Prediction markets
        'ROLLBIT': 'Rollbit - crypto casino (gokken)',
        'FUN': 'FunToken - gambling (gokken)',
        'DICE': 'TrustDice - gambling (gokken)',
        'AZURO': 'Azuro - betting protocol (gokken)',
        'POLYMARKET': 'Polymarket - prediction market (gokken)',
        'GNO': 'Gnosis - prediction markets (gokken)',

        # Leveraged / Derivatives
        'DYDX': 'dYdX - perpetual derivaten',
        'GMX': 'GMX - perpetual derivaten',
        'SNX': 'Synthetix - synthetische assets',
        'GNS': 'Gains Network - leveraged trading',
        'PERP': 'Perpetual Protocol - perpetuals',
        'KWENTA': 'Kwenta - derivaten platform',

        # Insurance (gharar)
        'NXM': 'Nexus Mutual - DeFi insurance (gharar)',
        'COVER': 'Cover Protocol - DeFi insurance (gharar)',
        'INSUR': 'InsurAce - DeFi insurance (gharar)',

        # Rebase tokens
        'OHM': 'Olympus DAO - rebase/rente mechanisme',
        'TIME': 'Wonderland - OHM fork (rebase)',
        'KLIMA': 'KlimaDAO - OHM fork (rebase)',
        'AMPL': 'Ampleforth - rebase token',
    }

    # =========================================================================
    # LAAG 2: Hardcoded Whitelist (altijd halal, override alles)
    # =========================================================================
    WHITELIST = {
        # Top coins die per ongeluk in een blacklist-categorie kunnen vallen
        'BTC': 'Bitcoin - digitaal goud, halal bij consensus',
        'ETH': 'Ethereum - infrastructuur, halal bij consensus',
        'SOL': 'Solana - infrastructuur L1',
        'BNB': 'BNB Chain - infrastructuur L1',
        'XRP': 'Ripple - betalingsnetwerk',
        'ADA': 'Cardano - infrastructuur L1',
        'DOT': 'Polkadot - infrastructuur L0',
        'AVAX': 'Avalanche - infrastructuur L1',
        'ATOM': 'Cosmos - infrastructuur L0',
        'LINK': 'Chainlink - oracle netwerk',
        'NEAR': 'NEAR Protocol - infrastructuur L1',
        'ICP': 'Internet Computer - infrastructuur',
        'FIL': 'Filecoin - gedecentraliseerde opslag',
        'AR': 'Arweave - permanente opslag',
        'HBAR': 'Hedera - enterprise L1',
        'APT': 'Aptos - infrastructuur L1',
        'SUI': 'Sui - infrastructuur L1',
        'SEI': 'Sei - infrastructuur L1',
        'TON': 'TON - Telegram L1',
        'INJ': 'Injective - financiele L1',
        'TIA': 'Celestia - data availability',
        'FET': 'Fetch.ai - AI infrastructuur',
        'RENDER': 'Render - GPU compute',
        'TAO': 'Bittensor - AI netwerk',
        'GRT': 'The Graph - data indexing',
        'STORJ': 'Storj - opslag',
        'LTC': 'Litecoin - betalingen',
        'BCH': 'Bitcoin Cash - betalingen',
        'ETC': 'Ethereum Classic - infrastructuur',
        'VET': 'VeChain - supply chain',
        'ALGO': 'Algorand - infrastructuur L1',
        'XLM': 'Stellar - betalingsnetwerk',
        'MINA': 'Mina - privacy L1',
        'KAS': 'Kaspa - PoW L1',
        'STX': 'Stacks - Bitcoin L2',
        'ARB': 'Arbitrum - Ethereum L2',
        'OP': 'Optimism - Ethereum L2',
        'POL': 'Polygon - Ethereum L2',
        'PYTH': 'Pyth - oracle netwerk',
        'ENS': 'ENS - identiteit',
        'SAND': 'The Sandbox - metaverse/gaming',
        'MANA': 'Decentraland - metaverse',
        'AXS': 'Axie Infinity - gaming',
        'GALA': 'Gala Games - gaming',
        'IMX': 'Immutable X - gaming L2',
        'CHZ': 'Chiliz - sport/entertainment',
        'BAT': 'Basic Attention Token - reclame',
        'FLUX': 'Flux - compute',
        'HNT': 'Helium - IoT netwerk',
        'ANKR': 'Ankr - infra/compute',
        'JASMY': 'JasmyCoin - IoT/data',
        'WLD': 'Worldcoin - identiteit',
        'RUNE': 'THORChain - cross-chain swap',
        'UNI': 'Uniswap - DEX governance',
        'JUP': 'Jupiter - DEX aggregator',
        'RAY': 'Raydium - DEX',
        'ORCA': 'Orca - DEX',

        # Coins uit bestaande Kraken PAIR_MAP (al gescreend)
        'ZEUS': 'Zeus Network - cross-chain bridge (grootste winner!)',
        'EIGEN': 'EigenLayer - restaking infra',
        'VIRTUAL': 'Virtual Protocol - AI agents',
        'ARKM': 'Arkham - blockchain intelligence',
        'TRAC': 'OriginTrail - supply chain',
        'GRASS': 'Grass - data netwerk',
        'OCEAN': 'Ocean Protocol - data marktplaats',
    }

    # =========================================================================
    # CoinGecko API
    # =========================================================================

    COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, cache_ttl: int = 86400):
        """
        Args:
            cache_ttl: Cache duur in seconden (default 24 uur)
        """
        self.cache_ttl = cache_ttl

        # Runtime caches
        self._category_cache: Dict[str, dict] = {}  # symbol → category data
        self._coin_id_cache: Dict[str, str] = {}     # symbol → coingecko coin id
        self._review_queue: List[dict] = []

        # Persistente bestanden
        self._custom_whitelist_file = BASE_DIR / 'halal_whitelist.json'
        self._custom_blacklist_file = BASE_DIR / 'halal_blacklist.json'
        self._review_file = BASE_DIR / 'halal_review_queue.json'
        self._cache_file = CACHE_DIR / 'halal_category_cache.json'
        self._coin_list_file = CACHE_DIR / 'coingecko_coin_list.json'

        # Laad custom lijsten
        self._custom_whitelist = self._load_json(self._custom_whitelist_file, {})
        self._custom_blacklist = self._load_json(self._custom_blacklist_file, {})
        self._review_queue = self._load_json(self._review_file, [])
        self._load_category_cache()
        self._load_coin_list()

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

    def _load_category_cache(self):
        if self._cache_file.exists():
            try:
                with open(self._cache_file, 'r') as f:
                    data = json.load(f)
                now = time.time()
                self._category_cache = {
                    k: v for k, v in data.items()
                    if now - v.get('cached_at', 0) < self.cache_ttl
                }
            except Exception:
                self._category_cache = {}

    def _save_category_cache(self):
        self._save_json(self._cache_file, self._category_cache)

    def _load_coin_list(self):
        """Laad CoinGecko coin list (symbol → id mapping)."""
        if self._coin_list_file.exists():
            try:
                with open(self._coin_list_file, 'r') as f:
                    data = json.load(f)
                    if time.time() - data.get('_cached_at', 0) < 604800:  # 7 dagen
                        self._coin_id_cache = data.get('coins', {})
                        return
            except Exception:
                pass
        # Cache verlopen of niet gevonden → wordt later gevuld
        self._coin_id_cache = {}

    def _fetch_coin_list(self):
        """Haal CoinGecko coin list op (symbol → id mapping)."""
        import requests
        try:
            resp = requests.get(
                f"{self.COINGECKO_BASE_URL}/coins/list",
                timeout=30
            )
            if resp.status_code == 200:
                coins = resp.json()
                mapping = {}
                for coin in coins:
                    sym = coin.get('symbol', '').upper()
                    coin_id = coin.get('id', '')
                    # Prefer coins met hogere market cap (first seen = usually biggest)
                    if sym not in mapping:
                        mapping[sym] = coin_id
                self._coin_id_cache = mapping
                self._save_json(self._coin_list_file, {
                    'coins': mapping,
                    '_cached_at': time.time(),
                })
                logger.info(f"CoinGecko coin list geladen: {len(mapping)} coins")
            elif resp.status_code == 429:
                logger.warning("CoinGecko rate limit - gebruik cached data")
            else:
                logger.error(f"CoinGecko coin list error: {resp.status_code}")
        except Exception as e:
            logger.error(f"CoinGecko coin list error: {e}")

    def _get_coin_id(self, symbol: str) -> Optional[str]:
        """Vertaal symbol naar CoinGecko coin ID."""
        symbol = symbol.upper()
        if not self._coin_id_cache:
            self._fetch_coin_list()
        return self._coin_id_cache.get(symbol)

    def _fetch_categories(self, symbol: str) -> Optional[List[str]]:
        """Haal CoinGecko categories op voor een coin."""
        import requests

        coin_id = self._get_coin_id(symbol)
        if not coin_id:
            logger.debug(f"CoinGecko coin ID niet gevonden voor {symbol}")
            return None

        try:
            # Rate limit: free tier = 10-30 calls/min
            time.sleep(3)

            resp = requests.get(
                f"{self.COINGECKO_BASE_URL}/coins/{coin_id}",
                params={
                    'localization': 'false',
                    'tickers': 'false',
                    'market_data': 'false',
                    'community_data': 'false',
                    'developer_data': 'false',
                },
                timeout=15
            )

            if resp.status_code == 200:
                data = resp.json()
                categories = data.get('categories', [])
                # Filter None en lege strings
                categories = [c for c in categories if c]
                return categories
            elif resp.status_code == 429:
                logger.warning(f"CoinGecko rate limit voor {symbol}")
                return None
            else:
                logger.debug(f"CoinGecko error {resp.status_code} voor {symbol}")
                return None
        except Exception as e:
            logger.error(f"CoinGecko categories error voor {symbol}: {e}")
            return None

    # =========================================================================
    # Main Check Method
    # =========================================================================

    def check(self, symbol: str, use_api: bool = True) -> dict:
        """
        Check of een coin halal is.

        Args:
            symbol: Token symbol (bijv. 'FET', 'BTC')
            use_api: Of CoinGecko API gebruikt mag worden (voor rate limiting)

        Returns: {
            'halal': bool | None,   # True=halal, False=haram, None=unknown
            'symbol': str,
            'reason': str,
            'source': str,          # 'whitelist', 'blacklist', 'category', 'unknown'
            'categories': list,     # CoinGecko categories (als beschikbaar)
        }
        """
        symbol = symbol.upper().strip()

        # LAAG 2: Whitelist check (override alles)
        if symbol in self.WHITELIST:
            return {
                'halal': True,
                'symbol': symbol,
                'reason': self.WHITELIST[symbol],
                'source': 'whitelist',
                'categories': [],
            }

        if symbol in self._custom_whitelist:
            return {
                'halal': True,
                'symbol': symbol,
                'reason': self._custom_whitelist[symbol],
                'source': 'custom_whitelist',
                'categories': [],
            }

        # Hardcoded coin blacklist check
        if symbol in self.BLACKLIST_COINS:
            return {
                'halal': False,
                'symbol': symbol,
                'reason': self.BLACKLIST_COINS[symbol],
                'source': 'blacklist_coins',
                'categories': [],
            }

        # Custom blacklist check
        if symbol in self._custom_blacklist:
            return {
                'halal': False,
                'symbol': symbol,
                'reason': self._custom_blacklist[symbol],
                'source': 'custom_blacklist',
                'categories': [],
            }

        # LAAG 1: Category check (cache of API)
        if symbol in self._category_cache:
            cached = self._category_cache[symbol]
            return self._evaluate_categories(symbol, cached.get('categories', []))

        if use_api:
            categories = self._fetch_categories(symbol)
            if categories is not None:
                # Cache resultaat
                self._category_cache[symbol] = {
                    'categories': categories,
                    'cached_at': time.time(),
                }
                self._save_category_cache()
                return self._evaluate_categories(symbol, categories)

        # LAAG 3: Unknown → review queue
        self._add_to_review(symbol)
        return {
            'halal': None,
            'symbol': symbol,
            'reason': 'Onbekend - toegevoegd aan review queue',
            'source': 'unknown',
            'categories': [],
        }

    def _evaluate_categories(self, symbol: str, categories: List[str]) -> dict:
        """Evalueer CoinGecko categories tegen blacklist."""
        # Normaliseer category namen (lowercase, strip)
        cat_normalized = {c.lower().replace(' ', '-'): c for c in categories}

        for blacklist_cat, reason in self.BLACKLIST_CATEGORIES.items():
            for norm_cat, orig_cat in cat_normalized.items():
                # Fuzzy match: check of blacklist term in de category naam zit
                if (blacklist_cat in norm_cat or
                    norm_cat in blacklist_cat or
                    # Check voor deelwoorden
                    any(word in norm_cat for word in blacklist_cat.split('-')
                        if len(word) > 3)):

                    # Maar check of het niet op de whitelist staat
                    if symbol.upper() in self.WHITELIST:
                        continue

                    return {
                        'halal': False,
                        'symbol': symbol,
                        'reason': f"{reason} (categorie: {orig_cat})",
                        'source': 'category',
                        'categories': categories,
                    }

        # Geen blacklisted categories gevonden → halal
        return {
            'halal': True,
            'symbol': symbol,
            'reason': f"Geen haram categories gevonden ({len(categories)} categories gecontroleerd)",
            'source': 'category',
            'categories': categories,
        }

    def _add_to_review(self, symbol: str):
        """Voeg coin toe aan review queue (als nog niet aanwezig)."""
        existing = {r['symbol'] for r in self._review_queue}
        if symbol not in existing:
            self._review_queue.append({
                'symbol': symbol,
                'added_at': time.time(),
                'added_date': time.strftime('%Y-%m-%d %H:%M'),
            })
            self._save_json(self._review_file, self._review_queue)
            logger.info(f"Halal review queue: {symbol} toegevoegd")

    # =========================================================================
    # Management Methods
    # =========================================================================

    def add_to_whitelist(self, symbol: str, reason: str = ''):
        """Voeg coin toe aan custom whitelist."""
        symbol = symbol.upper()
        self._custom_whitelist[symbol] = reason or 'Handmatig goedgekeurd'
        self._save_json(self._custom_whitelist_file, self._custom_whitelist)

        # Verwijder uit review queue
        self._review_queue = [r for r in self._review_queue if r['symbol'] != symbol]
        self._save_json(self._review_file, self._review_queue)

        logger.info(f"Whitelist: {symbol} toegevoegd - {reason}")

    def add_to_blacklist(self, symbol: str, reason: str = ''):
        """Voeg coin toe aan custom blacklist."""
        symbol = symbol.upper()
        self._custom_blacklist[symbol] = reason or 'Handmatig afgewezen'
        self._save_json(self._custom_blacklist_file, self._custom_blacklist)

        # Verwijder uit review queue
        self._review_queue = [r for r in self._review_queue if r['symbol'] != symbol]
        self._save_json(self._review_file, self._review_queue)

        logger.info(f"Blacklist: {symbol} toegevoegd - {reason}")

    def get_review_queue(self) -> List[dict]:
        """Haal review queue op."""
        return self._review_queue

    def get_stats(self) -> dict:
        """Haal statistieken op."""
        return {
            'hardcoded_whitelist': len(self.WHITELIST),
            'custom_whitelist': len(self._custom_whitelist),
            'custom_blacklist': len(self._custom_blacklist),
            'blacklist_categories': len(self.BLACKLIST_CATEGORIES),
            'cached_coins': len(self._category_cache),
            'review_queue': len(self._review_queue),
            'coin_id_cache': len(self._coin_id_cache),
        }

    def batch_check(self, symbols: List[str],
                    use_api: bool = True,
                    skip_known: bool = True) -> Dict[str, dict]:
        """
        Batch check meerdere coins.
        Handig voor het pre-screenen van een hele exchange.

        Args:
            symbols: Lijst van symbols om te checken
            use_api: Of CoinGecko API gebruikt mag worden
            skip_known: Skip coins die al in cache/whitelist/blacklist staan

        Returns: dict van symbol → check result
        """
        results = {}
        api_calls = 0

        for symbol in symbols:
            symbol = symbol.upper()

            # Skip als al bekend
            if skip_known:
                if symbol in self.WHITELIST or symbol in self._custom_whitelist:
                    results[symbol] = self.check(symbol, use_api=False)
                    continue
                if symbol in self._custom_blacklist:
                    results[symbol] = self.check(symbol, use_api=False)
                    continue
                if symbol in self._category_cache:
                    results[symbol] = self.check(symbol, use_api=False)
                    continue

            if use_api and api_calls < 25:  # Max 25 API calls per batch
                results[symbol] = self.check(symbol, use_api=True)
                api_calls += 1
            else:
                results[symbol] = self.check(symbol, use_api=False)

        # Statistieken
        halal_count = sum(1 for r in results.values() if r['halal'] is True)
        haram_count = sum(1 for r in results.values() if r['halal'] is False)
        unknown_count = sum(1 for r in results.values() if r['halal'] is None)

        logger.info(f"Batch check: {len(symbols)} coins → "
                     f"{halal_count} halal, {haram_count} haram, {unknown_count} unknown "
                     f"({api_calls} API calls)")

        return results

    def filter_pairs(self, pairs: List[str]) -> List[str]:
        """
        Filter een lijst van trading pairs en return alleen halal pairs.
        Pairs formaat: 'SYMBOL/QUOTE' (bijv. 'FET/USD', 'BTC/USDT')
        """
        halal_pairs = []
        for pair in pairs:
            symbol = pair.split('/')[0]
            result = self.check(symbol, use_api=False)  # Alleen cache/whitelist
            if result['halal'] is True:
                halal_pairs.append(pair)
            elif result['halal'] is False:
                logger.debug(f"Halal filter: {pair} afgewezen - {result['reason']}")
            # None (unknown) → ook toestaan (voorzichtigheids principe)
            # Liever een onbekende coin traden dan een goede kans missen
            elif result['halal'] is None:
                halal_pairs.append(pair)

        logger.info(f"Halal filter: {len(pairs)} → {len(halal_pairs)} pairs "
                     f"({len(pairs) - len(halal_pairs)} afgewezen)")
        return halal_pairs
