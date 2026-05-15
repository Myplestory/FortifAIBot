from __future__ import annotations

import discord
from discord import app_commands

import embeds
import parse
from phases import band_data


def _interpret(
    score_pre: float,
    target_band: str | None,
    *,
    inferred_from_run: bool,
    score_post: float | None = None,
    assisted_delta: str | None = None,
) -> list[tuple[str, str, bool]]:
    """Render score interpretation rows. After Finding B, the unassisted
    (pre-refinement) score is the headline; the assisted-recovery delta is a
    secondary row when post + delta are available.
    """
    keyword, stage = band_data.score_to_keyword(score_pre)
    rows: list[tuple[str, str, bool]] = []

    headline = f"`{score_pre:.1f}` of 5.0 (unassisted) → effective stage **{stage}** (`{keyword}`)"
    if inferred_from_run:
        headline += " · pulled from your latest graded run"
    rows.append(("Aggregate", headline, False))

    if isinstance(score_post, (int, float)) and assisted_delta:
        rows.append((
            "Assisted recovery",
            f"post `{score_post:.1f}` · Δ {assisted_delta} (improvement attributable to refinement scaffolding)",
            False,
        ))

    if target_band and target_band in parse.VALID_BANDS:
        target_int = int(target_band[1])
        delta = score_pre - target_int
        if abs(delta) < 0.2:
            cal = f"On target — you're delivering at-band performance for **{target_band}** unassisted."
        elif delta < 0:
            below = abs(delta)
            cal = (
                f"≈ {below:.1f} band(s) below target **{target_band}** (unassisted). "
                f"`/transcript` shows the per-band scores per question to locate the drag."
            )
        else:
            cal = (
                f"≈ {delta:.1f} band(s) above target **{target_band}** (unassisted). Consider raising "
                f"your `/sessionbegin band:` next session for harder questions."
            )
        rows.append(("Calibration vs. target", cal, False))

    rows.append((
        "​",
        "_The `career_level` keyword the grader emits in `/transcript` is derived from "
        "the unassisted aggregate (pre-refinement). Use this mapping as an approximation; "
        "the transcript is authoritative._",
        False,
    ))

    return rows


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="bands",
        description="Explain B1–B5, what an aggregate score means, and where you land vs. your target band.",
    )
    @app_commands.describe(
        score="Aggregate score (1.0–5.0) to interpret. Defaults to your latest graded run.",
        target_band="Target band to calibrate against. Defaults to your latest run's band.",
    )
    @app_commands.choices(target_band=[
        app_commands.Choice(name="B1 Foundational", value="B1"),
        app_commands.Choice(name="B2 Developing",   value="B2"),
        app_commands.Choice(name="B3 Competent",    value="B3"),
        app_commands.Choice(name="B4 Proficient",   value="B4"),
        app_commands.Choice(name="B5 Expert",       value="B5"),
    ])
    async def bands(
        interaction: discord.Interaction,
        score: float | None = None,
        target_band: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        target_str = target_band.value if target_band else None
        inferred = False
        score_post: float | None = None
        assisted_delta: str | None = None

        if score is None:
            user_id = str(interaction.user.id)
            active = parse.find_active_session(user_id)
            if active:
                graded = [
                    r for r in (active.get("runs") or [])
                    if r.get("aggregated_score_pre") is not None
                    or r.get("aggregated_score") is not None
                ]
                if graded:
                    latest = graded[-1]
                    # Prefer aggregated_score_pre (Finding B). Legacy runs only have
                    # aggregated_score (post-refinement), so fall back to it.
                    pre_val = latest.get("aggregated_score_pre")
                    score = float(pre_val if pre_val is not None else latest.get("aggregated_score"))
                    post_raw = latest.get("aggregated_score_post")
                    if isinstance(post_raw, (int, float)):
                        score_post = float(post_raw)
                    delta_raw = latest.get("assisted_delta")
                    if isinstance(delta_raw, str):
                        assisted_delta = delta_raw
                    if target_str is None:
                        target_str = latest.get("band") or active.get("band_preference")
                    inferred = True

        if score is not None and not (1.0 <= score <= 5.0):
            embed, files = embeds.error_embed(
                f"`score` must be between 1.0 and 5.0 (got `{score}`).",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.followup.send(embed=embed, files=files, ephemeral=True)
            return

        ladder_fields: list[tuple[str, str, bool]] = []
        for band_id, row in band_data.load_band_mappings().bands.items():
            yoe_str = f"{row.industry_ladder} · ~{row.yoe_range} YOE"
            body = (
                f"**{row.label}** · {yoe_str}\n"
                f"Dreyfus: {row.dreyfus.stage} · SWECOM {row.swecom.level} {row.swecom.title} · "
                f"SFIA {row.sfia.level} ({row.sfia.label})\n"
                f"_{row.blurb}_"
            )
            ladder_fields.append((band_id, body, False))

        ladder_fields.append((
            "Sources",
            (
                "Dreyfus & Dreyfus (1980, rev. 2021) skill-stage taxonomy · "
                "IEEE SWECOM (2014, aligned with SWEBOK v3.0 / ISO/IEC TR 19759:2015) · "
                "SFIA v9 (Oct 2024). Industry ladder rungs cross-referenced against "
                "publicly published Google/Meta/Amazon/Uber leveling guides (levels.fyi "
                "consensus). YOE ranges are nominal — actual progression varies by "
                "calibration cycle and individual."
            ),
            False,
        ))

        ladder_embed, ladder_files = embeds.build(
            title="Bands & career-level reference",
            description=(
                "B1–B5 align Dreyfus skill stages with two industry frameworks (IEEE SWECOM, "
                "SFIA v9) and major engineering ladders. Each band has a **career-level "
                "keyword** the grader emits in your transcript: "
                "`entry · developing · competent · proficient · expert`."
            ),
            fields=ladder_fields,
            icon=embeds.ICON_NAMES["grading"],
            footer=None,
        )

        scale_fields: list[tuple[str, str, bool]] = [
            ("5 — At-band",          "Mastered the band's expectations. Aggregate ≥4.5 → `expert` keyword.", False),
            ("4 — Nearly at-band",   "Solid at the band; occasional fallback to one stage below. → `proficient`.", False),
            ("3 — One band below",   "Demonstrating the prior stage's strength against this band's rubric. → `competent`.", False),
            ("2 — Two bands below",  "Recall is partial; needs scaffolding. → `developing`.", False),
            ("1 — Entry/novice",     "Effectively rules-only at this band. → `entry`.", False),
        ]

        scale_desc = (
            "Each question is scored against **all 5 bands**. Your *aggregate* is the mean "
            "of the 5 question scores at your **primary** (target) band. Score N at band B "
            "means you delivered at the level of a B**N**-strength practitioner being measured "
            "against B**B**'s rubric.\n\n"
            "_The aggregate and any score deltas are an **operational trend summary** — a "
            "study signal for where to point your next session, not a psychometric interval "
            "estimate and not a measurement of competence. Treat movement as direction, not "
            "magnitude._"
        )

        scale_embed, scale_files = embeds.build(
            title="Score scale (1–5)",
            description=scale_desc,
            fields=scale_fields,
            icon=embeds.ICON_NAMES["grading"],
            footer=None,
        )

        all_embeds: list[discord.Embed] = [ladder_embed, scale_embed]
        all_files: list[discord.File] = [*ladder_files, *scale_files]

        if score is not None:
            interp_embed, interp_files = embeds.build(
                title="Score interpretation",
                description=(
                    "How your unassisted aggregate maps onto the band ladder above. "
                    "Per-question and per-band breakdowns live in `/transcript`."
                ),
                fields=_interpret(
                    score,
                    target_str,
                    inferred_from_run=inferred,
                    score_post=score_post,
                    assisted_delta=assisted_delta,
                ),
                icon=embeds.ICON_NAMES["results"],
                footer=None,
            )
            all_embeds.append(interp_embed)
            all_files.extend(interp_files)

        groups = embeds.split_embeds_for_messages(all_embeds)
        embeds.finalize_footer(groups)

        for group in groups:
            files = embeds.rebuild_files_for_embeds(group)
            await interaction.followup.send(embeds=group, files=files, ephemeral=True)
