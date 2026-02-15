"""
Kraken API Client
-----------------
Veilige wrapper rond de Kraken API voor trading operations.
Ondersteunt: saldo opvragen, orders plaatsen, OHLC data ophalen,
en dynamische coin discovery via AssetPairs endpoint.
"""
import krakenex
import time
import logging
from typing import Optional, Dict, List

logger = logging.getLogger('trading_bot')


class KrakenClient:
    """Wrapper voor Kraken API met rate limiting en error handling."""

    # Kraken pair mapping (ticker → Kraken pair name)
    # 290 halal-friendly coins - geen lending, yield, stablecoins, memecoins
    PAIR_MAP = {
        # ===== AI & Compute (33) =====
        'FET/USD': 'FETUSD',
        'TAO/USD': 'TAOUSD',
        'RENDER/USD': 'RENDERUSD',
        'NEAR/USD': 'NEARUSD',
        'VIRTUAL/USD': 'VIRTUALUSD',
        'ARKM/USD': 'ARKMUSD',
        'EIGEN/USD': 'EIGENUSD',
        'TRAC/USD': 'TRACUSD',
        'GRT/USD': 'GRTUSD',
        'ZG/USD': '0GUSD',
        'AI16Z/USD': 'AI16ZUSD',
        'AI3/USD': 'AI3USD',
        'AIO/USD': 'AIOUSD',
        'AIOZ/USD': 'AIOZUSD',
        'AIXBT/USD': 'AIXBTUSD',
        'AKT/USD': 'AKTUSD',
        'ATH/USD': 'ATHUSD',
        'AVAAI/USD': 'AVAAIUSD',
        'BLUAI/USD': 'BLUAIUSD',
        'ELIZAOS/USD': 'ELIZAOSUSD',
        'FHE/USD': 'FHEUSD',
        'FLOCK/USD': 'FLOCKUSD',
        'GAIA/USD': 'GAIAUSD',
        'GAIB/USD': 'GAIBUSD',
        'GRASS/USD': 'GRASSUSD',
        'GRIFFAIN/USD': 'GRIFFAINUSD',
        'IAG/USD': 'IAGUSD',
        'KGEN/USD': 'KGENUSD',
        'NMR/USD': 'NMRUSD',
        'NOS/USD': 'NOSUSD',
        'OCEAN/USD': 'OCEANUSD',
        'PRIME/USD': 'PRIMEUSD',
        'PROMPT/USD': 'PROMPTUSD',
        'SAHARA/USD': 'SAHARAUSD',
        'SOGNI/USD': 'SOGNIUSD',
        'SWARMS/USD': 'SWARMSUSD',
        'UAI/USD': 'UAIUSD',
        'ZAMA/USD': 'ZAMAUSD',
        # ===== Infrastructure / L1 / L2 (95) =====
        'SOL/USD': 'SOLUSD',
        'DOT/USD': 'DOTUSD',
        'ATOM/USD': 'ATOMUSD',
        'AVAX/USD': 'AVAXUSD',
        'ADA/USD': 'ADAUSD',
        'BNB/USD': 'BNBUSD',
        'XRP/USD': 'XXRPZUSD',
        'XLM/USD': 'XXLMZUSD',
        'ALGO/USD': 'ALGOUSD',
        'HBAR/USD': 'HBARUSD',
        'ICP/USD': 'ICPUSD',
        'APT/USD': 'APTUSD',
        'SUI/USD': 'SUIUSD',
        'SEI/USD': 'SEIUSD',
        'TIA/USD': 'TIAUSD',
        'INJ/USD': 'INJUSD',
        'TON/USD': 'TONUSD',
        'KAS/USD': 'KASUSD',
        'EGLD/USD': 'EGLDUSD',
        'MINA/USD': 'MINAUSD',
        'CELO/USD': 'CELOUSD',
        'ETC/USD': 'XETCZUSD',
        'BCH/USD': 'BCHUSD',
        'LTC/USD': 'XLTCZUSD',
        'FLOW/USD': 'FLOWUSD',
        'TRX/USD': 'TRXUSD',
        'KAVA/USD': 'KAVAUSD',
        'FLR/USD': 'FLRUSD',
        'ASTR/USD': 'ASTRUSD',
        'GLMR/USD': 'GLMRUSD',
        'MOVR/USD': 'MOVRUSD',
        'KSM/USD': 'KSMUSD',
        'ARB/USD': 'ARBUSD',
        'OP/USD': 'OPUSD',
        'POL/USD': 'POLUSD',
        'STRK/USD': 'STRKUSD',
        'ZK/USD': 'ZKUSD',
        'LINEA/USD': 'LINEAUSD',
        'STX/USD': 'STXUSD',
        'MNT/USD': 'MNTUSD',
        'METIS/USD': 'METISUSD',
        'DYM/USD': 'DYMUSD',
        'BOBA/USD': 'BOBAUSD',
        'IMX/USD': 'IMXUSD',
        'LRC/USD': 'LRCUSD',
        'ZETA/USD': 'ZETAUSD',
        'BERA/USD': 'BERAUSD',
        'SONIC/USD': 'SONICUSD',
        'S/USD': 'SUSD',
        'OMNI/USD': 'OMNIUSD',
        'NTRN/USD': 'NTRNUSD',
        'CFX/USD': 'CFXUSD',
        'QTUM/USD': 'QTUMUSD',
        'ICX/USD': 'ICXUSD',
        'JUNO/USD': 'JUNOUSD',
        'OSMO/USD': 'OSMOUSD',
        'SAGA/USD': 'SAGAUSD',
        'LSK/USD': 'LSKUSD',
        'ACA/USD': 'ACAUSD',
        'SDN/USD': 'SDNUSD',
        'CLV/USD': 'CLVUSD',
        'BLZ/USD': 'BLZUSD',
        'CELR/USD': 'CELRUSD',
        'QNT/USD': 'QNTUSD',
        'B2/USD': 'B2USD',
        'B3/USD': 'B3USD',
        'BOB/USD': 'BOBUSD',
        'CORN/USD': 'CORNUSD',
        'ALEO/USD': 'ALEOUSD',
        'MOVE/USD': 'MOVEUSD',
        'INIT/USD': 'INITUSD',
        'IP/USD': 'IPUSD',
        'XDC/USD': 'XDCUSD',
        'DASH/USD': 'DASHUSD',
        'NANO/USD': 'NANOUSD',
        'XTZ/USD': 'XTZUSD',
        'ZRC/USD': 'ZRCUSD',
        'VET/USD': 'VETUSD',
        'VTHO/USD': 'VTHOUSD',
        'MXC/USD': 'MXCUSD',
        'COTI/USD': 'COTIUSD',
        'CHR/USD': 'CHRUSD',
        'EWT/USD': 'EWTUSD',
        'DAG/USD': 'DAGUSD',
        'MERL/USD': 'MERLUSD',
        'OBOL/USD': 'OBOLUSD',
        'CCD/USD': 'CCDUSD',
        'U2U/USD': 'U2UUSD',
        'LAYER/USD': 'LAYERUSD',
        'TANSSI/USD': 'TANSSIUSD',
        'SOON/USD': 'SOONUSD',
        'XION/USD': 'XIONUSD',
        'ALT/USD': 'ALTUSD',
        'ANLOG/USD': 'ANLOGUSD',
        'T/USD': 'TUSD',
        'POND/USD': 'PONDUSD',
        # ===== DePIN (33) =====
        'FIL/USD': 'FILUSD',
        'HNT/USD': 'HNTUSD',
        'AR/USD': 'ARUSD',
        'STORJ/USD': 'STORJUSD',
        'SC/USD': 'SCUSD',
        'FLUX/USD': 'FLUXUSD',
        'ANKR/USD': 'ANKRUSD',
        'POWR/USD': 'POWRUSD',
        'LPT/USD': 'LPTUSD',
        'DENT/USD': 'DENTUSD',
        'BTT/USD': 'BTTUSD',
        'PHA/USD': 'PHAUSD',
        'RLC/USD': 'RLCUSD',
        'NODL/USD': 'NODLUSD',
        'PEAQ/USD': 'PEAQUSD',
        'NODE/USD': 'NODEUSD',
        'XRT/USD': 'XRTUSD',
        'LMWR/USD': 'LMWRUSD',
        'SENT/USD': 'SENTUSD',
        'ALTHEA/USD': 'ALTHEAUSD',
        'PIPE/USD': 'PIPEUSD',
        'CLOUD/USD': 'CLOUDUSD',
        'NYM/USD': 'NYMUSD',
        'BLESS/USD': 'BLESSUSD',
        'TEA/USD': 'TEAUSD',
        'BDX/USD': 'BDXUSD',
        'SPACE/USD': 'SPACEUSD',
        'DMC/USD': 'DMCUSD',
        'LAVA/USD': 'LAVAUSD',
        'RIVER/USD': 'RIVERUSD',
        'SXT/USD': 'SXTUSD',
        'EDGE/USD': 'EDGEUSD',
        'IR/USD': 'IRUSD',
        # ===== Data / Oracle / Indexing (12) =====
        'LINK/USD': 'LINKUSD',
        'BAND/USD': 'BANDUSD',
        'API3/USD': 'API3USD',
        'PYTH/USD': 'PYTHUSD',
        'CQT/USD': 'CQTUSD',
        'UMA/USD': 'UMAUSD',
        'XYO/USD': 'XYOUSD',
        'CARV/USD': 'CARVUSD',
        'SCA/USD': 'SCAUSD',
        # ===== DeFi swap-only (28) =====
        'RUNE/USD': 'RUNEUSD',
        'UNI/USD': 'UNIUSD',
        'SUSHI/USD': 'SUSHIUSD',
        '1INCH/USD': '1INCHUSD',
        'JUP/USD': 'JUPUSD',
        'RAY/USD': 'RAYUSD',
        'ORCA/USD': 'ORCAUSD',
        'JOE/USD': 'JOEUSD',
        'ZRX/USD': 'ZRXUSD',
        'COW/USD': 'COWUSD',
        'BAL/USD': 'BALUSD',
        'KNC/USD': 'KNCUSD',
        'VELODROME/USD': 'VELODROMEUSD',
        'AERO/USD': 'AEROUSD',
        'IDEX/USD': 'IDEXUSD',
        'SAROS/USD': 'SAROSUSD',
        'ORDER/USD': 'ORDERUSD',
        'VOOI/USD': 'VOOIUSD',
        'ODOS/USD': 'ODOSUSD',
        'ENSO/USD': 'ENSOUSD',
        'SAFE/USD': 'SAFEUSD',
        'CAKE/USD': 'CAKEUSD',
        'HFT/USD': 'HFTUSD',
        'DEEP/USD': 'DEEPUSD',
        'ELX/USD': 'ELXUSD',
        'ACX/USD': 'ACXUSD',
        'HDX/USD': 'HDXUSD',
        'RBC/USD': 'RBCUSD',
        # ===== Gaming / Metaverse / NFT (25) =====
        'AXS/USD': 'AXSUSD',
        'SAND/USD': 'SANDUSD',
        'MANA/USD': 'MANAUSD',
        'GALA/USD': 'GALAUSD',
        'ENJ/USD': 'ENJUSD',
        'ALICE/USD': 'ALICEUSD',
        'YGG/USD': 'YGGUSD',
        'BIGTIME/USD': 'BIGTIMEUSD',
        'SUPER/USD': 'SUPERUSD',
        'PORTAL/USD': 'PORTALUSD',
        'TLM/USD': 'TLMUSD',
        'PDA/USD': 'PDAUSD',
        'BEAM/USD': 'BEAMUSD',
        'ATLAS/USD': 'ATLASUSD',
        'CHZ/USD': 'CHZUSD',
        'TVK/USD': 'TVKUSD',
        'POLIS/USD': 'POLISUSD',
        'MV/USD': 'MVUSD',
        'GMT/USD': 'GMTUSD',
        'GAME2/USD': 'GAME2USD',
        'MON/USD': 'MONUSD',
        'VANRY/USD': 'VANRYUSD',
        'NIL/USD': 'NILUSD',
        'PLAY/USD': 'PLAYUSD',
        'ESPORTS/USD': 'ESPORTSUSD',
        # ===== Identity / Social (10) =====
        'ENS/USD': 'ENSUSD',
        'WLD/USD': 'WLDUSD',
        'LIT/USD': 'LITUSD',
        'MASK/USD': 'MASKUSD',
        'CYBER/USD': 'CYBERUSD',
        'UXLINK/USD': 'UXLINKUSD',
        'MOCA/USD': 'MOCAUSD',
        'SAPIEN/USD': 'SAPIENUSD',
        'KAITO/USD': 'KAITOUSD',
        'BIO/USD': 'BIOUSD',
        # ===== Cross-Chain / Bridge (10) =====
        'W/USD': 'WUSD',
        'ZRO/USD': 'ZROUSD',
        'STG/USD': 'STGUSD',
        'SYN/USD': 'SYNUSD',
        'BICO/USD': 'BICOUSD',
        'SSV/USD': 'SSVUSD',
        'WCT/USD': 'WCTUSD',
        'PARTI/USD': 'PARTIUSD',
        'ZEUS/USD': 'ZEUSUSD',
        # ===== Other Utility (35) =====
        'BAT/USD': 'BATUSD',
        'JASMY/USD': 'JASMYUSD',
        'EDU/USD': 'EDUUSD',
        'ACH/USD': 'ACHUSD',
        'TEL/USD': 'TELUSD',
        'CRO/USD': 'CROUSD',
        'HOLO/USD': 'HOLOUSD',
        'ADX/USD': 'ADXUSD',
        'OXT/USD': 'OXTUSD',
        'CTSI/USD': 'CTSIUSD',
        'GTC/USD': 'GTCUSD',
        'RAD/USD': 'RADUSD',
        'AUDIO/USD': 'AUDIOUSD',
        'LCX/USD': 'LCXUSD',
        'CVC/USD': 'CVCUSD',
        'ARPA/USD': 'ARPAUSD',
        'FORTH/USD': 'FORTHUSD',
        'TOKEN/USD': 'TOKENUSD',
        'OPEN/USD': 'OPENUSD',
        'INX/USD': 'INXUSD',
        'C98/USD': 'C98USD',
        'SWEAT/USD': 'SWEATUSD',
        'KIN/USD': 'KINUSD',
        'GUN/USD': 'GUNUSD',
        'HONEY/USD': 'HONEYUSD',
        'PRO/USD': 'PROUSD',
        'ZBCN/USD': 'ZBCNUSD',
        'ME/USD': 'MEUSD',
        'TNSR/USD': 'TNSRUSD',
        'ZORA/USD': 'ZORAUSD',
        'WOO/USD': 'WOOUSD',
        'FIDA/USD': 'FIDAUSD',
        'RARI/USD': 'RARIUSD',
        'RSC/USD': 'RSCUSD',
        # ===== Privacy - grey zone (8) =====
        'SCRT/USD': 'SCRTUSD',
        'BDXN/USD': 'BDXNUSD',
        'ANON/USD': 'ANONUSD',
        'TEER/USD': 'TEERUSD',
        'AZTEC/USD': 'AZTECUSD',
        # ===== Legacy =====
        'BTC/USD': 'XXBTZUSD',
        'ETH/USD': 'XETHZUSD',
    }

    def __init__(self, api_key: str, private_key: str):
        self.api = krakenex.API()
        self.api.key = api_key
        self.api.secret = private_key
        self._last_request_time = 0
        self._min_interval = 1.0  # Minimum 1 sec between requests

    def _rate_limit(self):
        """Voorkom rate limiting door minimale interval te respecteren."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _query_public(self, method: str, params: dict = None) -> dict:
        """Public API call met error handling."""
        self._rate_limit()
        try:
            result = self.api.query_public(method, params or {})
            if result.get('error') and len(result['error']) > 0:
                logger.error(f"Kraken API error ({method}): {result['error']}")
                return None
            return result.get('result', {})
        except Exception as e:
            logger.error(f"Kraken API exception ({method}): {e}")
            return None

    def _query_private(self, method: str, params: dict = None) -> dict:
        """Private API call met error handling."""
        self._rate_limit()
        try:
            result = self.api.query_private(method, params or {})
            if result.get('error') and len(result['error']) > 0:
                logger.error(f"Kraken API error ({method}): {result['error']}")
                return None
            return result.get('result', {})
        except Exception as e:
            logger.error(f"Kraken API exception ({method}): {e}")
            return None

    def get_kraken_pair(self, pair: str) -> str:
        """Converteer onze pair naam naar Kraken's pair naam."""
        # Eerst checken in hardcoded map (snelst)
        if pair in self.PAIR_MAP:
            return self.PAIR_MAP[pair]
        # Dan in dynamische discovery cache
        if self._discovery_cache and pair in self._discovery_cache:
            return self._discovery_cache[pair]
        # Fallback: simpele string replace
        return pair.replace('/', '')

    # === DYNAMIC DISCOVERY ===

    # Stablecoins, wrapped tokens, yield tokens die we NOOIT willen traden
    _EXCLUDED_BASES = {
        # Stablecoins & fiat
        'USDT', 'USDC', 'DAI', 'TUSD', 'BUSD', 'GUSD', 'PAX', 'USDP',
        'FRAX', 'LUSD', 'SUSD', 'UST', 'PYUSD', 'FDUSD', 'EURC', 'EURT',
        'USD1', 'USDD', 'USDE', 'USDG', 'USDQ', 'USDR', 'USDS', 'USDUC',
        'RLUSD', 'AUSD',
        # Fiat currencies
        'EUR', 'GBP', 'AUD', 'CAD', 'JPY', 'CHF', 'NZD',
        'EURQ', 'EURR', 'EUROP', 'TGBP', 'AUDX',
        # Wrapped / pegged / liquid staked
        'WBTC', 'WETH', 'STETH', 'RETH', 'CBETH', 'WSTETH', 'MSOL',
        'JITOSOL', 'BNSOL', 'CMETH', 'METH', 'LSETH', 'LSSOL', 'TBTC',
        'WAXL',
        # Yield / lending / staking tokens (haram)
        'AAVE', 'COMP', 'MKR', 'CRV', 'CVX', 'YFI', 'LIDO', 'RPL',
        'MORPHO', 'ENA', 'ETHFI', 'PENDLE', 'ONDO', 'SPX', 'PAXG',
        'LDO', 'LQTY', 'SPELL', 'ALCX', 'FXS', 'CPOOL', 'BADGER',
        'FARM', 'SWELL', 'PUFFER', 'USUAL', 'SNX',
        # Memecoins
        'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'BRETT', 'NEIRO',
        'TRUMP', 'MELANIA', 'POPCAT', 'MEW', 'PONKE', 'TURBO', 'BABYDOGE',
        'COQ', 'MYRO', 'SLERF', 'BOME', 'MAGA',
        'FARTCOIN', 'RETARDIO', 'TITCOIN', 'BODEN', 'TREMP', 'USELESS',
        'CHEEMS', 'DOGS', 'DOG', 'FWOG', 'GOAT', 'GIGA', 'MOODENG',
        'PNUT', 'PENGU', 'SNEK', 'MOG', 'HIPPO', 'ZEREBRO', 'SUNDOG',
        'HPOS10I', 'APU', 'CAT', 'MICHI', 'TOSHI', 'DEGEN', 'BILLY',
        'GHIBLI',
        # Gambling / casino
        'ROLLBIT', 'FUN', 'WINR',
    }

    _discovery_cache: Optional[Dict[str, str]] = None
    _discovery_cache_time: float = 0
    _DISCOVERY_CACHE_TTL: float = 3600  # 1 uur cache

    def discover_all_usd_pairs(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Haal ALLE actieve USD spot pairs op van Kraken via AssetPairs API.

        Returns: dict mapping 'BASE/USD' → 'KRAKENNAME'
        Voorbeeld: {'FET/USD': 'FETUSD', 'XRP/USD': 'XXRPZUSD', ...}

        Resultaten worden 1 uur gecached. Gefilterd op:
        - Alleen USD quote currency
        - Alleen spot pairs (geen futures/margin)
        - Exclusie van stablecoins, wrapped, yield, memecoins
        """
        now = time.time()
        if (not force_refresh
                and self._discovery_cache is not None
                and (now - self._discovery_cache_time) < self._DISCOVERY_CACHE_TTL):
            return self._discovery_cache

        logger.info("Kraken: discovering all USD pairs via AssetPairs API...")
        result = self._query_public('AssetPairs')
        if not result:
            logger.error("Kraken AssetPairs API call gefaald, val terug op PAIR_MAP")
            return dict(self.PAIR_MAP)

        discovered = {}
        skipped_stable = 0
        skipped_inactive = 0

        for kraken_name, info in result.items():
            # Alleen spot pairs (skip .d darkpool pairs)
            if '.d' in kraken_name:
                continue

            # Check of pair actief is
            status = info.get('status', 'online')
            if status != 'online':
                skipped_inactive += 1
                continue

            # Quote moet USD zijn
            quote = info.get('quote', '')
            # Kraken gebruikt soms 'ZUSD' als quote
            if quote not in ('ZUSD', 'USD'):
                continue

            # Extract base currency
            base = info.get('base', '')
            # Kraken prefixes: X voor crypto, Z voor fiat
            # Verwijder X prefix als die er is (XXBT → XBT → BTC)
            clean_base = base
            if clean_base.startswith('X') and len(clean_base) > 3:
                clean_base = clean_base[1:]
            if clean_base.startswith('Z') and len(clean_base) > 3:
                clean_base = clean_base[1:]

            # Kraken speciale namen → standaard
            base_map = {
                'XBT': 'BTC',
                'XETH': 'ETH',
                'XDG': 'DOGE',
                'XETC': 'ETC',
                'XMLN': 'MLN',
                'XREP': 'REP',
                'XXLM': 'XLM',
                'XXMR': 'XMR',
                'XXRP': 'XRP',
                'XZEC': 'ZEC',
                'XLTC': 'LTC',
            }
            standard_base = base_map.get(clean_base, clean_base)

            # Wsname (websocket name) is het meest betrouwbaar
            wsname = info.get('wsname', '')
            if wsname and '/USD' in wsname:
                ws_base = wsname.split('/')[0]
                if ws_base:
                    standard_base = ws_base

            # Filter ongewenste tokens
            if standard_base.upper() in self._EXCLUDED_BASES:
                skipped_stable += 1
                continue

            pair_key = f"{standard_base}/USD"
            discovered[pair_key] = kraken_name

        # Merge met hardcoded PAIR_MAP (sommige speciale namen)
        # PAIR_MAP heeft voorrang voor bekende mappings
        for pair, kraken_name in self.PAIR_MAP.items():
            if pair not in discovered:
                discovered[pair] = kraken_name

        self._discovery_cache = discovered
        self._discovery_cache_time = now

        logger.info(f"Kraken discovery: {len(discovered)} USD pairs gevonden "
                     f"(skipped: {skipped_stable} stablecoins/excluded, "
                     f"{skipped_inactive} inactive)")
        return discovered

    def get_all_tradeable_pairs(self) -> List[str]:
        """
        Haal alle tradeable pair namen op in 'BASE/USD' formaat.
        Gebruikt dynamische discovery (niet hardcoded).
        """
        pairs = self.discover_all_usd_pairs()
        return sorted(pairs.keys())

    # === PUBLIC METHODS ===

    def get_ticker(self, pair: str) -> Optional[dict]:
        """Haal huidige prijs op voor een pair."""
        kraken_pair = self.get_kraken_pair(pair)
        result = self._query_public('Ticker', {'pair': kraken_pair})
        if result:
            # Kraken geeft soms een andere key terug
            for key, data in result.items():
                return {
                    'ask': float(data['a'][0]),
                    'bid': float(data['b'][0]),
                    'last': float(data['c'][0]),
                    'volume_24h': float(data['v'][1]),
                    'high_24h': float(data['h'][1]),
                    'low_24h': float(data['l'][1]),
                }
        return None

    def get_ohlc(self, pair: str, interval: int = 240, since: int = None) -> Optional[list]:
        """
        Haal OHLC candle data op.
        interval: in minuten (240 = 4H)
        Geeft lijst van [time, open, high, low, close, vwap, volume, count]
        """
        kraken_pair = self.get_kraken_pair(pair)
        params = {'pair': kraken_pair, 'interval': interval}
        if since:
            params['since'] = since
        result = self._query_public('OHLC', params)
        if result:
            for key, data in result.items():
                if key != 'last':
                    candles = []
                    for c in data:
                        candles.append({
                            'time': int(c[0]),
                            'open': float(c[1]),
                            'high': float(c[2]),
                            'low': float(c[3]),
                            'close': float(c[4]),
                            'vwap': float(c[5]),
                            'volume': float(c[6]),
                            'count': int(c[7]),
                        })
                    return candles
        return None

    # === PRIVATE METHODS ===

    def get_balance(self) -> Optional[dict]:
        """Haal account saldo op."""
        result = self._query_private('Balance')
        if result:
            balances = {}
            for asset, amount in result.items():
                amt = float(amount)
                if amt > 0:
                    balances[asset] = amt
            return balances
        return None

    def get_trade_balance(self, asset: str = 'ZUSD') -> Optional[dict]:
        """Haal trade balance op (totale waarde, vrij saldo, etc.)."""
        result = self._query_private('TradeBalance', {'asset': asset})
        if result:
            return {
                'equity': float(result.get('e', 0)),
                'free_margin': float(result.get('mf', 0)),
                'trade_balance': float(result.get('tb', 0)),
            }
        return None

    def get_open_orders(self) -> Optional[dict]:
        """Haal alle open orders op."""
        result = self._query_private('OpenOrders')
        if result:
            return result.get('open', {})
        return None

    def get_open_positions(self) -> Optional[dict]:
        """Haal alle open posities op."""
        result = self._query_private('OpenPositions')
        return result

    def place_market_buy(self, pair: str, volume: float) -> Optional[str]:
        """
        Plaats een market buy order.
        Returns: order ID of None bij fout.
        """
        kraken_pair = self.get_kraken_pair(pair)
        result = self._query_private('AddOrder', {
            'pair': kraken_pair,
            'type': 'buy',
            'ordertype': 'market',
            'volume': str(round(volume, 8)),
        })
        if result:
            txids = result.get('txid', [])
            if txids:
                order_id = txids[0]
                logger.info(f"BUY order geplaatst: {pair} volume={volume} order={order_id}")
                return order_id
        return None

    def place_market_sell(self, pair: str, volume: float) -> Optional[str]:
        """
        Plaats een market sell order.
        Returns: order ID of None bij fout.
        """
        kraken_pair = self.get_kraken_pair(pair)
        result = self._query_private('AddOrder', {
            'pair': kraken_pair,
            'type': 'sell',
            'ordertype': 'market',
            'volume': str(round(volume, 8)),
        })
        if result:
            txids = result.get('txid', [])
            if txids:
                order_id = txids[0]
                logger.info(f"SELL order geplaatst: {pair} volume={volume} order={order_id}")
                return order_id
        return None

    def place_limit_buy(self, pair: str, volume: float, price: float) -> Optional[str]:
        """Plaats een limit buy order."""
        kraken_pair = self.get_kraken_pair(pair)
        result = self._query_private('AddOrder', {
            'pair': kraken_pair,
            'type': 'buy',
            'ordertype': 'limit',
            'price': str(price),
            'volume': str(round(volume, 8)),
        })
        if result:
            txids = result.get('txid', [])
            if txids:
                order_id = txids[0]
                logger.info(f"LIMIT BUY: {pair} vol={volume} price={price} order={order_id}")
                return order_id
        return None

    def convert_usdc_to_usd(self, amount: float) -> Optional[str]:
        """
        Converteer USDC naar USD via market sell.
        USDC/USD is ~1:1, minimale slippage.
        Returns: order ID of None bij fout.
        """
        result = self._query_private('AddOrder', {
            'pair': 'USDCUSD',
            'type': 'sell',
            'ordertype': 'market',
            'volume': str(round(amount, 2)),
        })
        if result:
            txids = result.get('txid', [])
            if txids:
                order_id = txids[0]
                logger.info(f"USDC→USD conversie: {amount} USDC, order={order_id}")
                return order_id
        logger.error(f"USDC→USD conversie gefaald voor {amount} USDC")
        return None

    def get_usdc_balance(self) -> float:
        """Haal USDC saldo op."""
        balance = self.get_balance()
        if balance:
            return balance.get('USDC', 0.0)
        return 0.0

    def get_usd_balance(self) -> float:
        """Haal USD saldo op."""
        balance = self.get_balance()
        if balance:
            return balance.get('ZUSD', balance.get('USD', 0.0))
        return 0.0

    def ensure_usd_available(self, needed: float, buffer: float = 5.0) -> bool:
        """
        Zorg dat er genoeg USD is. Converteer USDC als nodig.
        needed: benodigd bedrag in USD
        buffer: extra USD om fees te dekken
        Returns: True als USD beschikbaar is.
        """
        balance = self.get_balance()
        if not balance:
            return False

        usd = balance.get('ZUSD', balance.get('USD', 0.0))
        usdc = balance.get('USDC', 0.0)

        if usd >= needed:
            logger.info(f"USD saldo voldoende: ${usd:.2f} >= ${needed:.2f}")
            return True

        # Bereken hoeveel USDC we moeten converteren
        shortfall = needed - usd + buffer
        if usdc < shortfall:
            logger.warning(f"Onvoldoende saldo: USD=${usd:.2f}, USDC=${usdc:.2f}, nodig=${needed:.2f}")
            return False

        logger.info(f"USD te laag (${usd:.2f}), converteer ${shortfall:.2f} USDC → USD...")
        order_id = self.convert_usdc_to_usd(shortfall)
        if order_id:
            # Wacht even tot order verwerkt is
            import time
            time.sleep(3)
            new_usd = self.get_usd_balance()
            logger.info(f"Conversie OK. Nieuw USD saldo: ${new_usd:.2f}")
            return new_usd >= needed
        return False

    def cancel_order(self, order_id: str) -> bool:
        """Annuleer een open order."""
        result = self._query_private('CancelOrder', {'txid': order_id})
        if result:
            logger.info(f"Order geannuleerd: {order_id}")
            return True
        return False

    def test_connection(self) -> bool:
        """Test of de API verbinding werkt."""
        # Public test
        result = self._query_public('Time')
        if not result:
            logger.error("Public API test gefaald")
            return False

        # Private test
        balance = self.get_balance()
        if balance is None:
            logger.error("Private API test gefaald - check je API keys")
            return False

        logger.info(f"Kraken verbinding OK. Saldo: {balance}")
        return True
