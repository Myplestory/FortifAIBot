from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import parse


@dataclass
class StatsView:
    title: str
    subtitle: str
    total_runs: int
    total_questions: int
    completed_questions: int
    avg_run_duration_seconds: float | None
    field_counts: dict[str, int] = field(default_factory=dict)
    topic_counts: dict[str, int] = field(default_factory=dict)
    timeline: list[str] = field(default_factory=list)
    grading_unavailable: bool = True

    @property
    def completion_rate(self) -> float:
        if not self.total_questions:
            return 0.0
        return self.completed_questions / self.total_questions

    @property
    def avg_duration_human(self) -> str:
        if not self.avg_run_duration_seconds:
            return "—"
        s = int(self.avg_run_duration_seconds)
        if s < 60:
            return f"{s}s"
        return f"{s // 60}m {s % 60}s"


@dataclass
class AnalyzeView:
    title: str
    subtitle: str
    growth: list[tuple[str, float]]
    decline: list[tuple[str, float]]
    untouched_fields: list[str]
    untouched_topics: list[str]
    over_indexed: list[tuple[str, float]]
    deltas: dict[str, float]
    grading_unavailable: bool = True


def _user_runs(discord_user_id: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for s in parse.all_user_sessions(discord_user_id):
        for r in s.get("runs", []):
            out.append((s, r))
    return out


def _seconds_between(start: str, end: str) -> float | None:
    try:
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(end)
        return (b - a).total_seconds()
    except (ValueError, TypeError):
        return None


def _accumulate(runs: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int], list[str], int, int, list[float]]:
    field_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    timeline: list[str] = []
    total_q = 0
    completed_q = 0
    durations: list[float] = []
    for r in runs:
        timeline.append(r.get("start", ""))
        d = _seconds_between(r.get("start", ""), r.get("end", ""))
        if d is not None:
            durations.append(d)
        for q_wrap in r.get("questions", []):
            for _, qrec in q_wrap.items():
                total_q += 1
                if qrec.get("response"):
                    completed_q += 1
                f = qrec.get("field")
                if isinstance(f, str):
                    field_counts[f] += 1
                for t in qrec.get("topics", []) or []:
                    topic_counts[t] += 1
    return dict(field_counts), dict(topic_counts), timeline, total_q, completed_q, durations


def _scope_subtitle(n: int | None) -> str:
    if n is None or n == -1:
        return "Active session (whole)"
    if n == 1:
        return "Last run"
    return f"Last {n} runs"


def runcount_stats(discord_user_id: str, n: int | None) -> StatsView:
    runs = parse.runs_by_scope(discord_user_id, n)
    fc, tc, tl, total_q, comp_q, durations = _accumulate(runs)
    avg = sum(durations) / len(durations) if durations else None
    return StatsView(
        title="Stats",
        subtitle=_scope_subtitle(n),
        total_runs=len(runs),
        total_questions=total_q,
        completed_questions=comp_q,
        avg_run_duration_seconds=avg,
        field_counts=fc,
        topic_counts=tc,
        timeline=tl,
    )


def timeline_stats(discord_user_id: str, range_token: str) -> StatsView:
    pairs = _user_runs(discord_user_id)
    cutoff = None
    label = range_token
    now = datetime.now(timezone.utc)
    if range_token == "7d":
        cutoff = now - timedelta(days=7)
    elif range_token == "30d":
        cutoff = now - timedelta(days=30)
    elif range_token == "90d":
        cutoff = now - timedelta(days=90)
    elif range_token == "all":
        cutoff = None
        label = "all time"

    def _within(r: dict[str, Any]) -> bool:
        if cutoff is None:
            return True
        try:
            return datetime.fromisoformat(r.get("start", "")) >= cutoff
        except (ValueError, TypeError):
            return False

    runs = [r for _, r in pairs if _within(r)]
    fc, tc, tl, total_q, comp_q, durations = _accumulate(runs)
    avg = sum(durations) / len(durations) if durations else None
    return StatsView(
        title="Stats by timeline",
        subtitle=f"Range: {label}",
        total_runs=len(runs),
        total_questions=total_q,
        completed_questions=comp_q,
        avg_run_duration_seconds=avg,
        field_counts=fc,
        topic_counts=tc,
        timeline=tl,
    )


def _split_recent(runs: list[dict[str, Any]], n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(runs) < 2 * n:
        half = max(1, len(runs) // 2)
        return runs[:-half], runs[-half:]
    return runs[: -n], runs[-n:]


def analyze_trends(discord_user_id: str, n: int | None = None) -> AnalyzeView:
    runs = parse.runs_by_scope(discord_user_id, n)
    older, newer = _split_recent(runs, 5)
    older_fc, older_tc, *_ = _accumulate(older)
    newer_fc, newer_tc, *_ = _accumulate(newer)

    def _delta(a: dict[str, int], b: dict[str, int]) -> dict[str, float]:
        out: dict[str, float] = {}
        keys = set(a) | set(b)
        for k in keys:
            out[k] = b.get(k, 0) - a.get(k, 0)
        return out

    field_delta = _delta(older_fc, newer_fc)
    growth = sorted([(k, v) for k, v in field_delta.items() if v > 0], key=lambda kv: kv[1], reverse=True)[:3]
    decline = sorted([(k, v) for k, v in field_delta.items() if v < 0], key=lambda kv: kv[1])[:3]
    return AnalyzeView(
        title="Trends",
        subtitle=f"{_scope_subtitle(n)} · recent {len(newer)} vs prior {len(older)}",
        growth=[(k, float(v)) for k, v in growth],
        decline=[(k, float(v)) for k, v in decline],
        untouched_fields=[],
        untouched_topics=[],
        over_indexed=[],
        deltas={k: float(v) for k, v in field_delta.items()},
    )


def analyze_gaps(discord_user_id: str, meta: dict[str, Any], n: int | None = None) -> AnalyzeView:
    runs = parse.runs_by_scope(discord_user_id, n)
    fc, tc, *_ = _accumulate(runs)
    all_fields = list((meta.get("fields") or {}).keys())
    untouched_fields = [f for f in all_fields if not fc.get(f)]
    all_topics: list[str] = []
    for slug, fdata in (meta.get("fields") or {}).items():
        for t in fdata.get("topics", []):
            all_topics.append(t)
    untouched_topics = [t for t in all_topics if not tc.get(t)]
    return AnalyzeView(
        title="Gaps",
        subtitle=f"{_scope_subtitle(n)} · fields and topics not yet tested",
        growth=[],
        decline=[],
        untouched_fields=untouched_fields,
        untouched_topics=untouched_topics[:20],
        over_indexed=[],
        deltas={},
    )


def analyze_bias(discord_user_id: str, meta: dict[str, Any], n: int | None = None) -> AnalyzeView:
    runs = parse.runs_by_scope(discord_user_id, n)
    fc, tc, *_ = _accumulate(runs)
    total_field_q = sum(fc.values()) or 1
    expected = 1.0 / max(1, len(meta.get("fields") or {}))
    ratios = {f: (count / total_field_q) - expected for f, count in fc.items()}
    over = sorted([(k, v) for k, v in ratios.items() if v > 0], key=lambda kv: kv[1], reverse=True)[:5]
    return AnalyzeView(
        title="Bias",
        subtitle=f"{_scope_subtitle(n)} · over-indexed fields vs uniform",
        growth=[],
        decline=[],
        untouched_fields=[],
        untouched_topics=[],
        over_indexed=[(k, float(v)) for k, v in over],
        deltas=ratios,
    )
