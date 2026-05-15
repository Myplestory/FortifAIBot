from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands

import embeds
import generate
import parse


_SWEEP_MODES = [
    app_commands.Choice(name="All — cleanup + regrade + catalog (recommended)", value="all"),
    app_commands.Choice(name="Cleanup only — drop runs with no answers", value="cleanup"),
    app_commands.Choice(name="Regrade only — re-run grading on failed runs", value="regrade"),
    app_commands.Choice(name="Regrade last — force re-grade the latest run (even if already graded)", value="regrade-last"),
    app_commands.Choice(name="Catalog only — heal meta.json from your run history", value="catalog"),
]


async def _regrade_one(user_id: str, session_id: str, run: dict[str, Any], session: dict[str, Any]) -> tuple[bool, str]:
    run_industry = (run.get("industry") or "swe").lower()
    run_band = run.get("band") or session.get("band_preference", "B3")
    if not parse.grader_available(run_industry):
        return False, f"grader template missing for industry `{run_industry}`"
    # Fix B/D: comparison points + entry_state are extracted from the runs
    # chronologically up to this one, so regrading a mid-history run still
    # compares backward and the coherence gradient measures only that window.
    entry_state = generate.build_entry_state(session, run_band, str(run.get("id")))
    comparison_points = generate.build_comparison_points(session, run_band, str(run.get("id")))
    try:
        grading = await asyncio.to_thread(
            generate.grade,
            industry=run_industry,
            answerer_band=run_band,
            current_run=run,
            entry_state=entry_state,
            comparison_points=comparison_points,
        )
    except generate.GradingError as e:
        return False, str(e)
    parse.apply_grading(user_id, session_id, str(run["id"]), grading)
    parse.apply_meta_updates(grading.get("meta_updates") or {})
    return True, ""


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="sweep", description="Sweep abandoned runs, re-grade failed gradings, and heal the meta.json catalog.")
    @app_commands.describe(mode="cleanup, regrade, regrade-last, catalog, or all. Default: all.")
    @app_commands.choices(mode=_SWEEP_MODES)
    async def sweep(interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None):
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
        session_id = str(active["id"])

        chosen = mode.value if mode is not None else "all"
        do_cleanup = chosen in ("cleanup", "all")
        do_regrade = chosen in ("regrade", "all")
        do_catalog = chosen in ("catalog", "all")
        # regrade-last is mutually exclusive with the other modes — it's a force
        # re-grade of the latest run regardless of existing grading state, used
        # to apply prompt/template changes to a previously-graded run.
        do_regrade_last = chosen == "regrade-last"

        cleaned_ids: list[str] = []
        if do_cleanup:
            cleaned_ids = parse.cleanup_abandoned_runs(user_id, session_id=session_id)

        regraded_ids: list[str] = []
        failed_regrades: list[tuple[str, str]] = []
        skipped_count = 0
        if do_regrade:
            active_after = parse.find_active_session_by_id(user_id, session_id) or {}
            targets = parse.runs_needing_grading(user_id, session_id=session_id)
            skipped_count = len([
                r for r in (active_after.get("runs", []) or [])
                if r.get("status") == "complete" and r.get("aggregated_score") is None
                and not parse._run_has_any_response(r)
            ])
            for r in targets:
                ok, err = await _regrade_one(user_id, session_id, r, active_after)
                if ok:
                    regraded_ids.append(str(r.get("id", "?")))
                else:
                    failed_regrades.append((str(r.get("id", "?")), err))

        # Force re-grade of the latest run, regardless of prior grading state.
        # Mutually exclusive with do_regrade above.
        force_regrade_body: str | None = None
        force_regrade_failed = False
        if do_regrade_last:
            active_after = parse.find_active_session_by_id(user_id, session_id) or {}
            runs = active_after.get("runs", []) or []
            if not runs:
                force_regrade_body = "_No runs in this session to regrade._"
            else:
                latest = runs[-1]
                latest_id = str(latest.get("id", "?"))
                if latest.get("status") != "complete":
                    force_regrade_body = (
                        f"⚠️ Latest run `#{latest_id}` is not complete "
                        f"(status `{latest.get('status', '?')}`)."
                    )
                    force_regrade_failed = True
                elif not parse._run_has_any_response(latest):
                    force_regrade_body = f"⚠️ Latest run `#{latest_id}` has no responses to grade."
                    force_regrade_failed = True
                else:
                    ok, err = await _regrade_one(user_id, session_id, latest, active_after)
                    if ok:
                        # Chain into catalog: deterministic meta.json heal from
                        # full run history. The grader's `meta_updates` is
                        # LLM-judged and can be empty even after a successful
                        # regrade; heal_meta_from_user_runs guarantees the
                        # field/topic catalog reflects every persisted run.
                        cat = await asyncio.to_thread(parse.heal_meta_from_user_runs, user_id)
                        runs_n = cat["runs_processed"]
                        fields_added = cat["fields_added"]
                        topics_added = cat["topics_added_total"]
                        if not fields_added and topics_added == 0:
                            cat_line = f" Catalog walked **{runs_n}** run(s); meta.json already in sync."
                        else:
                            parts = [f" Catalog walked **{runs_n}** run(s)."]
                            if fields_added:
                                parts.append(f"Added field(s): {', '.join(f'`{f}`' for f in fields_added)}.")
                            if topics_added:
                                parts.append(f"Added **{topics_added}** new topic(s).")
                            cat_line = " ".join(parts)
                        force_regrade_body = (
                            f"✅ Re-graded run `#{latest_id}` (forced; previous grading state ignored)."
                            f"\n{cat_line}"
                        )
                    else:
                        force_regrade_body = f"⚠️ Re-grade failed for run `#{latest_id}` — {err}"
                        force_regrade_failed = True

        catalog_summary: dict[str, Any] | None = None
        if do_catalog:
            catalog_summary = await asyncio.to_thread(parse.heal_meta_from_user_runs, user_id)

        fields_listed: list[tuple[str, str, bool]] = []

        if do_cleanup:
            if cleaned_ids:
                body = f"Removed **{len(cleaned_ids)}** run(s): {', '.join(f'`#{i}`' for i in cleaned_ids)}"
            else:
                body = "_No abandoned runs found._"
            fields_listed.append(("🧹 Cleanup", body, False))

        if do_regrade:
            body_lines: list[str] = []
            if regraded_ids:
                body_lines.append(f"✅ Re-graded **{len(regraded_ids)}** run(s): {', '.join(f'`#{i}`' for i in regraded_ids)}")
            if failed_regrades:
                body_lines.append(
                    "⚠️ Still failing:\n"
                    + "\n".join(f"  • `#{rid}` — {err}" for rid, err in failed_regrades)
                )
            if skipped_count and do_cleanup is False:
                body_lines.append(f"ℹ️ Skipped {skipped_count} ungraded run(s) with no responses (run `cleanup` to drop them).")
            if not body_lines:
                body_lines.append("_No runs needed re-grading._")
            fields_listed.append(("♻️ Regrade", "\n".join(body_lines), False))

        if do_regrade_last and force_regrade_body is not None:
            fields_listed.append(("♻️ Regrade last", force_regrade_body, False))

        if do_catalog and catalog_summary is not None:
            runs_n = catalog_summary["runs_processed"]
            fields_added = catalog_summary["fields_added"]
            topics_added = catalog_summary["topics_added_total"]
            if runs_n == 0:
                body = "_No runs found to heal from._"
            elif not fields_added and topics_added == 0:
                body = f"Walked **{runs_n}** run(s); meta.json already in sync."
            else:
                parts = [f"Walked **{runs_n}** run(s)."]
                if fields_added:
                    parts.append(f"Added field(s): {', '.join(f'`{f}`' for f in fields_added)}.")
                if topics_added:
                    parts.append(f"Added **{topics_added}** new topic(s) across canonical fields.")
                body = " ".join(parts)
            fields_listed.append(("📚 Catalog", body, False))

        any_failure = bool(failed_regrades) or force_regrade_failed
        color = embeds.OK_GREEN if not any_failure else embeds.WARN_AMBER
        regrade_only = (
            (do_regrade and not do_cleanup and not do_catalog and not do_regrade_last)
            or do_regrade_last
        )
        icon = embeds.ICON_NAMES["regrade"] if regrade_only else embeds.ICON_NAMES["sweep"]
        embed, files = embeds.build(
            title="Housekeeping complete",
            description=f"Mode: **{chosen}** · session **`{active.get('name', '?')}`** (id `{active.get('id', '?')}`).",
            fields=fields_listed,
            icon=icon,
            color=color,
        )
        await interaction.followup.send(embed=embed, files=files, ephemeral=True)
