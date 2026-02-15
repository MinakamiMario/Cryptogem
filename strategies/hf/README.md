# HF Strategy — Development

High Frequency strategy research folder.

## Status: Development

This strategy is in early research phase. No validated configs yet.

## Usage

```bash
make hf-check    # Run HF tests (placeholder)
```

## Architecture

HF imports the shared backtest engine from `trading_bot/`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "trading_bot"))
from agent_team_v3 import precompute_all, run_backtest, normalize_cfg
```

No files were moved — `trading_bot/` remains the shared engine.

## Isolation Rules

- HF changes MUST NOT modify files in `trading_bot/` without running `make check`
- HF has its own configs, scripts, and reports
- GRID_BEST validation is enforced via `scripts/ci_guard.sh`
