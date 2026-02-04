from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelRate:
    input_per_million: float
    output_per_million: float


CUSTOM_RATES: dict[str, ModelRate] = {
    "qwen2:14b": ModelRate(0.04, 0.10),
    "qwen3:14b": ModelRate(0.04, 0.10),
}

FLEX_RATES: dict[str, ModelRate] = {
    "gpt-5.2": ModelRate(0.875, 7.00),
    "gpt-5.1": ModelRate(0.625, 5.00),
    "gpt-5": ModelRate(0.625, 5.00),
    "gpt-5-mini": ModelRate(0.125, 1.00),
    "gpt-5-nano": ModelRate(0.025, 0.20),
    "o3": ModelRate(1.00, 4.00),
    "o4-mini": ModelRate(0.55, 2.20),
    "gpt-4o": ModelRate(2.50, 10.00),
}

STANDARD_RATES: dict[str, ModelRate] = {
    "gpt-5.2": ModelRate(1.75, 14.00),
    "gpt-5.1": ModelRate(1.25, 10.00),
    "gpt-5": ModelRate(1.25, 10.00),
    "gpt-5-mini": ModelRate(0.25, 2.00),
    "gpt-5-nano": ModelRate(0.05, 0.40),
    "gpt-4o": ModelRate(2.50, 10.00),
}


def resolve_rate(model: str, service_tier: str | None) -> Optional[ModelRate]:
    if not model:
        return None
    model_key = _normalise_model(model)
    if model_key in CUSTOM_RATES:
        return CUSTOM_RATES[model_key]
    tier = (service_tier or "standard").strip().lower()
    if tier == "flex":
        return FLEX_RATES.get(model_key)
    return STANDARD_RATES.get(model_key)


def compute_cost_usd(
    model: str,
    tokens_prompt: int | None,
    tokens_completion: int | None,
    service_tier: str | None = None,
) -> tuple[float, float, float] | None:
    if tokens_prompt is None or tokens_completion is None:
        return None
    rate = resolve_rate(model, service_tier)
    if rate is None:
        return None
    input_cost = (tokens_prompt / 1_000_000.0) * rate.input_per_million
    output_cost = (tokens_completion / 1_000_000.0) * rate.output_per_million
    total = input_cost + output_cost
    return (input_cost, output_cost, total)


def _normalise_model(model: str) -> str:
    lowered = model.strip().lower()
    for prefix in ("openai/", "chatgpt/"):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :]
    return lowered
