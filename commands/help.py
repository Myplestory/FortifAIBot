from __future__ import annotations

import discord
from discord import app_commands

import embeds


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="help", description="List the bot's slash commands, grouped by category.")
    async def help_cmd(interaction: discord.Interaction):
        categories: list[tuple[str, str, str, list[tuple[str, str]]]] = [
            (
                "Session management",
                "play",
                "Sessions are named, multi-active. Use `/sessionswitch` to flip between them.",
                [
                    ("/sessionbegin name:<unique> [band] [industry] [fields] [topics] [domain] [stack]", "Open a new named session (band default B3). Optional scope args become defaults inherited by `/knowledgeharden` runs in this session."),
                    ("/sessionend [name]", "Close the current session, or the named one. Emits a deduped reading list."),
                    ("/sessionswitch name:<name>", "Set the current pointer to another active session."),
                    ("/sessionlist active", "List your active sessions; current is marked."),
                    ("/sessionlist closed", "List your closed (archived) sessions."),
                    ("/sessionrestore id:<archive-id> name:<unique>", "Bring a closed session back to active under a new name."),
                ],
            ),
            (
                "Knowledge hardening",
                "target",
                "Tunes the quiz to your band, fields, business domain, and tech stack.",
                [
                    (
                        "/knowledgeharden [industry] [fields] [topics] [domain] [stack]",
                        "Run a 5-question quiz in your current session. "
                        "`domain` (fintech, saas, healthcare, …) frames scenarios; "
                        "`stack` (python,django,react,…) tunes concrete tooling. "
                        "Grading runs at the end with 2 pieces of literature per question.",
                    ),
                ],
            ),
            (
                "Stats",
                "chart-column",
                "All scopes default to the current active session.",
                [
                    ("/stats runcount [n]", "Run-scoped stats. n: null/-1=whole session, 1=last run, N=last N."),
                    ("/stats session [n]", "Same scope semantic, framed as session."),
                    ("/stats timeline range:7d|30d|90d|all", "Stats over a recent time range."),
                ],
            ),
            (
                "Analyze",
                "trending-up",
                "Same `n` semantic as /stats.",
                [
                    ("/analyze trends [n]", "Activity trends across runs."),
                    ("/analyze gaps [n]", "Untouched fields and topics."),
                    ("/analyze bias [n]", "Over-indexed fields relative to uniform coverage."),
                    ("/analyze progression [n]", "Per-run aggregated-score trajectory (unlocks at 5 graded runs)."),
                ],
            ),
            (
                "Reference",
                "book-open",
                "Look up the rubric or the field/topic graph.",
                [
                    ("/rubric [field] [topics]", "Framework citations (Dreyfus / SWECOM / SFIA) and SFIA scope."),
                    ("/bands [score] [target_band]", "Explain B1–B5 and what an aggregate score means. No args = interpret your latest run."),
                    ("/directory [industry] [field]", "Industries → fields → topics directory."),
                ],
            ),
            (
                "Housekeeping",
                "trash-2",
                "Cleanup, re-grading, reminders, and this help message.",
                [
                    ("/sweep [mode]", "Sweep abandoned runs, re-grade failed gradings, and heal the meta.json catalog (default: all)."),
                    ("/transcript [run]", "Fetch the grading transcript for a run in the current session (default: latest)."),
                    ("/schedule add|list|remove", "Recurring DM reminders to take a quiz."),
                    ("/help", "This message."),
                ],
            ),
        ]

        all_embeds: list[discord.Embed] = []
        all_files: list[discord.File] = []
        for title, icon_name, subtitle, cmd_pairs in categories:
            fields_listed = [(name, desc, False) for name, desc in cmd_pairs]
            embed, files = embeds.build(
                title=title,
                description=subtitle,
                fields=fields_listed,
                icon=icon_name,
                color=embeds.BLUE_PRIMARY,
                footer=None,  # only the last embed needs the footer
            )
            all_embeds.append(embed)
            all_files.extend(files)
        # Restore the standard footer on the final embed.
        if all_embeds:
            all_embeds[-1].set_footer(text=embeds.DEFAULT_FOOTER)

        await interaction.response.send_message(embeds=all_embeds, files=all_files, ephemeral=True)
