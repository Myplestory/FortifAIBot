from __future__ import annotations

import discord
from discord import app_commands

import embeds
import parse

from util import split_csv


RUBRIC_FRAMEWORKS = [
    (
        "Dreyfus Model",
        "Stuart E. Dreyfus & Hubert L. Dreyfus, *A Five-Stage Model of the Mental Activities Involved in Directed Skill Acquisition*, U.C. Berkeley ORC, 1980. Revised: Dreyfus & Rousse, *Revisiting the Six Stages of Skill Acquisition*, 2021.",
    ),
    (
        "IEEE SWECOM",
        "IEEE Computer Society, *Software Engineering Competency Model (SWECOM)*, 2014. Aligned with SWEBOK v3.0 (ISO/IEC TR 19759:2015).",
    ),
    (
        "SFIA v9",
        "SFIA Foundation, *SFIA 9*, October 2024. Adopted by organisations across 200+ countries.",
    ),
]


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="rubric", description="Framework citations and per-field SFIA scope.")
    @app_commands.describe(field="Field slug (optional).", topics="Comma-separated topic slugs (optional).")
    async def rubric(interaction: discord.Interaction, field: str | None = None, topics: str | None = None):
        fields_listed: list[tuple[str, str, bool]] = [(name, body, False) for name, body in RUBRIC_FRAMEWORKS]
        description = "Citations behind the 5-band grading methodology."

        if field:
            if field not in parse.CANONICAL_FIELDS:
                embed, files = embeds.error_embed(
                    f"Unknown field `{field}`. Valid: {', '.join(parse.CANONICAL_FIELDS.keys())}.",
                    icon=embeds.ICON_NAMES["rubric"],
                )
                await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
                return
            skills = parse.CANONICAL_FIELDS[field]["sfia_skills"]
            fields_listed.append((f"SFIA scope · {field}", ", ".join(skills), False))
            topics_list = split_csv(topics)
            if topics_list:
                tag_str = " ".join(f"`{t}`" for t in topics_list)
                fields_listed.append(("Topics", tag_str, False))

        embed, files = embeds.build(
            title="Rubric & frameworks",
            description=description,
            fields=fields_listed,
            icon=embeds.ICON_NAMES["rubric"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
