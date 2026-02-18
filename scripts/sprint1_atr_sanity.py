"""
Sprint 1 Sanity Check: RSI MR entry + ATR-based TP/SL exits.

Tests whether the entry signal has latent edge when combined with
volatility-aware exits (k*ATR) instead of fixed % exits.

9 combos: k_sl ∈ {1.5, 2.0, 2.5} × k_tp ∈ {2.0, 3.0, 4.0}
Time limits: 10, 15, 20 bars (one per k_tp tier)
RSI entry: 25 (best from Sprint 1)
"""
import sys, json, time, importlib
sys.path.insert(0, ".")
sys.path.insert(0, "trading_bot")

_ind = importlib.import_module("strategies.4h.sprint1.indicators")
_eng = importlib.import_module("strategies.4h.sprint1.engine")

# ── ATR-based signal_fn ──────────────────────────────────────────────

def signal_rsi_mr_atr(candles, bar, indicators, params):
    """RSI MR entry (same as H4H-01a) with ATR-scaled exits."""
    rsi = indicators["rsi"][bar]
    if rsi is None:
        return None

    rsi_entry = params.get("rsi_entry", 25)
    if rsi >= rsi_entry:
        return None

    closes = indicators["closes"]
    if bar < 1 or closes[bar] <= closes[bar - 1]:
        return None  # green bar bounce confirm

    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    if cur_vol < vol_avg * 0.5:
        return None

    # ATR-based exits
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None

    entry_price = closes[bar]
    k_sl = params.get("k_sl", 2.0)
    k_tp = params.get("k_tp", 3.0)
    tm = params.get("time_limit", 15)

    return {
        "stop_price": entry_price - k_sl * atr,
        "target_price": entry_price + k_tp * atr,
        "time_limit": tm,
        "strength": (rsi_entry - rsi) / rsi_entry,
    }


# ── Sweep grid ────────────────────────────────────────────────────────

GRID = []
for k_sl in [1.5, 2.0, 2.5]:
    for k_tp, tm in [(2.0, 10), (3.0, 15), (4.0, 20)]:
        GRID.append({
            "id": f"atr_sl{k_sl}_tp{k_tp}_tm{tm}",
            "params": {"rsi_entry": 25, "k_sl": k_sl, "k_tp": k_tp, "time_limit": tm, "max_pos": 3},
        })

# ── Run ──────────────────────────────────────────────────────────────

def main():
    with open("trading_bot/candle_cache_532.json") as f:
        data = json.load(f)

    with open("strategies/4h/universe_sprint1.json") as f:
        univ = json.load(f)
    coins = univ["coins"]

    print(f"Precomputing indicators for {len(coins)} coins...")
    t0 = time.time()
    indicators = _ind.precompute_all(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s\n")

    # Sprint 1 baseline for comparison
    print(f"{'ID':<28s} {'Tr':>4s} {'WR%':>5s} {'PF':>5s} {'DD%':>5s} {'P&L':>9s}  {'STOP':>4s} {'TP':>4s} {'TM':>4s} {'END':>4s}")
    print("-" * 90)

    # First: fixed baseline (Sprint 1 best = PF 0.89)
    _hyp = importlib.import_module("strategies.4h.sprint1.hypotheses")
    signal_h4h01_rsi_mr = _hyp.signal_h4h01_rsi_mr
    baseline_params = {"rsi_entry": 25, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3}
    bt = _eng.run_backtest(data, coins, signal_h4h01_rsi_mr, baseline_params, indicators)
    ec = bt.exit_classes
    n_stop = sum(v["count"] for v in ec.get("B", {}).values() if "STOP" in list(ec["B"].keys())[list(ec["B"].values()).index(v)] if "STOP" in list(ec["B"].keys())[list(ec["B"].values()).index(v)])
    # simpler approach
    stop_ct = ec.get("B", {}).get("FIXED STOP", {}).get("count", 0)
    tp_ct = ec.get("A", {}).get("PROFIT TARGET", {}).get("count", 0)
    tm_ct = ec.get("B", {}).get("TIME MAX", {}).get("count", 0)
    end_ct = ec.get("B", {}).get("END", {}).get("count", 0)
    print(f"{'BASELINE fixed%':<28s} {bt.trades:4d} {bt.wr:5.1f} {bt.pf:5.2f} {bt.dd:5.1f} {bt.pnl:+9.2f}  {stop_ct:4d} {tp_ct:4d} {tm_ct:4d} {end_ct:4d}")
    print()

    # ATR grid
    results = []
    for cfg in GRID:
        bt = _eng.run_backtest(data, coins, signal_rsi_mr_atr, cfg["params"], indicators)
        ec = bt.exit_classes
        stop_ct = ec.get("B", {}).get("FIXED STOP", {}).get("count", 0)
        tp_ct = ec.get("A", {}).get("PROFIT TARGET", {}).get("count", 0)
        tm_ct = ec.get("B", {}).get("TIME MAX", {}).get("count", 0)
        end_ct = ec.get("B", {}).get("END", {}).get("count", 0)

        print(f"{cfg['id']:<28s} {bt.trades:4d} {bt.wr:5.1f} {bt.pf:5.2f} {bt.dd:5.1f} {bt.pnl:+9.2f}  {stop_ct:4d} {tp_ct:4d} {tm_ct:4d} {end_ct:4d}")
        results.append({
            "id": cfg["id"], "params": cfg["params"],
            "trades": bt.trades, "wr": bt.wr, "pf": bt.pf, "dd": bt.dd, "pnl": bt.pnl,
            "exits": {"stop": stop_ct, "tp": tp_ct, "tm": tm_ct, "end": end_ct},
        })

    print()
    best = max(results, key=lambda x: x["pf"])
    print(f"Best ATR config: {best['id']} | PF={best['pf']:.2f} | P&L=${best['pnl']:+.2f} | DD={best['dd']:.1f}%")
    print(f"Baseline (fixed %):         | PF=0.89 | P&L=$-513 | DD=37.9%")

    if best["pf"] > 1.1:
        print("\n⚡ PF > 1.1 — entry signal HAS latent edge, exit calibration was the problem!")
    elif best["pf"] > 1.0:
        print("\n📊 PF > 1.0 — marginal improvement, ATR helps but entry still weak.")
    else:
        print("\n❌ PF < 1.0 — entry signal genuinely has no edge, regardless of exit type.")

    # Save results
    out = {"baseline_pf": 0.89, "grid": results, "best": best}
    with open("reports/4h/sprint1_atr_sanity.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: reports/4h/sprint1_atr_sanity.json")


if __name__ == "__main__":
    main()
