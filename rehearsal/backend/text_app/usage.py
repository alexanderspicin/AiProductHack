"""Token accounting, not provider billing. Prices checked 2026-09-04."""
from decimal import Decimal

PRICE_VERSION = "2026-09-04"
PRICES = {
    "gpt-5.6-luna": ("0.20", "0.02", "1.20"),
    "gpt-4.1-mini": ("0.40", "0.10", "1.60"),
    "gpt-4.1-mini-2025-04-14": ("0.40", "0.10", "1.60"),
}
PRICE_SOURCES = [
    "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    "https://developers.openai.com/api/docs/models/gpt-4.1-mini",
]


def token_usage(value):
    """Reject incomplete or inconsistent usage instead of manufacturing zeros."""
    if not isinstance(value, dict):
        return None
    prompt = value.get("prompt_tokens")
    output = value.get("completion_tokens")
    total = value.get("total_tokens")
    inputs = value.get("prompt_tokens_details") or {}
    outputs = value.get("completion_tokens_details") or {}
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return None
    cached, written, reasoning = inputs.get("cached_tokens", 0), inputs.get("cache_write_tokens", 0), outputs.get("reasoning_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (prompt, output, total, cached, written, reasoning)):
        return None
    if total != prompt + output or cached + written > prompt or reasoning > output:
        return None
    return {"input_tokens": prompt, "output_tokens": output, "total_tokens": total,
            "cached_tokens": cached, "cache_write_tokens": written, "reasoning_tokens": reasoning}


def cost_nano_usd(model, usage, *, standard_openai=True):
    """Integer nanodollars; cached input and reasoning are subsets, not extras."""
    if not standard_openai or model not in PRICES or usage is None:
        return None
    incoming, cached, outgoing = map(Decimal, PRICES[model])
    prompt, writes = usage["input_tokens"], usage["cache_write_tokens"]
    write_multiplier = Decimal("1.25") if model == "gpt-5.6-luna" else Decimal(1)
    if writes and model != "gpt-5.6-luna":
        return None  # No verified write tariff for this model.
    if model == "gpt-5.6-luna" and prompt > 272_000:
        incoming *= 2
        cached *= 2
        outgoing *= Decimal("1.5")
    dollars_per_million = ((prompt - usage["cached_tokens"] - writes) * incoming
                           + usage["cached_tokens"] * cached + writes * incoming * write_multiplier
                           + usage["output_tokens"] * outgoing)
    return int(dollars_per_million * 1000)
