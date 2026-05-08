from __future__ import annotations

from pathlib import Path


SCOPE_DESCRIBE = (
    "Scope: null/-1 = entire active session (default); 1 = last run; N = last N runs of the active session."
)


def cleanup_chart(path: Path | None) -> None:
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
