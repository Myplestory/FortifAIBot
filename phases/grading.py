from __future__ import annotations

import json
import logging
import re
from typing import Any

import llm
import parse

from phases import band_data, movement
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
_BANDS = ("B1", "B2", "B3", "B4", "B5")

# Fix A — band-ceiling thresholds. Tunable. The ceiling marks genuine mastery
# (the score table puts "core insight present" at 4); the transitional band
# marks correct-direction-but-incomplete (score 3). Derived in code, not
# improvised by the judge — per Zheng et al., threshold logic belongs in code.
_CEILING_THRESHOLD = 4
_TRANSITIONAL_THRESHOLD = 3


class GradingError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# System prompt builders
#
# The monolithic grader split into two prompts (Fix E): a per-question grader
# applied once per question in isolation, and a small qualitative-stitch prompt
# applied once at the end for cross-question themes. All run-level arithmetic
# moved out of the prompt entirely into `_stitch`.
# --------------------------------------------------------------------------


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
    a no-op when the placeholders are absent.
    """
    if "{{BAND_TABLE_VERBATIM}}" in text:
        text = text.replace("{{BAND_TABLE_VERBATIM}}", band_data.render_band_table_md())
    if "{{SFIA_FACETS_TABLE}}" in text:
        text = text.replace("{{SFIA_FACETS_TABLE}}", band_data.render_sfia_facets_md())
    return text


def build_question_grader_system(industry: str = DEFAULT_INDUSTRY) -> str:
    """Per-question grader system prompt:
        templates/dreyfus.md                       (cross-domain skill-stage taxonomy)
        + templates/<industry>/score.md              (domain-specific frameworks)
        + templates/<industry>/invariants.md         (per-field mechanism oracle, optional)
        + templates/<industry>/grader_question.md    (per-question procedural rules + schema)

    One sandboxed LLM call per question is built from this prompt; run-level
    aggregation, deltas, and the report are assembled deterministically
    afterward. YAML placeholders are substituted post-load so the band ladder
    renders from a single source of truth.
    """
    dreyfus = _load_root_template("dreyfus")
    score = _stitch_band_data(_load_template(industry, "score"))
    invariants = _load_optional_template(industry, "invariants")
    grader = _stitch_band_data(_load_template(industry, "grader_question"))
    parts = [dreyfus, score]
    if invariants:
        parts.append(invariants)
    parts.append(grader)
    return SCORE_GRADER_SEPARATOR.join(parts)


def build_stitch_grader_system(industry: str = DEFAULT_INDUSTRY) -> str:
    """Qualitative-stitch system prompt — a single small file. The stitch call
    only synthesises cross-question themes (delta overlap/diff, level-change
    reasons); all run-level arithmetic is done in `_stitch`, so this prompt does
    not carry the band ladder or the scoring rubric.
    """
    return _load_template(industry, "grader_stitch")


# --------------------------------------------------------------------------
# Per-question grading — one sandboxed LLM call per question
# --------------------------------------------------------------------------


def _question_records(current_run: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap `current_run.questions` (list of `{"question_<i>": rec}` wrappers)
    into an ordered list of question records.
    """
    out: list[dict[str, Any]] = []
    for wrap in current_run.get("questions", []) or []:
        if not isinstance(wrap, dict):
            continue
        for _, rec in wrap.items():
            if isinstance(rec, dict):
                out.append(rec)
                break
    return out


_QUESTION_INPUT_KEYS = (
    "field",
    "topics",
    "sfia_skills",
    "question",
    "response",
    "refine",
    "refine_response",
    "refine_form",
)


def _validate_literature_entry(entry: dict[str, Any], where: str) -> None:
    for key in ("type", "title", "author", "url", "section", "reading_time_estimate", "why"):
        if key not in entry:
            raise GradingError(f"{where} literature missing key {key!r}")
    if entry["type"] not in _LIT_TYPES:
        raise GradingError(f"{where} literature.type must be remediation|growth, got {entry['type']!r}")


def _validate_question_result(qr: dict[str, Any], expected_id: int, answerer_band: str) -> None:
    """Validate one `_grade_question` LLM output. Identity fields (question_id,
    field, topics) are app-owned and overwritten before this runs, so this only
    checks the LLM-authored fields. `band_ceiling_post` / `transitional_post`
    are no longer emitted by the grader (Fix A — derived in `_stitch`). Raises
    GradingError so the per-call retry can correct the model.
    """
    where = f"question {expected_id}"
    for key in (
        "reference",
        "bands_pre",
        "bands_post",
        "assessment",
        "response_redacted",
        "refine_response_redacted",
        "literature",
        "criteria",
        "topics_added",
    ):
        if key not in qr:
            raise GradingError(f"{where}: missing key {key!r}")
    # Fix C: the grader must commit a reference before scoring.
    ref = qr["reference"]
    if not isinstance(ref, dict):
        raise GradingError(f"{where}: reference must be an object")
    if not isinstance(ref.get("mechanism_invariant"), str) or not ref["mechanism_invariant"].strip():
        raise GradingError(f"{where}: reference.mechanism_invariant must be a non-empty string")
    for ref_key in ("key_facts", "citations"):
        if not isinstance(ref.get(ref_key), list):
            raise GradingError(f"{where}: reference.{ref_key} must be a list")
    for redacted_key in ("response_redacted", "refine_response_redacted"):
        if not isinstance(qr[redacted_key], str):
            raise GradingError(
                f"{where}: {redacted_key} must be a string, got {type(qr[redacted_key]).__name__}"
            )
    for tag in ("bands_pre", "bands_post"):
        if not isinstance(qr[tag], list) or len(qr[tag]) != 5:
            raise GradingError(f"{where}: {tag} must be exactly 5 band entries")
    if not isinstance(qr["criteria"], dict):
        raise GradingError(f"{where}: criteria must be an object")
    bad_bands = [b for b in qr["criteria"].keys() if b not in _BANDS]
    if bad_bands:
        raise GradingError(f"{where}: criteria has non-band key(s) {bad_bands}")
    if not isinstance(qr["topics_added"], list):
        raise GradingError(f"{where}: topics_added must be a list")

    lit = qr["literature"]
    if not isinstance(lit, list):
        raise GradingError(f"{where}: literature must be a list")
    if len(lit) not in (0, 2):
        raise GradingError(
            f"{where}: literature must be exactly 2 entries (or 0 if unattempted), got {len(lit)}"
        )
    for i, e in enumerate(lit):
        _validate_literature_entry(e, f"{where}.literature[{i}]")
    if not lit:
        return

    # Mix rule (matches grader_question.md): driven by the post-refinement score
    # AT THE PRIMARY EVALUATION BAND.
    #   score 5  → 2 × growth
    #   score 4  → 1 growth + 1 remediation
    #   score ≤3 → 2 × remediation
    primary_score = movement.primary_band_score(qr.get("bands_post"), answerer_band)
    if primary_score is None:
        return
    types = sorted(e["type"] for e in lit)
    if primary_score >= 5 and types != ["growth", "growth"]:
        raise GradingError(
            f"{where}: literature mix — primary-band post score {primary_score} requires 2 growth entries, got {types}"
        )
    if primary_score == 4 and types != ["growth", "remediation"]:
        raise GradingError(
            f"{where}: literature mix — primary-band post score 4 requires 1 growth + 1 remediation, got {types}"
        )
    if 1 <= primary_score <= 3 and types != ["remediation", "remediation"]:
        raise GradingError(
            f"{where}: literature mix — primary-band post score {primary_score} requires 2 remediation entries, got {types}"
        )


def _build_user_prompt_question(
    *,
    question_id: int,
    answerer_band: str,
    qrec: dict[str, Any],
    meta_field: dict[str, Any],
) -> str:
    scoped = {k: qrec.get(k) for k in _QUESTION_INPUT_KEYS}
    return (
        f"Grade question {question_id} of a completed spot check run, in isolation. "
        "You see only this question — nothing else from the run.\n\n"
        f"primary_evaluation_band: {json.dumps(answerer_band)}\n\n"
        "question (the complete conversation for this question — original response, "
        "refinement probe, and refine_response — presented intact in one place; "
        "score the post-refinement state as primary):\n"
        f"{json.dumps(scoped, ensure_ascii=False)}\n\n"
        "meta_field (existing meta.json knowledge for this question's field; reuse "
        "existing citation keys where possible, propose new ones in `criteria`):\n"
        f"{json.dumps(meta_field, ensure_ascii=False)}\n"
    )


def _question_retry_hint(error: Exception) -> str:
    """Append a tailored correction hint based on what the validator flagged so
    the model can self-diagnose instead of re-checking the wrong invariant.
    """
    msg = str(error)
    msg_l = msg.lower()
    base = (
        f'\n\nPrevious attempt failed validation: "{msg}". '
        "Regenerate the same JSON correctly per the per-question output schema."
    )
    if "literature" in msg_l:
        return base + (
            " Literature mix is driven by the POST-REFINEMENT SCORE AT THE PRIMARY EVALUATION BAND: "
            "score 5 → 2 growth; score 4 → 1 growth + 1 remediation; score 1–3 → 2 remediation."
        )
    if "bands_pre" in msg_l or "bands_post" in msg_l:
        return base + " bands_pre and bands_post must EACH be exactly 5 entries, one per band B1–B5 in order."
    return base


def _grade_question(
    *,
    system_prompt: str,
    answerer_band: str,
    question_id: int,
    qrec: dict[str, Any],
    meta_field: dict[str, Any],
) -> dict[str, Any]:
    """One sandboxed LLM call grading a single question against all five bands.

    `llm.call_llm` is stateless; sandboxing is enforced by building this call's
    prompt from scratch with only this question's data — no run-level context,
    no carryover from sibling questions. Per-question output is small, so
    truncation is rare: a modest budget with one bump plus a short
    validation-retry chain replaces the monolithic grader's pooled 32k budget.
    Total iterations capped at 3.
    """
    user = _build_user_prompt_question(
        question_id=question_id,
        answerer_band=answerer_band,
        qrec=qrec,
        meta_field=meta_field,
    )
    model = llm.get_model("generate")
    log.info("grading question %d/5 field=%s band=%s", question_id, qrec.get("field"), answerer_band)

    last_error: Exception | None = None
    max_tokens = 12000
    truncation_bumps_left = 1
    validation_retries_left = 2
    for attempt in range(1, 4):
        try:
            raw = llm.call_llm(system=system_prompt, user=user, model=model, max_tokens=max_tokens)
            parsed = json.loads(_extract_first_json_object(raw))
            # The app owns identity fields — overwrite the LLM's echo so a
            # mis-echo can't corrupt the stitch. A robustness win from
            # sandboxing per question (the monolithic grader could not).
            parsed["question_id"] = question_id
            parsed["field"] = qrec.get("field")
            parsed["topics"] = qrec.get("topics") or []
            _validate_question_result(parsed, question_id, answerer_band)
            return parsed
        except llm.LLMTruncatedError as e:
            last_error = e
            log.warning("question %d attempt %d truncated at max_tokens=%d", question_id, attempt, max_tokens)
            if truncation_bumps_left <= 0:
                raise GradingError(
                    f"question {question_id} grading exceeded {max_tokens} tokens after bump"
                ) from e
            truncation_bumps_left -= 1
            max_tokens = 20000
        except (json.JSONDecodeError, GradingError) as e:
            last_error = e
            log.warning("question %d grading attempt %d failed: %s", question_id, attempt, e)
            if validation_retries_left <= 0:
                break
            validation_retries_left -= 1
            user = user + _question_retry_hint(e)
        except llm.LLMError as e:
            raise GradingError(f"question {question_id} LLM call failed: {e}") from e
    raise GradingError(f"question {question_id} grading failed after retry: {last_error}")


# --------------------------------------------------------------------------
# Deterministic stitch — pure arithmetic / threshold logic, no LLM call
# --------------------------------------------------------------------------


def _derive_ceiling(
    bands_post: list[Any] | None,
) -> tuple[str | None, str | None, bool]:
    """Derive `(band_ceiling_post, transitional_post, non_monotonic_post)` from a
    post-refinement band profile (Fix A).

    A genuine mastery ceiling is *contiguous*: you have not "reached" B4 if you
    scored below mastery at B2. So:
      - `band_ceiling_post`: the highest band B_k such that every band B1..B_k
        scored ≥ _CEILING_THRESHOLD — an unbroken mastery prefix ("core insight
        present"). `None` when even B1 falls short. A high score at B5 with a
        hole at B2 does NOT raise the ceiling; that hole is a discrepancy to
        surface, not launder into a clean number.
      - `transitional_post`: the single band immediately above the ceiling, when
        it scored ≥ _TRANSITIONAL_THRESHOLD (correct direction, approaching).
        Adjacent-only — it never jumps the gap. With no ceiling yet the adjacent
        band is B1; with a B5 ceiling there is no band above.
      - `non_monotonic_post`: True when some band outscored the band below it.
        A coherent profile is non-increasing (higher bands are strictly harder);
        a rise means the five-band scores are not internally consistent, and the
        contiguous ceiling alone would otherwise hide that.
    """
    scores: dict[int, float] = {}
    for b in bands_post or []:
        if not isinstance(b, dict):
            continue
        idx = movement._band_index(b.get("band"))
        score = b.get("score")
        if idx is None or not isinstance(score, (int, float)):
            continue
        scores[idx] = score

    # Contiguous mastery prefix: walk B1→B5, stop at the first band that breaks.
    ceiling_idx: int | None = None
    for i in range(len(_BANDS)):
        if i in scores and scores[i] >= _CEILING_THRESHOLD:
            ceiling_idx = i
        else:
            break

    # Transitional: the adjacent band just above the ceiling (B1 when there is
    # no ceiling yet), credited only when it clears the transitional threshold.
    adjacent_idx = 0 if ceiling_idx is None else ceiling_idx + 1
    transitional_idx: int | None = None
    if (
        adjacent_idx < len(_BANDS)
        and adjacent_idx in scores
        and scores[adjacent_idx] >= _TRANSITIONAL_THRESHOLD
    ):
        transitional_idx = adjacent_idx

    # Non-monotonic: any band scoring strictly above the band below it.
    ordered = [scores[i] for i in range(len(_BANDS)) if i in scores]
    non_monotonic = any(hi > lo for lo, hi in zip(ordered, ordered[1:]))

    ceiling = _BANDS[ceiling_idx] if ceiling_idx is not None else None
    transitional = _BANDS[transitional_idx] if transitional_idx is not None else None
    return ceiling, transitional, non_monotonic


def _ceiling_stats(question_results: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    """(median, low, high) of the per-question `band_ceiling_post` values, by
    band index. Unattempted questions (null ceiling) are excluded; all-null
    yields (None, None, None).
    """
    ceilings = sorted(
        (qr.get("band_ceiling_post") for qr in question_results
         if qr.get("band_ceiling_post") in _BANDS),
        key=_BANDS.index,
    )
    if not ceilings:
        return None, None, None
    return ceilings[len(ceilings) // 2], ceilings[0], ceilings[-1]


def _merge_criteria(question_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble `meta_updates.criteria_set` from each question's per-field
    `criteria`. Group by field; on a same-field collision (two questions in one
    field), keep the longer description, union citations, take the latest
    reasoning — the same merge `parse.apply_meta_updates` applies downstream.
    """
    out: dict[str, dict[str, Any]] = {}
    for qr in question_results:
        field = qr.get("field")
        criteria = qr.get("criteria")
        if not isinstance(field, str) or not field or not isinstance(criteria, dict) or not criteria:
            continue
        field_bucket = out.setdefault(field, {})
        for band, entry in criteria.items():
            if band not in _BANDS or not isinstance(entry, dict):
                continue
            existing = field_bucket.get(band)
            if existing is None:
                field_bucket[band] = entry
                continue
            if len(entry.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = entry["description"]
                if entry.get("name"):
                    existing["name"] = entry["name"]
            existing_cites = existing.setdefault("citations", {})
            for ck, cv in (entry.get("citations") or {}).items():
                existing_cites.setdefault(ck, cv)
            if entry.get("reasoning"):
                existing["reasoning"] = entry["reasoning"]
    # Drop fields whose every entry was filtered out (non-band keys / non-dicts).
    return {f: bands for f, bands in out.items() if bands}


def _merge_topics_added(question_results: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Assemble `meta_updates.topics_added` from each question's per-field
    `topics_added`, deduped, first-seen order preserved. Empty buckets dropped.
    """
    out: dict[str, list[str]] = {}
    for qr in question_results:
        field = qr.get("field")
        added = qr.get("topics_added")
        if not isinstance(field, str) or not field or not isinstance(added, list):
            continue
        bucket = out.setdefault(field, [])
        for t in added:
            if isinstance(t, str) and t and t not in bucket:
                bucket.append(t)
    return {f: ts for f, ts in out.items() if ts}


_QG_VIEW_KEYS = (
    "question_id",
    "field",
    "topics",
    "reference",
    "bands_pre",
    "bands_post",
    "band_ceiling_post",
    "transitional_post",
    "non_monotonic_post",
    "assessment",
    "response_redacted",
    "refine_response_redacted",
    "literature",
)


def _question_grading_view(qr: dict[str, Any]) -> dict[str, Any]:
    """Project a per-question result onto the persisted `questions_grading`
    schema — drops `criteria` / `topics_added`, which the stitch rolls into
    `meta_updates`.
    """
    return {k: qr.get(k) for k in _QG_VIEW_KEYS}


def _stitch(
    question_results: list[dict[str, Any]],
    *,
    answerer_band: str,
    current_run: dict[str, Any],
    entry_state: dict[str, Any] | None,
    comparison_points: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Deterministic cross-question stitch — pure arithmetic and threshold logic,
    no LLM call (per Zheng et al.: threshold logic belongs in code, not the
    judge). Produces `run_aggregation`, the numeric/band-derived `session_summary`
    fields, the `field_delta` / `topic_delta` trees, `meta_updates`, and the
    `questions_grading` projection.

    Returns `(stitched, delta_jobs)` — the assembled (report-less) grading dict
    plus the flat `delta_jobs` list the qualitative stitch themes.
    """
    # Fix A: band ceiling / transitional / non-monotonic flag are derived
    # deterministically from each question's post-refinement band profile — the
    # per-question grader no longer emits them. Set them on the result dicts so
    # the projection, ceiling stats, and strengths logic below all read one
    # derived value.
    for qr in question_results:
        ceiling, transitional, non_monotonic = _derive_ceiling(qr.get("bands_post"))
        qr["band_ceiling_post"] = ceiling
        qr["transitional_post"] = transitional
        qr["non_monotonic_post"] = non_monotonic

    fail_threshold = band_data.critical_failure_config().fail_score_threshold

    pre_scores = [
        s for qr in question_results
        if (s := movement.primary_band_score(qr.get("bands_pre"), answerer_band)) is not None
    ]
    post_scores = [
        s for qr in question_results
        if (s := movement.primary_band_score(qr.get("bands_post"), answerer_band)) is not None
    ]
    pre_mean = round(sum(pre_scores) / len(pre_scores), 1) if pre_scores else None
    post_mean = round(sum(post_scores) / len(post_scores), 1) if post_scores else None

    career_level, dreyfus_stage = "", ""
    if pre_mean is not None:
        career_level, dreyfus_stage = band_data.score_to_keyword(pre_mean)

    assisted_delta = "0.0"
    if pre_mean is not None and post_mean is not None:
        assisted_delta = movement.format_delta_string(post_mean - pre_mean)

    # strengths / weaknesses — the grader rules, moved into code.
    field_post = movement.current_field_scores(question_results, answerer_band)
    topic_post = movement.current_topic_scores(question_results, answerer_band)
    band_i = movement._band_index(answerer_band)
    next_band_idx = band_i + 1 if band_i is not None else None
    field_ceiling: dict[str, int] = {}
    for qr in question_results:
        f = qr.get("field")
        c = movement._band_index(qr.get("band_ceiling_post"))
        if isinstance(f, str) and f and c is not None:
            field_ceiling[f] = max(field_ceiling.get(f, -1), c)
    strengths_fields = sorted(
        f for f, c in field_ceiling.items()
        if next_band_idx is not None and c >= next_band_idx
    )
    strengths_topics = sorted(t for t, s in topic_post.items() if s >= 4)
    weaknesses_fields = sorted(f for f, s in field_post.items() if s <= 2)
    weaknesses_topics = sorted(t for t, s in topic_post.items() if s <= 2)

    run_aggregation = {
        "aggregated_score_pre": pre_mean,
        "aggregated_score_post": post_mean,
        "aggregated_score": post_mean,  # documented alias of aggregated_score_post
        "assisted_delta": assisted_delta,
        "fail_count_pre": sum(1 for s in pre_scores if s <= fail_threshold),
        "fail_count_post": sum(1 for s in post_scores if s <= fail_threshold),
        "career_level": career_level,
        "strengths": {"fields": strengths_fields, "topics": strengths_topics},
        "weaknesses": {"fields": weaknesses_fields, "topics": weaknesses_topics},
    }

    # session_summary — numeric / band-derived fields, fully deterministic.
    median_ceiling, range_low, range_high = _ceiling_stats(question_results)
    attempted = sum(
        1 for qrec in _question_records(current_run)
        if (qrec.get("response") or "").strip()
    )
    # Confidence in the aggregate as a real measurement: a full 5-question run
    # is High; a partly-abandoned run is less of a measurement.
    confidence = "High" if attempted >= 5 else ("Medium" if attempted >= 3 else "Low")
    session_summary: dict[str, Any] = {
        "primary_evaluation_band": answerer_band,
        "median_band_ceiling": median_ceiling,
        "range_low": range_low,
        "range_high": range_high,
        "aggregate_dreyfus_stage": dreyfus_stage,
        "aggregate_swecom_level": None,
        "aggregate_sfia_level": None,
        "aggregate_yoe_equivalent": None,
        "confidence": confidence,
    }
    if median_ceiling in _BANDS:
        row = band_data.get_band(median_ceiling)
        session_summary["aggregate_swecom_level"] = row.swecom.level
        session_summary["aggregate_sfia_level"] = row.sfia.level
        session_summary["aggregate_yoe_equivalent"] = f"{row.yoe_range} years"

    field_delta, topic_delta, delta_jobs = movement.build_delta_trees(
        question_results,
        answerer_band,
        entry_state=entry_state,
        comparison_points=comparison_points,
    )

    stitched = {
        "session_summary": session_summary,
        "questions_grading": [_question_grading_view(qr) for qr in question_results],
        "run_aggregation": run_aggregation,
        "field_delta": field_delta,
        "topic_delta": topic_delta,
        "meta_updates": {
            "criteria_set": _merge_criteria(question_results),
            "topics_added": _merge_topics_added(question_results),
        },
    }
    return stitched, delta_jobs


# --------------------------------------------------------------------------
# Qualitative stitch — one small LLM call for cross-question themes
# --------------------------------------------------------------------------


def _build_user_prompt_stitch(
    question_results: list[dict[str, Any]],
    delta_jobs: list[dict[str, Any]],
) -> str:
    compact = []
    for qr in question_results:
        compact.append({
            "question_id": qr.get("question_id"),
            "field": qr.get("field"),
            "topics": qr.get("topics"),
            "assessment": qr.get("assessment"),
            "bands_post": [
                {
                    "band": b.get("band"),
                    "score": b.get("score"),
                    "reason": b.get("reason"),
                    "citations": b.get("citations"),
                }
                for b in (qr.get("bands_post") or [])
                if isinstance(b, dict)
            ],
        })
    return (
        "Synthesize the cross-question qualitative layer for this graded run.\n\n"
        "question_results (compact — the five questions, already graded):\n"
        f"{json.dumps(compact, ensure_ascii=False)}\n\n"
        "delta_jobs (arithmetic already computed — emit one theme record per id):\n"
        f"{json.dumps(delta_jobs, ensure_ascii=False)}\n"
    )


def _validate_stitch_result(out: dict[str, Any], delta_jobs: list[dict[str, Any]]) -> None:
    themes = out.get("themes")
    if not isinstance(themes, list):
        raise GradingError("stitch output: themes must be a list")
    got_ids = {t.get("id") for t in themes if isinstance(t, dict)}
    want_ids = {j["id"] for j in delta_jobs}
    missing = want_ids - got_ids
    if missing:
        raise GradingError(f"stitch output: missing theme record(s) for id(s) {sorted(missing)}")


def _stitch_qualitative(
    *,
    industry: str,
    question_results: list[dict[str, Any]],
    delta_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One small LLM call: the genuinely cross-question qualitative output —
    delta overlap/diff themes and level-change reasons. The orchestrator only
    calls this when `delta_jobs` is non-empty; in Phase 1 no call site passes
    entry_state / comparison_points, so this stays dormant.
    """
    system_prompt = build_stitch_grader_system(industry)
    user = _build_user_prompt_stitch(question_results, delta_jobs)
    model = llm.get_model("generate")
    log.info("stitch qualitative: %d delta job(s)", len(delta_jobs))

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            raw = llm.call_llm(system=system_prompt, user=user, model=model, max_tokens=12000)
            parsed = json.loads(_extract_first_json_object(raw))
            _validate_stitch_result(parsed, delta_jobs)
            return parsed["themes"]
        except (json.JSONDecodeError, GradingError) as e:
            last_error = e
            log.warning("stitch attempt %d failed: %s", attempt, e)
            if attempt == 1:
                user = user + (
                    f'\n\nPrevious attempt failed validation: "{e}". Regenerate per the schema.'
                )
            else:
                break
        except llm.LLMError as e:
            raise GradingError(f"stitch LLM call failed: {e}") from e
    raise GradingError(f"stitch failed after retry: {last_error}")


# --------------------------------------------------------------------------
# Final-schema guard + orchestrator
# --------------------------------------------------------------------------


def _validate_final(out: dict[str, Any], answerer_band: str) -> None:
    """Light schema guard on the assembled grading dict. `_stitch` builds this
    deterministically from already-validated per-question results, so this
    mostly catches stitch-side bugs — cheap insurance before the output reaches
    `apply_grading`.
    """
    for key in (
        "session_summary",
        "questions_grading",
        "run_aggregation",
        "field_delta",
        "topic_delta",
        "meta_updates",
    ):
        if key not in out:
            raise GradingError(f"assembled grading missing key {key!r}")
    for tree_key in ("field_delta", "topic_delta"):
        tree = out[tree_key]
        if not isinstance(tree, dict) or set(tree) != {"runs", "time"}:
            raise GradingError(f"{tree_key} must be an object with exactly 'runs' and 'time' keys")
        if not all(isinstance(tree[branch], dict) for branch in ("runs", "time")):
            raise GradingError(f"{tree_key} 'runs'/'time' branches must be objects")
    qg = out["questions_grading"]
    if not isinstance(qg, list) or len(qg) != 5:
        raise GradingError(
            f"questions_grading must be a list of 5, got "
            f"{len(qg) if isinstance(qg, list) else type(qg).__name__}"
        )
    agg = out["run_aggregation"]
    for key in ("aggregated_score", "aggregated_score_pre", "aggregated_score_post"):
        v = agg.get(key)
        if v is not None and not (isinstance(v, (int, float)) and 1.0 <= float(v) <= 5.0):
            raise GradingError(f"run_aggregation.{key} must be a number in [1.0, 5.0] or null, got {v!r}")
    delta = agg.get("assisted_delta")
    if not isinstance(delta, str) or not _DELTA_RE.match(delta):
        raise GradingError(f"run_aggregation.assisted_delta malformed: {delta!r}")
    for key in ("fail_count_pre", "fail_count_post"):
        v = agg.get(key)
        if not isinstance(v, int) or not (0 <= v <= 5):
            raise GradingError(f"run_aggregation.{key} must be an integer in [0, 5], got {v!r}")
    mu = out["meta_updates"]
    if not isinstance(mu, dict):
        raise GradingError("meta_updates must be an object")
    for sub in ("criteria_set", "topics_added"):
        block = mu.get(sub, {})
        if not isinstance(block, dict):
            raise GradingError(f"meta_updates.{sub} must be an object")
        bad = [s for s in block if s not in parse.CANONICAL_FIELDS]
        if bad:
            raise GradingError(f"meta_updates.{sub} has non-canonical field slug(s): {bad}")


def grade(
    *,
    industry: str = DEFAULT_INDUSTRY,
    answerer_band: str,
    current_run: dict[str, Any],
    entry_state: dict[str, Any] | None = None,
    comparison_points: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 4 grading, sandboxed per question (Fix E).

    Orchestrates:
      1. `_grade_question` x5 — five sandboxed LLM calls, one per question, each
         built from scratch with only that question's data; no carryover.
      2. `_stitch` — deterministic code: run aggregation, numeric session_summary,
         strengths/weaknesses, delta-tree arithmetic, meta_updates.
      3. `_stitch_qualitative` — one small LLM call for cross-question delta
         themes; skipped when there are no deltas to theme, and degraded to
         empty themes (rather than failing the run) if the call itself errors.

    The assembled output matches the persisted grading schema exactly;
    `parse.apply_grading` is unchanged. The run-complete and `/transcript`
    embeds (`content/quiz.py`) are the single canonical display path — there is
    no separate markdown report.
    """
    question_system = build_question_grader_system(industry)
    meta = parse.read_meta()
    meta_fields = meta.get("fields", {}) or {}

    qrecs = _question_records(current_run)
    if len(qrecs) != 5:
        raise GradingError(f"current_run must contain 5 questions, got {len(qrecs)}")

    question_results: list[dict[str, Any]] = []
    for i, qrec in enumerate(qrecs, start=1):
        field = qrec.get("field")
        meta_field = meta_fields.get(field, {}) if isinstance(field, str) else {}
        question_results.append(
            _grade_question(
                system_prompt=question_system,
                answerer_band=answerer_band,
                question_id=i,
                qrec=qrec,
                meta_field=meta_field,
            )
        )

    stitched, delta_jobs = _stitch(
        question_results,
        answerer_band=answerer_band,
        current_run=current_run,
        entry_state=entry_state,
        comparison_points=comparison_points,
    )

    if delta_jobs:
        # A qualitative-stitch failure must not discard a fully graded run: the
        # five per-question scores and all run-level arithmetic are already in
        # hand. Degrade to empty delta themes (apply_themes still strips the
        # transient `_id`s and stubs the qualitative fields) and log it.
        try:
            themes = _stitch_qualitative(
                industry=industry,
                question_results=question_results,
                delta_jobs=delta_jobs,
            )
        except GradingError as e:
            log.warning("qualitative stitch failed; delta themes left empty: %s", e)
            themes = []
        movement.apply_themes(stitched["field_delta"], stitched["topic_delta"], themes)

    _validate_final(stitched, answerer_band)
    return stitched
