from __future__ import annotations

import io

import discord
from discord import app_commands

import embeds
import parse


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="transcript", description="Fetch the grading transcript (markdown) for a run in the current session.")
    @app_commands.describe(run="Run id within the current session. Omit for the latest run.")
    async def transcript(interaction: discord.Interaction, run: int | None = None):
        user_id = str(interaction.user.id)
        active = parse.find_active_session(user_id)
        if active is None:
            embed, files = embeds.error_embed(
                "No current session. Open one with `/sessionbegin` first or `/sessionswitch` to one of your active sessions.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        runs = active.get("runs", []) or []
        session_name = active.get("name", "?")

        if not runs:
            embed, files = embeds.error_embed(
                f"Session `{session_name}` has no runs yet.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
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
                await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
                return

        run_id = str(target.get("id", "?"))
        md = (target.get("report_markdown") or "").strip()
        if not md:
            embed, files = embeds.error_embed(
                f"Run `#{run_id}` has no grading transcript yet — try `/sweep regrade`.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        buf = io.BytesIO(md.encode("utf-8"))
        filename = f"transcript-{active.get('id', 'session')}-run{run_id}.md"
        transcript_file = discord.File(buf, filename=filename)

        embed, files = embeds.build(
            title="Grading transcript",
            description=f"Session **`{session_name}`** · run `#{run_id}` · attached as `{filename}`.",
            icon=embeds.ICON_NAMES["grading"],
        )
        files.append(transcript_file)
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
