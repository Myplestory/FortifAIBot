from __future__ import annotations

import discord
from discord import app_commands

import analytics
import charts
import parse

from commands.shared import SCOPE_DESCRIBE, cleanup_chart
from content.analyze import analyze_embed_from_view, progression_embed_from_view


def register(tree: app_commands.CommandTree) -> None:
    analyze_group = app_commands.Group(name="analyze", description="Trends, gaps, and bias analytics.")

    @analyze_group.command(name="trends", description="Activity trends across runs in the active session.")
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def analyze_trends_cmd(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        view = analytics.analyze_trends(str(interaction.user.id), n)
        chart = charts.delta_diverging(view.deltas, title="Field deltas") if view.deltas else None
        embed, files = analyze_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    @analyze_group.command(name="gaps", description="Fields and topics not yet tested.")
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def analyze_gaps_cmd(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        meta = parse.read_meta()
        view = analytics.analyze_gaps(str(interaction.user.id), meta, n)
        embed, files = analyze_embed_from_view(view, None)
        await interaction.followup.send(embed=embed, files=files)

    @analyze_group.command(name="bias", description="Over-indexed fields/topics relative to uniform coverage.")
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def analyze_bias_cmd(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        meta = parse.read_meta()
        view = analytics.analyze_bias(str(interaction.user.id), meta, n)
        chart = charts.delta_diverging(view.deltas, title="Bias vs uniform")
        embed, files = analyze_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    @analyze_group.command(
        name="progression",
        description="Per-run aggregated-score trajectory (unlocks at 5 graded runs).",
    )
    @app_commands.describe(n=SCOPE_DESCRIBE)
    async def analyze_progression_cmd(interaction: discord.Interaction, n: int | None = None):
        await interaction.response.defer(thinking=True)
        view = analytics.analyze_progression(str(interaction.user.id), n)
        # Below threshold → no chart; the embed surfaces the lack-of-data state.
        chart = (
            charts.score_progression(view.pre_scores, view.post_scores, title="Score progression")
            if not view.insufficient_data
            else None
        )
        embed, files = progression_embed_from_view(view, chart)
        try:
            await interaction.followup.send(embed=embed, files=files)
        finally:
            cleanup_chart(chart)

    tree.add_command(analyze_group)
