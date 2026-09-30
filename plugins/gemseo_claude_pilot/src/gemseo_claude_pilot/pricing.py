"""An estimate of what calls cost with an API key (spec § 5.4).

Prices in USD per million tokens, from Anthropic's price list; keep them up to
date. The estimate is shown as such: the bill is the reference. With a
subscription, calls are not billed per token and no cost is shown.
"""

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
}
"""Input and output prices of each model."""

CACHE_WRITE = 1.25
"""Price of the tokens written to the prompt cache, relative to input tokens."""

CACHE_READ = 0.1
"""Price of the tokens read from the prompt cache, relative to input tokens."""


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """The estimated cost of a call in USD; 0 for a model without a known price."""
    input_price, output_price = PRICES.get(model, (0.0, 0.0))
    return (
        input_price
        * (
            input_tokens
            + CACHE_WRITE * cache_write_tokens
            + CACHE_READ * cache_read_tokens
        )
        + output_price * output_tokens
    ) / 1e6
