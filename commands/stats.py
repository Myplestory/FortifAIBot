from __future__ import annotations

import discord
from discord import app_commands

import analytics
import charts

from commands.shared import SCOPE_DESCRIBE, cleanup_chart
from content.stats import stats_embed_from_view


def register(tree: app_commands.CommandTree) -> None:
    stats_group = app_commands.Group(name="stats", description="Aggregate stats from your sessions.")

    @stats_group.command(name="runcount", description="Stats by run scope (default: whole active session).")
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def stats_runcount(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        view = analytics.runcount_stats(str(interaction.user.id), n)
        chart = charts.field_distribution(view.field_counts, title="Runs by field") if view.field_counts else None
        embed, files = stats_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    @stats_group.command(name="timeline", description="Stats over a recent time range.")
    @app_commands.choices(range=[
        app_commands.Choice(name="Last 7 days", value="7d"),
        app_commands.Choice(name="Last 30 days", value="30d"),
        app_commands.Choice(name="Last 90 days", value="90d"),
        app_commands.Choice(name="All time", value="all"),
    ])
    async def stats_timeline(interaction: discord.Interaction, range: app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)
        view = analytics.timeline_stats(str(interaction.user.id), range.value)
        chart = charts.runs_over_time(view.timeline, granularity="day", title=f"Runs · {range.name}")
        embed, files = stats_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    @stats_group.command(name="session", description="Stats for the active session (default: whole session).")
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def stats_session(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        view = analytics.runcount_stats(str(interaction.user.id), n)
        chart = charts.field_distribution(view.field_counts, title="Session field distribution") if view.field_counts else None
        embed, files = stats_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    tree.add_command(stats_group)
