"""
Data Resolver for 4H Strategy Research

Resolves dataset_id -> file path using the CryptogemData registry.
Supports:
- dataset_id lookup from registry.json
- DATA_ROOT environment variable override
- Fallback to trading_bot/candle_cache_532.json for backward compatibility
- Validation of file existence and basic integrity
- Alias support for common datasets

Usage:
    from strategies.4h.data_resolver import resolve_dataset, list_datasets

    path = resolve_dataset("candle_cache_532")          # legacy alias
    path = resolve_dataset("4h_default")                 # convenience alias
    path = resolve_dataset("ohlcv_4h_kraken_spot_usd_526")  # exact registry ID
    datasets = list_datasets()                           # list all available
    datasets = list_datasets(status_filter="canonical")  # only canonical
"""

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# DatasetInfo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetInfo:
    """Immutable descriptor for a single dataset in the registry."""

    dataset_id: str
    canonical_path: Optional[Path]
    legacy_path: Optional[Path]
    status: str  # "canonical" or "legacy"
    description: str
    size_mb: Optional[float] = None
    coins: Optional[int] = None
    timeframe: Optional[str] = None
    exchange: Optional[str] = None
    used_by: tuple = field(default_factory=tuple)
    note: Optional[str] = None

    def resolved_path(self, data_root: Path) -> Optional[Path]:
        """Return the best available absolute path for this dataset.

        Prefers canonical_path when it exists on disk, falls back to
        legacy_path (resolved relative to data_root).
        """
        if self.canonical_path is not None:
            abs_canonical = data_root / self.canonical_path
            if abs_canonical.exists():
                return abs_canonical
        if self.legacy_path is not None:
            abs_legacy = data_root / self.legacy_path
            if abs_legacy.exists():
                return abs_legacy
        return None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_ROOT = Path.home() / "CryptogemData"
REGISTRY_REL_PATH = Path("manifests") / "registry.json"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Fallback for backward compatibility (the 4H dataset lives in-repo)
LEGACY_CACHE = REPO_ROOT / "trading_bot" / "candle_cache_532.json"

# Aliases map human-friendly names to canonical registry IDs.
# Thread-safe: dict is immutable after module load.
_ALIASES: Dict[str, str] = {
    # 4H DualConfirm (main trading bot dataset)
    "4h_default": "ohlcv_4h_kraken_spot_usd_526",
    "4h_kraken": "ohlcv_4h_kraken_spot_usd_526",
    "4h_kraken_526": "ohlcv_4h_kraken_spot_usd_526",
    "candle_cache_532": "ohlcv_4h_kraken_spot_usd_526",
    # MEXC 1H (HF research)
    "1h_mexc": "ohlcv_1h_mexc_spot_usd_hf_316",
    "1h_mexc_316": "ohlcv_1h_mexc_spot_usd_hf_316",
    # Bybit 1H
    "1h_bybit": "ohlcv_1h_bybit_spot_usd_454",
    "1h_bybit_454": "ohlcv_1h_bybit_spot_usd_454",
    # Bybit 1H real VWAP
    "1h_bybit_vwap": "ohlcv_1h_bybit_spot_usd_real_vwap_166",
    "1h_bybit_real_vwap": "ohlcv_1h_bybit_spot_usd_real_vwap_166",
    # Bybit 1m
    "1m_bybit": "ohlcv_1m_bybit_spot_usd_166",
    "1m_bybit_166": "ohlcv_1m_bybit_spot_usd_166",
    # Kraken 1H parts
    "1h_kraken": "ohlcv_1h_kraken_spot_usd",
    # Orderbook snapshots
    "ob_mexc": "orderbook_mexc_spot_001",
    "ob_bybit": "orderbook_bybit_spot_001",
}


# ---------------------------------------------------------------------------
# Thread-safe registry cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cached_registry: Optional[Dict[str, Any]] = None
_cached_data_root: Optional[Path] = None


def _invalidate_cache() -> None:
    """Clear the cached registry (useful for testing)."""
    global _cached_registry, _cached_data_root
    with _cache_lock:
        _cached_registry = None
        _cached_data_root = None


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def get_data_root() -> Path:
    """Return DATA_ROOT from environment, .env file, or default.

    Resolution order:
    1. os.environ["DATA_ROOT"]
    2. .env file in REPO_ROOT (simple KEY=VALUE parsing)
    3. DEFAULT_DATA_ROOT (~/CryptogemData)
    """
    # 1. Environment variable
    env_val = os.environ.get("DATA_ROOT")
    if env_val:
        return Path(env_val).expanduser().resolve()

    # 2. .env file in repo root
    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.is_file():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == "DATA_ROOT" and value.strip():
                        return Path(value.strip()).expanduser().resolve()
        except OSError:
            pass  # Fall through to default

    # 3. Default
    return DEFAULT_DATA_ROOT.expanduser().resolve()


def load_registry(data_root: Optional[Path] = None) -> Dict[str, Any]:
    """Load and parse registry.json, with thread-safe caching.

    Returns the parsed JSON dict. Raises FileNotFoundError if the
    registry file does not exist (callers can still use fallback).
    """
    global _cached_registry, _cached_data_root

    if data_root is None:
        data_root = get_data_root()

    with _cache_lock:
        if _cached_registry is not None and _cached_data_root == data_root:
            return _cached_registry

    registry_path = data_root / REGISTRY_REL_PATH

    if not registry_path.is_file():
        raise FileNotFoundError(
            f"Registry not found at {registry_path}. "
            f"DATA_ROOT={data_root}. "
            f"Run 'python3 ~/CryptogemData/dataset_verify.py' to check setup."
        )

    with open(registry_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    with _cache_lock:
        _cached_registry = raw
        _cached_data_root = data_root

    return raw


def _parse_dataset(entry: Dict[str, Any]) -> DatasetInfo:
    """Parse a single registry entry dict into a DatasetInfo."""
    canonical = entry.get("canonical_path")
    legacy = entry.get("path")
    used_by = entry.get("used_by", [])

    return DatasetInfo(
        dataset_id=entry["id"],
        canonical_path=Path(canonical) if canonical else None,
        legacy_path=Path(legacy) if legacy else None,
        status=entry.get("status", "unknown"),
        description=entry.get("description", ""),
        size_mb=entry.get("size_mb"),
        coins=entry.get("coins"),
        timeframe=entry.get("timeframe"),
        exchange=entry.get("exchange"),
        used_by=tuple(used_by) if isinstance(used_by, list) else (used_by,),
        note=entry.get("note"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_dataset(dataset_id: str, data_root: Optional[Path] = None) -> Path:
    """Resolve dataset_id to an absolute file path.

    Resolution order:
    1. Resolve alias -> canonical registry ID
    2. Look up ID in registry.json
    3. Return canonical_path if it exists, else legacy path
    4. Special case: 4H dataset falls back to in-repo candle_cache_532.json

    Args:
        dataset_id: Registry ID or alias (e.g. "4h_default", "candle_cache_532").
        data_root: Override DATA_ROOT (for testing). Uses get_data_root() if None.

    Returns:
        Absolute Path to the dataset file or directory.

    Raises:
        FileNotFoundError: If the dataset cannot be located on disk.
        KeyError: If dataset_id is not found in registry or aliases.
    """
    if data_root is None:
        data_root = get_data_root()

    # Step 1: resolve alias
    canonical_id = _ALIASES.get(dataset_id, dataset_id)

    # Step 2: try registry lookup
    try:
        registry = load_registry(data_root)
        datasets = registry.get("datasets", [])

        for entry in datasets:
            if entry.get("id") == canonical_id:
                info = _parse_dataset(entry)
                resolved = info.resolved_path(data_root)
                if resolved is not None:
                    return resolved.resolve()

                # Special case: 4H dataset has no path in registry (lives in-repo)
                if canonical_id == "ohlcv_4h_kraken_spot_usd_526":
                    if LEGACY_CACHE.is_file():
                        return LEGACY_CACHE.resolve()

                raise FileNotFoundError(
                    f"Dataset '{canonical_id}' found in registry but file "
                    f"not on disk. Checked canonical_path={info.canonical_path}, "
                    f"legacy_path={info.legacy_path} under {data_root}"
                )

        raise KeyError(
            f"Dataset '{dataset_id}' (resolved: '{canonical_id}') "
            f"not found in registry. Available IDs: "
            f"{[e['id'] for e in datasets]}"
        )

    except FileNotFoundError as e:
        # Registry itself missing -- try fallback for known datasets
        if canonical_id == "ohlcv_4h_kraken_spot_usd_526" and LEGACY_CACHE.is_file():
            return LEGACY_CACHE.resolve()
        raise


def get_dataset_info(dataset_id: str, data_root: Optional[Path] = None) -> DatasetInfo:
    """Return DatasetInfo for a given ID or alias without resolving to disk.

    Args:
        dataset_id: Registry ID or alias.
        data_root: Override DATA_ROOT. Uses get_data_root() if None.

    Returns:
        DatasetInfo dataclass.

    Raises:
        KeyError: If dataset_id not found.
        FileNotFoundError: If registry not found.
    """
    if data_root is None:
        data_root = get_data_root()

    canonical_id = _ALIASES.get(dataset_id, dataset_id)
    registry = load_registry(data_root)

    for entry in registry.get("datasets", []):
        if entry.get("id") == canonical_id:
            return _parse_dataset(entry)

    raise KeyError(
        f"Dataset '{dataset_id}' (resolved: '{canonical_id}') not found in registry."
    )


def list_datasets(
    status_filter: Optional[str] = None,
    data_root: Optional[Path] = None,
) -> List[DatasetInfo]:
    """List all datasets in the registry, optionally filtered by status.

    Args:
        status_filter: "canonical", "legacy", or None for all.
        data_root: Override DATA_ROOT. Uses get_data_root() if None.

    Returns:
        List of DatasetInfo, sorted by dataset_id.
    """
    if data_root is None:
        data_root = get_data_root()

    registry = load_registry(data_root)
    results: List[DatasetInfo] = []

    for entry in registry.get("datasets", []):
        info = _parse_dataset(entry)
        if status_filter is not None and info.status != status_filter:
            continue
        results.append(info)

    return sorted(results, key=lambda d: d.dataset_id)


def list_aliases() -> Dict[str, str]:
    """Return a copy of the alias -> registry ID mapping."""
    return dict(_ALIASES)


def validate_dataset(path: Path) -> Dict[str, Any]:
    """Basic validation: file exists, readable, expected structure.

    For JSON files: checks valid JSON, has list-of-dicts or dict-of-lists.
    For JSONL files: checks first line is valid JSON.
    For directories: checks non-empty.

    Returns:
        Dict with keys: valid (bool), path, size_mb, format, error (if any),
        coins (int, for candle caches), bars_sample (int, first coin).
    """
    result: Dict[str, Any] = {
        "valid": False,
        "path": str(path),
        "size_mb": None,
        "format": None,
        "error": None,
        "coins": None,
        "bars_sample": None,
    }

    if not path.exists():
        result["error"] = f"Path does not exist: {path}"
        return result

    # Directory
    if path.is_dir():
        contents = list(path.iterdir())
        result["format"] = "directory"
        result["size_mb"] = None
        result["valid"] = len(contents) > 0
        if not result["valid"]:
            result["error"] = "Directory is empty"
        return result

    # File size
    stat = path.stat()
    result["size_mb"] = round(stat.st_size / (1024 * 1024), 2)

    suffix = path.suffix.lower()

    # JSONL
    if suffix == ".jsonl":
        result["format"] = "jsonl"
        try:
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.strip():
                    json.loads(first_line)
                    result["valid"] = True
                else:
                    result["error"] = "JSONL file is empty"
        except (json.JSONDecodeError, OSError) as e:
            result["error"] = f"JSONL parse error: {e}"
        return result

    # JSON (candle caches, etc.)
    if suffix == ".json":
        result["format"] = "json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # Candle cache format: {"COIN/USD": [...], ...}
                result["coins"] = len(data)
                first_key = next(iter(data), None)
                if first_key is not None and isinstance(data[first_key], list):
                    result["bars_sample"] = len(data[first_key])
                result["valid"] = True
            elif isinstance(data, list):
                result["valid"] = len(data) > 0
                if not result["valid"]:
                    result["error"] = "JSON array is empty"
            else:
                result["error"] = f"Unexpected JSON root type: {type(data).__name__}"

        except json.JSONDecodeError as e:
            result["error"] = f"JSON parse error: {e}"
        except OSError as e:
            result["error"] = f"Read error: {e}"
        return result

    # Unknown format -- just check readability
    result["format"] = suffix.lstrip(".")
    try:
        with open(path, "rb") as f:
            f.read(1024)
        result["valid"] = True
    except OSError as e:
        result["error"] = f"Read error: {e}"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_main() -> None:
    """Command-line entrypoint: list datasets and resolve the 4H default."""
    import sys

    data_root = get_data_root()
    print(f"DATA_ROOT: {data_root}")
    print(f"Registry:  {data_root / REGISTRY_REL_PATH}")
    print()

    # List all datasets
    try:
        datasets = list_datasets(data_root=data_root)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"{'ID':<45} {'Status':<12} {'TF':<5} {'Exchange':<8} {'Coins':<6} Description")
    print("-" * 120)
    for ds in datasets:
        coins_str = str(ds.coins) if ds.coins else "-"
        tf_str = ds.timeframe or "-"
        ex_str = ds.exchange or "-"
        desc = ds.description[:50] + ("..." if len(ds.description) > 50 else "")
        print(f"{ds.dataset_id:<45} {ds.status:<12} {tf_str:<5} {ex_str:<8} {coins_str:<6} {desc}")

    print()

    # Resolve the 4H default
    print("--- Resolving 4H default dataset ---")
    for alias in ("4h_default", "candle_cache_532", "4h_kraken"):
        try:
            path = resolve_dataset(alias, data_root=data_root)
            print(f"  {alias:<25} -> {path}")
        except (FileNotFoundError, KeyError) as e:
            print(f"  {alias:<25} -> ERROR: {e}")

    print()

    # Validate the 4H dataset
    print("--- Validation ---")
    try:
        default_path = resolve_dataset("4h_default", data_root=data_root)
        result = validate_dataset(default_path)
        for k, v in result.items():
            print(f"  {k}: {v}")
    except (FileNotFoundError, KeyError) as e:
        print(f"  Could not validate: {e}")

    print()

    # Show aliases
    print("--- Aliases ---")
    for alias, target in sorted(list_aliases().items()):
        print(f"  {alias:<25} -> {target}")


if __name__ == "__main__":
    _cli_main()
