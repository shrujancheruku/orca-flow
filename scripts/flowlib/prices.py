"""API list prices, used as a cost proxy.

The founder runs on a subscription, so these dollars are a yardstick for
comparing runs, not a bill. Update the table and PRICES_AS_OF together.
"""

from __future__ import annotations

PRICES_AS_OF = "2026-11-04"
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"


def _rates(inp: float, out: float, cache_read: float) -> dict:
    """Dollars per million tokens. A cache write costs 1.25x input (5-minute TTL)."""
    return {"input": inp, "output": out, "cache_read": cache_read, "cache_write": round(inp * 1.25, 6)}


# The longest matching key wins, so "opus-4-1" beats "opus-4".
PRICES = {
    "fable-5-1": _rates(10, 50, 0.25),
    "mythos-5-1": _rates(10, 50, 0.25),
    "fable-5": _rates(10, 50, 1),
    "mythos-5": _rates(10, 50, 1),
    "opus-5-5": _rates(4, 20, 0.20),
    "opus-5": _rates(5, 25, 0.50),
    "opus-4-8": _rates(5, 25, 0.50),
    "opus-4-7": _rates(5, 25, 0.50),
    "opus-4-6": _rates(5, 25, 0.50),
    "opus-4-5": _rates(5, 25, 0.50),
    "opus-4-1": _rates(15, 75, 1.50),
    "opus-4": _rates(15, 75, 1.50),
    "sonnet-5-5": _rates(2, 10, 0.10),
    "sonnet-5": _rates(2, 10, 0.20),
    "sonnet-4-6": _rates(3, 15, 0.30),
    "sonnet-4-5": _rates(3, 15, 0.30),
    "sonnet-4": _rates(3, 15, 0.30),
    "haiku-5-5": _rates(0.10, 0.50, 0.01),
    "haiku-4-5": _rates(1, 5, 0.10),
    "3-5-haiku": _rates(0.80, 4, 0.08),
}

# Prompts over this many tokens are billed at the long tier.
LONG_TIERS = {
    "haiku-5-5": (100_000, _rates(0.50, 2.50, 0.05)),
}

TOKEN_KEYS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


def match_key(model: str):
    model = (model or "").lower()
    hits = [k for k in PRICES if k in model]
    return max(hits, key=len) if hits else None


def family(model: str) -> str:
    model = (model or "").lower()
    for name in ("fable", "mythos", "opus", "sonnet", "haiku"):
        if name in model:
            return name
    return "unknown"


def usage_tokens(usage: dict) -> dict:
    return {short: int(usage.get(long) or 0) for long, short in TOKEN_KEYS.items()}


def message_cost(model: str, usage: dict):
    """Dollars for one assistant message, or None for an unpriced model."""
    key = match_key(model)
    if key is None:
        return None
    tokens = usage_tokens(usage)
    rates = PRICES[key]
    if key in LONG_TIERS:
        limit, long_rates = LONG_TIERS[key]
        prompt = tokens["input"] + tokens["cache_read"] + tokens["cache_write"]
        if prompt > limit:
            rates = long_rates
    return sum(tokens[k] * rates[k] for k in tokens) / 1_000_000
