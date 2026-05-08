from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from util import humanize_duration, now_iso

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
SESSIONS_DIR = ROOT / "sessions"
ACTIVE_PATH = DATA_DIR / "session.json"
META_PATH = DATA_DIR / "meta.json"

CANONICAL_FIELDS: dict[str, dict[str, Any]] = {
    "systems-distributed": {
        "name": "Systems / Distributed Systems",
        "description": "Design and reasoning across distributed systems, capacity, real-time/embedded, and high-performance computing.",
        "sfia_skills": ["Systems design", "Solution architecture", "Software design", "Programming/software development", "Systems integration and build", "Real-time/embedded systems development", "Systems and software lifecycle engineering", "High-performance computing", "Capacity management", "Methods and tools"],
    },
    "backend": {
        "name": "Backend Engineering",
        "description": "API services, databases, and the engineering practices around shipping and supporting them.",
        "sfia_skills": ["Programming/software development", "Software design", "Database design", "Database administration", "Solution architecture", "Application support", "Functional testing", "Non-functional testing", "Configuration management", "Release management", "Systems integration and build", "Requirements definition and management"],
    },
    "sre": {
        "name": "SRE",
        "description": "Reliability, capacity, deployment, observability, and infrastructure operations.",
        "sfia_skills": ["Infrastructure operations", "Infrastructure design", "Capacity management", "Application support", "Release management", "Deployment", "Configuration management", "System software administration", "Network design", "Network support", "Non-functional testing"],
    },
    "ml-engineering": {
        "name": "ML Engineering",
        "description": "Production ML: training, serving, data pipelines, numerical methods, and HPC.",
        "sfia_skills": ["Machine learning", "Data science", "Data engineering", "Programming/software development", "Numerical analysis", "High-performance computing", "Data modelling and design"],
    },
    "ai-llm": {
        "name": "AI / LLM Engineering",
        "description": "LLM application architecture, prompt design, evaluation, and integration patterns.",
        "sfia_skills": ["Machine learning", "Data science", "Solution architecture", "Software design", "Programming/software development"],
    },
    "frontend": {
        "name": "Frontend Engineering",
        "description": "Client-side application engineering, UX, and frontend testing/support.",
        "sfia_skills": ["Programming/software development", "Software design", "User experience design", "Functional testing", "Non-functional testing", "Application support"],
    },
    "data-engineering": {
        "name": "Data Engineering",
        "description": "Data pipelines, warehousing, modelling, analytics, and visualisation.",
        "sfia_skills": ["Data engineering", "Database design", "Database administration", "Data modelling and design", "Data analytics", "Data visualisation", "Data science", "Programming/software development"],
    },
    "security": {
        "name": "Security",
        "description": "Information security, vulnerability research, and safety assessment.",
        "sfia_skills": ["Information security", "Vulnerability research", "Safety assessment"],
    },
}

VALID_BANDS = {"B1", "B2", "B3", "B4", "B5"}

_question_bank: dict[str, dict[str, Any]] = {}


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path: Path) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path) as f:
        return json.load(f)


def _read_active() -> dict[str, dict[str, Any]]:
    """Read active sessions, migrating legacy single-session-per-user shape to
    the multi-session shape. Persists the migrated form immediately so the
    next operation observes the canonical layout on disk.

    Legacy: { "<user_id>": <session_record> }
    Current: { "<user_id>": { "current": "<name>" | null, "sessions": { "<name>": <session_record> } } }
    """
    data = _read_json(ACTIVE_PATH)
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    migrated = False
    for uid, val in data.items():
        if not isinstance(val, dict):
            continue
        if isinstance(val.get("sessions"), dict):
            out[uid] = val
            continue
        if "id" in val and "runs" in val:
            session_name = val.get("name") or "default"
            val["name"] = session_name
            out[uid] = {
                "current": session_name,
                "sessions": {session_name: val},
            }
            migrated = True
            log.info(
                "migrated legacy single-session for user=%s → active session name=%r",
                uid, session_name,
            )
    if migrated:
        _atomic_write(ACTIVE_PATH, out)
    return out


def _write_active(data: dict[str, dict[str, Any]]) -> None:
    _atomic_write(ACTIVE_PATH, data)


def _user_active_block(active: dict[str, dict[str, Any]], user_id: str) -> dict[str, Any]:
    return active.setdefault(user_id, {"current": None, "sessions": {}})


def _find_active_by_id(active: dict[str, dict[str, Any]], user_id: str, session_id: str) -> tuple[str, dict[str, Any]] | None:
    block = active.get(user_id)
    if not block:
        return None
    for name, s in (block.get("sessions") or {}).items():
        if str(s.get("id")) == str(session_id):
            return name, s
    return None


def ensure_runtime_dirs() -> None:
    """Eagerly create the local state directories so a fresh clone has them
    on disk after first run. Both directories are gitignored — the app owns
    their contents.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def seed_meta_if_empty() -> None:
    """Ensure every canonical field has a shell in meta.json. Additive: existing
    entries (criteria, topics, hand-seeded data) are preserved; only missing
    canonical slugs are filled in. Self-healing — a partial or hand-edited
    meta.json is brought back into shape on the next read.
    """
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(META_PATH) or {}
    fields = existing.get("fields") or {}
    missing = [slug for slug in CANONICAL_FIELDS if slug not in fields]
    if not missing:
        return
    for slug in missing:
        m = CANONICAL_FIELDS[slug]
        fields[slug] = {
            "name": m["name"],
            "description": m["description"],
            "criteria": {},
            "topics": [],
        }
    existing["fields"] = fields
    _atomic_write(META_PATH, existing)


def read_meta() -> dict[str, Any]:
    seed_meta_if_empty()
    return _read_json(META_PATH) or {"fields": {}}


def write_meta(data: dict[str, Any]) -> None:
    _atomic_write(META_PATH, data)


def find_active_session(user_id: str, name: str | None = None) -> dict[str, Any] | None:
    """Return a specific named active session, or the user's current session if
    `name` is None. Returns None if no match.
    """
    block = _read_active().get(user_id)
    if not block:
        return None
    sessions = block.get("sessions") or {}
    if name is None:
        current = block.get("current")
        return sessions.get(current) if current else None
    return sessions.get(name)


def list_active_sessions(user_id: str) -> list[dict[str, Any]]:
    """All active sessions for the user, in stable insertion order."""
    block = _read_active().get(user_id) or {}
    return list((block.get("sessions") or {}).values())


def get_current_session_name(user_id: str) -> str | None:
    block = _read_active().get(user_id)
    return block.get("current") if block else None


def switch_session(user_id: str, name: str) -> dict[str, Any] | None:
    """Set the user's current pointer to the named active session. Returns the
    new current session record, or None if name doesn't match.
    """
    active = _read_active()
    block = active.get(user_id)
    if not block or name not in (block.get("sessions") or {}):
        return None
    block["current"] = name
    _write_active(active)
    return block["sessions"][name]


def _make_session_id(user_id: str, started_iso: str) -> str:
    compact = started_iso.replace(":", "").replace("-", "").replace("+0000", "Z")[:15]
    return f"{user_id}-{compact}"


def create_session(
    user_id: str,
    user_name: str,
    name: str,
    band: str,
    quiz_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new active session under the given unique-per-user `name`.
    Sets the new session as current. Raises ValueError if `name` collides with
    another active session's name for this user.

    `quiz_defaults` (optional) declares granular scope inherited by
    `/knowledgeharden` runs in this session: `industry`, `fields`, `topics`,
    `domain`, `stack`. Per-run args still override.
    """
    if band not in VALID_BANDS:
        raise ValueError(f"invalid band {band!r}")
    if not name or not name.strip():
        raise ValueError("session name is required")
    name = name.strip()
    active = _read_active()
    block = _user_active_block(active, user_id)
    sessions = block.setdefault("sessions", {})
    if name in sessions:
        raise ValueError(f"active session named {name!r} already exists")
    started = now_iso()
    record = {
        "id": _make_session_id(user_id, started),
        "name": name,
        "discord_user_id": user_id,
        "discord_user_name": user_name,
        "band_preference": band,
        "start": started,
        "end": None,
        "duration": None,
        "status": "in_progress",
        "runs": [],
    }
    cleaned_defaults = _clean_quiz_defaults(quiz_defaults)
    if cleaned_defaults:
        record["quiz_defaults"] = cleaned_defaults
    sessions[name] = record
    block["current"] = name
    _write_active(active)
    return record


def _clean_quiz_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Drop empty values so the session record only carries scopes the user
    actually declared. Returns {} when nothing meaningful was supplied.
    """
    if not raw:
        return {}
    out: dict[str, Any] = {}
    industry = (raw.get("industry") or "").strip() or None
    if industry:
        out["industry"] = industry
    domain = (raw.get("domain") or "").strip() or None
    if domain:
        out["domain"] = domain
    for key in ("fields", "topics", "stack"):
        vals = [str(v).strip() for v in (raw.get(key) or []) if str(v).strip()]
        if vals:
            out[key] = vals
    return out


def end_session(user_id: str, name: str | None = None) -> dict[str, Any] | None:
    """Close a session. If `name` is None, closes the current session. Updates
    the current pointer: if the closed session was current, current is reset
    to None (or the lone remaining active session, if exactly one).
    """
    active = _read_active()
    block = active.get(user_id)
    if not block:
        return None
    sessions = block.get("sessions") or {}
    target_name = name if name is not None else block.get("current")
    if not target_name or target_name not in sessions:
        return None
    rec = sessions.pop(target_name)
    rec["end"] = now_iso()
    rec["duration"] = humanize_duration(rec["start"], rec["end"])
    rec["status"] = "complete"
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(SESSIONS_DIR / f"{rec['id']}.json", rec)
    if block.get("current") == target_name:
        remaining = list(sessions.keys())
        block["current"] = remaining[0] if len(remaining) == 1 else None
    _write_active(active)
    return rec


def persist_run(
    *,
    user_id: str,
    session_id: str,
    industry: str,
    band: str,
    domain: str | None = None,
    stack: list[str] | None = None,
    fields_invoked: list[str],
    topics_invoked: list[str],
    model_called: str,
    model_refine: str,
    started_at: str,
    ended_at: str,
    practical_exercises: list[dict[str, Any]],
    generation_metadata: dict[str, Any],
    questions: list[dict[str, Any]],
) -> str:
    """Persist a completed run into the session identified by `session_id`. The
    explicit id (rather than "current session") protects against the user
    switching sessions mid-quiz.
    """
    active = _read_active()
    found = _find_active_by_id(active, user_id, session_id)
    if not found:
        raise RuntimeError(f"no active session with id {session_id!r} for user")
    _, rec = found
    existing_ids: list[int] = []
    for r in rec.get("runs", []) or []:
        try:
            existing_ids.append(int(r.get("id")))
        except (TypeError, ValueError):
            pass
    new_run_id = str((max(existing_ids) if existing_ids else 0) + 1)
    rec.setdefault("runs", []).append(
        {
            "id": new_run_id,
            "industry": industry,
            "band": band,
            "domain": domain or "",
            "stack": list(stack or []),
            "fields_invoked": fields_invoked,
            "topics_invoked": topics_invoked,
            "model_called": model_called,
            "model_refine": model_refine,
            "start": started_at,
            "end": ended_at,
            "duration": humanize_duration(started_at, ended_at),
            "status": "complete",
            "aggregated_score": None,
            "field_delta": {"runs": {}, "time": {}},
            "topic_delta": {"runs": {}, "time": {}},
            "career_level": "",
            "strengths": {"fields": [], "topics": []},
            "weaknesses": {"fields": [], "topics": []},
            "practical_exercises": practical_exercises,
            "generation_metadata": generation_metadata,
            "questions": questions,
        }
    )
    _write_active(active)
    apply_run_to_meta(fields_invoked, _topics_by_field_from_questions(questions))
    return new_run_id


def _topics_by_field_from_questions(questions: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Extract a {field: [topics]} map from the persisted question wraps. Each
    wrap looks like {"question_N": {"field": ..., "topics": [...], ...}}.
    """
    out: dict[str, list[str]] = {}
    for wrap in questions or []:
        if not isinstance(wrap, dict):
            continue
        for _, qrec in wrap.items():
            if not isinstance(qrec, dict):
                continue
            field = qrec.get("field")
            topics = qrec.get("topics") or []
            if not isinstance(field, str) or not field:
                continue
            bucket = out.setdefault(field, [])
            for t in topics:
                if isinstance(t, str) and t and t not in bucket:
                    bucket.append(t)
    return out


def apply_run_to_meta(fields_invoked: list[str], topics_by_field: dict[str, list[str]]) -> None:
    """Deterministic catalog growth. Independent of LLM-emitted `meta_updates`:
    every persisted run unions its invoked fields and per-field topics into
    `meta.json`, so the catalog reflects what was actually quizzed even when
    the model returns an empty `meta_updates`.
    """
    if not fields_invoked and not topics_by_field:
        return
    meta = read_meta()
    fields = meta.setdefault("fields", {})
    changed = False

    def _ensure_field(slug: str) -> dict[str, Any] | None:
        if slug not in CANONICAL_FIELDS:
            return None
        return fields.setdefault(
            slug,
            {
                "name": CANONICAL_FIELDS[slug]["name"],
                "description": CANONICAL_FIELDS[slug]["description"],
                "criteria": {},
                "topics": [],
            },
        )

    for slug in fields_invoked or []:
        entry = _ensure_field(slug)
        if entry is None:
            log.warning("apply_run_to_meta: dropping non-canonical field %r", slug)
            continue
        if "topics" not in entry:
            entry["topics"] = []
            changed = True

    for slug, topics in (topics_by_field or {}).items():
        entry = _ensure_field(slug)
        if entry is None:
            log.warning("apply_run_to_meta: dropping topics under non-canonical field %r", slug)
            continue
        existing = set(entry.get("topics", []))
        for t in topics:
            if t and t not in existing:
                entry.setdefault("topics", []).append(t)
                existing.add(t)
                changed = True

    if changed:
        write_meta(meta)


def heal_meta_from_user_runs(user_id: str) -> dict[str, Any]:
    """Reconstruct meta.json's field/topic catalog from all of the user's
    persisted runs (active + archived sessions). Idempotent — re-running on a
    healed catalog is a no-op. Use this in `/sweep catalog` to recover from a
    truncated, hand-edited, or otherwise stale meta.json.

    Returns a summary delta:
        {"runs_processed": int, "fields_added": [slug, ...], "topics_added_total": int}
    """
    pre = read_meta()
    pre_fields = set(pre.get("fields", {}).keys())
    pre_topics_per_field = {
        slug: set(entry.get("topics", []) or [])
        for slug, entry in (pre.get("fields") or {}).items()
    }

    sessions = list_active_sessions(user_id) + list_completed_for_user(user_id)
    runs_processed = 0
    for s in sessions:
        for run in s.get("runs", []) or []:
            fields_invoked = run.get("fields_invoked") or []
            topics_by_field = _topics_by_field_from_questions(run.get("questions") or [])
            if not fields_invoked and not topics_by_field:
                continue
            apply_run_to_meta(fields_invoked, topics_by_field)
            runs_processed += 1

    post = read_meta()
    fields_added = sorted(set(post.get("fields", {}).keys()) - pre_fields)
    topics_added_total = 0
    for slug, entry in (post.get("fields") or {}).items():
        post_set = set(entry.get("topics", []) or [])
        topics_added_total += len(post_set - pre_topics_per_field.get(slug, set()))

    return {
        "runs_processed": runs_processed,
        "fields_added": fields_added,
        "topics_added_total": topics_added_total,
    }


def apply_meta_updates(meta_updates: dict[str, Any]) -> None:
    if not meta_updates:
        return
    topics_added = meta_updates.get("topics_added") or {}
    criteria_set = meta_updates.get("criteria_set") or {}
    if not topics_added and not criteria_set:
        return
    meta = read_meta()
    fields = meta.setdefault("fields", {})
    changed = False

    def _ensure_field(slug: str) -> dict[str, Any]:
        return fields.setdefault(
            slug,
            {
                "name": CANONICAL_FIELDS[slug]["name"],
                "description": CANONICAL_FIELDS[slug]["description"],
                "criteria": {},
                "topics": [],
            },
        )

    for slug, new_topics in topics_added.items():
        if slug not in CANONICAL_FIELDS:
            log.warning("apply_meta_updates: dropping topics_added for non-canonical field %r", slug)
            continue
        entry = _ensure_field(slug)
        existing = set(entry.get("topics", []))
        for t in new_topics:
            if t and t not in existing:
                entry.setdefault("topics", []).append(t)
                existing.add(t)
                changed = True

    for slug, by_band in criteria_set.items():
        if slug not in CANONICAL_FIELDS:
            log.warning("apply_meta_updates: dropping criteria_set for non-canonical field %r", slug)
            continue
        if not isinstance(by_band, dict):
            log.warning("apply_meta_updates: criteria_set[%r] not a dict (got %s)", slug, type(by_band).__name__)
            continue
        entry = _ensure_field(slug)
        criteria = entry.setdefault("criteria", {})
        for raw_band, incoming in by_band.items():
            band = raw_band.upper() if isinstance(raw_band, str) else raw_band
            if band not in VALID_BANDS:
                log.warning("apply_meta_updates: dropping criteria for %r — unknown band %r", slug, raw_band)
                continue
            if not isinstance(incoming, dict):
                log.warning("apply_meta_updates: criteria_set[%r][%r] not a dict (got %s)", slug, raw_band, type(incoming).__name__)
                continue
            existing_band = criteria.get(band)
            if not existing_band:
                criteria[band] = {
                    "name": incoming.get("name", ""),
                    "description": incoming.get("description", ""),
                    "citations": dict(incoming.get("citations", {}) or {}),
                    "reasoning": incoming.get("reasoning", ""),
                }
                changed = True
                continue
            # Merge per grader.md rules: keep existing name/description unless incoming substantively
            # refines (we treat "longer" as the substantive signal); ALWAYS union citations; replace reasoning.
            if incoming.get("description") and len(incoming["description"]) > len(existing_band.get("description", "")):
                existing_band["description"] = incoming["description"]
                if incoming.get("name"):
                    existing_band["name"] = incoming["name"]
                changed = True
            existing_cites = existing_band.setdefault("citations", {})
            for ck, cv in (incoming.get("citations") or {}).items():
                if ck not in existing_cites:
                    existing_cites[ck] = cv
                    changed = True
            if incoming.get("reasoning") and incoming["reasoning"] != existing_band.get("reasoning"):
                existing_band["reasoning"] = incoming["reasoning"]
                changed = True

    if changed:
        write_meta(meta)


def apply_grading(user_id: str, session_id: str, run_id: str, grading: dict[str, Any]) -> None:
    """Merge Phase 4 grading output into the matching run record under session_id."""
    active = _read_active()
    found = _find_active_by_id(active, user_id, session_id)
    if not found:
        raise RuntimeError(f"no active session with id {session_id!r} for user")
    _, rec = found
    runs = rec.get("runs", [])
    target = next((r for r in runs if str(r.get("id")) == str(run_id)), None)
    if target is None:
        raise RuntimeError(f"run {run_id!r} not found in session {session_id!r}")

    agg = grading.get("run_aggregation", {}) or {}
    target["aggregated_score"] = agg.get("aggregated_score")
    target["career_level"] = agg.get("career_level", "")
    target["strengths"] = agg.get("strengths", {"fields": [], "topics": []})
    target["weaknesses"] = agg.get("weaknesses", {"fields": [], "topics": []})
    target["field_delta"] = grading.get("field_delta", {"runs": {}, "time": {}})
    target["topic_delta"] = grading.get("topic_delta", {"runs": {}, "time": {}})
    target["session_summary"] = grading.get("session_summary", {})
    target["report_markdown"] = grading.get("report_markdown", "")

    qg_list = grading.get("questions_grading", []) or []
    questions = target.get("questions", []) or []
    by_id = {qg.get("question_id"): qg for qg in qg_list}
    for i, wrap in enumerate(questions, start=1):
        key = f"question_{i}"
        if key not in wrap:
            continue
        qg = by_id.get(i)
        if not qg:
            continue
        qrec = wrap[key]
        qrec["bands_pre"] = qg.get("bands_pre", [])
        qrec["bands"] = qg.get("bands_post", [])
        qrec["band_ceiling_post"] = qg.get("band_ceiling_post")
        qrec["transitional_post"] = qg.get("transitional_post")
        qrec["assessment"] = qg.get("assessment", "")
        qrec["literature"] = qg.get("literature", [])

    _write_active(active)


def _run_has_any_response(run: dict[str, Any]) -> bool:
    for wrap in run.get("questions", []) or []:
        for _, qrec in wrap.items():
            if (qrec.get("response") or "").strip():
                return True
    return False


def _run_has_grading(run: dict[str, Any]) -> bool:
    return run.get("aggregated_score") is not None


def cleanup_abandoned_runs(user_id: str, session_id: str | None = None) -> list[str]:
    """Remove abandoned runs from the named session (or current session if
    `session_id` is None). A run is abandoned if every question's response is
    empty/whitespace. Returns the list of removed run ids.
    """
    active = _read_active()
    if session_id is not None:
        found = _find_active_by_id(active, user_id, session_id)
        if not found:
            return []
        _, rec = found
    else:
        block = active.get(user_id) or {}
        current = block.get("current")
        if not current:
            return []
        rec = (block.get("sessions") or {}).get(current)
        if not rec:
            return []
    runs = rec.get("runs", []) or []
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for r in runs:
        if _run_has_any_response(r):
            kept.append(r)
        else:
            removed.append(str(r.get("id", "?")))
    if removed:
        rec["runs"] = kept
        _write_active(active)
    return removed


def runs_needing_grading(user_id: str, session_id: str | None = None) -> list[dict[str, Any]]:
    """Runs in the named session (or current session) that finished with
    responses but never produced an aggregated score.
    """
    s = find_active_session(user_id) if session_id is None else find_active_session_by_id(user_id, session_id)
    if not s:
        return []
    out: list[dict[str, Any]] = []
    for r in s.get("runs", []) or []:
        if r.get("status") == "complete" and not _run_has_grading(r) and _run_has_any_response(r):
            out.append(r)
    return out


def find_active_session_by_id(user_id: str, session_id: str) -> dict[str, Any] | None:
    found = _find_active_by_id(_read_active(), user_id, session_id)
    return found[1] if found else None


def runs_by_scope(user_id: str, n: int | None) -> list[dict[str, Any]]:
    """Resolve the unified `n` arg for /stats and /analyze, scoped to the
    user's CURRENT active session.

    null or -1 → entire current session's runs.
    1         → last run only.
    N (>1)    → last N runs.
    Returns [] if no current session.
    """
    active = find_active_session(user_id)
    if not active:
        return []
    runs = list(active.get("runs", []) or [])
    if n is None or n == -1:
        return runs
    if n <= 0:
        return []
    return runs[-n:]


def list_completed_for_user(user_id: str) -> list[dict[str, Any]]:
    if not SESSIONS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(SESSIONS_DIR.glob("*.json")):
        data = _read_json(p)
        if isinstance(data, dict) and data.get("discord_user_id") == user_id:
            out.append(data)
    return out


def restore_session(user_id: str, session_id: str, name: str) -> dict[str, Any]:
    """Move a previously archived session from `sessions/<id>.json` back to the
    active block under the given (unique) `name`. Sets the restored session as
    current and removes the archive file. Raises ValueError on collisions or
    missing/foreign archives.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("restore name is required")
    closed_path = SESSIONS_DIR / f"{session_id}.json"
    if not closed_path.exists():
        raise ValueError(f"closed session {session_id!r} not found")
    data = _read_json(closed_path)
    if not isinstance(data, dict) or data.get("discord_user_id") != user_id:
        raise ValueError(f"closed session {session_id!r} is not yours")

    active = _read_active()
    block = _user_active_block(active, user_id)
    sessions = block.setdefault("sessions", {})
    if name in sessions:
        raise ValueError(f"active session named {name!r} already exists")

    # Re-open the record: clear close metadata and rename.
    data["status"] = "in_progress"
    data["end"] = None
    data["duration"] = None
    data["name"] = name

    sessions[name] = data
    block["current"] = name
    _write_active(active)
    closed_path.unlink()
    return data


def all_user_sessions(user_id: str) -> list[dict[str, Any]]:
    sessions = list_completed_for_user(user_id)
    active = find_active_session(user_id)
    if active:
        sessions.append(active)
    return sessions


def latest_session(user_id: str) -> dict[str, Any] | None:
    sessions = all_user_sessions(user_id)
    return sessions[-1] if sessions else None


def get_session(user_id: str, session_id: str | int) -> dict[str, Any] | None:
    if str(session_id) == "-1":
        return latest_session(user_id)
    for s in all_user_sessions(user_id):
        if str(s.get("id")) == str(session_id):
            return s
    return None


def questionbank(thread_id: str, generated: dict[str, Any]) -> None:
    _question_bank[thread_id] = generated


def get_bank(thread_id: str) -> dict[str, Any] | None:
    return _question_bank.get(thread_id)


def clear_bank(thread_id: str) -> None:
    _question_bank.pop(thread_id, None)


def segment(bank: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, wrap in enumerate(bank.get("questions", []), start=1):
        key = f"question_{i}"
        if key not in wrap:
            raise ValueError(f"questionbank missing {key}")
        rec = dict(wrap[key])
        rec["_index"] = i
        out.append(rec)
    if len(out) != 5:
        raise ValueError(f"questionbank must contain 5 questions, got {len(out)}")
    return out


def grader_available(industry: str = "swe") -> bool:
    p = ROOT / "templates" / industry / "grader.md"
    return p.exists() and p.stat().st_size > 0
