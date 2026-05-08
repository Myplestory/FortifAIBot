from __future__ import annotations

import discord
from discord import app_commands

import embeds
import generate
import parse


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="directory", description="Industries → fields → topics. No args lists industries.")
    @app_commands.describe(
        industry="Industry slug; pass it to list fields under that industry.",
        field="Field slug; with an industry, lists topics under that field.",
    )
    async def directory(
        interaction: discord.Interaction,
        industry: str | None = None,
        field: str | None = None,
    ):
        industries = generate.list_industries()
        meta = parse.read_meta()
        fields_dict = meta.get("fields", {})

        # No args → list industries.
        if not industry:
            if field:
                embed, files = embeds.error_embed(
                    "`field` requires an `industry` argument.",
                    icon=embeds.ICON_NAMES["directory"],
                )
                await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
                return
            if not industries:
                embed, files = embeds.error_embed(
                    "No industries found under `templates/`.",
                    icon=embeds.ICON_NAMES["directory"],
                )
                await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
                return
            rows: list[tuple[str, str, bool]] = []
            for ind in industries:
                field_count = len(parse.CANONICAL_FIELDS)
                topic_count = sum(len(fields_dict.get(s, {}).get("topics", []) or []) for s in parse.CANONICAL_FIELDS)
                rows.append((ind, f"`{ind}` · {field_count} field(s) · {topic_count} topic(s)", False))
            embed, files = embeds.build(
                title="Industry directory",
                description="Industries are template namespaces under `templates/`.",
                fields=rows,
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        # Validate industry.
        if industry not in industries:
            valid = ", ".join(f"`{i}`" for i in industries) or "(none)"
            embed, files = embeds.error_embed(
                f"Unknown industry `{industry}`. Valid: {valid}.",
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        # `industry` only → list fields under that industry (topic counts come from the shared meta.json).
        if not field:
            rows = []
            for slug, meta_entry in parse.CANONICAL_FIELDS.items():
                topic_count = len(fields_dict.get(slug, {}).get("topics", []) or [])
                rows.append((meta_entry["name"], f"`{slug}` · {topic_count} topic(s)\n{meta_entry['description']}", False))
            embed, files = embeds.build(
                title=f"Fields · {industry}",
                description="The 8 canonical engineering fields. Pass `field` to list topics.",
                fields=rows,
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return

        # `industry` + `field` → list topics under that field.
        if field not in parse.CANONICAL_FIELDS:
            valid = ", ".join(f"`{k}`" for k in parse.CANONICAL_FIELDS.keys())
            embed, files = embeds.error_embed(
                f"Unknown field `{field}`. Valid: {valid}.",
                icon=embeds.ICON_NAMES["directory"],
            )
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True)
            return
        topics = fields_dict.get(field, {}).get("topics", []) or []
        body = "\n".join(f"• `{t}`" for t in topics) if topics else "_No topics yet — they grow as questions are generated._"
        embed, files = embeds.build(
            title=f"Topics · {industry} / {field}",
            description=parse.CANONICAL_FIELDS[field]["description"],
            fields=[("Topics", body, False)],
            icon=embeds.ICON_NAMES["directory"],
        )
        await interaction.response.send_message(embed=embed, files=files, ephemeral=True)

    @directory.autocomplete("industry")
    async def _directory_industry_autocomplete(interaction: discord.Interaction, current: str):
        current_low = (current or "").lower()
        return [
            app_commands.Choice(name=i, value=i)
            for i in generate.list_industries()
            if current_low in i.lower()
        ][:25]

    @directory.autocomplete("field")
    async def _directory_field_autocomplete(interaction: discord.Interaction, current: str):
        current_low = (current or "").lower()
        return [
            app_commands.Choice(name=slug, value=slug)
            for slug in parse.CANONICAL_FIELDS
            if current_low in slug.lower()
        ][:25]
