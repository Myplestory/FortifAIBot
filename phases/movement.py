"""Within-session and cross-run movement: current-state scoring, delta-record
arithmetic, comparison-point extraction, and the intensity×time×breadth
coherence gradient.

The grading pipeline's deterministic stitch step (`phases.grading._stitch`)
uses these helpers to build `field_delta` / `topic_delta` without an LLM call —
only the qualitative themes (`overlap` / `diff` / `level_change_reason`) are
deferred to `_stitch_qualitative`. The `build_*` helpers are called by the
command sites (`/knowledgeharden`, `/sweep`) to extract `entry_state` /
`comparison_points` from already-persisted run data, with no new persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from phases import band_data


_BANDS = ("B1", "B2", "B3", "B4", "B5")

# Fix B — cross-run comparison points: vs. the run 1 / 5 / 10 / 30 graded runs
# back (the `runs` tree) and vs. the most recent run ≥1 / 5 / 10 / 30 days back
# (the `time` tree). Tunable.
_COMPARISON_POINTS = (1, 5, 10, 30)

# Fix D — within-session coherence gradient. The per-field confidence weight
#   w_f = clamp(breadth_share_f × intensity_norm × time_coherence, 0, 1)
# drives the within-session verdict LABEL, not the delta number (the raw delta
# stays true). All constants tunable.
_TARGET_INTENSITY = 3.0   # runs/day that normalises intensity to 1.0
_VERDICT_MEANINGFUL = 0.66
_VERDICT_TENTATIVE = 0.33


def _band_index(band: str | None) -> int | None:
    """0-based index of a band id, or None if not a recognised band."""
    if isinstance(band, str) and band in _BANDS:
        return _BANDS.index(band)
    return None


def format_delta_string(x: float) -> str:
    """Format a 1-decimal float as the signed string the schema requires:
    '+0.6' / '-0.4' / '0.0' (no '+' on zero, no '-0.0').
    """
    rounded = round(x, 1)
    if rounded == 0:
        return "0.0"
    if rounded > 0:
        return f"+{rounded:.1f}"
    return f"{rounded:.1f}"


def primary_band_score(bands: list[Any] | None, answerer_band: str) -> int | None:
    """Pull the integer score at the answerer's primary evaluation band out of a
    5-entry `bands_pre` / `bands_post` tuple. Returns None when the primary band
    is absent or its score is non-numeric.
    """
    for b in bands or []:
        if isinstance(b, dict) and b.get("band") == answerer_band:
            raw = b.get("score")
            if isinstance(raw, (int, float)):
                return int(raw)
            return None
    return None


def _mean1(values: list[float]) -> float | None:
    """Mean rounded to 1 decimal, or None for an empty list."""
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def current_field_scores(
    question_results: list[dict[str, Any]],
    answerer_band: str,
    *,
    tag: str = "bands_post",
) -> dict[str, float]:
    """Per-field score: mean of `tag` scores at the primary evaluation band
    across questions in that field, rounded to 1 decimal.

    `tag` is `bands_post` for fresh per-question grader results; `bands` for a
    persisted, already-graded run (`apply_grading` stores post scores there).
    """
    by_field: dict[str, list[float]] = {}
    for qr in question_results:
        field = qr.get("field")
        if not isinstance(field, str) or not field:
            continue
        score = primary_band_score(qr.get(tag), answerer_band)
        if score is not None:
            by_field.setdefault(field, []).append(float(score))
    return {f: m for f, scores in by_field.items() if (m := _mean1(scores)) is not None}


def current_topic_scores(
    question_results: list[dict[str, Any]],
    answerer_band: str,
    *,
    tag: str = "bands_post",
) -> dict[str, float]:
    """Per-topic score: mean of `tag` scores at the primary evaluation band
    across questions tagged with that topic, rounded to 1 decimal.
    """
    by_topic: dict[str, list[float]] = {}
    for qr in question_results:
        score = primary_band_score(qr.get(tag), answerer_band)
        if score is None:
            continue
        for topic in qr.get("topics") or []:
            if isinstance(topic, str) and topic:
                by_topic.setdefault(topic, []).append(float(score))
    return {t: m for t, scores in by_topic.items() if (m := _mean1(scores)) is not None}


def field_question_counts(question_results: list[dict[str, Any]]) -> dict[str, int]:
    """Questions-per-field map. Feeds the Fix D `breadth_share_f` term and the
    per-field confidence heuristic.
    """
    counts: dict[str, int] = {}
    for qr in question_results:
        field = qr.get("field")
        if isinstance(field, str) and field:
            counts[field] = counts.get(field, 0) + 1
    return counts


# --------------------------------------------------------------------------
# entry_state / comparison_points extraction (Fix B)
#
# Both pull per-field/topic mean post scores + career_level + date out of
# already-persisted run data — no new persistence. Called by the command sites
# and passed into `grade()`, which routes them to the stitch step only.
# --------------------------------------------------------------------------


def _run_date(run: dict[str, Any] | None) -> str | None:
    if not isinstance(run, dict):
        return None
    for key in ("start", "date", "started_at"):
        v = run.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _days_between(older: str | None, newer: str | None) -> float:
    """Calendar days from `older` to `newer` (ISO-8601). 0.0 on unparseable input."""
    if not older or not newer:
        return 0.0
    try:
        a = datetime.fromisoformat(older)
        b = datetime.fromisoformat(newer)
    except ValueError:
        return 0.0
    return (b - a).total_seconds() / 86400.0


def _unwrap_run_questions(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap a persisted run's `questions` (list of `{"question_<i>": qrec}`
    wrappers) into an ordered list of question records.
    """
    out: list[dict[str, Any]] = []
    for wrap in run.get("questions", []) or []:
        if not isinstance(wrap, dict):
            continue
        for _, qrec in wrap.items():
            if isinstance(qrec, dict):
                out.append(qrec)
                break
    return out


def _run_scores(run: dict[str, Any], answerer_band: str) -> tuple[dict[str, float], dict[str, float]]:
    """`(field_scores, topic_scores)` for a persisted graded run, scored at
    `answerer_band` — the current run's band, so the comparison is apples to
    apples even if the prior run was nominally graded at a different band.
    """
    qrecs = _unwrap_run_questions(run)
    return (
        current_field_scores(qrecs, answerer_band, tag="bands"),
        current_topic_scores(qrecs, answerer_band, tag="bands"),
    )


def _comparison_entry(run: dict[str, Any], answerer_band: str) -> dict[str, Any]:
    field_scores, topic_scores = _run_scores(run, answerer_band)
    return {
        "from_date": _run_date(run),
        "field_scores": field_scores,
        "topic_scores": topic_scores,
        "career_level": run.get("career_level") or "",
    }


def _session_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Session-shape stats over `runs` (entry .. current inclusive): run count,
    total questions, questions-per-field/topic, calendar span, active days.
    Feeds the Fix D coherence gradient.
    """
    R = len(runs)
    questions_total = 0
    by_field: dict[str, int] = {}
    by_topic: dict[str, int] = {}
    dates = []
    for run in runs:
        for qrec in _unwrap_run_questions(run):
            questions_total += 1
            field = qrec.get("field")
            if isinstance(field, str) and field:
                by_field[field] = by_field.get(field, 0) + 1
            for topic in qrec.get("topics") or []:
                if isinstance(topic, str) and topic:
                    by_topic[topic] = by_topic.get(topic, 0) + 1
        d = _run_date(run)
        if d:
            try:
                dates.append(datetime.fromisoformat(d).date())
            except ValueError:
                pass
    if dates:
        days_span = (max(dates) - min(dates)).days + 1   # inclusive day count
        days_active = len(set(dates))
    else:
        days_span = 1
        days_active = 1
    return {
        "runs": R,
        "questions_total": questions_total,
        "questions_by_field": by_field,
        "questions_by_topic": by_topic,
        "days_span": days_span,
        "days_active": days_active,
    }


def build_entry_state(
    session: dict[str, Any],
    answerer_band: str,
    current_run_id: str,
) -> dict[str, Any]:
    """Snapshot of the session's entry point — the first graded run's per-field/
    topic mean post scores + career_level + date — plus `session_stats` over the
    runs from entry through the current run, which the Fix D coherence gradient
    consumes. Feeds the `-1` within-session deltas. Returns the empty-state
    default (with stats still populated) when there is no graded first run.

    Scoped to runs[: current_run_id] inclusive so regrading a mid-history run
    measures only the session up to that point. No new persistence — everything
    comes from the run log.
    """
    runs = session.get("runs", []) or []
    cur_idx = next(
        (i for i, r in enumerate(runs) if str(r.get("id")) == str(current_run_id)),
        None,
    )
    scope = runs if cur_idx is None else runs[: cur_idx + 1]
    stats = _session_stats(scope)
    graded = [r for r in scope if r.get("aggregated_score") is not None]
    first = graded[0] if graded else None
    if first is None:
        return {"date": None, "field_scores": {}, "topic_scores": {}, "career_level": "", "session_stats": stats}
    field_scores, topic_scores = _run_scores(first, answerer_band)
    return {
        "date": _run_date(first),
        "field_scores": field_scores,
        "topic_scores": topic_scores,
        "career_level": first.get("career_level") or "",
        "session_stats": stats,
    }


def _verdict_for(w: float) -> str:
    """Verdict bucket for a coherence/recency weight (Fix D, tunable)."""
    if w >= _VERDICT_MEANINGFUL:
        return "meaningful"
    if w >= _VERDICT_TENTATIVE:
        return "tentative"
    return "insufficient"


def coherence_gradient(session_stats: dict[str, Any], kind: str, slug: str) -> dict[str, Any]:
    """Fix D within-session coherence gradient for a `-1` delta:
        breadth_share = q_f / Q         (penalises a thin, spread-out session)
        intensity_norm = min(R / D_span / target, 1)   (runs per calendar day)
        time_coherence = D_active / D_span             (clustered work scores high)
        w_f = clamp(breadth_share × intensity_norm × time_coherence, 0, 1)
    Returns the `coherence` sub-record: `w_f`, `verdict`, and the `questions` /
    `days_span` counts the renderer needs for the "insufficient signal" line.
    """
    Q = session_stats.get("questions_total", 0) or 0
    counts = session_stats.get(
        "questions_by_field" if kind == "field" else "questions_by_topic"
    ) or {}
    q_f = counts.get(slug, 0)
    R = session_stats.get("runs", 0) or 0
    days_span = session_stats.get("days_span", 1) or 1
    days_active = session_stats.get("days_active", 0) or 0

    breadth_share = (q_f / Q) if Q else 0.0
    intensity_norm = min(R / days_span / _TARGET_INTENSITY, 1.0) if days_span else 0.0
    time_coherence = (days_active / days_span) if days_span else 0.0
    w_f = max(0.0, min(breadth_share * intensity_norm * time_coherence, 1.0))
    return {
        "w_f": round(w_f, 3),
        "verdict": _verdict_for(w_f),
        "questions": q_f,
        "days_span": days_span,
    }


def recency_weight(point: str) -> dict[str, Any]:
    """Fix D weight for a cross-run (1/5/10/30) delta — the simpler weight the
    plan scopes to non-`-1` points. A single-run delta is noise; a 10+-run delta
    is a sustained trend: w = min(N / 10, 1). Same verdict buckets.
    """
    try:
        n = abs(int(point))
    except (TypeError, ValueError):
        n = 1
    w = min(n / 10.0, 1.0)
    return {"w_f": round(w, 3), "verdict": _verdict_for(w), "questions": None, "days_span": None}


def build_comparison_points(
    session: dict[str, Any],
    answerer_band: str,
    current_run_id: str,
) -> dict[str, Any]:
    """Build the `comparison_points` structure the stitch step uses for the
    1/5/10/30 cross-run deltas.

    Walks the session's runs in chronological (list) order, takes the GRADED
    runs strictly before the current one, and for each comparison point N picks:
      - `runs` tree: the run N graded-runs back.
      - `time` tree: the most recent prior run ≥ N calendar days back.
    Each entry carries that run's per-field/topic mean post score (at
    `answerer_band`), `career_level`, and date. Points with no qualifying run
    are simply absent. No new persistence — everything comes from the run log.
    """
    runs = session.get("runs", []) or []
    cur_idx = next(
        (i for i, r in enumerate(runs) if str(r.get("id")) == str(current_run_id)),
        None,
    )
    if cur_idx is None:
        return {"runs": {}, "time": {}}
    cur_date = _run_date(runs[cur_idx])
    prior = [r for r in runs[:cur_idx] if r.get("aggregated_score") is not None]
    if not prior:
        return {"runs": {}, "time": {}}

    runs_tree: dict[str, Any] = {}
    time_tree: dict[str, Any] = {}
    for n in _COMPARISON_POINTS:
        if len(prior) >= n:
            runs_tree[str(n)] = _comparison_entry(prior[-n], answerer_band)
        if cur_date is not None:
            older = [r for r in prior if _days_between(_run_date(r), cur_date) >= n]
            if older:
                time_tree[str(n)] = _comparison_entry(older[-1], answerer_band)
    return {"runs": runs_tree, "time": time_tree}


# --------------------------------------------------------------------------
# Delta-tree arithmetic
# --------------------------------------------------------------------------


def _delta_record(
    *,
    kind: str,
    slug: str,
    point: str,
    branch: str,
    from_date: str | None,
    from_score: float,
    cur_score: float,
    coherence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one `(delta_record, delta_job)` pair. The record is the persisted
    sessions.json DeltaRecord with its qualitative fields stubbed (the stitch
    LLM fills them, matched by the transient `_id`); the job is the structured
    input that stitch call receives.

    `career_level_before` / `_after` are derived per field/topic from the
    from-score and current-score via the score→keyword thresholds — so each
    record carries that field's own level transition. `coherence` carries the
    Fix D `w_f` + verdict; it drives the verdict LABEL, never the delta number.
    """
    diff = round(cur_score - from_score, 1)
    direction = "+" if diff > 0.05 else ("-" if diff < -0.05 else "=")
    delta = format_delta_string(diff)
    before_kw, _ = band_data.score_to_keyword(from_score)
    after_kw, _ = band_data.score_to_keyword(cur_score)
    job_id = f"{branch}:{kind}:{slug}:{point}"
    record = {
        "from": from_date,
        "direction": direction,
        "delta": delta,
        "overlap": [],
        "diff": [],
        "career_level_before": before_kw,
        "career_level_after": after_kw,
        "level_change_reason": "",
        "level_change_citations": [],
        "coherence": coherence,
        "_id": job_id,
    }
    job = {
        "id": job_id,
        "kind": kind,
        "slug": slug,
        "point": point,
        "from_date": from_date,
        "from_score": from_score,
        "from_career_level": before_kw,
        "current_score": cur_score,
        "current_career_level": after_kw,
        "direction": direction,
        "delta": delta,
        "w_f": coherence.get("w_f"),
        "verdict": coherence.get("verdict"),
    }
    return record, job


def _emit_point_deltas(
    field_branch: dict[str, Any],
    topic_branch: dict[str, Any],
    delta_jobs: list[dict[str, Any]],
    *,
    point: str,
    branch: str,
    entry: dict[str, Any],
    cur_field: dict[str, float],
    cur_topic: dict[str, float],
    session_stats: dict[str, Any],
) -> None:
    """Emit delta records for one comparison point. Overlap gate: a record is
    emitted for a field/topic only when it was tested at BOTH the comparison
    point and now (it has a from-score and a current-score). The `-1`
    within-session point gets the full coherence gradient; `1/5/10/30` get the
    simpler recency weight (Fix D scope).
    """
    from_date = entry.get("from_date")
    for kind, from_scores, cur_scores, dest in (
        ("field", entry.get("field_scores") or {}, cur_field, field_branch),
        ("topic", entry.get("topic_scores") or {}, cur_topic, topic_branch),
    ):
        for slug, from_score in from_scores.items():
            cur_score = cur_scores.get(slug)
            if cur_score is None or not isinstance(from_score, (int, float)):
                continue
            if point == "-1":
                coherence = coherence_gradient(session_stats, kind, slug)
            else:
                coherence = recency_weight(point)
            record, job = _delta_record(
                kind=kind,
                slug=slug,
                point=point,
                branch=branch,
                from_date=from_date,
                from_score=float(from_score),
                cur_score=float(cur_score),
                coherence=coherence,
            )
            dest.setdefault(slug, {})[point] = record
            delta_jobs.append(job)


def build_delta_trees(
    question_results: list[dict[str, Any]],
    answerer_band: str,
    *,
    entry_state: dict[str, Any] | None,
    comparison_points: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Build the `field_delta` / `topic_delta` trees and the flat `delta_jobs`
    list the qualitative stitch call themes.

    Returns `(field_delta, topic_delta, delta_jobs)`. Each tree is
    `{"runs": {...}, "time": {...}}`; every delta record carries a transient
    `_id` that `apply_themes` strips after merging the stitch themes, plus a
    `coherence` sub-record (Fix D `w_f` + verdict).

    `comparison_points` (Fix B) drives the `1/5/10/30` deltas in both trees,
    weighted by the recency weight. `entry_state` drives the `-1` within-session
    delta, weighted by the full coherence gradient over `entry_state.session_stats`.
    """
    field_delta: dict[str, Any] = {"runs": {}, "time": {}}
    topic_delta: dict[str, Any] = {"runs": {}, "time": {}}
    delta_jobs: list[dict[str, Any]] = []

    cur_field = current_field_scores(question_results, answerer_band)
    cur_topic = current_topic_scores(question_results, answerer_band)
    session_stats = (entry_state or {}).get("session_stats") or {}

    cp = comparison_points or {}
    for branch in ("runs", "time"):
        for point, entry in (cp.get(branch) or {}).items():
            if isinstance(entry, dict):
                _emit_point_deltas(
                    field_delta[branch], topic_delta[branch], delta_jobs,
                    point=str(point), branch=branch, entry=entry,
                    cur_field=cur_field, cur_topic=cur_topic,
                    session_stats=session_stats,
                )

    # `-1` within-session: entry_state is the session's shared entry origin, so
    # it lands in BOTH trees. Active once the call sites wire entry_state (Fix D).
    if entry_state and (entry_state.get("field_scores") or entry_state.get("topic_scores")):
        normalized = {
            "from_date": entry_state.get("date"),
            "field_scores": entry_state.get("field_scores") or {},
            "topic_scores": entry_state.get("topic_scores") or {},
        }
        for branch in ("runs", "time"):
            _emit_point_deltas(
                field_delta[branch], topic_delta[branch], delta_jobs,
                point="-1", branch=branch, entry=normalized,
                cur_field=cur_field, cur_topic=cur_topic,
                session_stats=session_stats,
            )

    return field_delta, topic_delta, delta_jobs


def apply_themes(
    field_delta: dict[str, Any],
    topic_delta: dict[str, Any],
    themes: list[dict[str, Any]],
) -> None:
    """Merge the qualitative-stitch `themes` back into the delta trees in place,
    matched by the transient `_id` each record carries from `build_delta_trees`.

    Each delta record is left with `overlap` / `diff` / `level_change_reason` /
    `level_change_citations` filled (from its theme, or empty defaults when the
    stitch produced no match) and the transient `_id` stripped, so the persisted
    record matches the sessions.json DeltaRecord schema. A no-op on the empty
    trees a comparison-less run produces.
    """
    by_id = {t["id"]: t for t in themes if isinstance(t, dict) and "id" in t}
    for tree in (field_delta, topic_delta):
        for branch in ("runs", "time"):
            for by_point in (tree.get(branch) or {}).values():
                if not isinstance(by_point, dict):
                    continue
                for record in by_point.values():
                    if not isinstance(record, dict):
                        continue
                    theme = by_id.get(record.pop("_id", None))
                    record["overlap"] = (theme or {}).get("overlap") or []
                    record["diff"] = (theme or {}).get("diff") or []
                    record["level_change_reason"] = (theme or {}).get("level_change_reason") or ""
                    record["level_change_citations"] = (theme or {}).get("level_change_citations") or []
