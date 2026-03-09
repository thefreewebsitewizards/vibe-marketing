"""Thin LLM wrapper — routes to OpenRouter (OpenAI-compat) or direct Anthropic."""

import base64
import time
from dataclasses import dataclass, field
from openai import OpenAI
from loguru import logger
import httpx

from src.config import settings

# Per-million-token pricing: (prompt_price, completion_price)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash": (0.15, 0.60),
    "google/gemini-2.5-pro": (1.25, 10.00),
    "google/gemini-2.0-flash": (0.10, 0.40),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
}


@dataclass
class ChatResult:
    """LLM response with usage/cost metadata."""
    text: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: str = ""
    generation_id: str = ""


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token counts using known pricing."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    prompt_price, completion_price = pricing
    return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000


def get_model_for_step(step: str) -> str:
    """Resolve which model to use for a pipeline step.

    Checks for a step-specific override in settings, falls back to default.
    """
    override = getattr(settings, f"openrouter_model_{step}", "")
    return override or settings.openrouter_model


def _get_client(model_override: str = "") -> tuple[OpenAI, str]:
    """Return an OpenAI-compatible client and model name."""
    if settings.openrouter_api_key:
        model = model_override or settings.openrouter_model
        logger.info(f"Using OpenRouter model: {model}")

        if "anthropic" in model.lower() or "claude" in model.lower():
            logger.warning(
                f"OpenRouter model '{model}' routes to Anthropic — "
                "if Anthropic credits are exhausted this will fail. "
                "Consider switching to a non-Anthropic model."
            )

        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        return client, model

    raise RuntimeError(
        "No LLM API key available. Set OPENROUTER_API_KEY in .env"
    )


def chat(
    system: str,
    user_content: str | list,
    max_tokens: int = 2000,
    model_override: str = "",
) -> ChatResult:
    """Send a chat completion and return a ChatResult with text + usage."""
    client, model = _get_client(model_override)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
    except Exception as e:
        err = str(e).lower()
        if any(keyword in err for keyword in ("credit", "payment", "billing", "quota", "insufficient")):
            raise RuntimeError(
                f"LLM API payment/credit error on model '{model}'. "
                f"Check your OpenRouter balance or switch models. Original: {e}"
            ) from e
        raise

    choice = response.choices[0]
    finish_reason = choice.finish_reason or ""
    msg = choice.message
    text = msg.content

    if finish_reason == "length":
        logger.warning(f"LLM response truncated (finish_reason=length, model={model}, max_tokens={max_tokens})")

    # Reasoning models (e.g. kimi-k2.5) put output in reasoning instead of content
    if text is None and hasattr(msg, "reasoning") and msg.reasoning:
        text = msg.reasoning
        logger.info(f"Using reasoning field as content (model: {model})")

    if text is None:
        raise RuntimeError(f"LLM returned empty response (model: {model})")

    # Extract usage data
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    if response.usage:
        prompt_tokens = response.usage.prompt_tokens or 0
        completion_tokens = response.usage.completion_tokens or 0
        total_tokens = response.usage.total_tokens or 0

    cost = estimate_cost(model, prompt_tokens, completion_tokens)

    # Capture OpenRouter generation ID for actual cost lookup
    generation_id = getattr(response, "id", "") or ""

    return ChatResult(
        text=text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        finish_reason=finish_reason,
        generation_id=generation_id,
    )


def fetch_generation_cost(generation_id: str, retries: int = 3) -> dict | None:
    """Fetch actual cost from OpenRouter's generation API.

    OpenRouter may take a moment to finalize cost data, so we retry with backoff.

    Returns:
        Dict with keys: total_cost, tokens_prompt, tokens_completion,
        native_tokens_prompt, native_tokens_completion, model.
        None if lookup fails.
    """
    if not generation_id or not settings.openrouter_api_key:
        return None

    url = f"https://openrouter.ai/api/v1/generation?id={generation_id}"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}

    for attempt in range(retries):
        try:
            resp = httpx.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if data.get("total_cost") is not None:
                    return {
                        "total_cost": float(data["total_cost"]),
                        "tokens_prompt": data.get("tokens_prompt", 0),
                        "tokens_completion": data.get("tokens_completion", 0),
                        "native_tokens_prompt": data.get("native_tokens_prompt", 0),
                        "native_tokens_completion": data.get("native_tokens_completion", 0),
                        "model": data.get("model", ""),
                    }
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
        except httpx.HTTPError as e:
            logger.debug(f"OpenRouter generation lookup failed (attempt {attempt + 1}): {e}")
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))

    return None
