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


def question_embed(
    idx: int,
    q: dict[str, Any],
    *,
    timeout_seconds: int = 1800,
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
    timeout_seconds: int = 1800,
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


def _band_matrix_block(grading: dict[str, Any]) -> str:
    """ASCII matrix of post-refinement scores, one row per question, columns B1..B5."""
    COL_Q, COL_F, COL_B = 4, 26, 4
    width = COL_Q + COL_F + COL_B * 5
    header = (
        f"{'Q':<{COL_Q}}{'Field':<{COL_F}}"
        f"{'B1':<{COL_B}}{'B2':<{COL_B}}{'B3':<{COL_B}}{'B4':<{COL_B}}{'B5':<{COL_B}}"
    )
    rows: list[str] = [header, "─" * width]
    for qg in grading.get("questions_grading", []) or []:
        qid = str(qg.get("question_id", "?"))
        field_slug = (qg.get("field") or "?")[:COL_F - 1]
        bands = qg.get("bands_post") or []
        cells: list[str] = []
        for band_record in bands[:5]:
            s = band_record.get("score")
            cells.append(str(int(s)) if isinstance(s, (int, float)) else "—")
        while len(cells) < 5:
            cells.append("—")
        rows.append(
            f"{qid:<{COL_Q}}{field_slug:<{COL_F}}"
            f"{cells[0]:<{COL_B}}{cells[1]:<{COL_B}}{cells[2]:<{COL_B}}{cells[3]:<{COL_B}}{cells[4]:<{COL_B}}"
        )
    return "```\n" + "\n".join(rows) + "\n```"


def _per_field_diagnostic_lines(grading: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for qg in grading.get("questions_grading", []) or []:
        qid = qg.get("question_id", "?")
        field_slug = qg.get("field", "?")
        ceiling = qg.get("band_ceiling_post") or "—"
        assessment = (qg.get("assessment") or "").strip()
        first_sentence = assessment.split(". ")[0].rstrip(".") if assessment else "—"
        out.append(f"**Q{qid}** `{field_slug}` · ceiling **{ceiling}** — {first_sentence}.")
    return out


def _literature_block_lines(grading: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for qg in grading.get("questions_grading", []) or []:
        qid = qg.get("question_id", "?")
        for entry in qg.get("literature", []) or []:
            badge = "[growth]" if entry.get("type") == "growth" else "[remediation]"
            out.append(f"**Q{qid}** · `{badge}` · {_format_lit_entry(entry)}")
    return out


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
        score = agg.get("aggregated_score")
        career = agg.get("career_level") or "—"
        score_str = f"**{score}**" if isinstance(score, (int, float)) else "**—**"
        summary = grading.get("session_summary") or {}
        ceiling = summary.get("median_band_ceiling") or "—"
        rng_low = summary.get("range_low") or "—"
        rng_high = summary.get("range_high") or "—"
        yoe = summary.get("aggregate_yoe_equivalent") or "—"
        confidence = summary.get("confidence") or "—"

        summary_fields.append((
            "Aggregate",
            (
                f"score {score_str} · career level **{career}** · YOE **{yoe}**\n"
                f"median ceiling **{ceiling}** · range **{rng_low}–{rng_high}** · confidence **{confidence}**"
            ),
            False,
        ))

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
        # ---- 2. Matrix embed --------------------------------------------
        matrix_fields: list[tuple[str, str, bool]] = []
        matrix_fields.append((
            "Band matrix · post-refinement",
            _band_matrix_block(grading),
            False,
        ))
        diag_lines = _per_field_diagnostic_lines(grading)
        if diag_lines:
            matrix_fields.extend(_chunk_field("Per-question diagnostic", "\n".join(diag_lines)))

        matrix_embed, matrix_files = build(
            title="Run complete · matrix",
            description="Each question scored independently across all five bands. "
                        "The diagnostic line names the gap, not the answer.",
            fields=matrix_fields,
            icon=ICON_NAMES["stats"],
            color=BLUE_PRIMARY,
            footer=None,
        )
        all_embeds.append(matrix_embed)
        all_files.extend(matrix_files)

        # ---- 3. Literature + exercises embed ----------------------------
        lit_fields: list[tuple[str, str, bool]] = []
        lit_lines = _literature_block_lines(grading)
        if lit_lines:
            lit_fields.extend(_chunk_field("Literature · 2 per question", "\n".join(lit_lines)))
        if exercises:
            ex_lines = "\n".join(
                f"• **{e.get('name')}** — `{e.get('source')}` — {e.get('concept_mapping')}"
                for e in exercises
            )
            lit_fields.append(("Practical exercises", ex_lines, False))

        if lit_fields:
            lit_embed, lit_files = build(
                title="Run complete · literature",
                description="Per-question literature scoped to your band. "
                            "Reading list deduped at `/sessionend`.",
                fields=lit_fields,
                icon=ICON_NAMES["literature"],
                color=BLUE_PRIMARY,
                footer=None,
            )
            all_embeds.append(lit_embed)
            all_files.extend(lit_files)

    # Footer only on the last embed for visual termination.
    if all_embeds:
        all_embeds[-1].set_footer(text=DEFAULT_FOOTER)

    return all_embeds, all_files
