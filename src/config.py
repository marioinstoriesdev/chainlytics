"""
hackathon/src/config.py
Loads config.yaml from the hackathon directory.

All runtime values -- API key, keypair, thresholds, watchlist -- live there.
Nothing is hardcoded in this file or any other source file.

Users need:
  - chainlytics.api_key   : Chainlytics subscriber key (PRO/ENTERPRISE/STARTER)
  - solana.keypair        : 64-byte wallet array for local trade signing
  No Vanish API key is required -- Chainlytics holds the operator key server-side.
"""

from pathlib import Path
from typing import Any, Dict, List

import yaml

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
_config: Dict[str, Any] = {}


def load() -> Dict[str, Any]:
    global _config
    if _config:
        return _config
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {_CONFIG_PATH}. "
            "Copy config.example.yaml to config.yaml and fill in your values."
        )
    with open(_CONFIG_PATH, "r") as f:
        _config = yaml.safe_load(f) or {}
    return _config


def get(section: str, key: str, default: Any = None) -> Any:
    return load().get(section, {}).get(key, default)


# -- Chainlytics (covers both scoring and Vanish proxy access) ---------------

def chainlytics_api_url() -> str:
    return get("chainlytics", "api_url", "https://api.chainlytics.dev")

def chainlytics_api_key() -> str:
    return get("chainlytics", "api_key", "")

def chainlytics_chain() -> str:
    return get("chainlytics", "chain", "sol")


# -- Solana -----------------------------------------------------------------

def solana_rpc_url() -> str:
    return get("solana", "rpc_url", "https://api.mainnet-beta.solana.com")

def solana_keypair_bytes() -> bytes:
    raw = load().get("solana", {}).get("keypair", [])
    if not raw:
        raise ValueError(
            "solana.keypair is not set in config.yaml. "
            "Generate with: solana-keygen new --outfile wallet.json && cat wallet.json"
        )
    return bytes(raw)


# -- Execution --------------------------------------------------------------

def _exec(key: str, default: Any) -> Any:
    return load().get("execution", {}).get(key, default)

def watchlist() -> List[str]:          return _exec("watchlist", [])
def min_score() -> float:             return float(_exec("min_score", 7.0))
def min_confidence() -> float:        return float(_exec("min_confidence", 0.70))
def trade_amount_lamports() -> int:   return int(_exec("trade_amount_lamports", 5_000_000))
def loan_additional_sol() -> int:     return int(_exec("loan_additional_sol", 12_000_000))
def jito_tip_amount() -> int:         return int(_exec("jito_tip_amount", 1_000_000))
def split_repay() -> int:             return int(_exec("split_repay", 1))
def poll_interval_seconds() -> int:   return int(_exec("poll_interval_seconds", 30))
def commit_poll_interval_seconds() -> int: return int(_exec("commit_poll_interval_seconds", 3))
def commit_max_polls() -> int:        return int(_exec("commit_max_polls", 40))
def max_concurrent_trades() -> int:   return int(_exec("max_concurrent_trades", 2))
def output_token_address() -> str:    return _exec("output_token_address", "") or ""


# -- Server -----------------------------------------------------------------

def server_host() -> str: return load().get("server", {}).get("host", "0.0.0.0")
def server_port() -> int: return int(load().get("server", {}).get("port", 3000))
