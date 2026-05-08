from __future__ import annotations

from pathlib import Path

import discord

import analytics

from content.shared import ICON_NAMES, build


def stats_embed_from_view(
    view: analytics.StatsView,
    chart_path: Path | None,
) -> tuple[discord.Embed, list[discord.File]]:
    fields_listed = [
        ("Total runs", str(view.total_runs), True),
        ("Questions answered", f"{view.completed_questions} / {view.total_questions}", True),
        ("Avg run duration", view.avg_duration_human, True),
    ]
    fields_listed.append((
        "Top fields",
        ", ".join(f"`{k}` ({v})" for k, v in sorted(view.field_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]) or "—",
        False,
    ))
    if view.grading_unavailable:
        fields_listed.append(("Bands & scores", "Available after grading lands.", False))
    return build(
        title=view.title,
        description=view.subtitle,
        fields=fields_listed,
        icon=ICON_NAMES["stats"],
        chart=chart_path,
    )
