from __future__ import annotations

import json
import logging
import re
from typing import Any

import llm
import parse

from phases import band_data
from phases.grading_report import render_report
from phases.shared import (
    DEFAULT_INDUSTRY,
    SCORE_GRADER_SEPARATOR,
    TEMPLATES_ROOT,
    _extract_first_json_object,
    _load_root_template,
    _load_template,
)


log = logging.getLogger(__name__)

_LIT_TYPES = {"remediation", "growth"}
_DELTA_RE = re.compile(r"^[+\-]?\d+\.\d$")


def _load_optional_template(industry: str, name: str) -> str | None:
    """Load an industry template if present; return None if missing.

    Used for the invariants.md mechanism oracle, which is currently only shipped
    for swe. Other industries can opt in by adding their own invariants.md.
    """
    p = TEMPLATES_ROOT / industry / f"{name}.md"
    if not p.exists() or p.stat().st_size == 0:
        return None
    return _load_template(industry, name)


def _stitch_band_data(text: str) -> str:
    """Substitute YAML-rendered tables into template placeholders. Idempotent —
    a no-op when the placeholders are absent (e.g. non-swe industries that
    don't use the placeholder convention).
    """
    if "{{BAND_TABLE_VERBATIM}}" in text:
        text = text.replace("{{BAND_TABLE_VERBATIM}}", band_data.render_band_table_md())
    if "{{SFIA_FACETS_TABLE}}" in text:
        text = text.replace("{{SFIA_FACETS_TABLE}}", band_data.render_sfia_facets_md())
    return text


class GradingError(RuntimeError):
    pass


def build_grader_system(industry: str = DEFAULT_INDUSTRY) -> str:
    """Stitched grader system prompt:
        templates/dreyfus.md                  (cross-domain skill-stage taxonomy)
        + templates/<industry>/score.md         (domain-specific frameworks: SWECOM/SFIA for swe)
        + templates/<industry>/invariants.md    (per-field mechanism oracle, optional)
        + templates/<industry>/grader.md        (procedural rules + output schema)

    The invariants file gates articulation credit on mechanism satisfaction; it's
    stitched into the grader only (NOT the generator) so the model that scores
    answers sees the per-field mechanism floors, while the model that generates
    questions does not pre-tell itself what answer is on-mechanism.

    YAML placeholders inside score.md and grader.md are substituted post-load so
    the band ladder (commands/bands.py / grader.md / score.md previously
    out-of-sync) renders from a single source of truth.
    """
    dreyfus = _load_root_template("dreyfus")
    score = _stitch_band_data(_load_template(industry, "score"))
    invariants = _load_optional_template(industry, "invariants")
    grader = _stitch_band_data(_load_template(industry, "grader"))
    parts = [dreyfus, score]
    if invariants:
        parts.append(invariants)
    parts.append(grader)
    return SCORE_GRADER_SEPARATOR.join(parts)


def _validate_literature_entry(entry: dict[str, Any], where: str) -> None:
    for key in ("type", "title", "author", "url", "section", "reading_time_estimate", "why"):
        if key not in entry:
            raise GradingError(f"{where} literature missing key {key!r}")
    if entry["type"] not in _LIT_TYPES:
        raise GradingError(f"{where} literature.type must be remediation|growth, got {entry['type']!r}")


def _validate_question_grading(qg: dict[str, Any], expected_id: int, answerer_band: str) -> None:
    if qg.get("question_id") != expected_id:
        raise GradingError(f"questions_grading[{expected_id - 1}] question_id mismatch")
    for key in (
        "field",
        "topics",
        "bands_pre",
        "bands_post",
        "band_ceiling_post",
        "assessment",
        "response_redacted",
        "refine_response_redacted",
        "literature",
    ):
        if key not in qg:
            raise GradingError(f"questions_grading[{expected_id - 1}] missing key {key!r}")
    for redacted_key in ("response_redacted", "refine_response_redacted"):
        if not isinstance(qg[redacted_key], str):
            raise GradingError(
                f"questions_grading[{expected_id - 1}].{redacted_key} must be a string, got {type(qg[redacted_key]).__name__}"
            )
    for tag in ("bands_pre", "bands_post"):
        if not isinstance(qg[tag], list) or len(qg[tag]) != 5:
            raise GradingError(f"questions_grading[{expected_id - 1}] {tag} must be 5 entries")
    lit = qg["literature"]
    if not isinstance(lit, list):
        raise GradingError(f"questions_grading[{expected_id - 1}] literature must be a list")
    if len(lit) not in (0, 2):
        raise GradingError(
            f"questions_grading[{expected_id - 1}] literature must be exactly 2 entries (or 0 if unattempted), got {len(lit)}"
        )
    for i, e in enumerate(lit):
        _validate_literature_entry(e, f"questions_grading[{expected_id - 1}].literature[{i}]")
    if not lit:
        return

    # Mix rule (matches grader.md): driven by the post-refinement score AT THE
    # PRIMARY EVALUATION BAND, mapped to a band-treatment.
    #   score 5  → 2 × growth      (answerer hit ceiling at primary band)
    #   score 4  → 1 growth + 1 remediation
    #   score ≤3 → 2 × remediation (foundational gap)
    primary_score: int | None = None
    for b in qg.get("bands_post") or []:
        if isinstance(b, dict) and b.get("band") == answerer_band:
            raw = b.get("score")
            if isinstance(raw, (int, float)):
                primary_score = int(raw)
            break
    if primary_score is None:
        # No primary-band score available — accept any 2-entry mix.
        return

    types = sorted(e["type"] for e in lit)
    if primary_score >= 5 and types != ["growth", "growth"]:
        raise GradingError(
            f"Q{expected_id} primary-band score {primary_score} at {answerer_band} requires 2 growth entries, got {types}"
        )
    if primary_score == 4 and types != ["growth", "remediation"]:
        raise GradingError(
            f"Q{expected_id} primary-band score 4 at {answerer_band} requires 1 growth + 1 remediation, got {types}"
        )
    if 1 <= primary_score <= 3 and types != ["remediation", "remediation"]:
        raise GradingError(
            f"Q{expected_id} primary-band score {primary_score} at {answerer_band} requires 2 remediation entries, got {types}"
        )


def _format_delta_string(x: float) -> str:
    """Format a 1-decimal float as the signed string the schema requires:
    '+0.6' / '-0.4' / '0.0' (no '+' on zero, no '-0.0').
    """
    rounded = round(x, 1)
    if rounded == 0:
        return "0.0"
    if rounded > 0:
        return f"+{rounded:.1f}"
    return f"{rounded:.1f}"


def _primary_score(qg: dict[str, Any], tag: str, answerer_band: str) -> int | None:
    for b in qg.get(tag) or []:
        if isinstance(b, dict) and b.get("band") == answerer_band:
            raw = b.get("score")
            if isinstance(raw, (int, float)):
                return int(raw)
            return None
    return None


def _validate_grading(out: dict[str, Any], answerer_band: str) -> None:
    for key in (
        "session_summary",
        "questions_grading",
        "run_aggregation",
        "field_delta",
        "topic_delta",
        "meta_updates",
    ):
        if key not in out:
            raise GradingError(f"grading output missing key {key!r}")
    qg = out["questions_grading"]
    if not isinstance(qg, list) or len(qg) != 5:
        raise GradingError(f"questions_grading must be a list of 5, got {type(qg).__name__} len={len(qg) if isinstance(qg, list) else 'n/a'}")
    for i, q in enumerate(qg, start=1):
        _validate_question_grading(q, i, answerer_band)
    agg = out["run_aggregation"]
    for key in (
        "aggregated_score",
        "aggregated_score_pre",
        "aggregated_score_post",
        "assisted_delta",
        "fail_count_pre",
        "fail_count_post",
        "career_level",
        "strengths",
        "weaknesses",
    ):
        if key not in agg:
            raise GradingError(f"run_aggregation missing key {key!r}")
    for key in ("aggregated_score", "aggregated_score_pre", "aggregated_score_post"):
        v = agg[key]
        if not isinstance(v, (int, float)) or not (1.0 <= float(v) <= 5.0):
            raise GradingError(f"run_aggregation.{key} must be a number in [1.0, 5.0], got {v!r}")
    delta = agg["assisted_delta"]
    if not isinstance(delta, str) or not _DELTA_RE.match(delta):
        raise GradingError(
            f"run_aggregation.assisted_delta must be a signed 1-decimal string (e.g. '+0.6'), got {delta!r}"
        )
    for key in ("fail_count_pre", "fail_count_post"):
        v = agg[key]
        if not isinstance(v, int) or not (0 <= v <= 5):
            raise GradingError(f"run_aggregation.{key} must be an integer in [0, 5], got {v!r}")
    # Recompute every primary-band aggregate from the per-question primary-band scores
    # and OVERWRITE the model's emission. The model owns the per-question judgment
    # (scores, bands, assessments, literature); the application owns the arithmetic.
    # Previously we validated the model's arithmetic and raised on mismatch; that
    # invited a regression where a stuck model re-emitted the same wrong value
    # through the retry hint and exhausted the retry budget. Overwriting eliminates
    # the failure mode entirely. Type/range checks above still fire when the model
    # emits a non-number where a number is expected — once the shape is right we
    # just don't trust the value.
    pre_primary = [
        s for q in qg if (s := _primary_score(q, "bands_pre", answerer_band)) is not None
    ]
    post_primary = [
        s for q in qg if (s := _primary_score(q, "bands_post", answerer_band)) is not None
    ]

    fail_threshold = band_data.critical_failure_config().fail_score_threshold
    agg["fail_count_pre"] = sum(1 for s in pre_primary if s <= fail_threshold)
    agg["fail_count_post"] = sum(1 for s in post_primary if s <= fail_threshold)

    # When the primary band is absent on every question (`pre_primary`/`post_primary`
    # empty) the bands_pre/post 5-entry check above would already have raised — the
    # guards here are defensive against that check being relaxed.
    expected_pre_mean: float | None = None
    expected_post_mean: float | None = None
    if pre_primary:
        expected_pre_mean = round(sum(pre_primary) / len(pre_primary), 1)
        agg["aggregated_score_pre"] = expected_pre_mean
        # career_level and aggregate_dreyfus_stage derive from aggregated_score_pre
        # (the unassisted score) via band_data.score_to_keyword.
        career, stage = band_data.score_to_keyword(expected_pre_mean)
        agg["career_level"] = career
        ss = out.get("session_summary")
        if isinstance(ss, dict):
            ss["aggregate_dreyfus_stage"] = stage
    if post_primary:
        expected_post_mean = round(sum(post_primary) / len(post_primary), 1)
        agg["aggregated_score_post"] = expected_post_mean
        # `aggregated_score` is documented as the alias of aggregated_score_post.
        agg["aggregated_score"] = expected_post_mean
    if expected_pre_mean is not None and expected_post_mean is not None:
        agg["assisted_delta"] = _format_delta_string(expected_post_mean - expected_pre_mean)
    mu = out["meta_updates"]
    if not isinstance(mu, dict):
        raise GradingError("meta_updates must be an object")
    if "criteria_set" in mu:
        if not isinstance(mu["criteria_set"], dict):
            raise GradingError("meta_updates.criteria_set must be an object")
        bad = [s for s in mu["criteria_set"].keys() if s not in parse.CANONICAL_FIELDS]
        if bad:
            raise GradingError(
                f"meta_updates.criteria_set has non-canonical field slug(s): {bad}. "
                f"Valid: {sorted(parse.CANONICAL_FIELDS.keys())}"
            )
    if "topics_added" in mu:
        if not isinstance(mu["topics_added"], dict):
            raise GradingError("meta_updates.topics_added must be an object")
        bad = [s for s in mu["topics_added"].keys() if s not in parse.CANONICAL_FIELDS]
        if bad:
            raise GradingError(
                f"meta_updates.topics_added has non-canonical field slug(s): {bad}. "
                f"Valid: {sorted(parse.CANONICAL_FIELDS.keys())}"
            )


def _build_user_prompt_grade(
    *,
    answerer_band: str,
    current_run: dict[str, Any],
    entry_state: dict[str, Any],
    comparison_points: dict[str, Any],
    meta_json: dict[str, Any],
) -> str:
    return (
        "Grade the completed spot check run.\n\n"
        f"primary_evaluation_band: {json.dumps(answerer_band)}\n\n"
        "current_run:\n"
        f"{json.dumps(current_run, ensure_ascii=False)}\n\n"
        "entry_state (snapshot at session start; use for `-1` within-session deltas):\n"
        f"{json.dumps(entry_state, ensure_ascii=False)}\n\n"
        "comparison_points (last 1/5/10/30 graded runs; omit any key absent here from delta output):\n"
        f"{json.dumps(comparison_points, ensure_ascii=False)}\n\n"
        "meta_json (current; reuse existing citation keys where possible, propose new ones in meta_updates.criteria_set):\n"
        f"{json.dumps(meta_json, ensure_ascii=False)}\n"
    )


def grade(
    *,
    industry: str = DEFAULT_INDUSTRY,
    answerer_band: str,
    current_run: dict[str, Any],
    entry_state: dict[str, Any] | None = None,
    comparison_points: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4 grading. One sandboxed LLM call (with up to one retry).

    Loads the stitched score+grader system prompt, builds the user prompt with
    current run + comparison context, validates the strict output schema, and
    enforces the band-keyed 2-literature-per-question invariant.
    """
    system_prompt = build_grader_system(industry)
    meta = parse.read_meta()
    user = _build_user_prompt_grade(
        answerer_band=answerer_band,
        current_run=current_run,
        entry_state=entry_state or {"date": None, "field_scores": {}, "topic_scores": {}, "career_level": ""},
        comparison_points=comparison_points or {},
        meta_json=meta,
    )
    model = llm.get_model("generate")

    # Two orthogonal recovery paths with independent budgets:
    #   - Truncation: same prompt, just needs more headroom. One bump 24000 → 32000.
    #   - Validation: same budget, needs a prompt-level correction. One reminder pass.
    # Pooling them caused a regression where a truncation on attempt 1 left no slot to
    # repair an arithmetic mismatch on attempt 2. Cap total iterations at 3 so a
    # pathological loop can't run away.
    last_error: Exception | None = None
    max_tokens = 24000
    truncation_bumps_left = 1
    validation_retries_left = 1
    for attempt in range(1, 4):
        try:
            raw = llm.call_llm(system=system_prompt, user=user, model=model, max_tokens=max_tokens)
            parsed = json.loads(_extract_first_json_object(raw))
            _validate_grading(parsed, answerer_band)
            parsed["report_markdown"] = render_report(
                grading=parsed,
                current_run=current_run,
                answerer_band=answerer_band,
            )
            return parsed
        except llm.LLMTruncatedError as e:
            last_error = e
            log.warning("grading attempt %d truncated at max_tokens=%d: %s", attempt, max_tokens, e)
            if truncation_bumps_left <= 0:
                raise GradingError(
                    f"grading output exceeded {max_tokens} tokens after retry; "
                    "consider trimming input (comparison_points/meta_json) or splitting the schema"
                ) from e
            truncation_bumps_left -= 1
            # claude-opus-4-7's standard ceiling. If 32000 still truncates the schema/input
            # is structurally too large and a further token bump won't save us.
            max_tokens = 32000
        except (json.JSONDecodeError, GradingError) as e:
            last_error = e
            log.warning("grading attempt %d failed: %s", attempt, e)
            if validation_retries_left <= 0:
                break
            validation_retries_left -= 1
            user = user + _validation_retry_hint(e)
        except llm.LLMError as e:
            raise GradingError(f"LLM call failed: {e}") from e
    raise GradingError(f"grading failed after retry: {last_error}")


def _validation_retry_hint(error: Exception) -> str:
    """Append a tailored correction hint to the user prompt based on what the validator
    flagged. The previous static reminder preached the literature-mix rule even when
    the failure was arithmetic, which was noisy and unhelpful — match the hint to the
    error so the model can self-diagnose instead of re-checking the wrong invariant.
    """
    msg = str(error)
    msg_l = msg.lower()
    base = f'\n\nPrevious attempt failed validation: "{msg}". Regenerate the same JSON correctly per the schema.'
    # Note: the run_aggregation arithmetic-mismatch branch was dropped after
    # _validate_grading switched from validating to overwriting those fields — the
    # validator no longer raises "disagrees with per-question recompute" or the
    # aggregated_score / fail_count_* mismatches, so the corresponding hint is
    # unreachable. Literature mix and assisted_delta-format errors still raise.
    if "literature" in msg_l:
        return base + (
            " Literature mix is driven by the POST-REFINEMENT SCORE AT THE PRIMARY EVALUATION BAND: "
            "score 5 → 2 growth; score 4 → 1 growth + 1 remediation; score 1–3 → 2 remediation."
        )
    if "assisted_delta" in msg_l:
        return base + (
            " assisted_delta is the signed string of (aggregated_score_post − aggregated_score_pre) "
            "rounded to 1 decimal, e.g. '+0.6', '-0.4', '0.0'."
        )
    return base
