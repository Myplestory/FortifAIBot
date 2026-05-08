from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

import llm
import parse

from phases.shared import (
    DEFAULT_INDUSTRY,
    SCORE_GRADER_SEPARATOR,
    _extract_first_json_object,
    _load_root_template,
    _load_template,
)


log = logging.getLogger(__name__)

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CANONICAL_FIELD_SLUGS = set(parse.CANONICAL_FIELDS.keys())


class GenerationError(RuntimeError):
    pass


def build_generation_system(industry: str = DEFAULT_INDUSTRY) -> str:
    """Stitched generator system prompt:
        templates/dreyfus.md            (cross-domain skill-stage taxonomy)
        + templates/<industry>/score.md   (domain-specific frameworks)
        + templates/<industry>/generation.md  (generation procedure)

    Questions are tuned to a target band, so the generator must see the same verbatim
    band definitions the grader uses. Without this, generated questions can drift from
    the empirical authority and end up calibrated to a different band ladder than the
    one they'll later be scored against.
    """
    dreyfus = _load_root_template("dreyfus")
    score = _load_template(industry, "score")
    generation = _load_template(industry, "generation")
    return (
        dreyfus
        + SCORE_GRADER_SEPARATOR
        + score
        + SCORE_GRADER_SEPARATOR
        + generation
    )


_BAND_GUIDANCE = {
    "B1": "basic terminology and rule-following — name-the-concept, identify-the-pattern. NOT mechanism, NOT tradeoffs.",
    "B2": "pattern recognition and direction — when-would-you-use, what-pattern-fits. Light mechanism only.",
    "B3": "mechanism articulation and tradeoff identification — explain why X works and what it gives up.",
    "B4": "holistic recognition and committed recommendations — propose, dismiss alternatives with reasons, justify under pressure.",
    "B5": "intuitive mastery and design-space articulation — derive from first principles, define the class of solutions.",
}


def _build_user_prompt_generate(
    fields: list[str],
    answerer_band: str,
    prior_weaknesses: list[str] | None,
    context_notes: str | None,
    domain: str | None,
    stack: list[str] | None,
    meta_json: dict[str, Any],
) -> str:
    band_guidance = _BAND_GUIDANCE.get(answerer_band, "")
    one_below = {"B1": "no band", "B2": "B1", "B3": "B2", "B4": "B3", "B5": "B4"}.get(answerer_band, "")
    one_above = {"B1": "B2", "B2": "B3", "B3": "B4", "B4": "B5", "B5": "no band"}.get(answerer_band, "")
    return (
        "Generate the spot check test bank.\n\n"
        "=== HARD CONSTRAINT: BAND CALIBRATION (do not violate) ===\n"
        f"Target band: {answerer_band}.\n"
        f"What {answerer_band} tests: {band_guidance}\n"
        f"A fully-mastered {answerer_band} practitioner must be able to score 5/5; a {one_below} practitioner "
        f"must score at most 3/5. Do NOT pose questions that require {one_above}-level mastery (the answerer "
        f"cannot reach them) or trivia below {answerer_band} (the answerer is not challenged).\n"
        f"Every one of the 5 questions must be calibrated to {answerer_band} — no drift toward easier or harder.\n\n"
        "=== HARD CONSTRAINT: FIELD COVERAGE ===\n"
        f"Use exactly these fields, one question per field, in this order: {json.dumps(fields)}.\n"
        "Do NOT substitute, drop, or duplicate any field. The selection has already been made; respect it.\n\n"
        "=== HARD CONSTRAINT: TOPIC VARIETY ===\n"
        "When choosing topics, prefer concepts NOT already present in `meta_json.fields[<field>].topics` "
        "for that field — surface fresh concepts the answerer has not yet been tested on. If a field already "
        "has many topics, propose new topic slugs (kebab-case) and include them in `meta_updates.topics_added`.\n\n"
        "=== INPUTS ===\n"
        f"Answerer primary band: {json.dumps(answerer_band)}\n"
        f"Prior weaknesses: {json.dumps(prior_weaknesses) if prior_weaknesses else 'none'}\n"
        f"Domain context: {json.dumps(domain) if domain else 'none'}  "
        "(if set, frame scenarios in this business domain — e.g. fintech, saas, healthcare, research — "
        "but never reference the answerer's specific projects)\n"
        f"Stack: {json.dumps(stack) if stack else 'none'}  "
        "(if set, prefer specifics from this stack when picking concrete tooling — e.g. python/django/postgres "
        "instead of generic placeholders — to make scenarios feel like the answerer's prep target)\n"
        f"Context notes: {json.dumps(context_notes) if context_notes else 'none'}\n\n"
        "Existing meta.json (for slug reuse and topic-variety reference):\n"
        f"{json.dumps(meta_json, ensure_ascii=False)}\n"
    )


def _select_fields_for_run(
    requested_fields: list[str] | None,
    meta_json: dict[str, Any],
    *,
    k: int = 5,
) -> list[str]:
    """Decide which fields the run will cover.

    Contract:
    - **Null arg (no fields specified)**: weighted-random-sample k fields from
      the canonical 8. Fields with FEWER topics in meta.json get higher weight
      so coverage rotates toward less-touched fields (counters the LLM's
      systems-distributed / ml-engineering / ai-llm bias).
    - **Explicit arg (directive but not absolute)**: the user's fields are
      included verbatim. If they specified fewer than k fields, the remaining
      slots are filled by the same weighted-random-sample from the other
      canonical fields. If they specified k or more, use the first k as-is —
      the bias does not apply to an explicit pick.
    """
    all_fields = list(parse.CANONICAL_FIELDS.keys())
    requested = [f for f in (requested_fields or []) if f in parse.CANONICAL_FIELDS]

    if len(requested) >= k:
        return requested[:k]

    # Build a weighted pool from the *non-requested* fields.
    fields_dict = (meta_json or {}).get("fields", {}) or {}
    pool = [f for f in all_fields if f not in requested]
    counts = {f: len(fields_dict.get(f, {}).get("topics", []) or []) for f in pool}
    max_c = max(counts.values()) if counts else 0
    pool_w = [(max_c - counts[f]) + 1 for f in pool]

    chosen = list(requested)
    slots = k - len(chosen)
    for _ in range(slots):
        if not pool:
            break
        idx = random.choices(range(len(pool)), weights=pool_w, k=1)[0]
        chosen.append(pool.pop(idx))
        pool_w.pop(idx)
    return chosen


def _validate_generation(out: dict[str, Any], expected_fields: list[str] | None) -> None:
    questions = out.get("questions")
    if not isinstance(questions, list) or len(questions) != 5:
        raise GenerationError(f"questions must be a list of 5 entries, got {type(questions).__name__} of len {len(questions) if isinstance(questions, list) else 'n/a'}")
    for i, wrap in enumerate(questions, start=1):
        key = f"question_{i}"
        if not isinstance(wrap, dict) or list(wrap.keys()) != [key]:
            raise GenerationError(f"questions[{i-1}] must be a single-keyed object with key {key!r}")
        rec = wrap[key]
        for required in ("field", "sfia_skills", "topics", "question"):
            if required not in rec:
                raise GenerationError(f"questions[{i-1}] missing required key {required!r}")
        field = rec["field"]
        if field not in CANONICAL_FIELD_SLUGS:
            raise GenerationError(f"questions[{i-1}] field {field!r} not in canonical 8")
        topics = rec["topics"]
        if not isinstance(topics, list) or not topics:
            raise GenerationError(f"questions[{i-1}] topics must be a non-empty list")
        for t in topics:
            if not isinstance(t, str) or not KEBAB_RE.match(t):
                raise GenerationError(f"questions[{i-1}] topic {t!r} must be kebab-case")
        sfia = rec["sfia_skills"]
        if not isinstance(sfia, list) or not sfia:
            raise GenerationError(f"questions[{i-1}] sfia_skills must be a non-empty list")
        if not isinstance(rec["question"], str) or not rec["question"].strip():
            raise GenerationError(f"questions[{i-1}] question must be a non-empty string")
    pe = out.get("practical_exercises", [])
    if not isinstance(pe, list) or not (1 <= len(pe) <= 2):
        raise GenerationError("practical_exercises must have 1 or 2 entries")


def generate(
    *,
    industry: str = DEFAULT_INDUSTRY,
    fields: list[str] | None,
    topics: list[str] | None,
    answerer_band: str,
    domain: str | None = None,
    stack: list[str] | None = None,
    context_notes: str | None = None,
) -> dict[str, Any]:
    """Phase 0 generation. One sandboxed LLM call (with up to one retry).

    `domain` (e.g., 'fintech', 'saas', 'healthcare') frames scenarios.
    `stack` (e.g., ['python', 'django', 'postgres']) tunes concrete tool choices.
    """
    system_prompt = build_generation_system(industry)
    meta = parse.read_meta()
    effective_fields = _select_fields_for_run(fields, meta, k=5)
    log.info(
        "generate: band=%s fields=%s domain=%s stack=%s",
        answerer_band, effective_fields, domain, stack,
    )
    user = _build_user_prompt_generate(
        fields=effective_fields,
        answerer_band=answerer_band,
        prior_weaknesses=topics or None,
        context_notes=context_notes,
        domain=domain,
        stack=stack,
        meta_json=meta,
    )
    model = llm.get_model("generate")

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            raw = llm.call_llm(system=system_prompt, user=user, model=model)
            parsed = json.loads(_extract_first_json_object(raw))
            _validate_generation(parsed, effective_fields)
            return parsed
        except (json.JSONDecodeError, GenerationError) as e:
            last_error = e
            log.warning("generation attempt %d failed: %s", attempt, e)
            if attempt == 1:
                user = user + (
                    f'\n\nPrevious attempt failed validation: "{e}". Regenerate.'
                )
            else:
                break
        except llm.LLMError as e:
            raise GenerationError(f"LLM call failed: {e}") from e
    raise GenerationError(f"generation failed after retry: {last_error}")
