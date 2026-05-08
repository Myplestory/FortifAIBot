"""Generic, domain-free utilities. Functions here must be pure and have no
import dependency on app modules (parse, generate, embeds, llm, scheduler).
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """UTC timestamp in ISO-8601 with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def humanize_duration(start: str, end: str) -> str:
    """Format an elapsed window between two ISO-8601 strings as `Xs`, `Xm Ys`,
    or `Xh Ym` — whichever is the most compact representation."""
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(end)
    seconds = int((b - a).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h, rem = divmod(seconds, 3600)
    return f"{h}h {rem // 60}m"


def split_csv(s: str | None) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty tokens.
    Returns [] for None, empty, or whitespace-only input."""
    if not s:
        return []
    return [tok.strip() for tok in s.split(",") if tok.strip()]
