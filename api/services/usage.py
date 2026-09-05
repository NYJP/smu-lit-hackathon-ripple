"""Token usage and configurable estimated model costs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


# Public API prices at implementation time. Operators can override aliases or
# add snapshot model names with RIPPLE_MODEL_PRICES_JSON.
_DEFAULT_PRICES: dict[str, ModelPrice] = {
    "gpt-5": ModelPrice(1.25, 10.00),
    "gpt-5-mini": ModelPrice(0.25, 2.00),
    "gpt-5.4-mini": ModelPrice(0.75, 4.50),
    "gpt-4.1": ModelPrice(2.00, 8.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "text-embedding-3-small": ModelPrice(0.02, 0.00),
}


def _prices() -> dict[str, ModelPrice]:
    prices = dict(_DEFAULT_PRICES)
    raw = os.environ.get("RIPPLE_MODEL_PRICES_JSON")
    if not raw:
        return prices
    try:
        overrides = json.loads(raw)
        for model, values in overrides.items():
            prices[str(model)] = ModelPrice(float(values["input"]), float(values["output"]))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return prices
    return prices


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimate USD cost, or return None when a model has no configured rate."""
    price = _prices().get(model)
    if price is None:
        return None
    return round(
        (prompt_tokens * price.input_per_million + completion_tokens * price.output_per_million)
        / 1_000_000,
        8,
    )
