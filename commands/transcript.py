from __future__ import annotations

import discord
from discord import app_commands

import embeds
import parse


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="transcript", description="Fetch the grading transcript (summary + per-question breakdown) for a run in the current session.")
    @app_commands.describe(run="Run id within the current session. Omit for the latest run.")
    async def transcript(interaction: discord.Interaction, run: int | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)

        user_id = str(interaction.user.id)
        active = parse.find_active_session(user_id)
        if active is None:
            embed, files = embeds.error_embed(
                "No current session. Open one with `/sessionbegin` first or `/sessionswitch` to one of your active sessions.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return

        runs = active.get("runs", []) or []
        session_name = active.get("name", "?")

        if not runs:
            embed, files = embeds.error_embed(
                f"Session `{session_name}` has no runs yet.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return

        if run is None:
            target = runs[-1]
        else:
            target = next((r for r in runs if str(r.get("id")) == str(run)), None)
            if target is None:
                embed, files = embeds.error_embed(
                    f"Run `#{run}` not found in session `{session_name}`.",
                    icon=embeds.ICON_NAMES["error"],
                )
                await interaction.followup.send(embed=embed, files=files, ephemeral=True)
                return

        run_id = str(target.get("id", "?"))
        if target.get("aggregated_score") is None:
            embed, files = embeds.error_embed(
                f"Run `#{run_id}` has no grading yet — try `/sweep mode:regrade`.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return

        all_embeds, _ = embeds.transcript_embeds(
            target,
            session_name=session_name,
            session_id=str(active.get("id", "?")),
        )
        groups = embeds.split_embeds_for_messages(all_embeds)
        embeds.finalize_footer(groups)
        for group in groups:
            files = embeds.rebuild_files_for_embeds(group)
            await interaction.followup.send(embeds=group, files=files, ephemeral=True)
