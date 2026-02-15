#!/usr/bin/env python3
"""Agent 4: Coin Attribution Analysis"""
import sys, json, time
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path("/Users/oussama/Cryptogem/trading_bot")
sys.path.insert(0, str(BASE_DIR))
from agent_team_v3 import precompute_all, run_backtest, INITIAL_CAPITAL

RESEARCH_CACHE = Path("/Users/oussama/Cryptogem/data/candle_cache_research_all.json")
LIVE_CACHE = BASE_DIR / "candle_cache_532.json"
REPORTS = Path("/Users/oussama/Cryptogem/reports")

C1 = {"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 15,
      "time_max_bars": 15, "tp_pct": 15, "vol_confirm": True, "vol_spike_mult": 3.0}

def coin_stats(trades):
    cd = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        c = t["pair"]
        cd[c]["trades"] += 1
        cd[c]["pnl"] += t["pnl"]
        if t["pnl"] > 0: cd[c]["wins"] += 1
    r = {}
    for coin, d in cd.items():
        n = d["trades"]
        r[coin] = {"coin": coin, "trades": n, "total_pnl": round(d["pnl"], 2),
                   "win_rate": round(d["wins"]/n*100, 1) if n else 0,
                   "avg_pnl": round(d["pnl"]/n, 2) if n else 0,
                   "wins": d["wins"], "losses": n - d["wins"], "is_winner": d["pnl"] > 0}
    return r

def metrics(bt):
    pf = bt["pf"]
    return {"trades": bt["trades"], "pnl": round(bt["pnl"], 2), "wr": round(bt["wr"], 1),
            "dd": round(bt["dd"], 1), "pf": round(pf, 2) if pf != float("inf") else 999.99,
            "final_equity": round(bt["final_equity"], 2)}

def bt_subset(data, coins, excl, cfg):
    sub = [c for c in coins if c not in excl]
    ind = precompute_all(data, sub)
    return run_backtest(ind, sub, cfg), sub

def main():
    t0 = time.time()
    print("=" * 70)
    print("COIN ATTRIBUTION ANALYSIS - Agent 4")
    print("=" * 70)

    # Load data
    print("\n[1] Loading RESEARCH_ALL...")
    with open(RESEARCH_CACHE) as f: rd = json.load(f)
    rc = sorted(k for k in rd.keys() if not k.startswith("_"))
    print(f"    {len(rc)} coins")

    print("[2] Loading LIVE_CURRENT...")
    with open(LIVE_CACHE) as f: ld = json.load(f)
    lc = sorted(k for k in ld.keys() if not k.startswith("_"))
    print(f"    {len(lc)} coins")

    live_set = set(lc)
    mexc_only = set(rc) - live_set
    print(f"    MEXC-only: {len(mexc_only)}")

    # Backtest RESEARCH_ALL
    print("\n[3] Backtest RESEARCH_ALL...")
    t1 = time.time()
    ri = precompute_all(rd, rc)
    btr = run_backtest(ri, rc, C1)
    print(f"    {time.time()-t1:.1f}s | {btr['trades']} tr | P&L ${btr['pnl']:+,.0f} | WR {btr['wr']:.1f}% | DD {btr['dd']:.1f}%")

    # Backtest LIVE
    print("\n[4] Backtest LIVE_CURRENT...")
    t2 = time.time()
    li = precompute_all(ld, lc)
    btl = run_backtest(li, lc, C1)
    print(f"    {time.time()-t2:.1f}s | {btl['trades']} tr | P&L ${btl['pnl']:+,.0f} | WR {btl['wr']:.1f}% | DD {btl['dd']:.1f}%")

    # Per-coin RESEARCH_ALL
    print("\n[5] Per-coin analysis...")
    rcs = coin_stats(btr["trade_list"])
    sc = sorted(rcs.values(), key=lambda x: x["total_pnl"], reverse=True)
    winners = [c for c in sc if c["is_winner"]]
    destroyers = [c for c in sc if not c["is_winner"]]
    t10w = sc[:10]
    t10d = sc[-10:][::-1]
    t25d = sc[-25:][::-1]

    print(f"    Total coins with trades: {len(rcs)}")
    print(f"    Winners: {len(winners)} | Destroyers: {len(destroyers)}")
    mxw = sum(1 for c in winners if c["coin"] in mexc_only)
    mxd = sum(1 for c in destroyers if c["coin"] in mexc_only)
    print(f"    MEXC-only: {mxw} winners, {mxd} destroyers")

    print("\n    TOP 10 WINNERS:")
    for c in t10w:
        mx = "MEXC" if c["coin"] in mexc_only else "KRK"
        print(f"    {c['coin']:<18} {c['trades']:>3}tr ${c['total_pnl']:>+9,.2f} WR:{c['win_rate']:>5.1f}% avg${c['avg_pnl']:>+8,.2f} [{mx}]")

    print("\n    TOP 10 DESTROYERS:")
    for c in t10d:
        mx = "MEXC" if c["coin"] in mexc_only else "KRK"
        print(f"    {c['coin']:<18} {c['trades']:>3}tr ${c['total_pnl']:>+9,.2f} WR:{c['win_rate']:>5.1f}% avg${c['avg_pnl']:>+8,.2f} [{mx}]")

    # Exclusion tests
    print("\n[6] Exclusion tests...")
    dc10 = set(c["coin"] for c in t10d)
    dc25 = set(c["coin"] for c in t25d)

    bt10, _ = bt_subset(rd, rc, dc10, C1)
    m10 = metrics(bt10)
    print(f"    Excl 10: {m10['trades']}tr P&L ${m10['pnl']:+,.0f} WR {m10['wr']:.1f}% DD {m10['dd']:.1f}%")

    bt25, _ = bt_subset(rd, rc, dc25, C1)
    m25 = metrics(bt25)
    print(f"    Excl 25: {m25['trades']}tr P&L ${m25['pnl']:+,.0f} WR {m25['wr']:.1f}% DD {m25['dd']:.1f}%")

    mf = metrics(btr)
    print(f"\n    Full:    {mf['trades']}tr ${mf['pnl']:+,.0f} WR{mf['wr']:.1f}% DD{mf['dd']:.1f}% PF{mf['pf']:.2f}")
    print(f"    Excl10:  {m10['trades']}tr ${m10['pnl']:+,.0f} WR{m10['wr']:.1f}% DD{m10['dd']:.1f}% PF{m10['pf']:.2f}")
    print(f"    Excl25:  {m25['trades']}tr ${m25['pnl']:+,.0f} WR{m25['wr']:.1f}% DD{m25['dd']:.1f}% PF{m25['pf']:.2f}")

    # LIVE LOO
    print("\n[7] LIVE_CURRENT LOO...")
    lcs = coin_stats(btl["trade_list"])
    ls = sorted(lcs.values(), key=lambda x: x["total_pnl"], reverse=True)
    tp = sum(max(0, c["total_pnl"]) for c in ls)
    eps = 1e-9
    t1p = ls[0]["total_pnl"] if ls else 0
    t1s = max(0, t1p) / max(eps, tp) * 100
    t3s = sum(max(0, c["total_pnl"]) for c in ls[:3]) / max(eps, tp) * 100
    print(f"    Top1: {ls[0]['coin'] if ls else 'N/A'} ${t1p:+,.2f} ({t1s:.1f}% of profit)")
    print(f"    Top3 share: {t3s:.1f}%")

    loo = []
    for cs in ls[:5]:
        cn = cs["coin"]
        bl, _ = bt_subset(ld, lc, {cn}, C1)
        ml = metrics(bl)
        dp = ml["pnl"] - btl["pnl"]
        loo.append({"coin": cn, "coin_pnl": cs["total_pnl"], "without_pnl": ml["pnl"],
                     "delta_pnl": round(dp, 2), "without_trades": ml["trades"], "without_wr": ml["wr"]})
        print(f"    Remove {cn:<16}: P&L ${ml['pnl']:>+9,.0f} (delta ${dp:>+7,.0f}) {ml['trades']}tr WR{ml['wr']:.1f}%")

    # Venue breakdown
    print("\n[8] Venue breakdown...")
    mxt = [c for c in rcs.values() if c["coin"] in mexc_only]
    mxwc = sum(1 for c in mxt if c["is_winner"])
    mxdc = sum(1 for c in mxt if not c["is_winner"])
    mxtp = sum(c["total_pnl"] for c in mxt)
    mxtr = sum(c["trades"] for c in mxt)

    lvt = [c for c in rcs.values() if c["coin"] in live_set]
    lvwc = sum(1 for c in lvt if c["is_winner"])
    lvdc = sum(1 for c in lvt if not c["is_winner"])
    lvtp = sum(c["total_pnl"] for c in lvt)
    lvtr = sum(c["trades"] for c in lvt)

    mxa = mxtp / max(1, mxtr)
    lva = lvtp / max(1, lvtr)
    print(f"    MEXC-only: {len(mxt)} coins {mxwc}W/{mxdc}D P&L ${mxtp:+,.0f} {mxtr}tr avg${mxa:+,.2f}")
    print(f"    Kraken:    {len(lvt)} coins {lvwc}W/{lvdc}D P&L ${lvtp:+,.0f} {lvtr}tr avg${lva:+,.2f}")

    ed = mxtp < 0 and lvtp > 0
    conc = "JA" if ed else "NEE"
    ev = f"MEXC P&L: ${mxtp:+,.0f} ({mxtr}tr avg${mxa:+,.2f}), Kraken P&L: ${lvtp:+,.0f} ({lvtr}tr avg${lva:+,.2f})"
    print(f"\n    CONCLUSIE: MEXC long-tail verwatert edge? {conc}")
    print(f"    {ev}")

    tt = time.time() - t0
    print(f"\n[DONE] {tt:.1f}s")

    # ===== SAVE JSON =====
    out = {
        "config": C1,
        "research_all": {
            "total_coins": len(rc), "coins_with_trades": len(rcs),
            "backtest": mf, "winners": len(winners), "destroyers": len(destroyers),
            "per_coin": {c["coin"]: c for c in sc},
            "top10_winners": [c["coin"] for c in t10w],
            "top10_destroyers": [c["coin"] for c in t10d],
            "exclusion_test_10": {"excluded": sorted(dc10), "metrics": m10},
            "exclusion_test_25": {"excluded": sorted(list(dc25)), "metrics": m25},
        },
        "live_current": {
            "total_coins": len(lc), "coins_with_trades": len(lcs),
            "backtest": metrics(btl), "top1_share_pct": round(t1s, 1),
            "top3_share_pct": round(t3s, 1),
            "top1_coin": ls[0]["coin"] if ls else None, "loo_results": loo,
            "per_coin": {c["coin"]: c for c in ls},
        },
        "venue_breakdown": {
            "mexc_only_count": len(mexc_only), "mexc_with_trades": len(mxt),
            "mexc_winners": mxwc, "mexc_destroyers": mxdc,
            "mexc_total_pnl": round(mxtp, 2), "mexc_trades": mxtr, "mexc_avg_pnl": round(mxa, 2),
            "kraken_with_trades": len(lvt), "kraken_winners": lvwc, "kraken_destroyers": lvdc,
            "kraken_total_pnl": round(lvtp, 2), "kraken_trades": lvtr, "kraken_avg_pnl": round(lva, 2),
        },
        "conclusion": {"mexc_dilutes_edge": conc, "evidence": ev},
    }
    with open(REPORTS / "coin_attribution.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved: {REPORTS}/coin_attribution.json")

    # ===== SAVE MARKDOWN =====
    pd10 = m10["pnl"] - mf["pnl"]
    pd25 = m25["pnl"] - mf["pnl"]
    wd10 = m10["wr"] - mf["wr"]
    wd25 = m25["wr"] - mf["wr"]
    re = m25["wr"] > 60 and m25["pnl"] > mf["pnl"] * 1.5

    m = []
    m.append("# Coin Attribution Analysis")
    m.append("")
    m.append(f"**Config C1**: `{json.dumps(C1)}`")
    m.append(f"**Runtime**: {tt:.1f}s")
    m.append("")
    m.append("## RESEARCH_ALL Universe")
    m.append("")
    m.append(f"- **Total coins**: {len(rc)}")
    m.append(f"- **Coins with trades**: {len(rcs)}")
    m.append(f"- **Positive coins**: {len(winners)} | **Negative coins**: {len(destroyers)}")
    m.append(f"- **Backtest**: {mf['trades']} trades | P&L ${mf['pnl']:+,.0f} | WR {mf['wr']:.1f}% | DD {mf['dd']:.1f}% | PF {mf['pf']:.2f}")
    m.append("")
    m.append("### Top 10 Winners")
    m.append("| # | Coin | Trades | Total P&L | WR% | Avg P&L | MEXC-only? |")
    m.append("|---|------|--------|-----------|-----|---------|------------|")
    for i, c in enumerate(t10w, 1):
        mx = "YES" if c["coin"] in mexc_only else "no"
        m.append(f"| {i} | {c['coin']} | {c['trades']} | ${c['total_pnl']:+,.2f} | {c['win_rate']:.1f}% | ${c['avg_pnl']:+,.2f} | {mx} |")
    m.append("")
    m.append("### Top 10 Destroyers (most negative first)")
    m.append("| # | Coin | Trades | Total P&L | WR% | Avg P&L | MEXC-only? |")
    m.append("|---|------|--------|-----------|-----|---------|------------|")
    for i, c in enumerate(t10d, 1):
        mx = "YES" if c["coin"] in mexc_only else "no"
        m.append(f"| {i} | {c['coin']} | {c['trades']} | ${c['total_pnl']:+,.2f} | {c['win_rate']:.1f}% | ${c['avg_pnl']:+,.2f} | {mx} |")
    m.append("")
    m.append("### Exclusion Test Results")
    m.append("| Scenario | Trades | P&L | WR% | DD% | PF |")
    m.append("|----------|--------|-----|-----|-----|-----|")
    m.append(f"| Full RESEARCH_ALL | {mf['trades']} | ${mf['pnl']:+,.0f} | {mf['wr']:.1f}% | {mf['dd']:.1f}% | {mf['pf']:.2f} |")
    m.append(f"| Excl. top 10 destroyers | {m10['trades']} | ${m10['pnl']:+,.0f} | {m10['wr']:.1f}% | {m10['dd']:.1f}% | {m10['pf']:.2f} |")
    m.append(f"| Excl. top 25 destroyers | {m25['trades']} | ${m25['pnl']:+,.0f} | {m25['wr']:.1f}% | {m25['dd']:.1f}% | {m25['pf']:.2f} |")
    m.append("")
    m.append("**Exclusion impact**:")
    m.append(f"- Excl. 10: P&L delta ${pd10:+,.0f}, WR delta {wd10:+.1f}pp")
    m.append(f"- Excl. 25: P&L delta ${pd25:+,.0f}, WR delta {wd25:+.1f}pp")
    re_str = "JA" if re else "NEE"
    wr_str = "JA" if m25["wr"] > 60 else "NEE"
    pnl_str = "JA" if pd25 > mf["pnl"] * 0.5 else "NEE"
    m.append(f"- **Does excluding destroyers restore edge?** {re_str} (WR>60%: {wr_str}, P&L significantly higher: {pnl_str})")
    m.append("")
    m.append("## LIVE_CURRENT Universe")
    m.append("")
    lm = metrics(btl)
    m.append(f"- **Total coins**: {len(lc)}")
    m.append(f"- **Coins with trades**: {len(lcs)}")
    m.append(f"- **Backtest**: {lm['trades']} trades | P&L ${lm['pnl']:+,.0f} | WR {lm['wr']:.1f}% | DD {lm['dd']:.1f}%")
    top1name = ls[0]["coin"] if ls else "N/A"
    m.append(f"- **Top 1 coin share**: {top1name} = {t1s:.1f}% of profit")
    m.append(f"- **Top 3 coins share**: {t3s:.1f}% of total profit")
    m.append("")
    m.append("### Leave-One-Out (Top 5 coins)")
    m.append("| Coin | Coin P&L | Without P&L | Delta | Without Trades | Without WR% |")
    m.append("|------|----------|-------------|-------|----------------|-------------|")
    for r in loo:
        m.append(f"| {r['coin']} | ${r['coin_pnl']:+,.2f} | ${r['without_pnl']:+,.0f} | ${r['delta_pnl']:+,.0f} | {r['without_trades']} | {r['without_wr']:.1f}% |")
    m.append("")
    m.append("## Venue Breakdown")
    m.append("| Venue | Coins w/ Trades | Winners | Destroyers | Total P&L | Trades | Avg P&L/trade |")
    m.append("|-------|-----------------|---------|------------|-----------|--------|---------------|")
    m.append(f"| MEXC-only | {len(mxt)} | {mxwc} | {mxdc} | ${mxtp:+,.0f} | {mxtr} | ${mxa:+,.2f} |")
    m.append(f"| Kraken | {len(lvt)} | {lvwc} | {lvdc} | ${lvtp:+,.0f} | {lvtr} | ${lva:+,.2f} |")
    m.append("")
    m.append("## Conclusie")
    m.append("")
    m.append(f"**MEXC long-tail verwatert edge door strategie-mismatch? {conc}**")
    m.append("")
    m.append(ev)
    m.append("")
    if conc == "JA":
        m.append("De MEXC-only coins dragen negatief bij aan het totaalresultaat.")
        m.append("De strategie presteert beter op Kraken-coins dan op de MEXC long-tail.")
    else:
        m.append("De MEXC-only coins dragen niet significant negatief bij.")
        m.append("De strategie presteert vergelijkbaar op beide venues.")

    with open(REPORTS / "coin_attribution.md", "w") as f:
        f.write("\n".join(m))
    print(f"Saved: {REPORTS}/coin_attribution.md")

if __name__ == "__main__":
    main()
