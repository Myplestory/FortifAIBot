from __future__ import annotations

import logging
import os
from typing import Literal

from anthropic import Anthropic, APIError

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMTruncatedError(LLMError):
    """Raised when the model stops because it hit the max_tokens cap.

    Distinct from generic LLMError so callers that can recover (e.g. by retrying
    with a larger budget) can catch this specifically; everyone else still sees
    it as an LLMError.
    """

    def __init__(self, output_tokens: int | str, max_tokens: int) -> None:
        self.output_tokens = output_tokens
        self.max_tokens = max_tokens
        super().__init__(
            f"LLM output truncated at max_tokens={max_tokens} (output_tokens={output_tokens})"
        )


def get_model(kind: Literal["generate", "refine"]) -> str:
    if kind == "generate":
        return os.environ.get("MODEL_GENERATE", "claude-opus-4-7")
    if kind == "refine":
        return os.environ.get("MODEL_REFINE", "claude-sonnet-4-6")
    raise ValueError(f"unknown model kind {kind!r}")


def call_llm(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 4000,
    cache_system: bool = True,
) -> str:
    """Make one sandboxed Anthropic call, always streamed.

    Anthropic requires streaming for any request whose generation may exceed
    ~10 minutes; the grader call uses max_tokens=24000 on Opus, which the
    non-streaming endpoint rejects preemptively. Streaming uniformly keeps
    the call site simple and works for short requests too. Output text is
    accumulated from the stream and returned as one string, preserving the
    prior synchronous return contract.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)

    if cache_system:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    else:
        system_param = system

    parts: list[str] = []
    final = None
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_param,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            for text in stream.text_stream:
                parts.append(text)
            final = stream.get_final_message()
    except APIError as e:
        raise LLMError(f"Anthropic API error: {e}") from e
    except Exception as e:
        raise LLMError(f"Unexpected LLM call failure: {e}") from e

    if not parts:
        raise LLMError("LLM returned no text content")

    full = "".join(parts)
    in_tokens = getattr(final.usage, "input_tokens", "?") if final is not None else "?"
    out_tokens = getattr(final.usage, "output_tokens", "?") if final is not None else "?"
    stop_reason = getattr(final, "stop_reason", None) if final is not None else None
    log.info(
        "llm call (streamed) model=%s sys_tokens=%s out_tokens=%s stop_reason=%s",
        model, in_tokens, out_tokens, stop_reason,
    )
    if stop_reason == "max_tokens":
        raise LLMTruncatedError(out_tokens, max_tokens)
    return full
