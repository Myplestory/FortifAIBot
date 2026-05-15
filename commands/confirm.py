from __future__ import annotations

import discord

import embeds


class ConfirmView(discord.ui.View):
    def __init__(self, *, label_yes: str = "Yes", label_no: str = "Cancel"):
        super().__init__(timeout=60)
        self.value: bool | None = None
        self._label_yes = label_yes
        self._label_no = label_no
        self.yes_button.label = label_yes
        self.no_button.label = label_no

    @discord.ui.button(style=discord.ButtonStyle.success, label="Yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Cancel")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


async def ask_confirm(
    interaction: discord.Interaction,
    *,
    action: str,
    detail: str,
    icon: str | None = None,
) -> bool:
    embed, files = embeds.confirm_embed(action, detail, icon=icon)
    view = ConfirmView(label_yes=f"Yes, {action.lower()}")
    # Dual-mode: if the caller already deferred (defer-first pattern), route the
    # confirm prompt through followup.send so we don't double-ACK the interaction.
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, files=files, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, files=files, view=view, ephemeral=True)
    await view.wait()
    return bool(view.value)
