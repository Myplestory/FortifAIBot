from __future__ import annotations

import json
import logging
import re
from typing import Any

import llm

from phases.shared import (
    DEFAULT_INDUSTRY,
    _extract_first_json_object,
    _load_template,
)


log = logging.getLogger(__name__)

DENYLIST_TOKENS = ("correct", "wrong", "right", "should", "instead", "actually")


class RefinementError(RuntimeError):
    pass


_SMART_QUOTE_MAP = str.maketrans({
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "′": "'",
    " ": " ",
})


REFINE_QUOTE_MIN_WORDS = 3


def _normalize_for_match(s: str) -> str:
    """Normalize whitespace and smart quotes for verbatim substring comparison."""
    s = s.translate(_SMART_QUOTE_MAP)
    return " ".join(s.split())


def _coerce_quote_to_substring(quote: str, response: str) -> str | None:
    """If `quote` isn't already a verbatim substring of `response` (after
    normalization), trim words from the right, then from the left, until we
    find a span of at least REFINE_QUOTE_MIN_WORDS words that IS present.
    Catches the common LLM failure mode where the model paraphrases a
    trailing or leading word but the bulk of the quote is real. Returns the
    trimmed span, or None if nothing usable.
    """
    norm_response = _normalize_for_match(response)
    if _normalize_for_match(quote) in norm_response:
        return quote

    words = quote.split()
    for end in range(len(words) - 1, REFINE_QUOTE_MIN_WORDS - 1, -1):
        candidate = " ".join(words[:end])
        if _normalize_for_match(candidate) in norm_response:
            return candidate

    for start in range(1, len(words) - REFINE_QUOTE_MIN_WORDS + 1):
        candidate = " ".join(words[start:])
        if _normalize_for_match(candidate) in norm_response:
            return candidate

    return None


def _canonicalize_refine(refine: str) -> str:
    """Rewrite the refine string into canonical punctuation form.

    Accepts both `'. Clarify:` (close-quote then period) and `.' Clarify:`
    (period then close-quote) and rewrites to the canonical `'. Clarify:`.
    Same for the fallback `'. What breaks` separator.
    """
    # Standard form: collapse `.\s*'\s*Clarify:` and `'\s*\.\s*Clarify:` to `'. Clarify: `.
    refine = re.sub(r"\.\s*'\s*Clarify:\s*", "'. Clarify: ", refine)
    refine = re.sub(r"'\s*\.\s*Clarify:\s*", "'. Clarify: ", refine)
    # Fallback form: same treatment for `What breaks if that assumption is wrong?`.
    refine = re.sub(r"\.\s*'\s*What breaks", "'. What breaks", refine)
    refine = re.sub(r"'\s*\.\s*What breaks", "'. What breaks", refine)
    return refine


def _validate_refinement(out: dict[str, Any], question_id: int, response: str) -> None:
    if out.get("question_id") != question_id:
        raise RefinementError(f"question_id mismatch: expected {question_id}, got {out.get('question_id')!r}")
    form = out.get("form")
    if form not in ("standard", "fallback", "skip"):
        raise RefinementError(f"form must be standard|fallback|skip, got {form!r}")
    refine = out.get("refine")
    if form == "skip":
        if refine is not None:
            raise RefinementError("skip form requires refine == null")
        return
    if not isinstance(refine, str) or not refine:
        raise RefinementError("refine must be a non-empty string for standard/fallback")

    refine = _canonicalize_refine(refine)

    # Auto-coerce: if the verbatim quote isn't a substring of the response
    # (LLM paraphrased an edge word), trim the quote down to the longest span
    # that IS in the response and substitute it back into the refine. This
    # handles the common "quoted span is not a verbatim substring" case
    # without requiring an LLM retry.
    m = re.match(r"^You said '([^']*)'", refine)
    if m:
        quoted_orig = m.group(1)
        norm_response = _normalize_for_match(response)
        if _normalize_for_match(quoted_orig) not in norm_response:
            coerced = _coerce_quote_to_substring(quoted_orig, response)
            if coerced is not None and coerced != quoted_orig:
                refine = refine.replace(f"You said '{quoted_orig}'", f"You said '{coerced}'", 1)
                log.info("refinement: coerced quote %r → %r", quoted_orig, coerced)

    out["refine"] = refine  # write back canonicalized + coerced form

    low = refine.lower()
    for tok in DENYLIST_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", low):
            raise RefinementError(f"refine contains denylisted token {tok!r}")
    if not refine.startswith("You said '"):
        raise RefinementError("refine must start with \"You said '\"")

    norm_response = _normalize_for_match(response)
    m = re.match(r"^You said '([^']*)'", refine)
    if not m:
        raise RefinementError("could not parse quoted span from refine")
    quoted = _normalize_for_match(m.group(1))
    if quoted not in norm_response:
        raise RefinementError("quoted span is not a verbatim substring of the response (post-normalization)")

    if form == "standard":
        if "'. Clarify:" not in refine:
            raise RefinementError("standard form must contain \"'. Clarify:\" after canonicalization")
    elif form == "fallback":
        suffix = "What breaks if that assumption is wrong?"
        if not refine.rstrip().endswith(suffix):
            raise RefinementError(f"fallback form must end with: {suffix!r}")


def _deterministic_fallback(question_id: int, response: str) -> dict[str, Any]:
    quote = response.replace("'", "\\'")[:80]
    return {
        "question_id": question_id,
        "refine": f"You said '{quote}...'. What breaks if that assumption is wrong?",
        "form": "fallback",
        "ambiguity_target": "deterministic fallback after validation failures",
    }


def refine(
    *,
    question_id: int,
    question_record: dict[str, Any],
    answerer_band: str,
    industry: str = DEFAULT_INDUSTRY,
) -> dict[str, Any]:
    """Phase 2 refinement. One sandboxed LLM call per question.

    `question_record` must contain {field, topics, question, response}.
    `answerer_band` is the session's primary evaluation band (B1..B5); the
    refine LLM uses it to scope what counts as "highest-leverage gap".
    """
    response = question_record.get("response", "") or ""
    if not response.strip():
        return {
            "question_id": question_id,
            "refine": None,
            "form": "skip",
            "ambiguity_target": "no response provided",
        }

    system_prompt = _load_template(industry, "refine")
    user = (
        "Generate the refinement.\n\n"
        f"question_id: {question_id}\n"
        f"answerer_band: {json.dumps(answerer_band)}\n\n"
        "question_record:\n"
        f"{json.dumps(question_record, ensure_ascii=False)}\n"
    )
    model = llm.get_model("refine")

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            raw = llm.call_llm(system=system_prompt, user=user, model=model)
            parsed = json.loads(_extract_first_json_object(raw))
            _validate_refinement(parsed, question_id, response)
            return parsed
        except (json.JSONDecodeError, RefinementError) as e:
            last_error = e
            log.warning("refinement attempt %d failed: %s", attempt, e)
            if attempt == 1:
                user = user + (
                    f'\n\nPrevious attempt failed validation: "{e}". Regenerate per the schema.'
                )
            else:
                break
        except llm.LLMError as e:
            log.error("refine LLM call failed: %s", e)
            return _deterministic_fallback(question_id, response)
    log.warning("refinement falling back deterministically after: %s", last_error)
    return _deterministic_fallback(question_id, response)
