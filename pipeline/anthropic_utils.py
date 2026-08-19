"""Shared Anthropic integration utilities."""

import json
import time
from collections.abc import Callable
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


Validator = Callable[[dict[str, Any]], bool]


def select_tool_input(
    inputs: list[dict[str, Any]], validate: Validator | None
) -> dict[str, Any]:
    """Pick the first tool input that satisfies `validate`.

    A response can carry more than one tool_use block, and the first is not
    reliably the good one: a real fit response appended a second block holding
    empty arrays and reasoning "placeholder" after a first block whose nested
    objects had been flattened. Indexing [0] made the usable content invisible.

    With no validator the first block is returned, preserving the behaviour of
    stages that have no shape worth checking.
    """
    if not inputs:
        raise ValueError("no tool_use block in response")
    if validate is None:
        return inputs[0]
    for candidate in inputs:
        if validate(candidate):
            return candidate
    raise ValueError(f"no usable tool_use block among {len(inputs)} returned")


def _tool_inputs(response: Message) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], b.input) for b in response.content if b.type == "tool_use"]


def call_model(
    stage: str, validate: Validator | None = None, attempts: int = 1, **kwargs: Any
) -> dict[str, Any]:
    """Call the Anthropic API and extract the forced-tool response.

    The single chokepoint for every pipeline model call. When a RunContext
    is active (set by a streaming endpoint or, later, a job worker), the
    full response envelope — usage, model, stop reason, latency, request
    and response snapshots — is recorded and emitted as events. With no
    active context this behaves exactly like the old inline pattern.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _call_once(stage, validate, attempt, **kwargs)
        except ValueError as exc:  # malformed tool call — worth another sample
            last_error = exc
    raise ValueError(f"{stage}: {attempts} attempt(s) produced no usable tool call ({last_error})")


def _call_once(
    stage: str, validate: Validator | None, attempt: int, **kwargs: Any
) -> dict[str, Any]:
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

    inputs = _tool_inputs(response)

    if ctx is not None:
        ctx.finish_call(
            seq=seq,
            stage=stage,
            attempt=attempt,
            tool_blocks=len(inputs),
            model=response.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
            request={k: v for k, v in kwargs.items()},
            response=[b.model_dump() for b in response.content],
            fallback_model=kwargs.get("model"),
        )
    return select_tool_input(inputs, validate)


def call_model_text(stage: str, **kwargs: Any) -> str:
    """Traced call for a stage that returns prose rather than a tool call.

    The control arm needs this. Calling the SDK directly, as it did, left half
    of every sweep's documents with no token, latency, or cost record — in a
    harness whose selling point is that every model call is accounted for.
    """
    ctx = current_trace.get()
    seq = ctx.begin_stage(stage) if ctx is not None else 0
    kwargs.setdefault("thinking", {"type": "disabled"})

    start = time.perf_counter()
    response = _get_anthropic_client().messages.create(**kwargs)
    latency_ms = int((time.perf_counter() - start) * 1000)

    if ctx is not None:
        ctx.finish_call(
            seq=seq,
            stage=stage,
            attempt=1,
            tool_blocks=0,
            model=response.model,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
            request={k: v for k, v in kwargs.items()},
            response=[b.model_dump() for b in response.content],
            fallback_model=kwargs.get("model"),
        )
    return "".join(b.text for b in response.content if b.type == "text").strip()


def dict_items(value: object) -> list[dict[str, Any]]:
    """Coerce a tool-result array field down to the objects it declared.

    A tool's `input_schema` is advisory. The API guarantees a well-formed tool
    call, not that nested structures match their declared types. Two shapes have
    been observed in real runs, both with `stop_reason=tool_use` and nothing
    truncated:

    - a list containing bare strings where the schema declared objects
    - the entire array delivered as a JSON *string*, wrapping the list in a
      single-key object: `"matches": "{\"matches\": [{...}]}"`

    The second one is why this function recovers rather than only filters.
    Returning `[]` for it discarded ten matches and eight gaps in silence, and
    the generator ran with no fit guidance while the stage reported success.

    Recovery stops where it would have to guess: an object with more than one
    key offers two candidate arrays and no basis for choosing, so it yields
    nothing rather than picking.
    """
    value = _recover_list(value)
    return [item for item in value if isinstance(item, dict)]


def _recover_list(value: object) -> list[Any]:
    """Best-effort recovery of an array field, whatever shape it arrived in.

    A bare string is NOT iterated: doing so yields characters, which is how one
    sentence became 868 findings in a live run. It is either recoverable JSON or
    a single item.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return [value] if value.strip() else []
        if isinstance(parsed, dict):
            if len(parsed) != 1:
                return []
            parsed = next(iter(parsed.values()))
        value = parsed

    if isinstance(value, list):
        return value
    return []


def str_items(value: object) -> list[str]:
    """Coerce a tool-result array-of-strings field.

    Items that arrive as objects are rendered rather than dropped — a finding
    reported in the wrong shape is still a finding, and silently discarding it
    would understate the penalty.
    """
    return [
        item if isinstance(item, str) else json.dumps(item, default=str)
        for item in _recover_list(value)
    ]
