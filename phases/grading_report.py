from __future__ import annotations

from typing import Any

from phases import band_data


_BANDS = ("B1", "B2", "B3", "B4", "B5")


def _question_records(current_run: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap `current_run.questions` (list of single-keyed wrappers `{"question_<i>": rec}`)
    into an ordered list of question records."""
    out: list[dict[str, Any]] = []
    for wrap in current_run.get("questions", []) or []:
        if not isinstance(wrap, dict):
            continue
        for _, rec in wrap.items():
            if isinstance(rec, dict):
                out.append(rec)
                break
    return out


def _band_score_map(bands: list[Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for b in bands or []:
        if isinstance(b, dict) and isinstance(b.get("band"), str):
            out[b["band"]] = b
    return out


def _delta_str(pre: Any, post: Any) -> str:
    try:
        d = float(post) - float(pre)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    return f"{sign}{abs(d):g}" if d != 0 else "0"


def _date_from_run(current_run: dict[str, Any]) -> str:
    for key in ("start", "date", "started_at"):
        v = current_run.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return "—"


def _confidence_from_n(n: int) -> str:
    if n >= 3:
        return "High"
    if n == 2:
        return "Medium"
    if n == 1:
        return "Low"
    return "n/a"


def _mode_band(values: list[str]) -> str | None:
    """Pick the highest-frequency band from a list. Ties broken by highest band
    (B5 > B1) since a tied 'ceiling' should reflect the upper bound."""
    if not values:
        return None
    counts: dict[str, int] = {}
    for v in values:
        if v in _BANDS:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    max_count = max(counts.values())
    tied = [b for b, c in counts.items() if c == max_count]
    return sorted(tied, key=lambda b: _BANDS.index(b))[-1]


def _format_band_label(band: str) -> str:
    if band not in _BANDS:
        return band
    row = band_data.get_band(band)
    return f"{band} {row.label}"


def _format_topics(topics: list[Any] | None) -> str:
    items = [t for t in (topics or []) if isinstance(t, str) and t]
    return ", ".join(f"`{t}`" for t in items) if items else "—"


def _format_lit_entry(entry: dict[str, Any]) -> str:
    title = entry.get("title", "")
    author = entry.get("author", "")
    url = entry.get("url", "")
    section = entry.get("section", "")
    rt = entry.get("reading_time_estimate", "")
    why = entry.get("why", "")
    head = f"[{title}]({url})" if url else title
    parts = [head]
    if author:
        parts.append(f"_{author}_")
    if section:
        parts.append(section)
    if rt:
        parts.append(f"({rt})")
    line = " — ".join(p for p in parts if p)
    if why:
        line = f"{line} — {why}"
    return line


def _render_per_question_section(
    *,
    idx: int,
    qrec_input: dict[str, Any],
    qg: dict[str, Any],
    answerer_band: str,
) -> str:
    field = qg.get("field") or qrec_input.get("field") or "—"
    topics = qg.get("topics") or qrec_input.get("topics") or []
    scenario = (qrec_input.get("question") or "").strip() or "_(scenario unavailable)_"
    response_redacted = (qg.get("response_redacted") or "").strip()
    refine_text = (qrec_input.get("refine") or "").strip()
    refine_redacted = (qg.get("refine_response_redacted") or "").strip()
    refine_form = qrec_input.get("refine_form")
    assessment = (qg.get("assessment") or "").strip() or "_(no assessment)_"

    lines: list[str] = [
        f"## Question {idx}",
        "",
        f"**Topics tested:** {_format_topics(topics)}",
        f"**Field:** `{field}`",
        "",
        "### Scenario",
        scenario,
        "",
        "### Response",
        response_redacted or "_(no response)_",
        "",
        "### Refinement",
    ]
    if refine_form == "skip" or not refine_text:
        lines.append("_(skipped — no probe)_")
    else:
        lines.append(f'**Question:** "{refine_text}"')
        lines.append(f"**Response:** {refine_redacted or '_(no reply)_'}")
    lines += [
        "",
        "### Assessment",
        assessment,
        "",
        "### Scores",
        "",
        f"**Primary evaluation band:** {answerer_band}",
        "",
        "| Band | Pre-Refinement | Post-Refinement | Delta | Justification |",
        "|---|---|---|---|---|",
    ]
    pre_map = _band_score_map(qg.get("bands_pre"))
    post_map = _band_score_map(qg.get("bands_post"))
    for b in _BANDS:
        pre = pre_map.get(b, {})
        post = post_map.get(b, {})
        pre_score = pre.get("score", "—")
        post_score = post.get("score", "—")
        reason = (post.get("reason") or pre.get("reason") or "").replace("|", "\\|").strip()
        if not reason:
            reason = "—"
        lines.append(
            f"| {_format_band_label(b)} | {pre_score} | {post_score} "
            f"| {_delta_str(pre_score, post_score)} | {reason} |"
        )

    lines += ["", "### Literature"]
    literature = qg.get("literature") or []
    if not literature:
        lines.append("_(none — question unattempted)_")
    else:
        for entry in literature:
            if not isinstance(entry, dict):
                continue
            badge = "[growth]" if entry.get("type") == "growth" else "[remediation]"
            lines.append(f"- `{badge}` {_format_lit_entry(entry)}")
    return "\n".join(lines)


def _render_aggregate_scores_table(
    questions_grading: list[dict[str, Any]],
) -> str:
    lines = [
        "| Question | Topics | Field | B1 | B2 | B3 | B4 | B5 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, qg in enumerate(questions_grading, start=1):
        post_map = _band_score_map(qg.get("bands_post"))
        scores = [str(post_map.get(b, {}).get("score", "—")) for b in _BANDS]
        topics = _format_topics(qg.get("topics"))
        field = qg.get("field") or "—"
        lines.append(f"| Q{i} | {topics} | `{field}` | " + " | ".join(scores) + " |")
    return "\n".join(lines)


def _render_within_session_movement(field_delta: dict[str, Any]) -> str:
    runs = (field_delta or {}).get("runs") or {}
    rows: list[str] = []
    for field, by_point in runs.items():
        if not isinstance(by_point, dict):
            continue
        rec = by_point.get("-1")
        if not isinstance(rec, dict):
            continue
        before = rec.get("career_level_before") or "—"
        after = rec.get("career_level_after") or "—"
        direction = rec.get("direction") or "="
        delta = rec.get("delta") or "0.0"
        reason = (rec.get("level_change_reason") or "").strip()
        line = f"- **`{field}`**: {before} → {after} ({direction}{delta})"
        if reason:
            line = f"{line}. {reason}"
        rows.append(line)
    if not rows:
        return "_(no within-session movement)_"
    return "\n".join(rows)


def _render_field_estimates(
    *,
    questions_grading: list[dict[str, Any]],
) -> str:
    """Per-field rollup. Band ceiling = mode of per-question band_ceiling_post for the field;
    YOE comes from band_mappings.yaml; confidence is heuristic from question count."""
    by_field: dict[str, list[dict[str, Any]]] = {}
    for qg in questions_grading:
        field = qg.get("field")
        if isinstance(field, str) and field:
            by_field.setdefault(field, []).append(qg)

    lines = [
        "| Field | Questions | Band Ceiling | YOE Equivalent | Confidence |",
        "|---|---|---|---|---|",
    ]
    for field in sorted(by_field):
        items = by_field[field]
        ceilings = [c for c in (qg.get("band_ceiling_post") for qg in items) if isinstance(c, str) and c in _BANDS]
        ceiling = _mode_band(ceilings)
        if ceiling:
            yoe = band_data.get_band(ceiling).yoe_range
            ceiling_label = _format_band_label(ceiling)
        else:
            yoe = "n/a"
            ceiling_label = "n/a"
        lines.append(
            f"| `{field}` | {len(items)} | {ceiling_label} | {yoe} | {_confidence_from_n(len(items))} |"
        )
    return "\n".join(lines)


def _render_aggregate_estimate(
    *,
    session_summary: dict[str, Any],
    run_aggregation: dict[str, Any],
) -> str:
    rows = [
        ("Aggregate score (unassisted, pre-refinement)", run_aggregation.get("aggregated_score_pre")),
        ("Aggregate score (post-refinement)", run_aggregation.get("aggregated_score_post")),
        ("Assisted recovery (Δ)", run_aggregation.get("assisted_delta")),
        ("Critical failures (unassisted)", f"{run_aggregation.get('fail_count_pre', 0)} of 5"),
        ("Critical failures (post-refinement)", f"{run_aggregation.get('fail_count_post', 0)} of 5"),
        ("Career level (from unassisted)", run_aggregation.get("career_level")),
        ("Median band ceiling", session_summary.get("median_band_ceiling")),
        ("Range", f"{session_summary.get('range_low', '—')}–{session_summary.get('range_high', '—')}"),
        ("Aggregate Dreyfus stage", session_summary.get("aggregate_dreyfus_stage")),
        ("Aggregate SWECOM level", session_summary.get("aggregate_swecom_level")),
        ("Aggregate SFIA level", session_summary.get("aggregate_sfia_level")),
        ("Aggregate YOE", session_summary.get("aggregate_yoe_equivalent")),
        ("Confidence", session_summary.get("confidence")),
    ]
    lines = ["| Indicator | Value |", "|---|---|"]
    for label, value in rows:
        v = value if value not in (None, "") else "—"
        lines.append(f"| {label} | {v} |")
    return "\n".join(lines)


def _render_strengths_weaknesses(run_aggregation: dict[str, Any]) -> str:
    s = run_aggregation.get("strengths") or {}
    w = run_aggregation.get("weaknesses") or {}

    def _fmt(items: Any) -> str:
        items = items or []
        if not items:
            return "—"
        return ", ".join(f"`{x}`" for x in items if isinstance(x, str) and x)

    return (
        f"**Strengths:** fields = {_fmt(s.get('fields'))}; topics = {_fmt(s.get('topics'))}\n"
        f"**Weaknesses:** fields = {_fmt(w.get('fields'))}; topics = {_fmt(w.get('topics'))}"
    )


def _dedup_literature(
    questions_grading: list[dict[str, Any]],
    lit_type: str,
) -> list[dict[str, Any]]:
    """Dedupe literature entries by (url, title) pair across all questions, preserving
    first-seen order. Filters to the requested `lit_type`."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for qg in questions_grading:
        for entry in qg.get("literature") or []:
            if not isinstance(entry, dict) or entry.get("type") != lit_type:
                continue
            key = (str(entry.get("url", "")), str(entry.get("title", "")))
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
    return out


def _render_reading_section(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "_(none)_"
    return "\n".join(f"- {_format_lit_entry(e)}" for e in entries)


def render_report(
    *,
    grading: dict[str, Any],
    current_run: dict[str, Any],
    answerer_band: str,
) -> str:
    """Render the public-facing markdown report deterministically from the grader's
    structured JSON output plus the run input. The grader no longer authors markdown;
    its only contributions to the report are the per-question redacted text fields
    and the per-band `reason` strings, which this renderer quotes verbatim.
    """
    questions_grading = grading.get("questions_grading") or []
    session_summary = grading.get("session_summary") or {}
    run_aggregation = grading.get("run_aggregation") or {}
    field_delta = grading.get("field_delta") or {}

    qrecs = _question_records(current_run)
    fields_invoked = current_run.get("fields_invoked") or []
    field_list = ", ".join(f"`{f}`" for f in fields_invoked) if fields_invoked else "—"

    parts: list[str] = [
        "# Spot Check Report",
        "",
        f"**Date:** {_date_from_run(current_run)}",
        f"**Field(s):** {field_list}",
        f"**Questions:** {len(questions_grading)}",
        "**Grading Methodology:** Dreyfus (1980/2021), IEEE SWECOM (2014), SFIA v9 (2024)",
        "",
        "---",
        "",
    ]

    for i, qg in enumerate(questions_grading, start=1):
        qrec_input = qrecs[i - 1] if i - 1 < len(qrecs) else {}
        parts.append(
            _render_per_question_section(
                idx=i,
                qrec_input=qrec_input,
                qg=qg,
                answerer_band=answerer_band,
            )
        )
        parts.append("")
        parts.append("---")
        parts.append("")

    parts += [
        "## Aggregate",
        "",
        "### Scores",
        "",
        _render_aggregate_scores_table(questions_grading),
        "",
        "### Within-Session Movement (`-1`)",
        "",
        _render_within_session_movement(field_delta),
        "",
        "### Field Estimates",
        "",
        _render_field_estimates(questions_grading=questions_grading),
        "",
        "### Aggregate Estimate",
        "",
        _render_aggregate_estimate(
            session_summary=session_summary,
            run_aggregation=run_aggregation,
        ),
        "",
        "### Strengths and Weaknesses",
        "",
        _render_strengths_weaknesses(run_aggregation),
        "",
        "### Remediation Reading",
        "",
        _render_reading_section(_dedup_literature(questions_grading, "remediation")),
        "",
        "### Growth Reading",
        "",
        _render_reading_section(_dedup_literature(questions_grading, "growth")),
        "",
    ]
    return "\n".join(parts)
