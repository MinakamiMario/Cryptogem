"""
Exchange configuration registry for multi-exchange HF strategy validation.

Provides ExchangeConfig dataclass with:
- Fee defaults per account tier (CLI-overridable, never hardcoded as truth)
- Symbol mapping via fetch_markets() (not string replace)
- Fee snapshot for report reproducibility
- Rate limit / politeness settings

Usage:
    from strategies.hf.screening.exchange_config import get_exchange, FeeSnapshot

    cfg = get_exchange('bybit')
    snap = FeeSnapshot.from_config(cfg, source='My Fee Rates page')
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Fee snapshot — embedded in every report for reproducibility
# ---------------------------------------------------------------------------

@dataclass
class FeeSnapshot:
    """Immutable fee record embedded in report metadata.

    Every backtest / OB analysis report MUST include this so results
    can be reproduced with the exact same fee assumptions.
    """
    exchange_id: str
    maker_fee_bps: float
    taker_fee_bps: float
    region: str = ""           # e.g. 'EU', 'US', 'global'
    account_tier: str = ""     # e.g. 'VIP0', 'Group 1', 'regular'
    source: str = ""           # e.g. 'My Fee Rates page', 'docs'
    timestamp: str = ""        # ISO 8601 when snapshot was taken

    @classmethod
    def from_config(
        cls,
        config: "ExchangeConfig",
        source: str = "",
        region: str = "",
        account_tier: str = "",
        maker_override: Optional[float] = None,
        taker_override: Optional[float] = None,
    ) -> "FeeSnapshot":
        """Build snapshot from config, optionally overriding fees."""
        return cls(
            exchange_id=config.id,
            maker_fee_bps=maker_override if maker_override is not None else config.maker_fee_bps,
            taker_fee_bps=taker_override if taker_override is not None else config.taker_fee_bps,
            region=region or config.region,
            account_tier=account_tier or config.account_tier,
            source=source,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Exchange configuration
# ---------------------------------------------------------------------------

@dataclass
class ExchangeConfig:
    """Per-exchange settings. Fee defaults are DEFAULTS, not truth.

    Always allow CLI overrides (--maker-fee-bps, --taker-fee-bps).
    The actual fee used in a run is recorded in FeeSnapshot.
    """
    id: str                         # 'mexc', 'bybit', 'okx'
    ccxt_id: str                    # CCXT constructor name
    quote_currency: str             # 'USDT'
    maker_fee_bps: float            # Default maker fee (VIP0/regular)
    taker_fee_bps: float            # Default taker fee (VIP0/regular)
    region: str = ""                # Default region
    account_tier: str = ""          # Default account tier label
    adverse_selection_mult: float = 0.3   # Maker fill adverse selection
    politeness_sleep_s: float = 0.05      # Extra sleep between API calls
    ob_depth_limit: int = 20              # Orderbook levels to fetch
    ccxt_options: Dict = field(default_factory=lambda: {"enableRateLimit": True})

    def create_ccxt_exchange(self):
        """Create a CCXT exchange instance. Requires ccxt installed."""
        import ccxt as _ccxt
        exchange_class = getattr(_ccxt, self.ccxt_id)
        return exchange_class(self.ccxt_options)


# ---------------------------------------------------------------------------
# Registry — fee defaults match user-verified account pages (2026-02-16)
# ---------------------------------------------------------------------------

EXCHANGES: Dict[str, ExchangeConfig] = {
    "mexc": ExchangeConfig(
        id="mexc",
        ccxt_id="mexc",
        quote_currency="USDT",
        maker_fee_bps=0.0,
        taker_fee_bps=10.0,
        region="global",
        account_tier="standard",
        adverse_selection_mult=0.3,
        politeness_sleep_s=0.05,
    ),
    "bybit": ExchangeConfig(
        id="bybit",
        ccxt_id="bybit",
        quote_currency="USDT",
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        region="EU",
        account_tier="regular",
        adverse_selection_mult=0.3,
        politeness_sleep_s=0.05,
    ),
    "okx": ExchangeConfig(
        id="okx",
        ccxt_id="okx",
        quote_currency="USDT",
        maker_fee_bps=20.0,
        taker_fee_bps=35.0,
        region="global",
        account_tier="Group 1 regular",
        adverse_selection_mult=0.3,
        politeness_sleep_s=0.05,
    ),
}


def get_exchange(exchange_id: str) -> ExchangeConfig:
    """Get exchange config by ID. Raises KeyError if unknown."""
    if exchange_id not in EXCHANGES:
        available = ", ".join(sorted(EXCHANGES.keys()))
        raise KeyError(
            f"Unknown exchange {exchange_id!r}. Available: {available}"
        )
    return EXCHANGES[exchange_id]


def list_exchanges() -> list:
    """List all configured exchange IDs."""
    return sorted(EXCHANGES.keys())


# ---------------------------------------------------------------------------
# CLI helpers — add these arguments to any argparse parser
# ---------------------------------------------------------------------------

def add_exchange_args(parser) -> None:
    """Add --exchange, --maker-fee-bps, --taker-fee-bps, --fee-source,
    --region, --account-tier to an argparse parser."""
    parser.add_argument(
        "--exchange", type=str, default="mexc",
        choices=list_exchanges(),
        help=f"Exchange ID (default: mexc). Available: {', '.join(list_exchanges())}",
    )
    parser.add_argument(
        "--maker-fee-bps", type=float, default=None,
        help="Override maker fee in bps (default: exchange config default)",
    )
    parser.add_argument(
        "--taker-fee-bps", type=float, default=None,
        help="Override taker fee in bps (default: exchange config default)",
    )
    parser.add_argument(
        "--fee-source", type=str, default="",
        help="Fee source description for report metadata",
    )
    parser.add_argument(
        "--region", type=str, default="",
        help="Region override for fee snapshot (e.g. 'EU', 'US')",
    )
    parser.add_argument(
        "--account-tier", type=str, default="",
        help="Account tier override (e.g. 'VIP0', 'Group 1')",
    )


def build_fee_snapshot(args) -> FeeSnapshot:
    """Build FeeSnapshot from parsed argparse args (after add_exchange_args)."""
    cfg = get_exchange(args.exchange)
    return FeeSnapshot.from_config(
        cfg,
        source=args.fee_source,
        region=args.region,
        account_tier=args.account_tier,
        maker_override=args.maker_fee_bps,
        taker_override=args.taker_fee_bps,
    )
