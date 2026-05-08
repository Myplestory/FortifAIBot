from __future__ import annotations

import discord
from discord import app_commands

import embeds
import parse


# Aligned with templates/dreyfus.md + templates/swe/score.md.
# Industry ladder mappings cross-referenced against:
#   - templates/swe/score.md L68 (Google L3–L5+ → bands)
#   - levels.fyi consensus (Google/Meta/Amazon/Uber leveling, public data)
#   - the user-shared feature matrix v3.0 (B3=L4/E4/SDE-2, B4=L5/E5/SDE-3,
#     B5=L6+/E6+/Principal)
# Bands B1 and B2 sit *within* a single industry rung (Google L3 / Meta E3 /
# Amazon L4) — the Dreyfus + SWECOM/SFIA distinction differentiates within
# that rung (intern/pre-shipping vs. shipping with supervision).
#
# Each row: band, project label (matches BAND_CHOICES in commands/session.py),
# Dreyfus stage, SWECOM level, SFIA level, industry-ladder mapping with YOE,
# one-line behavioral description.
_BAND_LADDER: list[tuple[str, str, str, str, str, str, str]] = [
    ("B1",
     "Foundational",
     "Novice",
     "L1 Technician",
     "L1 Follow",
     "Google L3 (early) / Meta E3 (early) / Amazon L4 (early SDE-I) · ~0–1 YOE",
     "Follows context-free rules; cannot exercise discretionary judgment. Needs close direction."),
    ("B2",
     "Developing",
     "Advanced Beginner",
     "L2 Entry Practitioner",
     "L2 Assist",
     "Google L3 (late) / Meta E3 (late) / Amazon L4 (SDE-I) · ~1–2 YOE",
     "Recognizes patterns from facts; ships with supervision; limited discretion in unfamiliar work."),
    ("B3",
     "Competent",
     "Competent",
     "L3 Experienced Practitioner",
     "L3 Apply",
     "Google L4 / Meta E4 / Amazon L5 (SDE-II) / Uber L4 · ~2–5 YOE",
     "Conscious deliberate planning; little/no supervision; complex non-routine work via standard methods."),
    ("B4",
     "Proficient",
     "Proficient",
     "L4 Technical Leader",
     "L4 Enable",
     "Google L5 / Meta E5 / Amazon L6 (Senior SDE / SDE-III) / Uber L5 · ~5–8 YOE",
     "Intuitive in familiar contexts; substantial autonomy; leads/directs others within a skill area."),
    ("B5",
     "Expert",
     "Expert",
     "L5 Senior SW Engineer",
     "L5 Ensure/Advise",
     "Google L6+ / Meta E6+ / Amazon L7 (Principal) / Uber Staff (L5b/L6) · ~8+ YOE",
     "Fluid intuitive performance; creates new processes; sets organizational direction."),
]


# Score (1–5) → career_level keyword used by the grader (templates/swe/grader.md).
# Half-band tolerance, matching the per-band-ceiling inference rule.
def _score_to_keyword(score: float) -> tuple[str, str]:
    """Returns (career_level keyword, Dreyfus stage label)."""
    if score >= 4.5:
        return "expert", "Expert"
    if score >= 3.5:
        return "proficient", "Proficient"
    if score >= 2.5:
        return "competent", "Competent"
    if score >= 1.5:
        return "developing", "Advanced Beginner"
    return "entry", "Novice"


def _interpret(score: float, target_band: str | None, *, inferred_from_run: bool) -> list[tuple[str, str, bool]]:
    keyword, stage = _score_to_keyword(score)
    rows: list[tuple[str, str, bool]] = []

    headline = f"`{score:.1f}` of 5.0 → effective stage **{stage}** (`{keyword}`)"
    if inferred_from_run:
        headline += " · pulled from your latest graded run"
    rows.append(("Aggregate", headline, False))

    if target_band and target_band in parse.VALID_BANDS:
        target_int = int(target_band[1])
        delta = score - target_int
        if abs(delta) < 0.2:
            cal = f"On target — you're delivering at-band performance for **{target_band}**."
        elif delta < 0:
            below = abs(delta)
            cal = (
                f"≈ {below:.1f} band(s) below target **{target_band}**. "
                f"`/transcript` shows the per-band scores per question to locate the drag."
            )
        else:
            cal = (
                f"≈ {delta:.1f} band(s) above target **{target_band}**. Consider raising "
                f"your `/sessionbegin band:` next session for harder questions."
            )
        rows.append(("Calibration vs. target", cal, False))

    rows.append((
        "​",
        "_The `career_level` keyword the grader emits in `/transcript` is the mode of "
        "per-question ceilings — not a direct function of the aggregate. Use this "
        "mapping as an approximation; the transcript is authoritative._",
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
        target_str = target_band.value if target_band else None
        inferred = False

        if score is None:
            user_id = str(interaction.user.id)
            active = parse.find_active_session(user_id)
            if active:
                graded = [r for r in (active.get("runs") or []) if r.get("aggregated_score") is not None]
                if graded:
                    latest = graded[-1]
                    score = float(latest.get("aggregated_score"))
                    if target_str is None:
                        target_str = latest.get("band") or active.get("band_preference")
                    inferred = True

        if score is not None and not (1.0 <= score <= 5.0):
            embed, files = embeds.error_embed(
                f"`score` must be between 1.0 and 5.0 (got `{score}`).",
                icon=embeds.ICON_NAMES["error"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        ladder_fields: list[tuple[str, str, bool]] = []
        for band, label, dreyfus, swecom, sfia, yoe, blurb in _BAND_LADDER:
            body = (
                f"**{label}** · {yoe}\n"
                f"Dreyfus: {dreyfus} · SWECOM {swecom} · SFIA {sfia}\n"
                f"_{blurb}_"
            )
            ladder_fields.append((band, body, False))

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
            "against B**B**'s rubric."
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
                    "How your aggregate maps onto the band ladder above. Per-question and "
                    "per-band breakdowns live in `/transcript`."
                ),
                fields=_interpret(score, target_str, inferred_from_run=inferred),
                icon=embeds.ICON_NAMES["results"],
                footer=None,
            )
            all_embeds.append(interp_embed)
            all_files.extend(interp_files)

        groups = embeds.split_embeds_for_messages(all_embeds)
        embeds.finalize_footer(groups)

        await interaction.response.defer(ephemeral=True, thinking=True)
        for group in groups:
            files = embeds.rebuild_files_for_embeds(group)
            await interaction.followup.send(embeds=group, files=files, ephemeral=True)
