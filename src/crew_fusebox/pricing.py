"""Pricing adapter — dollar cost from token counts, via LiteLLM's maintained data.

We deliberately do **not** hand-maintain a price table (it goes stale on every provider price
change). LiteLLM already ships ``model_prices_and_context_window.json`` and the
``token_counter`` / ``cost_per_token`` helpers, and CrewAI routes through LiteLLM, so it is a
transitive dependency rather than new weight.

Every function here **fails open**: on any error (LiteLLM missing, unknown model, bad input)
it logs a one-line ``stderr`` warning and returns a zero cost/estimate instead of raising, so
a pricing hiccup can never crash the host application (see ``CONVENTIONS.md`` §3).

``litellm`` is imported lazily so the package imports (and unit tests run) without it installed.
"""

from __future__ import annotations

import sys
from typing import Any


def _warn(msg: str) -> None:
    print(f"[crew-fusebox] pricing: {msg} (failing open)", file=sys.stderr)


def _litellm() -> Any | None:
    """Import litellm lazily; return the module or ``None`` (fail open)."""
    try:
        import litellm  # type: ignore

        return litellm
    except Exception as exc:  # pragma: no cover - exercised via monkeypatched import
        _warn(f"litellm unavailable: {exc!r}")
        return None


def count_input_tokens(model: str, messages: list[dict[str, Any]] | None) -> int:
    """Count prompt tokens for ``messages`` using LiteLLM's tokenizer for ``model``.

    Returns 0 on any error (fail open).
    """
    if not messages:
        return 0
    litellm = _litellm()
    if litellm is None:
        return 0
    try:
        return int(litellm.token_counter(model=model, messages=messages))
    except Exception as exc:
        _warn(f"token_counter(messages) failed for model={model!r}: {exc!r}")
        return 0


def count_output_tokens(model: str, text: str | None) -> int:
    """Count completion tokens for ``text`` using LiteLLM's tokenizer for ``model``.

    Returns 0 on any error (fail open).
    """
    if not text:
        return 0
    litellm = _litellm()
    if litellm is None:
        return 0
    try:
        return int(litellm.token_counter(model=model, text=text))
    except Exception as exc:
        _warn(f"token_counter(text) failed for model={model!r}: {exc!r}")
        return 0


def price(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Return the dollar cost of ``prompt_tokens``/``completion_tokens`` for ``model``.

    Uses ``litellm.cost_per_token``, which returns a ``(prompt_cost, completion_cost)`` tuple
    in USD sourced from LiteLLM's maintained pricing data. Returns 0.0 on any error or unknown
    model (fail open).
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0
    litellm = _litellm()
    if litellm is None:
        return 0.0
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=max(prompt_tokens, 0),
            completion_tokens=max(completion_tokens, 0),
            cache_read_input_tokens=max(cache_read_input_tokens, 0),
            cache_creation_input_tokens=max(cache_creation_input_tokens, 0),
        )
        return float(prompt_cost) + float(completion_cost)
    except Exception as exc:
        _warn(f"cost_per_token failed for model={model!r}: {exc!r}")
        return 0.0
