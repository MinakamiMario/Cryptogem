# HF 1H Candle Data Availability Report

| Field | Value |
|-------|-------|
| Date | 2026-02-15 |
| Data source | `data/cache_parts_hf/1h/` (per-coin part files) |
| Manifest | `data/manifest_hf_1h.json` |
| Tiering source | `reports/hf/universe_tiering_001.json` |

## Manifest Summary

| Metric | Count |
|--------|-------|
| Total coins in manifest | 2134 |
| Done | 261 |
| Pending | 1873 |
| Failed | 0 |

### By Exchange

| Exchange | Done | Total | Pct |
|----------|------|-------|-----|
| Kraken | 261 | 614 | 42.5% |
| MEXC | 0 | 1520 | 0.0% |

### Part Files on Disk

| Exchange | Files |
|----------|-------|
| `kraken/` | 261 |
| `mexc/` | 0 |

Part files match manifest 1:1 (261 done = 261 files in `kraken/`, 0 in `mexc/`).

**Note**: Download halted at approximately the J-K alphabetical boundary on Kraken. MEXC download has not started.

## Tier Coverage

| Tier | Available | Total | Coverage |
|------|-----------|-------|----------|
| T1 (high-volume) | 43 | 100 | **43.0%** |
| T2 (mid-volume) | 92 | 216 | **42.6%** |

### T1 Available Coins (43)

All alphabetically A-J (download cursor position):

AB/USD, ACH/USD, ADA/USD, AKE/USD, ALGO/USD, APU/USD, ATH/USD, BANANAS31/USD, BEAM/USD, BLESS/USD, BONK/USD, BSX/USD, BTT/USD, CCD/USD, CHEEMS/USD, CHILLHOUSE/USD, COQ/USD, CPOOL/USD, CRV/USD, DENT/USD, DMC/USD, DOG/USD, DOGS/USD, ELX/USD, ENA/USD, FARTCOIN/USD, FET/USD, FLOKI/USD, FLR/USD, FWOG/USD, GALA/USD, GARI/USD, GHIBLI/USD, GIGA/USD, GRIFFAIN/USD, GRT/USD, GST/USD, GUN/USD, H/USD, HBAR/USD, HIPPO/USD, HONEY/USD, JASMY/USD

### T2 Available Coins (92)

0G/USD, 1INCH/USD, 2Z/USD, A/USD, ACT/USD, AERO/USD, AEVO/USD, AI3/USD, AIXBT/USD, AKT/USD, ALKIMI/USD, ALPHA/USD, ALT/USD, ALTHEA/USD, ANIME/USD, ANKR/USD, APE/USD, APR/USD, APT/USD, ARB/USD, ARC/USD, ARKM/USD, ARPA/USD, ASTER/USD, ASTR/USD, ATLAS/USD, ATOM/USD, AUDIO/USD, AURA/USD, AVAX/USD, AVNT/USD, BABY/USD, BAT/USD, BDXN/USD, BERT/USD, BICO/USD, BIGTIME/USD, BILLY/USD, BIO/USD, BLUAI/USD, BLUR/USD, BLZ/USD, BMT/USD, BOBA/USD, BODEN/USD, BTR/USD, CAMP/USD, CELO/USD, CELR/USD, CFG/USD, CHEX/USD, CHZ/USD, CLOUD/USD, CLV/USD, COTI/USD, CRO/USD, CTSI/USD, CVC/USD, CXT/USD, DBR/USD, DEEP/USD, DEGEN/USD, DOT/USD, DRIFT/USD, DRV/USD, DYDX/USD, DYM/USD, EDGE/USD, EIGEN/USD, ENJ/USD, ES/USD, ESX/USD, FHE/USD, FIDA/USD, FIL/USD, FIS/USD, FLOW/USD, FLUX/USD, GLMR/USD, GMT/USD, GOAT/USD, GOMINING/USD, HFT/USD, HOUSE/USD, HPOS10I/USD, ICNT/USD, ICP/USD, ICX/USD, IDEX/USD, IMX/USD, INIT/USD, IP/USD

## Bar Coverage Stats

| Scope | Count | Min | Max | Median | Mean |
|-------|-------|-----|-----|--------|------|
| All done coins | 261 | 81 | 722 | 721 | 703.7 |
| T1 available | 43 | 721 | 722 | 721 | 721.0 |
| T2 available | 92 | 721 | 721 | 721.0 | 721 |

### Bar Distribution (all done coins)

| Range | Count |
|-------|-------|
| <100 bars | 2 |
| 100-500 bars | 8 |
| 500-700 bars | 5 |
| 700+ bars | 246 |

**T1 and T2 available coins all have 721 bars (full history)**. Only non-tiered coins have low bar counts.

### Low Bar Coins (<500 bars)

| Coin | Bars |
|------|------|
| ALEO/USD | 415 |
| AZTEC/USD | 86 |
| BGB/USD | 391 |
| CASH/USD | 464 |
| CFX/USD | 223 |
| ESP/USD | 81 |
| FIDD/USD | 271 |
| HSK/USD | 490 |
| HYPE/USD | 440 |
| INX/USD | 388 |

None of these are T1 or T2 -- all are T3 or untiered.

## Missing Coins

### T1 Missing (57 coins)

| Coin | Exchange | Status |
|------|----------|--------|
| KAS/USD | kraken | pending |
| KEY/USD | kraken | pending |
| KOBAN/USD | kraken | pending |
| LINEA/USD | kraken | pending |
| LOBO/USD | kraken | pending |
| LOCKIN/USD | kraken | pending |
| LUNA/USD | kraken | pending |
| MEME/USD | kraken | pending |
| MEW/USD | kraken | pending |
| MIM/USD | unknown | NOT_IN_MANIFEST |
| MOG/USD | kraken | pending |
| MXC/USD | kraken | pending |
| NEIRO/USD | kraken | pending |
| NOT/USD | kraken | pending |
| NPC/USD | kraken | pending |
| PENGU/USD | kraken | pending |
| PEPE/USD | kraken | pending |
| PLUME/USD | kraken | pending |
| POL/USD | kraken | pending |
| PTB/USD | kraken | pending |
| PUMP/USD | kraken | pending |
| REKT/USD | kraken | pending |
| RIZE/USD | kraken | pending |
| RSR/USD | kraken | pending |
| SBR/USD | kraken | pending |
| SC/USD | kraken | pending |
| SEI/USD | kraken | pending |
| SGB/USD | kraken | pending |
| SHIB/USD | kraken | pending |
| SNEK/USD | kraken | pending |
| SPELL/USD | kraken | pending |
| SPX/USD | kraken | pending |
| STBL/USD | kraken | pending |
| STRK/USD | kraken | pending |
| SUI/USD | kraken | pending |
| SWELL/USD | kraken | pending |
| TITCOIN/USD | kraken | pending |
| TOSHI/USD | kraken | pending |
| TRX/USD | kraken | pending |
| TURBO/USD | kraken | pending |
| U/USD | kraken | pending |
| USELESS/USD | kraken | pending |
| WIF/USD | kraken | pending |
| WLFI/USD | kraken | pending |
| XAN/USD | kraken | pending |
| XCN/USD | kraken | pending |
| XDC/USD | kraken | pending |
| XDG/USD | unknown | NOT_IN_MANIFEST |
| XL1/USD | kraken | pending |
| XLM/USD | kraken | pending |
| XNY/USD | kraken | pending |
| XPL/USD | kraken | pending |
| XRP/USD | kraken | pending |
| ZBCN/USD | kraken | pending |
| ZEREBRO/USD | kraken | pending |
| ZK/USD | kraken | pending |
| ZORA/USD | kraken | pending |

- 55 coins pending (Kraken, download not yet reached)
- 2 coins not in manifest at all: MIM/USD, XDG/USD

### T2 Missing (124 coins)

124 coins with status `pending` (Kraken download not yet reached, all alphabetically J-Z):

JTO/USD, JUNO/USD, JUP/USD, KAVA/USD, KERNEL/USD, KET/USD, KMNO/USD, KTA/USD, LCX/USD, LDO/USD, LINK/USD, LMWR/USD, LOFI/USD, LRC/USD, MANA/USD, MELANIA/USD, MERL/USD, MF/USD, MINA/USD, MIRA/USD, MNGO/USD, MNT/USD, MOODENG/USD, MORPHO/USD, NANO/USD, NEAR/USD, NIL/USD, NOBODY/USD, NOS/USD, NYM/USD, OCEAN/USD, ODOS/USD, OGN/USD, OM/USD, OMG/USD, ONDO/USD, OP/USD, OSMO/USD, OXT/USD, PARTI/USD, PEAQ/USD, PERP/USD, PHA/USD, PLAY/USD, PNUT/USD, POLIS/USD, POND/USD, PONKE/USD, POPCAT/USD, PRCL/USD, PRIME/USD, PROMPT/USD, PUPS/USD, PYTH/USD, Q/USD, RARE/USD, RARI/USD, RAY/USD, REN/USD, RENDER/USD, RETARDIO/USD, REZ/USD, RUNE/USD, S/USD, SAGA/USD, SAHARA/USD, SAMO/USD, SAND/USD, SAPIEN/USD, SAROS/USD, SCRT/USD, SHX/USD, SIGMA/USD, SKY/USD, SLAY/USD, SNX/USD, SOL/USD, SPICE/USD, SPK/USD, SRM/USD, STORJ/USD, STX/USD, SUKU/USD, SUPER/USD, SUSHI/USD, SXT/USD, SYN/USD, SYRUP/USD, T/USD, TANSSI/USD, TIA/USD, TLM/USD, TNSR/USD, TOKEN/USD, TON/USD, TRAC/USD, TRU/USD, UFD/USD, UNI/USD, USUAL/USD, VANRY/USD, VELODROME/USD, VFY/USD, VINE/USD, VIRTUAL/USD, VSN/USD, W/USD, WAL/USD, WCT/USD, WELL/USD, WEN/USD, WLD/USD, WMTX/USD, WOO/USD, XMN/USD, XTZ/USD, XYO/USD, YALA/USD, YB/USD, ZBT/USD, ZEUS/USD, ZIG/USD, ZRO/USD, ZRX/USD

0 coins missing from manifest.

## Verdict

| Criterion | Threshold | Actual | Met? |
|-----------|-----------|--------|------|
| T1 coverage | >50% | 43.0% | **NO** |
| T2 coverage | >30% | 42.6% | **YES** |

### Status: **PARTIAL**

T2 meets the >30% threshold but T1 falls short of >50%. The gap is entirely due to the Kraken download being incomplete (stopped at ~J alphabetically). All downloaded coins have full 721-bar history. MEXC has not been started (0/1520).

### Action Required

1. **Resume Kraken 1H download** -- completing K-Z would bring T1 to ~100% and T2 to ~100% of Kraken coins
2. **Start MEXC 1H download** -- 1520 coins pending, needed for full T2 coverage
3. **Investigate MIM/USD, XDG/USD** -- 2 T1 coins not in manifest at all (possible ticker change or delisting)

Coverage is sufficient for **preliminary screening** on the A-J subset but **not sufficient for production screening** across the full universe.
