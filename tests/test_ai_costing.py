from __future__ import annotations

from lloyds_digest.ai.costing import compute_cost_usd


def test_flex_rate_for_gpt_5_nano_matches_expected() -> None:
    # 1M prompt + 1M completion on flex should map directly to published per-million prices.
    cost = compute_cost_usd(
        model="gpt-5-nano",
        tokens_prompt=1_000_000,
        tokens_completion=1_000_000,
        service_tier="flex",
    )
    assert cost == (0.025, 0.20, 0.225)


def test_flex_cached_input_pricing_applies_cached_rate() -> None:
    cost = compute_cost_usd(
        model="gpt-5-mini",
        tokens_prompt=1_000_000,
        tokens_completion=0,
        tokens_cached_input=1_000_000,
        service_tier="flex",
    )
    assert cost == (0.0125, 0.0, 0.0125)

