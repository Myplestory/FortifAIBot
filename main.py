from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import generate
import parse
import scheduler
from commands import (
    analyze as analyze_cmd,
    bands as bands_cmd,
    directory as directory_cmd,
    help as help_cmd,
    knowledgeharden as knowledgeharden_cmd,
    rubric as rubric_cmd,
    schedule as schedule_cmd,
    session as session_cmd,
    stats as stats_cmd,
    sweep as sweep_cmd,
    transcript as transcript_cmd,
)

load_dotenv()
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fortifai")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.dm_messages = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# --- extracted command modules --------------------------------------------


transcript_cmd.register(tree)
analyze_cmd.register(tree)
stats_cmd.register(tree)
session_cmd.register(tree)
help_cmd.register(tree)
rubric_cmd.register(tree)
bands_cmd.register(tree)
directory_cmd.register(tree)
schedule_cmd.register(tree)
sweep_cmd.register(tree)
knowledgeharden_cmd.register(tree, bot)


# --- lifecycle -------------------------------------------------------------


@bot.event
async def on_ready():
    log.info("logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
    parse.ensure_runtime_dirs()
    parse.seed_meta_if_empty()
    industries = generate.list_industries()
    log.info("industries available: %s", industries or "(none)")
    for industry in industries:
        if not parse.grader_available(industry):
            log.warning(
                "templates/%s/grader_question.md is missing or empty — grading unavailable for this industry.",
                industry,
            )
    scheduler.start(asyncio.get_running_loop(), schedule_cmd.make_on_schedule_fire(bot))

    # Slash command sync. Global syncs propagate over up to ~1 hour, which
    # makes development frustrating when a parameter list changes. If
    # DEV_GUILD_ID is set, we copy the global tree into that guild and sync
    # there too — guild-scoped commands appear immediately.
    dev_guild_id = os.environ.get("DEV_GUILD_ID", "").strip()
    try:
        synced_global = await tree.sync()
        log.info(
            "synced %d global slash commands: %s",
            len(synced_global),
            ", ".join(sorted(c.name for c in synced_global)),
        )
        if dev_guild_id:
            try:
                guild = discord.Object(id=int(dev_guild_id))
            except ValueError:
                log.warning("DEV_GUILD_ID=%r is not a valid integer; skipping guild sync", dev_guild_id)
            else:
                tree.copy_global_to(guild=guild)
                synced_guild = await tree.sync(guild=guild)
                log.info(
                    "synced %d slash commands to guild %s (instant): %s",
                    len(synced_guild),
                    dev_guild_id,
                    ", ".join(sorted(c.name for c in synced_guild)),
                )
    except discord.HTTPException as e:
        log.error("command sync failed: %s", e)


@bot.event
async def on_disconnect():
    log.info("bot disconnected")


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set.")
    parse.ensure_runtime_dirs()
    parse.seed_meta_if_empty()
    bot.run(token)


if __name__ == "__main__":
    main()
