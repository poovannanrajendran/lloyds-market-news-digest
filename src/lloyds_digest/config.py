from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


def _coerce_bool(value: bool | str | int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


@dataclass
class CacheConfig:
    enabled: bool = False
    directory: Path = Path("cache")

    def __post_init__(self) -> None:
        self.enabled = _coerce_bool(self.enabled)
        self.directory = Path(self.directory)


@dataclass
class OutputConfig:
    enabled: bool = True
    directory: Path = Path("output")

    def __post_init__(self) -> None:
        self.enabled = _coerce_bool(self.enabled)
        self.directory = Path(self.directory)


@dataclass
class AppConfig:
    topics_csv: str = ""
    cache: CacheConfig = field(default_factory=CacheConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    def validate(self) -> None:
        if not isinstance(self.topics_csv, str):
            raise ValueError("topics_csv must be a string")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AppConfig":
        cache = CacheConfig(**(data.get("cache", {}) or {}))
        output = OutputConfig(**(data.get("output", {}) or {}))
        topics_csv = data.get("topics_csv", "")
        config = cls(topics_csv=topics_csv, cache=cache, output=output)
        config.validate()
        return config


DEFAULT_CONFIG_PATH = Path("config.yaml")
ENV_PREFIX = "LLOYDS_DIGEST__"


def _deep_set(target: dict[str, Any], keys: list[str], value: Any) -> None:
    current = target
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


def _parse_env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        if not path or any(not part for part in path):
            continue
        _deep_set(overrides, path, value)
    return overrides


def _merge_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(
    path: Path | str = DEFAULT_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    config_path = Path(path)
    data: dict[str, Any] = {}
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw) or {}
        if not isinstance(loaded, dict):
            raise ValueError("config.yaml must define a mapping at the top level")
        data = loaded

    env_overrides = _parse_env_overrides(env or os.environ)
    merged = _merge_dicts(data, env_overrides)
    return AppConfig.from_dict(merged)
