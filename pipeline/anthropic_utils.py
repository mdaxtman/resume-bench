"""Shared Anthropic integration utilities."""

import time
from typing import Any, cast

import anthropic
from anthropic.types import Message

from config import get_anthropic_api_key
from telemetry import current_trace

_client: anthropic.Anthropic | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    """Get or initialize the singleton Anthropic client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_anthropic_api_key())
    return _client


def _extract_tool_response(response: Message) -> dict[str, Any]:
    """Extract tool input from the first tool_use block in response.

    Args:
        response: Anthropic message response

    Returns:
        The input dict from the tool_use block

    Raises:
        RuntimeError: If no tool_use block found in response
    """
    try:
        tool_block = next(b for b in response.content if b.type == "tool_use")
    except StopIteration:
        raise RuntimeError("No tool_use block in response")

    return cast(dict[str, Any], tool_block.input)


def call_model(stage: str, **kwargs: Any) -> dict[str, Any]:
    """Call the Anthropic API and extract the forced-tool response.

    The single chokepoint for every pipeline model call. When a RunContext
    is active (set by a streaming endpoint or, later, a job worker), the
    full response envelope — usage, model, stop reason, latency, request
    and response snapshots — is recorded and emitted as events. With no
    active context this behaves exactly like the old inline pattern.
    """
    ctx = current_trace.get()
    seq = ctx.begin_stage(stage) if ctx is not None else 0

    # claude-sonnet-5 runs adaptive thinking by default when `thinking` is
    # omitted; this pipeline's forced-tool calls with modest max_tokens must
    # not spend output budget on thinking, so default it off. A caller can
    # still pass an explicit `thinking` to override.
    kwargs.setdefault("thinking", {"type": "disabled"})

    start = time.perf_counter()
    response = _get_anthropic_client().messages.create(**kwargs)
    latency_ms = int((time.perf_counter() - start) * 1000)

    result = _extract_tool_response(response)

    if ctx is not None:
        ctx.finish_call(
            seq=seq,
            stage=stage,
            model=response.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
            request={k: v for k, v in kwargs.items()},
            response=[b.model_dump() for b in response.content],
            fallback_model=kwargs.get("model"),
        )
    return result


def dict_items(value: object) -> list[dict[str, Any]]:
    """Coerce a tool-result array field down to the objects it declared.

    A tool's `input_schema` is advisory. The API guarantees a well-formed tool
    call, not that nested items match their declared types — a fit run has
    returned `terminology` as a list of bare strings despite the schema
    requiring objects. Stages read these items with `.get()`, so drop anything
    that is not a dict here rather than raising AttributeError mid-stage after
    the model call has already been paid for.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
