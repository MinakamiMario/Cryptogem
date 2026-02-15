#\!/usr/bin/env python3
import sys, json, time, hashlib, statistics
from pathlib import Path
from datetime import datetime
BASE_DIR = Path("/Users/oussama/Cryptogem")
sys.path.insert(0, str(BASE_DIR / "trading_bot"))
from agent_team_v3 import precompute_all, run_backtest, normalize_cfg, KRAKEN_FEE, INITIAL_CAPITAL, START_BAR
from robustness_harness import run_candidate
RA = BASE_DIR / "data" / "candle_cache_research_all.json"
TP = BASE_DIR / "data" / "candle_cache_tradeable.json"
RD = BASE_DIR / "reports"
C1 = {"exit_type":"tp_sl","max_pos":1,"rsi_max":45,"sl_pct":15,"time_max_bars":15,"tp_pct":15,"vol_confirm":True,"vol_spike_mult":3.0}
GB = {"exit_type":"tp_sl","max_pos":1,"rsi_max":45,"sl_pct":10,"time_max_bars":15,"tp_pct":12,"vol_confirm":True,"vol_spike_mult":2.5}

def build():
    t0=time.time()
    with open(RA) as f: raw=json.load(f)
    cd={k:v for k,v in raw.items() if not k.startswith("_")}
    tot=len(cd); mb=max(len(v) for v in cd.values())
    print(f"Coins:{tot} MaxBars:{mb}")
    rm={"coverage":[],"gap_rate":[],"min_volume":[],"no_flatline":[],"price_valid":[]}
    ps={}
    for p,cn in cd.items():
        n=len(cn)
        if n<0.95*mb: rm["coverage"].append(p); continue
        g=sum(1 for i in range(1,n) if cn[i]["time"]-cn[i-1]["time"]>14400)
        if g/n>0.02: rm["gap_rate"].append(p); continue
        dv=[c["close"]*c.get("volume",0) for c in cn]
        if statistics.median(dv)<=100: rm["min_volume"].append(p); continue
        mx,cu=1,1
        for i in range(1,n):
            if cn[i]["close"]==cn[i-1]["close"]: cu+=1; mx=max(mx,cu)
            else: cu=1
        if mx>=20: rm["no_flatline"].append(p); continue
        if any(c["close"]<=0 for c in cn): rm["price_valid"].append(p); continue
        ps[p]=cn
    np2=len(ps); pct=round(np2/tot*100,1)
    for f2,l in rm.items(): print(f"  {f2:<20}{len(l):>6}")
    print(f"  PASSED: {np2} ({pct}%)")
    fs={"total_input":tot,"max_bars":mb,"coverage_threshold":int(0.95*mb),"removed_per_filter":{k:len(v) for k,v in rm.items()},"coins_passing":np2,"pass_rate_pct":pct}
    out=dict(ps)
    out["_timestamp"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out["_universe"]="tradeable"; out["_coins"]=np2
    out["_filters_applied"]=["coverage>=95%","gap_rate<=2%","med_dollar_vol>100","max_consec_flat<20","all_closes>0"]
    with open(TP,"w") as f: json.dump(out,f)
    h=hashlib.md5()
    with open(TP,"rb") as fh:
        for ch in iter(lambda:fh.read(8192),b""): h.update(ch)
    m5=h.hexdigest(); sz=TP.stat().st_size/1e6
    print(f"MD5:{m5} Size:{sz:.1f}MB Done:{time.time()-t0:.1f}s")
    fs["md5"]=m5; fs["file_path"]=str(TP)
    return ps,fs

def harness(td):
    co=[k for k in td if not k.startswith("_")]
    print(f"Coins:{len(co)}")
    t0=time.time(); ind=precompute_all(td,co)
    print(f"Precompute:{time.time()-t0:.1f}s")
    res={}
    for ci,lb,cf in [("C1_TPSL_RSI45","tp_sl RSI45 VolSpk3.0 TP15/SL15",C1),("GRID_BEST","tp_sl RSI45 VolSpk2.5 TP12/SL10",GB)]:
        print(f">>> {ci}"); r=run_candidate(ind,co,cf,ci,lb); res[ci]=r
    return res

def xm(r):
    b=r.get("baseline",{}); wf=r.get("walk_forward",{}); fr=r.get("friction",{})
    mc=r.get("monte_carlo",{}); jt=r.get("param_jitter",{}); uv=r.get("universe",{})
    f2=fr.get("matrix",{}).get("2.0x_fee+20bps",{}); co=uv.get("concentration",{})
    return {"trades":b.get("trades",0),"pnl":b.get("pnl",0),"wr":b.get("wr",0),"pf":b.get("pf",0),"dd":b.get("dd",0),"wf_pass":wf.get("wf_label","?"),"wf_go":wf.get("go",False),"wf_soft_go":wf.get("soft_go",False),"friction_2x_20bps_pnl":f2.get("pnl","?"),"friction_go":fr.get("go",False),"jitter_pct":jt.get("positive_pct",0),"jitter_go":jt.get("go",False),"mc_ruin_pct":mc.get("ruin_prob_pct","?"),"mc_go":mc.get("go",False),"mc_p95_dd":mc.get("max_dd",{}).get("p95","?"),"top1_share":round(co.get("top1_share",0)*100,1),"top3_share":round(co.get("top3_share",0)*100,1),"univ_go":uv.get("go",False),"verdict":r.get("verdict","?"),"fails":r.get("fails",[]),"elapsed_s":r.get("elapsed_s",0)}

def save(res,fs):
    RD.mkdir(exist_ok=True)
    met={ci:xm(r) for ci,r in res.items()}
    jo={"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"universe":"tradeable","filter_stats":fs,"results":{}}
    for ci,r in res.items(): jo["results"][ci]={"metrics":met[ci],"full_result":r}
    jp=RD/"tradeable_universe_results.json"
    with open(jp,"w") as f: json.dump(jo,f,indent=2,default=str)
    print(f"JSON:{jp}")
    m1=met.get("C1_TPSL_RSI45",{}); m2=met.get("GRID_BEST",{})
    md=["# Tradeable Universe: Harness Results",""]
    md.append("**Generated**: "+datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    md.append("**Cache**: "+chr(96)+fs["file_path"]+chr(96))
    md.append("**MD5**: "+chr(96)+fs["md5"]+chr(96))
    md.append("**Coins**: "+str(fs["coins_passing"])+" / "+str(fs["total_input"])+" ("+str(fs["pass_rate_pct"])+"%)"); md.append("")
    md.append("## Filter Statistics"); md.append("")
    md.append("| Filter | Removed | Remaining |"); md.append("|--------|---------|-----------|")
    rm=fs["total_input"]
    for ft in ["coverage","gap_rate","min_volume","no_flatline","price_valid"]:
        rv=fs["removed_per_filter"][ft]; rm-=rv; md.append("| "+ft+" | "+str(rv)+" | "+str(rm)+" |")
    md.append("| **TOTAL** | | **"+str(fs["coins_passing"])+"** |"); md.append("")
    md.append("## Config Comparison"); md.append("")
    md.append("| Metric | C1_TPSL_RSI45 | GRID_BEST |"); md.append("|--------|---------------|-----------|")
    for lb,ky in [("Trades","trades"),("PnL","pnl"),("WR%","wr"),("PF","pf"),("DD%","dd"),("WF","wf_pass"),("Fric2x20","friction_2x_20bps_pnl"),("Jitter%","jitter_pct"),("MCruin","mc_ruin_pct"),("MCp95DD","mc_p95_dd"),("Top1%","top1_share"),("Top3%","top3_share"),("Verdict","verdict")]:
        md.append("| "+lb+" | "+str(m1.get(ky,"?"))+" | "+str(m2.get(ky,"?"))+" |")
    md.append(""); md.append("## Verdicts"); md.append("")
    for ci in ["C1_TPSL_RSI45","GRID_BEST"]:
        m=met.get(ci,{}); md.append("### "+ci+": **"+str(m.get("verdict","?"))+"**"); md.append("")
        fl=m.get("fails",[])
        if fl:
            for f2 in fl: md.append("- FAIL: "+str(f2))
        else: md.append("- All tests passed")
        md.append("")
    mp=RD/"tradeable_universe_results.md"
    with open(mp,"w") as f: f.write(chr(10).join(md))
    print(f"MD:{mp}")
    return met

if __name__=="__main__":
    t0=time.time()
    td,fs=build()
    res=harness(td)
    met=save(res,fs)
    print(f"TOTAL:{time.time()-t0:.1f}s")
    for ci in ["C1_TPSL_RSI45","GRID_BEST"]:
        m=met[ci]; print(f"  {ci}: {m[chr(118)+chr(101)+chr(114)+chr(100)+chr(105)+chr(99)+chr(116)]} | {m[chr(116)+chr(114)+chr(97)+chr(100)+chr(101)+chr(115)]}tr {m[chr(112)+chr(110)+chr(108)]} WR{m[chr(119)+chr(114)]}% DD{m[chr(100)+chr(100)]}% WF{m[chr(119)+chr(102)+chr(95)+chr(112)+chr(97)+chr(115)+chr(115)]}")