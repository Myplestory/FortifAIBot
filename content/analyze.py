from __future__ import annotations

from pathlib import Path

import discord

import analytics

from content.shared import ICON_NAMES, build


def analyze_embed_from_view(
    view: analytics.AnalyzeView,
    chart_path: Path | None,
) -> tuple[discord.Embed, list[discord.File]]:
    fields_listed: list[tuple[str, str, bool]] = []
    if view.growth:
        fields_listed.append(("Top growth", "\n".join(f"• `{k}` (+{v:g})" for k, v in view.growth), True))
    if view.decline:
        fields_listed.append(("Top decline", "\n".join(f"• `{k}` ({v:+g})" for k, v in view.decline), True))
    if view.untouched_fields:
        fields_listed.append(("Untouched fields", ", ".join(f"`{f}`" for f in view.untouched_fields), False))
    if view.untouched_topics:
        fields_listed.append(("Untouched topics", ", ".join(f"`{t}`" for t in view.untouched_topics), False))
    if view.over_indexed:
        fields_listed.append(("Over-indexed", "\n".join(f"• `{k}` (+{v:.2f})" for k, v in view.over_indexed), False))
    if view.grading_unavailable:
        fields_listed.append(("Mastery & decay", "Available after grading lands.", False))
    return build(
        title=view.title,
        description=view.subtitle,
        fields=fields_listed or [("No data", "Run more sessions to populate analytics.", False)],
        icon=ICON_NAMES["analyze"],
        chart=chart_path,
    )
