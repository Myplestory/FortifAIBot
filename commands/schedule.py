from __future__ import annotations

import logging
from typing import Awaitable, Callable

import discord
from discord import app_commands

import embeds
import scheduler

from commands.confirm import ask_confirm


log = logging.getLogger(__name__)


def register(tree: app_commands.CommandTree) -> None:
    schedule_group = app_commands.Group(name="schedule", description="Recurring reminders to take a quiz.")

    @schedule_group.command(name="add", description="Add a recurring reminder.")
    @app_commands.describe(cadence="How often to fire.", time="Local time as HH:MM (24h UTC).")
    @app_commands.choices(cadence=[
        app_commands.Choice(name="Daily", value="daily"),
        app_commands.Choice(name="Every other day", value="every-other-day"),
        app_commands.Choice(name="Weekly (Mondays)", value="weekly"),
    ])
    async def schedule_add(
        interaction: discord.Interaction,
        cadence: app_commands.Choice[str],
        time: str,
    ):
        confirmed = await ask_confirm(
            interaction,
            action="Add schedule",
            detail=f"Create a `{cadence.name}` reminder at **{time} UTC**.",
            icon=embeds.ICON_NAMES["schedule"],
        )
        if not confirmed:
            embed, files = embeds.info_embed("Cancelled", "No schedule added.", icon=embeds.ICON_NAMES["schedule"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        try:
            job_id = scheduler.add(interaction.user.id, cadence.value, time)
        except ValueError as e:
            embed, files = embeds.error_embed(str(e), icon=embeds.ICON_NAMES["schedule"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        embed, files = embeds.info_embed(
            "Schedule added",
            f"Job `{job_id}` will fire on cadence **{cadence.name}** at **{time} UTC**.",
            icon=embeds.ICON_NAMES["schedule"],
        )
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    @schedule_group.command(name="list", description="List your active schedules.")
    async def schedule_list(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        rows = scheduler.list_for_user(interaction.user.id)
        if not rows:
            embed, files = embeds.info_embed("No schedules", "Use `/schedule add` to create one.", icon=embeds.ICON_NAMES["schedule"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        fields_listed: list[tuple[str, str, bool]] = []
        for r in rows:
            fields_listed.append((f"Job `{r['id']}`", f"Next: `{r['next_run'] or '—'}`\nTrigger: `{r['trigger']}`", False))
        embed, files = embeds.build(
            title="Schedules",
            description=f"{len(rows)} active job(s).",
            fields=fields_listed,
            icon=embeds.ICON_NAMES["schedule"],
        )
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    @schedule_group.command(name="remove", description="Remove a schedule by id.")
    @app_commands.describe(id="Job id from /schedule list.")
    async def schedule_remove(interaction: discord.Interaction, id: str):
        confirmed = await ask_confirm(
            interaction,
            action="Remove schedule",
            detail=f"Delete job `{id}`.",
            icon=embeds.ICON_NAMES["schedule"],
        )
        if not confirmed:
            embed, files = embeds.info_embed("Cancelled", "Schedule not removed.", icon=embeds.ICON_NAMES["schedule"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        ok = scheduler.remove(interaction.user.id, id)
        if not ok:
            embed, files = embeds.error_embed(f"Job `{id}` not found.", icon=embeds.ICON_NAMES["schedule"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        embed, files = embeds.info_embed("Schedule removed", f"Job `{id}` deleted.", icon=embeds.ICON_NAMES["schedule"])
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    tree.add_command(schedule_group)


def make_on_schedule_fire(bot: discord.Client) -> Callable[[int, str], Awaitable[None]]:
    """Return the scheduler fire callback, closed over `bot`. main.py wires
    this into `scheduler.start(...)` from `on_ready` once the client is
    connected.
    """
    async def _on_schedule_fire(user_id: int, job_id: str) -> None:
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.HTTPException:
                log.warning("scheduler fire: cannot resolve user %s", user_id)
                return
        embed, files = embeds.info_embed(
            "Time for a knowledge harden",
            "Open a session with `/sessionbegin`, then run `/knowledgeharden` to begin.",
            icon=embeds.ICON_NAMES["knowledgeharden"],
        )
        try:
            await user.send(embed=embed, files=files)
        except discord.Forbidden:
            log.warning("user %s has DMs disabled; cannot deliver schedule fire", user_id)

    return _on_schedule_fire
