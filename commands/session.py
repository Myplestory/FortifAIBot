from __future__ import annotations

from typing import Any

import discord
from discord import app_commands

import embeds
import generate
import parse

from commands.confirm import ask_confirm
from util import split_csv


BAND_CHOICES = [
    app_commands.Choice(name="B1 Foundational", value="B1"),
    app_commands.Choice(name="B2 Developing", value="B2"),
    app_commands.Choice(name="B3 Competent", value="B3"),
    app_commands.Choice(name="B4 Proficient", value="B4"),
    app_commands.Choice(name="B5 Expert", value="B5"),
]


def _build_session_rollup(
    session: dict[str, Any],
) -> tuple[discord.Embed, list[discord.File]] | None:
    runs = session.get("runs", []) or []
    remediation: list[tuple[str, dict[str, Any]]] = []
    growth: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    any_graded = False
    for r in runs:
        for wrap in r.get("questions", []) or []:
            for _, qrec in wrap.items():
                lit = qrec.get("literature") or []
                if lit:
                    any_graded = True
                for entry in lit:
                    key = entry.get("url") or f"{entry.get('title', '')}|{entry.get('section', '')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    bucket = growth if entry.get("type") == "growth" else remediation
                    bucket.append((str(r.get("id", "?")), entry))
    if not any_graded:
        return None
    return embeds.session_rollup_embed(
        session_id=session.get("id", "?"),
        duration=session.get("duration", "—"),
        runs_count=len(runs),
        remediation=remediation,
        growth=growth,
    )


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="sessionbegin", description="Open a named knowledge hardening session.")
    @app_commands.describe(
        name="Unique session identifier (e.g. interview-prep, fintech-research). Required.",
        band="Primary evaluation band; defaults to B3.",
        industry="Default industry for this session's quizzes (e.g. swe).",
        fields="Comma-separated default field slugs for this session.",
        topics="Comma-separated default topic slugs to bias toward.",
        domain="Default business domain to frame scenarios in.",
        stack="Comma-separated default tech stack to ground scenarios in.",
    )
    @app_commands.choices(band=BAND_CHOICES)
    async def sessionbegin(
        interaction: discord.Interaction,
        name: str,
        band: app_commands.Choice[str] | None = None,
        industry: str | None = None,
        fields: str | None = None,
        topics: str | None = None,
        domain: str | None = None,
        stack: str | None = None,
    ):
        user_id = str(interaction.user.id)
        name = (name or "").strip()
        if not name:
            embed, files = embeds.error_embed(
                "Session `name` is required and cannot be blank.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        if parse.find_active_session(user_id, name=name) is not None:
            embed, files = embeds.error_embed(
                f"You already have an active session named `{name}`. Pick a different name or close the existing one with `/sessionend name:{name}`.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        band_value = (band.value if band else "B3")

        # Validate scope defaults before showing the confirm dialog.
        industry_value = (industry or "").strip() or None
        if industry_value is not None:
            valid_industries = generate.list_industries()
            if industry_value not in valid_industries:
                valid_str = ", ".join(f"`{i}`" for i in valid_industries) or "(none — add a directory under templates/)"
                embed, files = embeds.error_embed(
                    f"Unknown industry `{industry_value}`. Valid: {valid_str}.",
                    icon=embeds.ICON_NAMES["error"],
                )
                await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
                return
        fields_list = split_csv(fields)
        bad_fields = [f for f in fields_list if f not in parse.CANONICAL_FIELDS]
        if bad_fields:
            valid_str = ", ".join(f"`{k}`" for k in parse.CANONICAL_FIELDS.keys())
            embed, files = embeds.error_embed(
                f"Unknown fields: {', '.join(bad_fields)}. Valid fields: {valid_str}.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        topics_list = split_csv(topics)
        stack_list = split_csv(stack)
        domain_value = (domain or "").strip() or None
        quiz_defaults = parse._clean_quiz_defaults({
            "industry": industry_value,
            "fields": fields_list,
            "topics": topics_list,
            "domain": domain_value,
            "stack": stack_list,
        })

        scope_lines: list[str] = []
        if quiz_defaults.get("industry"):
            scope_lines.append(f"industry: **`{quiz_defaults['industry']}`**")
        if quiz_defaults.get("fields"):
            scope_lines.append("fields: " + ", ".join(f"`{x}`" for x in quiz_defaults["fields"]))
        if quiz_defaults.get("topics"):
            scope_lines.append("topics: " + ", ".join(f"`{x}`" for x in quiz_defaults["topics"]))
        if quiz_defaults.get("domain"):
            scope_lines.append(f"domain: **`{quiz_defaults['domain']}`**")
        if quiz_defaults.get("stack"):
            scope_lines.append("stack: " + ", ".join(f"`{x}`" for x in quiz_defaults["stack"]))
        scope_blurb = ("\nDefaults: " + "; ".join(scope_lines) + ".") if scope_lines else ""

        confirmed = await ask_confirm(
            interaction,
            action="Start session",
            detail=f"Open session **`{name}`** with band preference **{band_value}**.{scope_blurb}",
            icon=embeds.ICON_NAMES["sessionbegin"],
        )
        if not confirmed:
            embed, files = embeds.info_embed("Cancelled", "No session was created.", icon=embeds.ICON_NAMES["sessionbegin"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        try:
            record = parse.create_session(
                user_id,
                interaction.user.display_name,
                name,
                band_value,
                quiz_defaults=quiz_defaults or None,
            )
        except ValueError as e:
            embed, files = embeds.error_embed(str(e), icon=embeds.ICON_NAMES["error"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        active_count = len(parse.list_active_sessions(user_id))
        success_msg = (
            f"Session **`{name}`** (id `{record['id']}`) is open and set as **current**. "
            f"You now have **{active_count}** active session(s). "
        )
        if scope_lines:
            success_msg += "Quiz defaults will apply when `/knowledgeharden` is run with no overrides. "
        success_msg += "Run `/knowledgeharden` to begin a quiz, or `/sessionswitch` to change the current pointer."
        embed, files = embeds.info_embed(
            "Session started",
            success_msg,
            icon=embeds.ICON_NAMES["sessionbegin"],
        )
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    @sessionbegin.autocomplete("industry")
    async def _sessionbegin_industry_autocomplete(interaction: discord.Interaction, current: str):
        current_low = (current or "").lower()
        return [
            app_commands.Choice(name=i, value=i)
            for i in generate.list_industries()
            if current_low in i.lower()
        ][:25]

    @tree.command(name="sessionend", description="End an active session (current by default).")
    @app_commands.describe(name="Session name to close. Defaults to your current session.")
    async def sessionend(interaction: discord.Interaction, name: str | None = None):
        user_id = str(interaction.user.id)
        target = parse.find_active_session(user_id, name=name)
        if not target:
            msg = (
                f"No active session named `{name}`."
                if name is not None
                else "No current session to end. Use `/sessionlist active` to see your sessions, or `/sessionswitch` to pick one."
            )
            embed, files = embeds.error_embed(msg, icon=embeds.ICON_NAMES["error"])
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        target_name = target.get("name", "default")
        confirmed = await ask_confirm(
            interaction,
            action="End session",
            detail=f"Close session **`{target_name}`** (id `{target['id']}`, {len(target.get('runs', []))} run(s)).",
            icon=embeds.ICON_NAMES["sessionend"],
        )
        if not confirmed:
            embed, files = embeds.info_embed("Cancelled", "Session left open.", icon=embeds.ICON_NAMES["sessionend"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        closed = parse.end_session(user_id, name=target_name)
        if closed is None:
            embed, files = embeds.error_embed("Session was already closed.", icon=embeds.ICON_NAMES["error"])
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return
        new_current = parse.get_current_session_name(user_id)
        next_hint = (
            f" Current is now **`{new_current}`**." if new_current
            else " You have no current session — use `/sessionswitch` or `/sessionbegin`."
        )
        embed, files = embeds.info_embed(
            "Session ended",
            f"Session **`{target_name}`** closed after {closed.get('duration', '—')} with {len(closed.get('runs', []))} run(s).{next_hint}",
            icon=embeds.ICON_NAMES["sessionend"],
        )
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

        rollup = _build_session_rollup(closed)
        if rollup is not None:
            rollup_embed, rollup_files = rollup
            await interaction.followup.send(embed=rollup_embed, files=rollup_files, ephemeral=True)

    @tree.command(name="sessionswitch", description="Switch your current pointer to another active session.")
    @app_commands.describe(name="Name of the active session to make current.")
    async def sessionswitch(interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        name = (name or "").strip()
        if not name:
            embed, files = embeds.error_embed("Session `name` is required.", icon=embeds.ICON_NAMES["error"])
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        target = parse.switch_session(user_id, name)
        if target is None:
            actives = [s.get("name", "?") for s in parse.list_active_sessions(user_id)]
            valid = ", ".join(f"`{n}`" for n in actives) or "_(none — open one with `/sessionbegin`)_"
            embed, files = embeds.error_embed(
                f"No active session named `{name}`. Active: {valid}.",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        embed, files = embeds.info_embed(
            "Switched session",
            f"Current is now **`{name}`** (id `{target['id']}`, band **{target.get('band_preference', '—')}**, {len(target.get('runs', []))} run(s)).",
            icon=embeds.ICON_NAMES["sessionswitch"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)

    @sessionswitch.autocomplete("name")
    async def _sessionswitch_name_autocomplete(interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        current_low = (current or "").lower()
        return [
            app_commands.Choice(name=s.get("name", "?"), value=s.get("name", "?"))
            for s in parse.list_active_sessions(user_id)
            if current_low in (s.get("name") or "").lower()
        ][:25]

    @sessionend.autocomplete("name")
    async def _sessionend_name_autocomplete(interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        current_low = (current or "").lower()
        return [
            app_commands.Choice(name=s.get("name", "?"), value=s.get("name", "?"))
            for s in parse.list_active_sessions(user_id)
            if current_low in (s.get("name") or "").lower()
        ][:25]

    sessionlist_group = app_commands.Group(name="sessionlist", description="List your sessions (active or closed).")

    @sessionlist_group.command(name="active", description="List your active sessions.")
    async def sessionlist_active(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        actives = parse.list_active_sessions(user_id)
        current = parse.get_current_session_name(user_id)
        if not actives:
            embed, files = embeds.info_embed(
                "No active sessions",
                "Open one with `/sessionbegin name:<unique>`.",
                icon=embeds.ICON_NAMES["sessionlist"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        fields_listed: list[tuple[str, str, bool]] = []
        for s in actives:
            nm = s.get("name", "?")
            marker = "  ← current" if nm == current else ""
            body = (
                f"id `{s.get('id')}` · band **{s.get('band_preference', '—')}** · "
                f"runs **{len(s.get('runs', []))}** · started `{s.get('start', '—')}`"
            )
            qd = s.get("quiz_defaults") or {}
            scope_bits: list[str] = []
            if qd.get("industry"):
                scope_bits.append(f"industry `{qd['industry']}`")
            if qd.get("fields"):
                scope_bits.append("fields " + ",".join(f"`{x}`" for x in qd["fields"]))
            if qd.get("topics"):
                scope_bits.append("topics " + ",".join(f"`{x}`" for x in qd["topics"]))
            if qd.get("domain"):
                scope_bits.append(f"domain `{qd['domain']}`")
            if qd.get("stack"):
                scope_bits.append("stack " + ",".join(f"`{x}`" for x in qd["stack"]))
            if scope_bits:
                body += "\nDefaults: " + " · ".join(scope_bits)
            fields_listed.append((f"`{nm}`{marker}", body, False))
        embed, files = embeds.build(
            title="Active sessions",
            description=f"You have **{len(actives)}** active session(s). Switch with `/sessionswitch name:<name>`.",
            fields=fields_listed,
            icon=embeds.ICON_NAMES["sessionlist"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)

    @sessionlist_group.command(name="closed", description="List your closed sessions.")
    async def sessionlist_closed(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        closed_records = parse.list_completed_for_user(user_id)
        if not closed_records:
            embed, files = embeds.info_embed(
                "No closed sessions",
                "Closed sessions are archived to `sessions/` once `/sessionend` runs.",
                icon=embeds.ICON_NAMES["sessionlist"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        fields_listed: list[tuple[str, str, bool]] = []
        for s in closed_records[-25:]:  # cap at 25 (Discord field max)
            nm = s.get("name") or "_(unnamed)_"
            body = (
                f"id `{s.get('id')}` · band **{s.get('band_preference', '—')}** · "
                f"runs **{len(s.get('runs', []))}** · duration **{s.get('duration', '—')}** · "
                f"closed `{s.get('end', '—')}`"
            )
            fields_listed.append((f"`{nm}`", body, False))
        embed, files = embeds.build(
            title="Closed sessions",
            description=f"You have **{len(closed_records)}** closed session(s). Showing the {len(fields_listed)} most recent.",
            fields=fields_listed,
            icon=embeds.ICON_NAMES["sessionlist"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)

    tree.add_command(sessionlist_group)

    @tree.command(name="sessionrestore", description="Bring a closed session back to active under a new name.")
    @app_commands.describe(
        id="Session id (from `/sessionlist closed`).",
        name="Active name to restore under (must be unique among your active sessions).",
    )
    async def sessionrestore(interaction: discord.Interaction, id: str, name: str):
        user_id = str(interaction.user.id)
        name = (name or "").strip()
        if not name:
            embed, files = embeds.error_embed("`name` is required.", icon=embeds.ICON_NAMES["error"])
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        try:
            rec = parse.restore_session(user_id, id, name)
        except ValueError as e:
            embed, files = embeds.error_embed(str(e), icon=embeds.ICON_NAMES["error"])
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        embed, files = embeds.info_embed(
            "Session restored",
            (
                f"Closed session `{id}` is now active as **`{name}`** (current). "
                f"It has **{len(rec.get('runs', []))}** run(s). Resume with `/knowledgeharden`."
            ),
            icon=embeds.ICON_NAMES["sessionswitch"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)

    @sessionrestore.autocomplete("id")
    async def _sessionrestore_id_autocomplete(interaction: discord.Interaction, current: str):
        user_id = str(interaction.user.id)
        current_low = (current or "").lower()
        return [
            app_commands.Choice(
                name=f"{s.get('name') or '(unnamed)'} · {s.get('id', '?')}"[:100],
                value=str(s.get("id", "")),
            )
            for s in parse.list_completed_for_user(user_id)
            if current_low in (s.get("id") or "").lower() or current_low in (s.get("name") or "").lower()
        ][:25]
