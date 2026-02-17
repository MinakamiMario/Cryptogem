# Data Architecture

## DATA_ROOT

All datasets live in `~/CryptogemData` (configurable via `.env` → `DATA_ROOT`).
The repo's `data/` is a symlink facade pointing at the legacy import — do NOT write to it.

## Structure

- `raw/` — immutable source data (orderbook snapshots, trade logs)
- `derived/` — computed artifacts (candle caches, VWAP aggregations, cost regimes)
- `manifests/registry.json` — dataset catalog with `canonical_path` + `status` (legacy|canonical)
- `_legacy_import/` — read-only dump of pre-migration `data/` dir. Locked with `chmod a-w`.

## Rules

- **New downloads go to `raw/` or `derived/`, NEVER to `_legacy_import/` or `data/` directly.**
- Registry entries track both `path` (legacy) and `canonical_path` (new location).
- Run `python3 ~/CryptogemData/dataset_verify.py` to check all paths + sizes.

## Bootstrap (new machine)

```bash
# 1. Set DATA_ROOT
cp .env.example .env          # edit DATA_ROOT if non-default

# 2. Create structure
mkdir -p ~/CryptogemData/{raw,derived,manifests,reports_archive}

# 3. Restore data (from backup/transfer)
#    Copy raw/ and derived/ contents to ~/CryptogemData/

# 4. Symlink for backward compat
ln -s ~/CryptogemData/_legacy_import/<timestamp> data

# 5. Verify
python3 ~/CryptogemData/dataset_verify.py
make check   # 66/66 should pass
```
