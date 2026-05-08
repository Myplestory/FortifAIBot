from __future__ import annotations

from typing import Any

import discord

from content.shared import (
    BLUE_PRIMARY,
    COUNTDOWN_FIELD_NAME,
    DEFAULT_FOOTER,
    ICON_NAMES,
    OK_GREEN,
    WARN_AMBER,
    _chunk_field,
    _format_lit_entry,
    build,
    format_remaining,
)
from phases import band_data


def question_embed(
    idx: int,
    q: dict[str, Any],
    *,
    timeout_seconds: int = 600,
) -> tuple[discord.Embed, list[discord.File]]:
    """Question prompt. Topics + SFIA skills are deliberately hidden — they would
    leak hints. Field is shown for context. The countdown field is updated by
    the ticker in main.py until the user responds.
    """
    field = q.get("field", "?")
    return build(
        title=f"Question {idx} of 5",
        description=q.get("question", ""),
        fields=[
            ("Field", f"`{field}`", True),
            ("Progress", f"Q{idx} of 5", True),
            (COUNTDOWN_FIELD_NAME, f"`{format_remaining(timeout_seconds)}` until timeout", True),
        ],
        icon=ICON_NAMES["question"],
        color=BLUE_PRIMARY,
    )


def refinement_embed(
    idx: int,
    text: str,
    *,
    timeout_seconds: int = 300,
) -> tuple[discord.Embed, list[discord.File]]:
    return build(
        title=f"Refinement · Q{idx}",
        description=text,
        fields=[
            (COUNTDOWN_FIELD_NAME, f"`{format_remaining(timeout_seconds)}` until timeout", True),
        ],
        icon=ICON_NAMES["refinement"],
        color=BLUE_PRIMARY,
    )


def skip_embed(idx: int) -> tuple[discord.Embed, list[discord.File]]:
    return build(
        title=f"Refinement · Q{idx}",
        description="No response captured — moving to the next question.",
        icon=ICON_NAMES["skip"],
        color=WARN_AMBER,
    )


def _format_band_pre_post(bands_pre: list[dict[str, Any]], bands_post: list[dict[str, Any]]) -> str:
    pre_by_band = {b.get("band"): b.get("score") for b in (bands_pre or [])}
    post_by_band = {b.get("band"): b.get("score") for b in (bands_post or [])}
    rows = ["band   pre  post  Δ"]
    for b in ("B1", "B2", "B3", "B4", "B5"):
        pre = pre_by_band.get(b)
        post = post_by_band.get(b)
        pre_s = str(int(pre)) if isinstance(pre, (int, float)) else "—"
        post_s = str(int(post)) if isinstance(post, (int, float)) else "—"
        if isinstance(pre, (int, float)) and isinstance(post, (int, float)):
            d = int(post) - int(pre)
            delta = f"+{d}" if d > 0 else (str(d) if d < 0 else "·")
        else:
            delta = "—"
        rows.append(f"{b:<5}  {pre_s:>3}   {post_s:>3}  {delta:>3}")
    return "```\n" + "\n".join(rows) + "\n```"


def question_breakdown_embed(
    qrec: dict[str, Any],
    *,
    idx: int,
) -> tuple[discord.Embed, list[discord.File]]:
    """Per-question breakdown: scenario, response, refinement, assessment,
    band scores (pre→post), and literature. Used by both the run-complete
    output and `/transcript`.
    """
    field_slug = qrec.get("field") or "?"
    topics = qrec.get("topics") or []
    ceiling = qrec.get("band_ceiling_post")
    transitional = qrec.get("transitional_post")

    title_parts = [f"Q{idx}", f"`{field_slug}`"]
    if ceiling:
        title_parts.append(f"ceiling **{ceiling}**")
    title = " · ".join(title_parts)

    desc_lines: list[str] = []
    if topics:
        desc_lines.append("Topics: " + ", ".join(f"`{t}`" for t in topics))
    if transitional:
        desc_lines.append(f"_Transitional toward **{transitional}**_")
    description = "\n".join(desc_lines)

    fields_listed: list[tuple[str, str, bool]] = []

    scenario = (qrec.get("question") or "").strip()
    if scenario:
        fields_listed.extend(_chunk_field("Scenario", scenario))

    response = (qrec.get("response") or "").strip() or "_(no response)_"
    fields_listed.extend(_chunk_field("Response", response))

    refine_form = qrec.get("refine_form")
    refine_text = (qrec.get("refine") or "").strip()
    if refine_form == "skip":
        fields_listed.append(("Refinement", "_(skipped — no probe)_", False))
    elif refine_text:
        fields_listed.extend(_chunk_field("Refinement", refine_text))
        refine_response = (qrec.get("refine_response") or "").strip() or "_(no reply)_"
        fields_listed.extend(_chunk_field("Refinement response", refine_response))

    assessment = (qrec.get("assessment") or "").strip()
    if assessment:
        fields_listed.extend(_chunk_field("Assessment", assessment))

    bands_pre = qrec.get("bands_pre") or []
    bands_post = qrec.get("bands") or []
    if bands_pre or bands_post:
        fields_listed.append(("Scores", _format_band_pre_post(bands_pre, bands_post), False))

    literature = qrec.get("literature") or []
    if literature:
        lit_lines: list[str] = []
        for entry in literature:
            badge = "[growth]" if entry.get("type") == "growth" else "[remediation]"
            lit_lines.append(f"`{badge}` {_format_lit_entry(entry)}")
        fields_listed.extend(_chunk_field("Literature", "\n".join(lit_lines)))

    return build(
        title=title,
        description=description,
        fields=fields_listed,
        icon=ICON_NAMES["grading"],
        color=BLUE_PRIMARY,
        footer=None,
    )


def _per_question_embeds_from_questions(
    questions: list[dict[str, Any]],
) -> tuple[list[discord.Embed], list[discord.File]]:
    """Iterate the persisted `questions` array (each entry shaped
    `{"question_N": qrec}`) and emit one embed per question."""
    out_embeds: list[discord.Embed] = []
    out_files: list[discord.File] = []
    for idx, wrap in enumerate(questions or [], start=1):
        if not isinstance(wrap, dict):
            continue
        qrec = wrap.get(f"question_{idx}")
        if not isinstance(qrec, dict):
            # Be tolerant: pick the first dict value if the key shape differs.
            qrec = next((v for v in wrap.values() if isinstance(v, dict)), None)
        if not qrec:
            continue
        e, f = question_breakdown_embed(qrec, idx=idx)
        out_embeds.append(e)
        out_files.extend(f)
    return out_embeds, out_files


def run_complete_embeds(
    run_id: str,
    session_id: str,
    durations: str,
    exercises: list[dict[str, Any]],
    *,
    industry: str = "—",
    band: str = "—",
    session_name: str = "—",
    domain: str | None = None,
    stack: list[str] | None = None,
    fields_covered: list[str] | None = None,
    topics_covered: list[str] | None = None,
    grading: dict[str, Any] | None = None,
    graded_run: dict[str, Any] | None = None,
) -> tuple[list[discord.Embed], list[discord.File]]:
    """Build the run-complete output as up to three embeds, each under
    Discord's 6000-char limit:
      1. Summary  — settings, session header, aggregate, strengths, gaps.
      2. Matrix   — 5-band scoring matrix + per-question diagnostic.
      3. Literature — 2-per-question literature + practical exercises.

    When grading is unavailable, only the summary embed is returned (with
    practical exercises folded in). All embeds are sent in a single message.
    """
    success = bool(grading and graded_run)
    all_embeds: list[discord.Embed] = []
    all_files: list[discord.File] = []

    # ---- 1. Summary embed -------------------------------------------------
    summary_fields: list[tuple[str, str, bool]] = []
    summary_fields.append(("Industry", f"`{industry}`", True))
    summary_fields.append(("Band", f"`{band}`", True))
    summary_fields.append(("Duration", durations, True))
    summary_fields.append((
        "Session · Run",
        f"`{session_name}` · id `{session_id}` · run **#{run_id}**",
        False,
    ))

    domain_str = f"`{domain}`" if domain else "_unscoped_"
    stack_str = ", ".join(f"`{s}`" for s in (stack or [])) if stack else "_unscoped_"
    summary_fields.append(("Domain", domain_str, True))
    summary_fields.append(("Stack", stack_str, True))
    summary_fields.append(("Run #", f"**{run_id}**", True))

    fields_str = ", ".join(f"`{f}`" for f in (fields_covered or [])) or "_(none recorded)_"
    summary_fields.append(("Fields covered", fields_str, False))

    topics_str = ", ".join(f"`{t}`" for t in (topics_covered or [])) or "_(none recorded)_"
    summary_fields.extend(_chunk_field("Topics covered", topics_str))

    if success:
        agg = grading.get("run_aggregation", {}) or {}
        # Finding B: headline switches to unassisted (pre-refinement) score.
        # Legacy runs only carry aggregated_score (post); fall back to it so
        # transcripts of older runs still render.
        score_pre = agg.get("aggregated_score_pre")
        score_post = agg.get("aggregated_score_post", agg.get("aggregated_score"))
        delta = agg.get("assisted_delta")
        fail_pre = agg.get("fail_count_pre", 0) or 0
        career = agg.get("career_level") or "—"
        summary = grading.get("session_summary") or {}
        ceiling = summary.get("median_band_ceiling") or "—"
        rng_low = summary.get("range_low") or "—"
        rng_high = summary.get("range_high") or "—"
        yoe = summary.get("aggregate_yoe_equivalent") or "—"
        confidence = summary.get("confidence") or "—"

        pre_str = f"**{score_pre}**" if isinstance(score_pre, (int, float)) else "**—**"
        post_str = f"**{score_post}**" if isinstance(score_post, (int, float)) else "**—**"
        delta_str = delta if isinstance(delta, str) else "—"

        # Finding E: when the unassisted run has too many critical failures, the
        # headline replaces the career-level keyword with a failure count so a
        # polarized run cannot mask gaps behind a competent/proficient label.
        cf_cfg = band_data.critical_failure_config()
        if isinstance(fail_pre, int) and fail_pre >= cf_cfg.suppress_keyword_at:
            aggregate_value = (
                f"score (unassisted) {pre_str} · "
                f"**blocked by {fail_pre} critical failure(s)**\n"
                f"assisted recovery: {delta_str} (post {post_str}) · YOE **{yoe}**\n"
                f"median ceiling **{ceiling}** · range **{rng_low}–{rng_high}** · "
                f"confidence **{confidence}**"
            )
        else:
            aggregate_value = (
                f"score (unassisted) {pre_str} · career level **{career}** · YOE **{yoe}**\n"
                f"assisted recovery: {delta_str} (post {post_str})\n"
                f"median ceiling **{ceiling}** · range **{rng_low}–{rng_high}** · "
                f"confidence **{confidence}**"
            )

        summary_fields.append(("Aggregate", aggregate_value, False))

        strengths = agg.get("strengths") or {}
        weaknesses = agg.get("weaknesses") or {}

        def _fmt(slugs: list[str] | None) -> str:
            return ", ".join(f"`{s}`" for s in (slugs or [])) or "_(none)_"

        summary_fields.append((
            "Strengths",
            f"fields: {_fmt(strengths.get('fields'))}\ntopics: {_fmt(strengths.get('topics'))}",
            False,
        ))
        summary_fields.append((
            "Gaps",
            f"fields: {_fmt(weaknesses.get('fields'))}\ntopics: {_fmt(weaknesses.get('topics'))}",
            False,
        ))

    summary_description = (
        "Grading complete. Questions scored against **all five bands** — keep scrolling for the matrix "
        "and per-question literature."
        if success
        else "Run captured — settings, topics, and exercises stored. Grading failed or was skipped; "
             "re-run with `/sweep mode:regrade` to retry the literature surface."
    )
    summary_color = OK_GREEN if success else WARN_AMBER

    # When grading didn't run, fold practical exercises into the summary embed
    # to keep the single-embed shape useful.
    if not success and exercises:
        ex_lines = "\n".join(
            f"• **{e.get('name')}** — `{e.get('source')}` — {e.get('concept_mapping')}"
            for e in exercises
        )
        summary_fields.append(("Practical exercises", ex_lines, False))

    summary_embed, summary_files = build(
        title="Run complete · summary" if success else "Run complete · grading deferred",
        description=summary_description,
        fields=summary_fields,
        icon=ICON_NAMES["results"] if success else ICON_NAMES["results_deferred"],
        color=summary_color,
        footer=None,
    )
    all_embeds.append(summary_embed)
    all_files.extend(summary_files)

    if success:
        # ---- 2..N. Per-question breakdown embeds ------------------------
        q_embeds, q_files = _per_question_embeds_from_questions(
            (graded_run or {}).get("questions") or []
        )
        all_embeds.extend(q_embeds)
        all_files.extend(q_files)

        # ---- N+1. Practical exercises (only when grading succeeded; the
        # no-grading branch folds them into the summary above). --------------
        if exercises:
            ex_lines = "\n".join(
                f"• **{e.get('name')}** — `{e.get('source')}` — {e.get('concept_mapping')}"
                for e in exercises
            )
            ex_embed, ex_files = build(
                title="Practical exercises",
                description="Hands-on follow-ups linked to the question topics.",
                fields=[("Exercises", ex_lines, False)],
                icon=ICON_NAMES["exercises"],
                color=BLUE_PRIMARY,
                footer=None,
            )
            all_embeds.append(ex_embed)
            all_files.extend(ex_files)

    # Footer only on the last embed for visual termination.
    if all_embeds:
        all_embeds[-1].set_footer(text=DEFAULT_FOOTER)

    return all_embeds, all_files


def transcript_embeds(
    run: dict[str, Any],
    *,
    session_name: str,
    session_id: str,
) -> tuple[list[discord.Embed], list[discord.File]]:
    """Render a persisted run record (post-grading) as the same summary +
    per-question embeds the quiz emits at run-complete. Used by `/transcript`.

    The run record is treated as the authoritative source — `apply_grading`
    has already merged `run_aggregation`, `session_summary`, and per-question
    grading data onto it. We synthesize the `grading` shape `run_complete_embeds`
    expects so a single render path serves both flows.
    """
    # `aggregated_score_pre` is the post-Finding-B authoritative signal; legacy
    # runs only have `aggregated_score`, so accept either as a "graded" marker.
    has_grading = (
        run.get("aggregated_score_pre") is not None
        or run.get("aggregated_score") is not None
    )
    grading: dict[str, Any] | None = None
    if has_grading:
        grading = {
            "run_aggregation": {
                "aggregated_score": run.get("aggregated_score"),
                "aggregated_score_pre": run.get("aggregated_score_pre"),
                "aggregated_score_post": run.get("aggregated_score_post"),
                "assisted_delta": run.get("assisted_delta"),
                "fail_count_pre": run.get("fail_count_pre", 0),
                "fail_count_post": run.get("fail_count_post", 0),
                "career_level": run.get("career_level", ""),
                "strengths": run.get("strengths") or {"fields": [], "topics": []},
                "weaknesses": run.get("weaknesses") or {"fields": [], "topics": []},
            },
            "session_summary": run.get("session_summary") or {},
            # questions_grading is no longer consumed by run_complete_embeds —
            # per-question embeds read directly from graded_run.questions.
            "questions_grading": [],
        }

    # Derive fields/topics covered from the questions array (authoritative)
    # rather than the legacy fields_invoked/topics_invoked, which can lag.
    fields_covered: list[str] = []
    topics_covered: list[str] = []
    seen_f: set[str] = set()
    seen_t: set[str] = set()
    for wrap in run.get("questions") or []:
        if not isinstance(wrap, dict):
            continue
        for _, qrec in wrap.items():
            if not isinstance(qrec, dict):
                continue
            f = qrec.get("field")
            if isinstance(f, str) and f and f not in seen_f:
                seen_f.add(f)
                fields_covered.append(f)
            for t in qrec.get("topics") or []:
                if isinstance(t, str) and t not in seen_t:
                    seen_t.add(t)
                    topics_covered.append(t)

    return run_complete_embeds(
        run_id=str(run.get("id", "?")),
        session_id=session_id,
        durations=run.get("duration") or "—",
        exercises=run.get("practical_exercises") or [],
        industry=run.get("industry") or "—",
        band=run.get("band") or "—",
        session_name=session_name,
        domain=run.get("domain") or None,
        stack=run.get("stack") or None,
        fields_covered=fields_covered,
        topics_covered=topics_covered,
        grading=grading,
        graded_run=run if has_grading else None,
    )
