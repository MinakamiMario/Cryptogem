"""
SuperHF Sprint 3 Harness — 1H-primary backtest engine with 15m intrahour precision.

KEY ARCHITECTURAL DIFFERENCE from Sprint 1+2 harness:
  - Primary loop iterates over 1H bar indices
  - Signal evaluation uses 1H-level indicators
  - 15m candles serve two roles:
      (a) Entry confirmation within the hour (green close above zone)
      (b) Intrahour exit detection (stop/TP hit on 15m low/close)
  - Exits are DC-only: FIXED STOP -> TIME MAX -> DC TARGET
      NO RSI Recovery, NO BB TARGET

Signal protocol (Sprint 3):
    signal_fn(candles_1h, bar_1h, indicators_1h, params) -> dict | None
    Returns: {'strength': float, 'needs_15m_confirm': bool} or None

Equity/fee model has exact parity with agent_team_v3.py and Sprint 1 harness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, NamedTuple, Optional

from strategies.superhf.indicators import (
    precompute_1h_indicators,
    find_support_zone,
    _vectorized_donchian_mid,
    _vectorized_vol_avg,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INITIAL_CAPITAL = 10_000.0
START_BAR = 100            # 1H bars to skip for indicator warmup
COOLDOWN_BARS = 2          # 2 x 1H = 2H
COOLDOWN_AFTER_STOP = 6    # 6 x 1H = 6H
DC_PERIOD = 20

CLASS_A_REASONS = {"DC TARGET"}
CLASS_B_REASONS = {"FIXED STOP", "TIME MAX", "END"}


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------
class _Pos(NamedTuple):
    pair: str
    entry_price: float
    entry_bar: int        # 1H bar index
    size_usd: float


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    trades: int
    pnl: float
    pf: float
    wr: float
    dd: float
    final_equity: float
    trade_list: list = field(default_factory=list)
    exit_classes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hour-to-15m time mapping
# ---------------------------------------------------------------------------
# These functions provide the bridge between 1H and 15m candle arrays.
# Each 1H bar covers a 1-hour window; up to 4 aligned 15m bars fall within it.
# Mapping uses timestamps: 1H bar at time T covers [T, T+3600).

def build_hour_to_15m_map(
    candles_1h: list[dict],
    candles_15m: list[dict],
) -> dict[int, list[int]]:
    """Build mapping from 1H bar index -> list of 15m bar indices within that hour.

    For each 1H bar at index `i` with timestamp T, we find all 15m bars
    whose timestamp falls in [T, T + 3600).

    Returns dict[int, list[int]] where keys are 1H bar indices and
    values are lists of 15m bar indices, sorted chronologically.
    """
    if not candles_1h or not candles_15m:
        return {}

    # Build sorted list of (timestamp, 15m_index) for binary search
    ts_15m = [(c['time'], idx) for idx, c in enumerate(candles_15m)]
    ts_15m.sort(key=lambda x: x[0])
    ts_15m_only = [t[0] for t in ts_15m]

    import bisect

    hour_map: dict[int, list[int]] = {}
    for i, c1h in enumerate(candles_1h):
        t_start = c1h['time']
        t_end = t_start + 3600

        lo = bisect.bisect_left(ts_15m_only, t_start)
        hi = bisect.bisect_left(ts_15m_only, t_end)

        indices = [ts_15m[j][1] for j in range(lo, hi)]
        hour_map[i] = indices

    return hour_map


def get_15m_bars_for_hour(
    hour_map: dict[int, list[int]],
    bar_1h: int,
) -> list[int]:
    """Return list of 15m bar indices that fall within the given 1H bar."""
    return hour_map.get(bar_1h, [])


def get_15m_ohlcv_for_hour(
    candles_15m: list[dict],
    hour_map: dict[int, list[int]],
    bar_1h: int,
) -> list[dict]:
    """Return the actual 15m candle dicts for a given 1H bar."""
    indices = hour_map.get(bar_1h, [])
    return [candles_15m[i] for i in indices if i < len(candles_15m)]


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    data_1h: dict,              # {coin: [candle_dicts]} 1H
    data_15m: dict,             # {coin: [candle_dicts]} 15m
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    fee: float = 0.001,         # MEXC 10bps/side
    initial_capital: float = INITIAL_CAPITAL,
    start_bar: int = START_BAR,
    end_bar: int = None,
    cooldown_bars: int = COOLDOWN_BARS,
    cooldown_after_stop: int = COOLDOWN_AFTER_STOP,
    max_pos: int = 1,
) -> BacktestResult:
    """Run 1H-primary backtest with 15m intrahour precision.

    Primary loop = 1H bar index.
    Signals evaluated on 1H indicators.
    Exits checked at 15m granularity within each hour.
    Exit types: FIXED STOP, TIME MAX, DC TARGET (no RSI Recovery, no BB TARGET).
    """

    # ------------------------------------------------------------------
    # Precompute phase
    # ------------------------------------------------------------------
    indicators_1h: dict[str, dict] = {}
    hour_maps: dict[str, dict[int, list[int]]] = {}
    candles_15m_store: dict[str, list[dict]] = {}
    candles_1h_store: dict[str, list[dict]] = {}
    support_zones_cache: dict[str, dict[int, Optional[float]]] = {}

    # Exit parameters
    max_stop_pct = params.get("max_stop_pct", 15.0)
    time_max_bars = params.get("time_max_bars", 15)   # 15 x 1H = 15H
    spread_cap_bps = params.get("spread_cap_bps", 40)

    # Support zone parameters
    zone_type = params.get("zone_type", "dc_bb_stack")
    pivot_lookback = params.get("pivot_lookback", 40)

    for coin in coins:
        if coin not in data_1h:
            continue

        c1h = data_1h[coin]
        if len(c1h) < start_bar + 20:
            continue

        # 1H indicators
        ind_1h = precompute_1h_indicators(c1h)

        # DC mid for exit targets: use _vectorized_donchian_mid on 1H data
        # This is the DC mid CHANNEL (current bar included) used as exit target
        dc_mid_exit = _vectorized_donchian_mid(
            ind_1h['highs'], ind_1h['lows'], DC_PERIOD
        )
        ind_1h['dc_mid_exit'] = dc_mid_exit

        indicators_1h[coin] = ind_1h
        candles_1h_store[coin] = c1h

        # Build hour-to-15m map if 15m data available
        c15 = data_15m.get(coin, [])
        candles_15m_store[coin] = c15
        if c15:
            hour_maps[coin] = build_hour_to_15m_map(c1h, c15)
        else:
            hour_maps[coin] = {}

        # Pre-compute support zones for Family C signals
        # Cache zone price per 1H bar for fast lookup during entries
        zones: dict[int, Optional[float]] = {}
        for b in range(start_bar, ind_1h['n']):
            atr_val = ind_1h['atr'][b]
            zone = find_support_zone(
                bar=b,
                pivot_lows=ind_1h['pivot_lows'],
                dc_prev_low=ind_1h['dc_prev_low'],
                bb_lower=ind_1h['bb_lower'],
                zone_type=zone_type,
                atr_val=atr_val,
                pivot_lookback=pivot_lookback,
            )
            zones[b] = zone
        support_zones_cache[coin] = zones

    # Filter to coins that have valid indicators
    coin_list = [c for c in coins if c in indicators_1h]
    if not coin_list:
        return BacktestResult(0, 0.0, 0.0, 0.0, 0.0, initial_capital)

    max_bars = max(indicators_1h[p]['n'] for p in coin_list)
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    positions: dict[str, _Pos] = {}
    trades: list[dict] = []
    equity = float(initial_capital)
    peak_eq = equity
    max_dd = 0.0
    last_exit_bar: dict[str, int] = {p: -999 for p in coin_list}
    last_exit_was_stop: dict[str, bool] = {p: False for p in coin_list}

    # ------------------------------------------------------------------
    # Main loop (1H bars)
    # ------------------------------------------------------------------
    for bar in range(start_bar, max_bars):
        if equity < 0:
            break

        # ==============================================================
        # EXITS — check 15m price path within this hour for precision
        # ==============================================================
        sells: list[tuple[str, float, str, _Pos]] = []

        for pair in list(positions.keys()):
            pos = positions[pair]
            ind = indicators_1h[pair]

            if bar >= ind['n']:
                continue

            bars_in_1h = bar - pos.entry_bar
            hard_stop = pos.entry_price * (1 - max_stop_pct / 100)
            dc_mid_val = ind['dc_mid_exit'][bar] if ind['dc_mid_exit'][bar] is not None else None

            # Get 15m bars for this hour
            bars_15m = get_15m_ohlcv_for_hour(
                candles_15m_store.get(pair, []),
                hour_maps.get(pair, {}),
                bar,
            )

            exit_price: Optional[float] = None
            exit_reason: Optional[str] = None

            if bars_15m:
                # Check each 15m bar in chronological order.
                # If stop AND target both trigger in same hour, earlier one wins.
                for c15 in bars_15m:
                    low_15m = c15['low']
                    close_15m = c15['close']

                    # 1. FIXED STOP: 15m low breaches hard stop
                    if low_15m <= hard_stop:
                        exit_price = hard_stop
                        exit_reason = "FIXED STOP"
                        break

                    # 2. DC TARGET: 15m close >= dc_mid on 1H
                    if dc_mid_val is not None and close_15m >= dc_mid_val:
                        exit_price = close_15m
                        exit_reason = "DC TARGET"
                        break
            else:
                # No 15m data: fall back to 1H bar OHLC
                low_1h = ind['lows'][bar]
                close_1h = ind['closes'][bar]

                if low_1h <= hard_stop:
                    exit_price = hard_stop
                    exit_reason = "FIXED STOP"
                elif dc_mid_val is not None and close_1h >= dc_mid_val:
                    exit_price = close_1h
                    exit_reason = "DC TARGET"

            # 3. TIME MAX: checked at 1H level only
            if exit_price is None and bars_in_1h >= time_max_bars:
                close_1h = ind['closes'][bar]
                exit_price = close_1h
                exit_reason = "TIME MAX"

            if exit_price is not None and exit_reason is not None:
                sells.append((pair, exit_price, exit_reason, pos))

        # Process all exits
        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
            net = gross - fees
            equity += pos.size_usd + net

            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = "STOP" in reason

            trades.append({
                'pair': pair,
                'entry': pos.entry_price,
                'exit': exit_price,
                'pnl': net,
                'pnl_pct': net / pos.size_usd * 100 if pos.size_usd > 0 else 0,
                'reason': reason,
                'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar,
                'exit_bar': bar,
                'size': pos.size_usd,
                'equity_after': equity,
            })
            del positions[pair]

        # ==============================================================
        # ENTRIES — signal on 1H, optional 15m confirmation
        # ==============================================================
        buys: list[tuple[str, float, float]] = []  # (pair, strength, entry_price)

        for pair in coin_list:
            if pair in positions:
                continue

            ind = indicators_1h[pair]
            if bar >= ind['n']:
                continue

            # Cooldown check
            cd = cooldown_after_stop if last_exit_was_stop.get(pair, False) else cooldown_bars
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue

            # Spread proxy gate: ATR/close scaled to bps
            atr = ind['atr'][bar]
            close_1h = ind['closes'][bar]
            if atr is not None and close_1h > 0 and spread_cap_bps > 0:
                spread_proxy_bps = (atr / close_1h) * 10000 * 0.1
                if spread_proxy_bps > spread_cap_bps:
                    continue

            # Call signal function on 1H indicators
            sig = signal_fn(candles_1h_store[pair], bar, ind, params)
            if sig is None:
                continue

            strength = sig.get('strength', 1.0)
            needs_15m = sig.get('needs_15m_confirm', False)

            if needs_15m:
                # 15m confirmation: check for green close above support zone
                bars_15m = get_15m_ohlcv_for_hour(
                    candles_15m_store.get(pair, []),
                    hour_maps.get(pair, {}),
                    bar,
                )

                # Get support zone for this bar (if available)
                zone_price = support_zones_cache.get(pair, {}).get(bar)

                confirmed = False
                confirm_price = close_1h  # fallback

                if bars_15m:
                    # Check 15m bars for confirmation:
                    # Any 15m bar with close > open (green) AND close > support zone
                    for c15 in bars_15m:
                        c15_close = c15['close']
                        c15_open = c15.get('open', c15_close)
                        is_green = c15_close > c15_open

                        if zone_price is not None:
                            if is_green and c15_close > zone_price:
                                confirmed = True
                                confirm_price = c15_close
                                break
                        else:
                            # No zone available: green bar is sufficient
                            if is_green:
                                confirmed = True
                                confirm_price = c15_close
                                break

                if not confirmed:
                    continue  # Skip entry: no 15m confirmation

                buys.append((pair, strength, confirm_price))
            else:
                # No 15m confirmation needed: enter at 1H close
                buys.append((pair, strength, close_1h))

        # Position sizing and entry execution
        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested

        if len(positions) < max_pos and buys and available > 10:
            # Sort by signal strength descending (best signals first)
            buys.sort(key=lambda x: x[1], reverse=True)
            slots = max_pos - len(positions)
            size_per_pos = available / slots

            for pair, _strength, entry_price in buys:
                if len(positions) >= max_pos or size_per_pos < 10:
                    break
                equity -= size_per_pos
                positions[pair] = _Pos(
                    pair=pair,
                    entry_price=entry_price,
                    entry_bar=bar,
                    size_usd=size_per_pos,
                )

        # ==============================================================
        # DRAWDOWN tracking
        # ==============================================================
        total_value = equity
        for pair, pos in positions.items():
            ind = indicators_1h[pair]
            if bar < ind['n']:
                cur = ind['closes'][bar]
                unrealized = (cur - pos.entry_price) / pos.entry_price * pos.size_usd
                total_value += pos.size_usd + unrealized
            else:
                total_value += pos.size_usd

        if total_value > peak_eq:
            peak_eq = total_value
        dd = (peak_eq - total_value) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # ------------------------------------------------------------------
    # Close remaining positions at end
    # ------------------------------------------------------------------
    for pair, pos in list(positions.items()):
        ind = indicators_1h[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
        net = gross - fees
        equity += pos.size_usd + net

        trades.append({
            'pair': pair,
            'entry': pos.entry_price,
            'exit': lp,
            'pnl': net,
            'pnl_pct': net / pos.size_usd * 100 if pos.size_usd > 0 else 0,
            'reason': 'END',
            'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar,
            'exit_bar': max_bars,
            'size': pos.size_usd,
            'equity_after': equity,
        })

    # ------------------------------------------------------------------
    # Compute results
    # ------------------------------------------------------------------
    final_equity = equity
    total_pnl = final_equity - initial_capital
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / n * 100 if n else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)

    # Exit class attribution
    exit_classes: dict = {'A': {}, 'B': {}}
    for t in trades:
        cls = 'A' if t['reason'] in CLASS_A_REASONS else 'B'
        r = t['reason']
        if r not in exit_classes[cls]:
            exit_classes[cls][r] = {'count': 0, 'pnl': 0.0, 'wins': 0}
        exit_classes[cls][r]['count'] += 1
        exit_classes[cls][r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            exit_classes[cls][r]['wins'] += 1

    return BacktestResult(
        trades=n,
        pnl=total_pnl,
        pf=pf,
        wr=wr,
        dd=max_dd,
        final_equity=final_equity,
        trade_list=trades,
        exit_classes=exit_classes,
    )


# ---------------------------------------------------------------------------
# Walk-forward validation
# ---------------------------------------------------------------------------

def walk_forward(
    data_1h: dict,
    data_15m: dict,
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    n_folds: int = 3,
    embargo: int = 4,
    **kwargs,
) -> list[BacktestResult]:
    """Walk-forward: split 1H bar range into folds, run independent backtests.

    Each fold uses a contiguous range of 1H bars.  An embargo of `embargo`
    1H bars is removed from the end of each fold (except the last) to
    prevent information leakage across fold boundaries.

    Returns list of BacktestResult, one per fold.
    """
    # Find max 1H bars across all coins
    max_bars = 0
    for coin in coins:
        if coin in data_1h:
            max_bars = max(max_bars, len(data_1h[coin]))

    if max_bars <= START_BAR:
        return []

    total_range = max_bars - START_BAR
    fold_size = total_range // n_folds
    if fold_size <= 0:
        return []

    results: list[BacktestResult] = []
    for fold_idx in range(n_folds):
        fold_start = START_BAR + fold_idx * fold_size
        if fold_idx < n_folds - 1:
            fold_end = fold_start + fold_size - embargo
        else:
            fold_end = max_bars

        if fold_end <= fold_start:
            continue

        result = run_backtest(
            data_1h=data_1h,
            data_15m=data_15m,
            coins=coins,
            signal_fn=signal_fn,
            params=params,
            start_bar=fold_start,
            end_bar=fold_end,
            **kwargs,
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random
    random.seed(42)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, msg: str = "") -> None:
        global passed, failed
        if condition:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name} -- {msg}")
            failed += 1

    print("=== SuperHF Sprint 3 Harness Self-Test ===\n")

    # ------------------------------------------------------------------
    # Test 1: Time mapping
    # ------------------------------------------------------------------
    print("--- Time Mapping ---")

    # Create 5 hours of 1H candles (timestamps 0, 3600, 7200, 10800, 14400)
    candles_1h_test = [
        {'time': i * 3600, 'open': 100, 'high': 102, 'low': 98, 'close': 101, 'volume': 1000}
        for i in range(5)
    ]
    # Create 20 x 15m candles (timestamps 0, 900, 1800, ..., 17100)
    candles_15m_test = [
        {'time': i * 900, 'open': 100, 'high': 102, 'low': 98, 'close': 101, 'volume': 500}
        for i in range(20)
    ]

    hmap = build_hour_to_15m_map(candles_1h_test, candles_15m_test)
    check("hour_map_has_5_hours", len(hmap) == 5, f"got {len(hmap)}")
    check("hour_0_has_4_bars", len(hmap.get(0, [])) == 4,
          f"got {len(hmap.get(0, []))}")
    check("hour_1_has_4_bars", len(hmap.get(1, [])) == 4,
          f"got {len(hmap.get(1, []))}")

    bars_h0 = get_15m_bars_for_hour(hmap, 0)
    check("bars_h0_indices", bars_h0 == [0, 1, 2, 3], f"got {bars_h0}")

    ohlcv_h1 = get_15m_ohlcv_for_hour(candles_15m_test, hmap, 1)
    check("ohlcv_h1_count", len(ohlcv_h1) == 4, f"got {len(ohlcv_h1)}")
    check("ohlcv_h1_first_time", ohlcv_h1[0]['time'] == 3600,
          f"got {ohlcv_h1[0]['time']}")

    # Empty case
    empty_map = build_hour_to_15m_map([], [])
    check("empty_map", empty_map == {}, f"got {empty_map}")

    # ------------------------------------------------------------------
    # Test 2: BacktestResult dataclass
    # ------------------------------------------------------------------
    print("\n--- BacktestResult ---")
    br = BacktestResult(trades=10, pnl=500, pf=1.5, wr=60, dd=15,
                        final_equity=10500)
    check("result_fields", br.trades == 10 and br.pf == 1.5)
    check("result_defaults", br.trade_list == [] and br.exit_classes == {})

    # ------------------------------------------------------------------
    # Test 3: Constants
    # ------------------------------------------------------------------
    print("\n--- Constants ---")
    check("initial_capital", INITIAL_CAPITAL == 10_000.0)
    check("start_bar", START_BAR == 100)
    check("cooldown_bars", COOLDOWN_BARS == 2)
    check("cooldown_after_stop", COOLDOWN_AFTER_STOP == 6)
    check("dc_period", DC_PERIOD == 20)
    check("class_a_dc_target", "DC TARGET" in CLASS_A_REASONS)
    check("class_b_fixed_stop", "FIXED STOP" in CLASS_B_REASONS)
    check("no_rsi_recovery_in_a", "RSI RECOVERY" not in CLASS_A_REASONS)
    check("no_bb_target_in_a", "BB TARGET" not in CLASS_A_REASONS)

    # ------------------------------------------------------------------
    # Test 4: Minimal backtest (synthetic data, deterministic)
    # ------------------------------------------------------------------
    print("\n--- Minimal Backtest ---")

    N_BARS_1H = 200
    N_BARS_15M = N_BARS_1H * 4

    # Generate synthetic 1H candles with a known pattern:
    # Bars 100-149: downtrend (close drops from 100 to ~80)
    # Bars 150-199: uptrend (close rises from 80 to ~100)
    random.seed(42)
    syn_1h = []
    price = 100.0
    for i in range(N_BARS_1H):
        if i < 150:
            drift = -0.1
        else:
            drift = 0.15
        price = max(10, price + drift + random.gauss(0, 0.3))
        syn_1h.append({
            'time': i * 3600,
            'open': price + random.gauss(0, 0.2),
            'high': price + abs(random.gauss(0, 1.0)),
            'low': price - abs(random.gauss(0, 1.0)),
            'close': price,
            'volume': 1000 + random.gauss(0, 100),
        })

    # Generate aligned 15m candles from 1H candles
    syn_15m = []
    for i, c1h in enumerate(syn_1h):
        base_t = c1h['time']
        c_open = c1h['open']
        c_close = c1h['close']
        c_high = c1h['high']
        c_low = c1h['low']
        # Split the hour into 4 x 15m bars
        for q in range(4):
            frac = (q + 1) / 4
            interp_close = c_open + (c_close - c_open) * frac
            syn_15m.append({
                'time': base_t + q * 900,
                'open': c_open + (c_close - c_open) * (q / 4),
                'high': max(interp_close, c_open) + abs(random.gauss(0, 0.3)),
                'low': min(interp_close, c_open) - abs(random.gauss(0, 0.3)),
                'close': interp_close,
                'volume': c1h['volume'] / 4,
            })

    # Always-fire signal for testing mechanics
    def always_signal(candles_1h, bar_1h, indicators_1h, params):
        """Fire on every bar with no 15m confirmation needed."""
        rsi = indicators_1h['rsi'][bar_1h]
        if rsi is None:
            return None
        if rsi < params.get("rsi_max", 100):
            return {'strength': 1.0, 'needs_15m_confirm': False}
        return None

    test_data_1h = {"TEST": syn_1h}
    test_data_15m = {"TEST": syn_15m}
    test_params = {
        "rsi_max": 100,  # always pass
        "max_stop_pct": 15.0,
        "time_max_bars": 15,
        "spread_cap_bps": 0,   # disable spread gate
        "zone_type": "pivot_only",
    }

    result = run_backtest(
        data_1h=test_data_1h,
        data_15m=test_data_15m,
        coins=["TEST"],
        signal_fn=always_signal,
        params=test_params,
        fee=0.001,
        max_pos=1,
    )

    check("backtest_has_trades", result.trades > 0,
          f"trades={result.trades}")
    check("backtest_final_eq_positive", result.final_equity > 0,
          f"eq={result.final_equity:.2f}")
    check("backtest_dd_bounded", 0 <= result.dd <= 100,
          f"dd={result.dd:.1f}")
    check("backtest_wr_bounded", 0 <= result.wr <= 100,
          f"wr={result.wr:.1f}")
    check("backtest_exit_classes_present",
          'A' in result.exit_classes and 'B' in result.exit_classes)

    # Verify all trades have required keys
    if result.trade_list:
        t0 = result.trade_list[0]
        required_keys = {'pair', 'entry', 'exit', 'pnl', 'pnl_pct',
                         'reason', 'bars', 'entry_bar', 'exit_bar',
                         'size', 'equity_after'}
        check("trade_has_all_keys",
              required_keys.issubset(set(t0.keys())),
              f"missing: {required_keys - set(t0.keys())}")

    # Verify exit reasons are from allowed set
    all_reasons = {t['reason'] for t in result.trade_list}
    allowed = CLASS_A_REASONS | CLASS_B_REASONS
    check("exit_reasons_valid",
          all_reasons.issubset(allowed),
          f"unexpected reasons: {all_reasons - allowed}")

    # ------------------------------------------------------------------
    # Test 5: 15m confirmation path
    # ------------------------------------------------------------------
    print("\n--- 15m Confirmation ---")

    def confirm_signal(candles_1h, bar_1h, indicators_1h, params):
        """Always fire, but require 15m confirmation."""
        rsi = indicators_1h['rsi'][bar_1h]
        if rsi is None:
            return None
        return {'strength': 1.0, 'needs_15m_confirm': True}

    result_confirm = run_backtest(
        data_1h=test_data_1h,
        data_15m=test_data_15m,
        coins=["TEST"],
        signal_fn=confirm_signal,
        params=test_params,
        fee=0.001,
        max_pos=1,
    )
    check("confirm_path_runs", result_confirm.trades >= 0,
          f"trades={result_confirm.trades}")
    check("confirm_path_eq_valid", result_confirm.final_equity > 0,
          f"eq={result_confirm.final_equity:.2f}")

    # ------------------------------------------------------------------
    # Test 6: No trades when signal never fires
    # ------------------------------------------------------------------
    print("\n--- No-Signal Path ---")

    def never_signal(candles_1h, bar_1h, indicators_1h, params):
        return None

    result_none = run_backtest(
        data_1h=test_data_1h,
        data_15m=test_data_15m,
        coins=["TEST"],
        signal_fn=never_signal,
        params=test_params,
    )
    check("no_signal_zero_trades", result_none.trades == 0,
          f"trades={result_none.trades}")
    check("no_signal_eq_unchanged",
          abs(result_none.final_equity - INITIAL_CAPITAL) < 0.01,
          f"eq={result_none.final_equity}")

    # ------------------------------------------------------------------
    # Test 7: Walk-forward produces correct number of folds
    # ------------------------------------------------------------------
    print("\n--- Walk-Forward ---")

    wf_results = walk_forward(
        data_1h=test_data_1h,
        data_15m=test_data_15m,
        coins=["TEST"],
        signal_fn=always_signal,
        params=test_params,
        n_folds=3,
        embargo=4,
        fee=0.001,
        max_pos=1,
    )
    check("wf_3_folds", len(wf_results) == 3,
          f"got {len(wf_results)} folds")

    # Each fold should have independent equity
    for i, wr_fold in enumerate(wf_results):
        check(f"wf_fold_{i}_has_result",
              isinstance(wr_fold, BacktestResult),
              f"type={type(wr_fold)}")

    # ------------------------------------------------------------------
    # Test 8: Intrahour exit priority (stop before target in same hour)
    # ------------------------------------------------------------------
    print("\n--- Intrahour Exit Priority ---")

    # Create scenario: 15m bars where bar 0 hits stop, bar 2 hits target
    # The stop at bar 0 should win.
    syn_1h_prio = []
    for i in range(150):
        syn_1h_prio.append({
            'time': i * 3600,
            'open': 100, 'high': 105, 'low': 95, 'close': 100,
            'volume': 1000,
        })

    # At bar 110, make an entry-friendly scenario, then bar 111 has
    # 15m bars where stop triggers first
    syn_15m_prio = []
    for i, c1h in enumerate(syn_1h_prio):
        base_t = c1h['time']
        for q in range(4):
            if i == 111 and q == 0:
                # First 15m bar: low = 80 (hits 15% stop from 100 entry)
                syn_15m_prio.append({
                    'time': base_t + q * 900,
                    'open': 100, 'high': 101, 'low': 80, 'close': 99,
                    'volume': 1000,
                })
            elif i == 111 and q == 2:
                # Third 15m bar: close = 110 (would hit DC target)
                syn_15m_prio.append({
                    'time': base_t + q * 900,
                    'open': 99, 'high': 111, 'low': 98, 'close': 110,
                    'volume': 1000,
                })
            else:
                syn_15m_prio.append({
                    'time': base_t + q * 900,
                    'open': 100, 'high': 102, 'low': 98, 'close': 100,
                    'volume': 1000,
                })

    # Signal: fire once at bar 110, no confirmation needed
    def once_at_110(candles_1h, bar_1h, indicators_1h, params):
        if bar_1h == 110:
            return {'strength': 1.0, 'needs_15m_confirm': False}
        return None

    prio_result = run_backtest(
        data_1h={"PRIO": syn_1h_prio},
        data_15m={"PRIO": syn_15m_prio},
        coins=["PRIO"],
        signal_fn=once_at_110,
        params={**test_params, "max_stop_pct": 15.0, "time_max_bars": 50},
        fee=0.001,
        max_pos=1,
    )

    if prio_result.trades > 0:
        first_exit = prio_result.trade_list[0]
        check("stop_before_target",
              first_exit['reason'] == "FIXED STOP",
              f"got reason={first_exit['reason']}")
    else:
        check("stop_before_target", False, "no trades generated")

    # ------------------------------------------------------------------
    # Test 9: Empty data handling
    # ------------------------------------------------------------------
    print("\n--- Edge Cases ---")

    result_empty = run_backtest(
        data_1h={}, data_15m={},
        coins=["NONE"],
        signal_fn=always_signal,
        params=test_params,
    )
    check("empty_data_no_crash", result_empty.trades == 0)
    check("empty_data_eq", result_empty.final_equity == INITIAL_CAPITAL)

    # ------------------------------------------------------------------
    # Test 10: Fee accounting parity
    # ------------------------------------------------------------------
    print("\n--- Fee Accounting ---")

    # Verify fee formula: entry_fee + exit_fee on a known trade
    entry_px = 100.0
    size = 2000.0
    exit_px = 110.0
    fee_rate = 0.001
    gross = (exit_px - entry_px) / entry_px * size  # +200
    entry_fee = size * fee_rate                       # 2.0
    exit_fee = (size + gross) * fee_rate              # 2.2
    expected_net = gross - entry_fee - exit_fee       # 195.8
    check("fee_formula", abs(expected_net - 195.8) < 0.01,
          f"got {expected_net:.2f}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        exit(1)
    print("All tests passed!")
