"""Load config.toml and limits.json. Fails closed if any limit is missing or invalid."""
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

REQUIRED_LIMITS = (
    "max_contracts_per_order",
    "max_open_exposure_usd",
    "max_daily_loss_usd",
    "max_orders_per_minute",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    markets: list
    poll_seconds: float
    target_price: float
    limits: dict


def load(config_path="config.toml", limits_path="limits.json") -> Config:
    try:
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read {config_path}: {e}") from e
    try:
        limits = json.loads(Path(limits_path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"cannot read {limits_path}: {e}") from e

    for key in REQUIRED_LIMITS:
        if key not in limits:
            raise ConfigError(f"limit '{key}' missing from {limits_path}")
        v = limits[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ConfigError(f"limit '{key}' must be a positive number, got {v!r}")

    markets = cfg.get("markets")
    if not markets or not isinstance(markets, list):
        raise ConfigError("config.toml needs markets = [\"slug\", ...]")
    for key in ("poll_seconds", "target_price"):
        if key not in cfg:
            raise ConfigError(f"config.toml missing {key}")
    return Config(markets=list(markets), poll_seconds=float(cfg["poll_seconds"]),
                  target_price=float(cfg["target_price"]), limits=dict(limits))
