from __future__ import annotations

from typing import Any

import discord

from content.shared import (
    BLUE_PRIMARY,
    ICON_NAMES,
    _chunk_field,
    _format_lit_entry,
    build,
)


def session_rollup_embed(
    session_id: str,
    duration: str,
    runs_count: int,
    remediation: list[tuple[str, dict[str, Any]]],
    growth: list[tuple[str, dict[str, Any]]],
) -> tuple[discord.Embed, list[discord.File]]:
    """Render the deduped session-level reading list at /sessionend.

    `remediation` and `growth` are lists of (run_origin_label, entry) tuples,
    pre-deduplicated by URL (or title+section fallback) by the caller.
    """
    fields: list[tuple[str, str, bool]] = [
        ("Session", f"`#{session_id}`", True),
        ("Duration", duration, True),
        ("Runs", str(runs_count), True),
    ]

    def _render(items: list[tuple[str, dict[str, Any]]]) -> str:
        if not items:
            return "_(none)_"
        lines: list[str] = []
        for origin, e in items:
            lines.append(f"• {_format_lit_entry(e)}  _(from run #{origin})_")
        return "\n".join(lines)

    fields.extend(_chunk_field("Remediation reading", _render(remediation)))
    fields.extend(_chunk_field("Growth reading", _render(growth)))

    return build(
        title="Session reading list",
        description="Deduplicated literature across all graded runs in this session. "
                    "Remediation closes specific gaps; growth points at the next-step progression.",
        fields=fields,
        icon=ICON_NAMES["literature"],
        color=BLUE_PRIMARY,
    )
