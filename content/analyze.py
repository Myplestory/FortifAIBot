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


def progression_embed_from_view(
    view: analytics.ProgressionView,
    chart_path: Path | None,
) -> tuple[discord.Embed, list[discord.File]]:
    if view.insufficient_data:
        message = (
            f"Score progression unlocks at {view.threshold} graded runs in the session. "
            f"You have {view.graded_count}."
        )
        return build(
            title=view.title,
            description=view.subtitle,
            fields=[("Lack of data", message, False)],
            icon=ICON_NAMES["analyze"],
            chart=None,
        )
    fields_listed: list[tuple[str, str, bool]] = []
    if view.first_pre is not None and view.last_pre is not None and view.net_change is not None:
        sign = "+" if view.net_change > 0 else ""  # negative values carry their own sign in the f-string
        fields_listed.append(
            (
                "Net change (unassisted)",
                f"{view.first_pre:.1f} → {view.last_pre:.1f} ({sign}{view.net_change:.1f})",
                True,
            )
        )
    if view.min_pre is not None and view.max_pre is not None:
        fields_listed.append(("Range (unassisted)", f"{view.min_pre:.1f} – {view.max_pre:.1f}", True))
    fields_listed.append(("Graded runs", str(view.graded_count), True))
    return build(
        title=view.title,
        description=view.subtitle,
        fields=fields_listed,
        icon=ICON_NAMES["analyze"],
        chart=chart_path,
    )
