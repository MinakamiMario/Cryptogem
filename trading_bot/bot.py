#!/usr/bin/env python3
"""
Bear Bounce Trading Bot V4 - Multi-Exchange Edition
-----------------------------------------------------
Automatische trading bot met V4 OPTIMIZED DualConfirm strategie.
Ondersteunt: Kraken + MEXC (CEX) + Solana/BSC DEX tokens.

V4 Optimalisaties (backtest: PF 78.29 | DD 1.9% | WR 83.3%):
  - Entry: Volume spike >2.0x + volume bar-to-bar confirm (V4)
  - Exit: Break-even stop na +3% winst
  - Exit: ATR trailing stop 2.0x
  - Exit: Time max 10 bars (40h) force close (V4: was 16)
  - Portfolio: 1x$2000 all-in + volume ranking
  - Smart cooldown: 8 bars na stop loss

Multi-Exchange:
  - Kraken: 289 halal coins (bestaand)
  - MEXC: 1,900+ coins, 0% maker fees (nieuw)
  - DEX: Solana/BSC tokens via GeckoTerminal candles (nieuw)
  - Halal filter: 3-laags systeem (whitelist + blacklist + CoinGecko)
  - DexScreener: liquidity checks voor DEX tokens

Gebruik:
    python bot.py                      # Kraken-only (backward compatible)
    python bot.py --multi-exchange     # Alle exchanges + halal filter
    python bot.py --dry-run            # Droog draaien
    python bot.py --check              # Eenmalige check
    python bot.py --status             # Toon status
    python bot.py --scan               # Toon alle beschikbare coins

Long only. No leverage. No shorting.
"""
import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from kraken_client import KrakenClient
from strategy import DonchianBounceStrategy, MeanReversionStrategy, DualConfirmStrategy, Position, Signal

# === SETUP ===
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

# Logging
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

TRADES_DIR = BASE_DIR / 'trades'
TRADES_DIR.mkdir(exist_ok=True)

STATE_FILE = BASE_DIR / 'bot_state.json'


def setup_logging(verbose=False):
    """Configureer logging naar bestand en console."""
    log_file = LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('trading_bot')


# === STATE MANAGEMENT ===

def load_state() -> dict:
    """Laad bot state (open posities, trade history)."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        'positions': {},
        'daily_pnl': 0.0,
        'daily_pnl_date': '',
        'total_trades': 0,
        'total_pnl': 0.0,
        'last_check': '',
    }


def save_state(state: dict):
    """Sla bot state op."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def log_trade(trade_data: dict):
    """Log een trade naar het trades bestand."""
    trades_file = TRADES_DIR / f"trades_{datetime.now().strftime('%Y%m')}.json"
    trades = []
    if trades_file.exists():
        with open(trades_file, 'r') as f:
            trades = json.load(f)
    trades.append(trade_data)
    with open(trades_file, 'w') as f:
        json.dump(trades, f, indent=2)


# === NOTIFICATIONS ===

def send_notification(message: str, logger: logging.Logger):
    """Stuur notificatie via Telegram (optioneel) en log."""
    logger.info(f"NOTIFICATIE: {message}")

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if token and chat_id:
        try:
            import requests
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={
                'chat_id': chat_id,
                'text': f"🤖 Trading Bot\n\n{message}",
                'parse_mode': 'HTML'
            }, timeout=10)
        except Exception as e:
            logger.warning(f"Telegram notificatie gefaald: {e}")


# === SAFETY CHECKS ===

class SafetyGuard:
    """Veiligheidscontroles om grote verliezen te voorkomen."""

    def __init__(self, max_daily_loss_pct=5.0, max_open_positions=3,
                 max_position_size_pct=40.0, min_balance=50.0):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.max_position_size_pct = max_position_size_pct
        self.min_balance = min_balance

    def can_open_trade(self, state: dict, balance: float, trade_amount: float,
                       logger: logging.Logger) -> tuple:
        """Check of een nieuwe trade veilig is. Returns (allowed, reason)."""

        # Check 1: Minimum saldo
        if balance < self.min_balance:
            return False, f"Saldo te laag: ${balance:.2f} < ${self.min_balance:.2f}"

        # Check 2: Max open posities
        num_positions = len(state.get('positions', {}))
        if num_positions >= self.max_open_positions:
            return False, f"Max posities bereikt: {num_positions}/{self.max_open_positions}"

        # Check 3: Max positie grootte
        max_amount = balance * (self.max_position_size_pct / 100)
        if trade_amount > max_amount:
            return False, f"Trade te groot: ${trade_amount:.2f} > ${max_amount:.2f} ({self.max_position_size_pct}% van saldo)"

        # Check 4: Daily loss limit
        today = datetime.now().strftime('%Y-%m-%d')
        if state.get('daily_pnl_date') == today:
            daily_loss_pct = abs(min(state.get('daily_pnl', 0), 0)) / max(balance, 1) * 100
            if daily_loss_pct >= self.max_daily_loss_pct:
                return False, f"Dagelijks verlies limiet bereikt: {daily_loss_pct:.1f}% >= {self.max_daily_loss_pct}%"

        return True, "OK"

    def reset_daily_if_needed(self, state: dict):
        """Reset dagelijkse P&L als het een nieuwe dag is."""
        today = datetime.now().strftime('%Y-%m-%d')
        if state.get('daily_pnl_date') != today:
            state['daily_pnl'] = 0.0
            state['daily_pnl_date'] = today


# === MAIN BOT ===

class TradingBot:
    """Hoofdbot die alles coördineert."""

    def __init__(self, dry_run=False, verbose=False, multi_exchange=False):
        self.dry_run = dry_run
        self.multi_exchange = multi_exchange
        self.logger = setup_logging(verbose)
        self.state = load_state()

        # ====================================================================
        # Exchange setup
        # ====================================================================
        if multi_exchange:
            self._init_multi_exchange()
        else:
            self._init_kraken_only()

        # Configuratie
        self.capital_per_trade = float(os.getenv('CAPITAL_PER_TRADE', '100'))

        # Strategy V4 OPTIMIZED
        strat_name = os.getenv('STRATEGY', 'dual')
        if strat_name == 'dual':
            self.strategy = DualConfirmStrategy(
                rsi_dc_max=40, rsi_bb_max=40, rsi_sell=70,
                atr_stop_mult=2.0, cooldown_bars=4,
                cooldown_after_stop=8,
                max_stop_loss_pct=15.0,
                volume_spike_filter=True, volume_spike_mult=2.0,
                breakeven_stop=True, breakeven_trigger_pct=3.0,
                volume_min_pct=0.5,
                time_max_bars=10,
                vol_confirm=True, vol_confirm_mult=1.0,
            )
        elif strat_name == 'donchian':
            self.strategy = DonchianBounceStrategy()
        elif strat_name == 'meanrev':
            self.strategy = MeanReversionStrategy()
        else:
            self.strategy = DualConfirmStrategy(
                rsi_dc_max=40, rsi_bb_max=40, rsi_sell=70,
                atr_stop_mult=2.0, cooldown_bars=4,
                cooldown_after_stop=8,
                max_stop_loss_pct=15.0,
                volume_spike_filter=True, volume_spike_mult=2.0,
                breakeven_stop=True, breakeven_trigger_pct=3.0,
                volume_min_pct=0.5,
                time_max_bars=10,
                vol_confirm=True, vol_confirm_mult=1.0,
            )

        # Per-coin strategy instances (voor cooldown tracking per coin)
        self.strategies = {}

        # Safety
        self.safety = SafetyGuard(
            max_daily_loss_pct=float(os.getenv('MAX_DAILY_LOSS_PCT', '5.0')),
            max_open_positions=int(os.getenv('MAX_OPEN_POSITIONS', '1')),
        )

        # Halal filter (altijd laden, ook in kraken-only mode)
        try:
            from halal_filter import HalalFilter
            self.halal_filter = HalalFilter()
        except ImportError:
            self.halal_filter = None

        mode_str = 'MULTI-EXCHANGE' if multi_exchange else 'KRAKEN-ONLY'
        exchanges_str = ', '.join(self.scanner.exchange_manager.exchanges.keys()) if multi_exchange else 'kraken'
        coin_count = len(self.coins)

        self.logger.info(f"Bot V4 gestart | {'DRY RUN' if dry_run else 'LIVE'} | {mode_str} | "
                         f"Exchanges: {exchanges_str} | "
                         f"Coins: {coin_count} | Capital/trade: ${self.capital_per_trade} | "
                         f"V4: VolSpike>2x | VolConfirm | BE+3% | RSI<40 | ATR2.0 | TimeMax10")

    def _init_kraken_only(self):
        """Oorspronkelijke Kraken-only modus (backward compatible)."""
        api_key = os.getenv('KRAKEN_API_KEY', '')
        private_key = os.getenv('KRAKEN_PRIVATE_KEY', '')
        if not api_key or not private_key:
            self.logger.error("KRAKEN_API_KEY of KRAKEN_PRIVATE_KEY niet ingesteld in .env")
            sys.exit(1)

        self.client = KrakenClient(api_key, private_key)
        self.scanner = None

        # Coins: dynamische discovery of .env fallback
        coins_str = os.getenv('COINS', '')
        if coins_str:
            self.coins = [c.strip() for c in coins_str.split(',') if c.strip()]
            self.logger.info(f"Coins uit .env: {len(self.coins)}")
        else:
            self.coins = self.client.get_all_tradeable_pairs()
            self.logger.info(f"Coins dynamisch ontdekt: {len(self.coins)}")

        # Coin info mapping voor backward compat
        self.coin_info = {
            pair: {
                'symbol': pair.split('/')[0],
                'pair': pair,
                'source': 'kraken',
                'source_type': 'cex',
                'fee_pct': 0.26,
                'quote': 'USD',
            }
            for pair in self.coins
        }

    def _init_multi_exchange(self):
        """Multi-exchange modus met CoinScanner."""
        from coin_scanner import CoinScanner

        # Detect welke DEX chains actief zijn
        dex_chains = []
        if os.getenv('ENABLE_DEX_SOLANA', 'true').lower() == 'true':
            dex_chains.append('solana')
        if os.getenv('ENABLE_DEX_BSC', 'true').lower() == 'true':
            dex_chains.append('bsc')
        # Ethereum default UIT (te dure gas)
        if os.getenv('ENABLE_DEX_ETH', 'false').lower() == 'true':
            dex_chains.append('ethereum')

        self.scanner = CoinScanner(
            enable_kraken=bool(os.getenv('KRAKEN_API_KEY')),
            enable_mexc=bool(os.getenv('MEXC_API_KEY')),
            enable_dex=len(dex_chains) > 0,
            enable_halal=True,
            dex_chains=dex_chains,
        )

        # Backward compat: ook KrakenClient direct beschikbaar houden
        api_key = os.getenv('KRAKEN_API_KEY', '')
        private_key = os.getenv('KRAKEN_PRIVATE_KEY', '')
        if api_key and private_key:
            self.client = KrakenClient(api_key, private_key)
        else:
            self.client = None

        # Scan alle coins
        self.logger.info("Multi-exchange scan gestart...")
        all_coins = self.scanner.scan_all()
        self.coins = [c['pair'] for c in all_coins]
        self.coin_info = {c['pair']: c for c in all_coins}

        self.logger.info(f"Multi-exchange scan klaar: {len(self.coins)} coins gevonden")

    def get_strategy_for(self, pair: str) -> DualConfirmStrategy:
        """Haal per-coin strategy instance op (voor cooldown tracking)."""
        if pair not in self.strategies:
            self.strategies[pair] = DualConfirmStrategy(
                rsi_dc_max=40, rsi_bb_max=40, rsi_sell=70,
                atr_stop_mult=2.0, cooldown_bars=4,
                cooldown_after_stop=8,
                max_stop_loss_pct=15.0,
                volume_spike_filter=True, volume_spike_mult=2.0,
                breakeven_stop=True, breakeven_trigger_pct=3.0,
                volume_min_pct=0.5,
                time_max_bars=10,
                vol_confirm=True, vol_confirm_mult=1.0,
            )
        return self.strategies[pair]

    def check_connection(self) -> bool:
        """Test exchange verbindingen."""
        self.logger.info("Verbinding testen...")

        if self.multi_exchange and self.scanner:
            results = self.scanner.exchange_manager.test_all_connections()
            all_ok = all(results.values())
            for name, ok in results.items():
                emoji = "✅" if ok else "❌"
                self.logger.info(f"{emoji} {name.upper()} verbinding {'OK' if ok else 'GEFAALD'}")
            # Minimaal 1 exchange moet werken
            if any(results.values()):
                return True
            self.logger.error("❌ Geen enkele exchange verbinding werkt!")
            return False
        else:
            if self.client.test_connection():
                self.logger.info("✅ Kraken verbinding OK")
                return True
            else:
                self.logger.error("❌ Kraken verbinding GEFAALD")
                return False

    def get_position(self, pair: str) -> Position:
        """Haal positie op uit state. Dwingt max stop loss cap af."""
        pos_data = self.state.get('positions', {}).get(pair)
        if pos_data:
            pos = Position(**{k: v for k, v in pos_data.items()
                              if k in ('pair', 'entry_price', 'volume',
                                       'stop_price', 'highest_price',
                                       'entry_time', 'order_id')})
            # Afdwingen max stop loss cap op bestaande posities
            if hasattr(self.strategy, 'max_stop_loss_pct'):
                max_stop = pos.entry_price * (1 - self.strategy.max_stop_loss_pct / 100)
                if pos.stop_price < max_stop:
                    self.logger.info(f"🛡️ Stop loss cap afgedwongen voor {pair}: "
                                     f"${pos.stop_price:.4f} → ${max_stop:.4f} "
                                     f"(max {self.strategy.max_stop_loss_pct}% verlies)")
                    pos.stop_price = max_stop
                    # Ook state updaten
                    self.state['positions'][pair]['stop_price'] = max_stop
                    save_state(self.state)
            return pos
        return None

    def save_position(self, pair: str, position: Position, exchange: str = 'kraken',
                      fee_pct: float = 0.26):
        """Sla positie op in state (met exchange info voor multi-exchange)."""
        if 'positions' not in self.state:
            self.state['positions'] = {}
        self.state['positions'][pair] = {
            'pair': position.pair,
            'entry_price': position.entry_price,
            'volume': position.volume,
            'stop_price': position.stop_price,
            'highest_price': position.highest_price,
            'entry_time': position.entry_time,
            'order_id': position.order_id,
            'exchange': exchange,
            'fee_pct': fee_pct,
        }
        save_state(self.state)

    def remove_position(self, pair: str):
        """Verwijder positie uit state."""
        if pair in self.state.get('positions', {}):
            del self.state['positions'][pair]
            save_state(self.state)

    def process_signal(self, signal: Signal, coin_info: dict = None):
        """Verwerk een trading signaal."""
        if signal.action == 'WAIT' or signal.action == 'HOLD':
            return

        if signal.action == 'BUY':
            self._execute_buy(signal, coin_info)

        elif signal.action in ('SELL_TARGET', 'SELL_STOP'):
            self._execute_sell(signal, coin_info)

    def _get_candles(self, pair: str, coin_info: dict = None):
        """Haal candles op via de juiste bron."""
        if self.multi_exchange and self.scanner and coin_info:
            return self.scanner.get_candles(coin_info)
        else:
            return self.client.get_ohlc(pair, interval=240)

    def _execute_buy(self, signal: Signal, coin_info: dict = None):
        """Voer een buy uit. Ondersteunt meerdere exchanges."""
        exchange = (coin_info or {}).get('source', 'kraken')
        fee_pct = (coin_info or {}).get('fee_pct', 0.26)

        # Haal balance op
        if self.multi_exchange and self.scanner:
            balance = self.scanner.exchange_manager.get_balance(exchange)
        else:
            balance = self.client.get_balance()

        usd_balance = 0
        usdc_balance = 0
        if balance:
            if exchange == 'kraken':
                usd_balance = balance.get('ZUSD', balance.get('USD', 0))
                usdc_balance = balance.get('USDC', 0)
            elif exchange == 'mexc':
                usd_balance = balance.get('USDT', 0)
                usdc_balance = 0  # MEXC gebruikt USDT
            else:
                usd_balance = balance.get('USDT', balance.get('USD', 0))
                usdc_balance = 0

        # Totaal beschikbaar
        total_available = usd_balance + usdc_balance

        # Safety check
        allowed, reason = self.safety.can_open_trade(
            self.state, total_available, self.capital_per_trade, self.logger)
        if not allowed:
            self.logger.warning(f"⚠️ Trade geblokkeerd: {reason}")
            send_notification(f"⚠️ BUY geblokkeerd voor {signal.pair}: {reason}", self.logger)
            return

        # Halal check bij entry (extra veiligheid)
        if self.halal_filter:
            symbol = signal.pair.split('/')[0]
            halal_result = self.halal_filter.check(symbol, use_api=False)
            if halal_result['halal'] is False:
                self.logger.warning(f"🚫 Halal filter: {signal.pair} afgewezen - {halal_result['reason']}")
                return

        # Auto-convert USDC → USD (alleen Kraken)
        if not self.dry_run and exchange == 'kraken' and usd_balance < self.capital_per_trade:
            self.logger.info(f"💱 USD saldo te laag (${usd_balance:.2f}), "
                             f"converteer USDC → USD...")
            if self.client.ensure_usd_available(self.capital_per_trade):
                self.logger.info("💱 USDC → USD conversie gelukt")
            else:
                self.logger.error("❌ USDC → USD conversie gefaald")
                send_notification(f"❌ USDC→USD conversie gefaald voor {signal.pair}", self.logger)
                return

        # Bereken volume
        volume = self.capital_per_trade / signal.price

        fee_str = f" | Fee: {fee_pct}%" if fee_pct != 0.26 else ""
        msg = (f"🟢 BUY {signal.pair} [{exchange.upper()}]{fee_str}\n"
               f"Prijs: ${signal.price:.4f}\n"
               f"Volume: {volume:.4f}\n"
               f"Bedrag: ${self.capital_per_trade:.2f}\n"
               f"Stop: ${signal.stop_price:.4f}\n"
               f"Target: ${signal.target_price:.4f}\n"
               f"RSI: {signal.rsi:.1f}\n"
               f"Reden: {signal.reason}")

        if self.dry_run:
            self.logger.info(f"[DRY RUN] {msg}")
            order_id = f"DRY-{exchange.upper()}-{int(time.time())}"
        else:
            # Order plaatsen via juiste exchange
            if self.multi_exchange and self.scanner:
                order_id = self.scanner.place_buy(coin_info, volume)
            else:
                order_id = self.client.place_market_buy(signal.pair, volume)

            if not order_id:
                self.logger.error(f"❌ BUY order gefaald voor {signal.pair} op {exchange}")
                send_notification(f"❌ BUY order GEFAALD voor {signal.pair} [{exchange}]", self.logger)
                return

        # Sla positie op (met exchange info)
        position = Position(
            pair=signal.pair,
            entry_price=signal.price,
            volume=volume,
            stop_price=signal.stop_price,
            highest_price=signal.price,
            entry_time=int(time.time()),
            order_id=order_id,
        )
        self.save_position(signal.pair, position, exchange=exchange, fee_pct=fee_pct)

        # Log trade
        log_trade({
            'type': 'BUY',
            'pair': signal.pair,
            'exchange': exchange,
            'fee_pct': fee_pct,
            'price': signal.price,
            'volume': volume,
            'amount_usd': self.capital_per_trade,
            'stop_price': signal.stop_price,
            'target_price': signal.target_price,
            'rsi': signal.rsi,
            'order_id': order_id,
            'timestamp': datetime.now().isoformat(),
            'dry_run': self.dry_run,
        })

        send_notification(msg, self.logger)
        self.state['total_trades'] = self.state.get('total_trades', 0) + 1
        save_state(self.state)

    def _execute_sell(self, signal: Signal, coin_info: dict = None):
        """Voer een sell uit."""
        position = self.get_position(signal.pair)
        if not position:
            self.logger.warning(f"Geen positie gevonden voor {signal.pair}")
            return

        # Haal exchange info uit positie state
        pos_data = self.state.get('positions', {}).get(signal.pair, {})
        exchange = pos_data.get('exchange', 'kraken')

        pnl = (signal.price - position.entry_price) * position.volume
        pnl_pct = (signal.price - position.entry_price) / position.entry_price * 100
        exit_type = "TARGET" if signal.action == 'SELL_TARGET' else "STOP LOSS"

        emoji = "🟢" if pnl > 0 else "🔴"
        msg = (f"{emoji} SELL {signal.pair} ({exit_type}) [{exchange.upper()}]\n"
               f"Entry: ${position.entry_price:.4f}\n"
               f"Exit: ${signal.price:.4f}\n"
               f"P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)\n"
               f"Volume: {position.volume:.4f}\n"
               f"Reden: {signal.reason}")

        if self.dry_run:
            self.logger.info(f"[DRY RUN] {msg}")
        else:
            # Sell via juiste exchange
            if self.multi_exchange and self.scanner and exchange != 'kraken':
                order_id = self.scanner.exchange_manager.place_market_sell(
                    exchange, signal.pair, position.volume)
            else:
                order_id = self.client.place_market_sell(signal.pair, position.volume)

            if not order_id:
                self.logger.error(f"❌ SELL order gefaald voor {signal.pair} op {exchange}")
                send_notification(f"❌ SELL order GEFAALD voor {signal.pair} [{exchange}]!", self.logger)
                return

        # Update state
        self.state['daily_pnl'] = self.state.get('daily_pnl', 0) + pnl
        self.state['total_pnl'] = self.state.get('total_pnl', 0) + pnl
        self.remove_position(signal.pair)

        # Log trade
        log_trade({
            'type': 'SELL',
            'exit_type': exit_type,
            'pair': signal.pair,
            'exchange': exchange,
            'entry_price': position.entry_price,
            'exit_price': signal.price,
            'volume': position.volume,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'rsi': signal.rsi,
            'timestamp': datetime.now().isoformat(),
            'dry_run': self.dry_run,
        })

        send_notification(msg, self.logger)
        save_state(self.state)

    def check_all_coins(self):
        """Check alle coins voor signalen (alle exchanges)."""
        self.logger.info(f"{'=' * 60}")
        self.logger.info(f"Check gestart: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.multi_exchange:
            exchanges = list(self.scanner.exchange_manager.exchanges.keys())
            self.logger.info(f"Mode: MULTI-EXCHANGE | Exchanges: {', '.join(exchanges)}")
        self.logger.info(f"Coins: {len(self.coins)}")
        self.logger.info(f"{'=' * 60}")

        self.safety.reset_daily_if_needed(self.state)

        signals_found = 0

        for pair in self.coins:
            try:
                coin_info = self.coin_info.get(pair, {})
                source = coin_info.get('source', 'kraken')

                # Haal 4H candle data op
                candles = self._get_candles(pair, coin_info)
                if not candles or len(candles) < 30:
                    self.logger.debug(f"{pair} [{source}]: Niet genoeg candle data "
                                       f"({len(candles) if candles else 0})")
                    continue

                # Haal huidige positie op
                position = self.get_position(pair)

                # Analyseer met per-coin strategy (voor cooldown tracking)
                strat_name = os.getenv('STRATEGY', 'dual')
                if strat_name == 'dual':
                    strategy = self.get_strategy_for(pair)
                else:
                    strategy = self.strategy
                signal = strategy.analyze(candles, position, pair)

                # Log signaal (alleen interessante)
                if signal.action in ('BUY', 'SELL_TARGET', 'SELL_STOP'):
                    status = "🟢" if signal.action == 'BUY' else "🔴"
                    self.logger.info(f"{status} {signal.pair} [{source}]: {signal.action} | {signal.reason}")
                    signals_found += 1
                elif signal.action == 'HOLD':
                    self.logger.info(f"⏳ {signal.pair} [{source}]: HOLD | {signal.reason}")

                # Verwerk signaal
                self.process_signal(signal, coin_info)

            except Exception as e:
                self.logger.error(f"Error bij {pair}: {e}", exc_info=True)

        self.state['last_check'] = datetime.now().isoformat()
        save_state(self.state)
        self.logger.info(f"\nCheck afgerond: {signals_found} signalen gevonden. "
                         f"Volgende check over 4 uur.\n")

    def show_status(self):
        """Toon huidige bot status."""
        mode = 'MULTI-EXCHANGE' if self.multi_exchange else 'KRAKEN-ONLY'

        print(f"\n{'=' * 60}")
        print(f"  BEAR BOUNCE TRADING BOT - STATUS")
        print(f"{'=' * 60}")
        print(f"  Mode:        {'DRY RUN' if self.dry_run else 'LIVE'} | {mode}")
        print(f"  Strategy:    {type(self.strategy).__name__}")
        print(f"  Coins:       {len(self.coins)}")
        print(f"  Capital:     ${self.capital_per_trade}/trade")
        print(f"  Last check:  {self.state.get('last_check', 'Nooit')}")
        print(f"  Total trades: {self.state.get('total_trades', 0)}")
        print(f"  Total P&L:   ${self.state.get('total_pnl', 0):.2f}")
        print(f"  Daily P&L:   ${self.state.get('daily_pnl', 0):.2f}")

        # Exchange info
        if self.multi_exchange and self.scanner:
            print(f"\n  EXCHANGES:")
            for name, client in self.scanner.exchange_manager.exchanges.items():
                pairs = client.get_tradeable_pairs()
                print(f"    {name.upper():10s} | {len(pairs):>5d} pairs | fee: {client.fee_pct}%")

        positions = self.state.get('positions', {})
        if positions:
            print(f"\n  OPEN POSITIES ({len(positions)}):")
            for pair, pos in positions.items():
                exchange = pos.get('exchange', 'kraken')
                fee = pos.get('fee_pct', 0.26)

                # Ticker ophalen via juiste exchange
                ticker = None
                if self.multi_exchange and self.scanner:
                    ticker = self.scanner.exchange_manager.get_ticker(exchange, pair)
                elif self.client:
                    ticker = self.client.get_ticker(pair)

                current_price = ticker['last'] if ticker else 0
                pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price'] * 100) if current_price else 0
                pnl_usd = (current_price - pos['entry_price']) * pos['volume'] if current_price else 0
                emoji = "🟢" if pnl_pct > 0 else "🔴"
                print(f"  {emoji} {pair} [{exchange}]: entry=${pos['entry_price']:.4f} "
                      f"now=${current_price:.4f} "
                      f"P&L={pnl_pct:+.1f}% (${pnl_usd:+.2f}) "
                      f"stop=${pos['stop_price']:.4f} fee={fee}%")
        else:
            print(f"\n  Geen open posities")

        # Saldo per exchange
        print(f"\n  SALDI:")
        if self.multi_exchange and self.scanner:
            for name in self.scanner.exchange_manager.exchanges:
                balance = self.scanner.exchange_manager.get_balance(name)
                if balance:
                    if name == 'kraken':
                        usd = balance.get('ZUSD', balance.get('USD', 0))
                        usdc = balance.get('USDC', 0)
                        print(f"    {name.upper():10s} | USD: ${usd:.2f} | USDC: ${usdc:.2f} | "
                              f"Totaal: ${usd + usdc:.2f}")
                    elif name == 'mexc':
                        usdt = balance.get('USDT', 0)
                        print(f"    {name.upper():10s} | USDT: ${usdt:.2f}")
        elif self.client:
            balance = self.client.get_balance()
            if balance:
                usd = balance.get('ZUSD', balance.get('USD', 0))
                usdc = balance.get('USDC', 0)
                print(f"    KRAKEN     | USD: ${usd:.2f} | USDC: ${usdc:.2f} | "
                      f"Totaal: ${usd + usdc:.2f}")

        # Halal stats
        if self.halal_filter:
            stats = self.halal_filter.get_stats()
            print(f"\n  HALAL FILTER:")
            print(f"    Whitelist: {stats['hardcoded_whitelist']} + "
                  f"{stats['custom_whitelist']} custom")
            print(f"    Blacklist: {stats['blacklist_categories']} categories")
            print(f"    Review queue: {stats['review_queue']}")

        print(f"{'=' * 60}\n")

    def show_scan(self):
        """Toon alle beschikbare coins na filtering."""
        if self.multi_exchange and self.scanner:
            self.scanner.print_overview()
        else:
            print(f"\n  Kraken coins: {len(self.coins)}")
            print(f"  Gebruik --multi-exchange voor volledige scan\n")

    def run_loop(self):
        """Start de continue trading loop (elke 4 uur)."""
        mode = 'MULTI-EXCHANGE' if self.multi_exchange else 'KRAKEN-ONLY'
        exchanges = ', '.join(self.scanner.exchange_manager.exchanges.keys()) if self.multi_exchange else 'kraken'

        self.logger.info(f"🤖 Bot loop gestart - draait elke 4 uur | {mode}")
        send_notification(f"🤖 Trading Bot gestart!\n"
                          f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'} | {mode}\n"
                          f"Exchanges: {exchanges}\n"
                          f"Coins: {len(self.coins)}\n"
                          f"Capital: ${self.capital_per_trade}/trade",
                          self.logger)

        while True:
            try:
                self.check_all_coins()

                # Wacht tot volgende 4H candle
                # 4H candles sluiten op 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
                now = datetime.utcnow()
                next_4h = now.replace(minute=1, second=0, microsecond=0)
                next_4h_hour = ((now.hour // 4) + 1) * 4
                if next_4h_hour >= 24:
                    next_4h = next_4h.replace(hour=0) + timedelta(days=1)
                else:
                    next_4h = next_4h.replace(hour=next_4h_hour)

                wait_seconds = (next_4h - now).total_seconds()
                # Minimum 5 minuten wachten, check 1 minuut na candle close
                wait_seconds = max(wait_seconds, 300)

                self.logger.info(f"⏳ Volgende check om {next_4h.strftime('%H:%M')} UTC "
                                 f"(over {wait_seconds / 60:.0f} minuten)")
                time.sleep(wait_seconds)

            except KeyboardInterrupt:
                self.logger.info("Bot gestopt door gebruiker (Ctrl+C)")
                send_notification("🛑 Trading Bot gestopt door gebruiker", self.logger)
                break
            except Exception as e:
                self.logger.error(f"Onverwachte fout: {e}", exc_info=True)
                send_notification(f"🚨 Bot error: {e}", self.logger)
                time.sleep(300)  # Wacht 5 min bij fout


# === CLI ===

def main():
    parser = argparse.ArgumentParser(description='Bear Bounce Trading Bot V4')
    parser.add_argument('--dry-run', action='store_true',
                        help='Droog draaien zonder echte orders')
    parser.add_argument('--check', action='store_true',
                        help='Eenmalige check (niet loopen)')
    parser.add_argument('--status', action='store_true',
                        help='Toon huidige status')
    parser.add_argument('--scan', action='store_true',
                        help='Toon alle beschikbare coins')
    parser.add_argument('--multi-exchange', '-m', action='store_true',
                        help='Multi-exchange modus (Kraken + MEXC + DEX)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Uitgebreide logging')
    args = parser.parse_args()

    bot = TradingBot(
        dry_run=args.dry_run,
        verbose=args.verbose,
        multi_exchange=args.multi_exchange,
    )

    if args.scan:
        bot.show_scan()
    elif args.status:
        bot.show_status()
    elif args.check:
        if bot.check_connection():
            bot.check_all_coins()
    else:
        if bot.check_connection():
            bot.run_loop()


if __name__ == '__main__':
    main()
