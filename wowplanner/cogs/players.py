"""Logique des commandes sur le BattleTag (déclarées dans cogs/commands.py)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

# Nom de 3 à 12 caractères (lettres, accents compris, et chiffres, sans commencer par un chiffre) + « #1234 ».
BATTLETAG_RE = re.compile(r"^[^\W\d_][^\W_]{2,11}#\d{3,6}$")


class PlayerCommands:
    def __init__(self, bot: WowPlannerBot):
        self.db = bot.db

    async def set_tag(self, interaction: discord.Interaction, tag: str) -> None:
        tag = tag.strip().replace(" ", "")
        if not BATTLETAG_RE.match(tag):
            await interaction.response.send_message(
                "⚠️ Ça ne ressemble pas à un BattleTag. Format attendu : `Nom#1234` "
                "(tu le trouves en haut de l'appli Battle.net).",
                ephemeral=True,
            )
            return
        previous = self.db.get_battletag(interaction.user.id)
        self.db.set_battletag(interaction.user.id, tag)
        replaced = f" (remplace `{previous}`)" if previous and previous != tag else ""
        await interaction.response.send_message(
            f"✅ BattleTag enregistré : `{tag}`{replaced}. Les autres le verront avec `/liste battletags`.",
            ephemeral=True,
        )

    async def delete_tag(self, interaction: discord.Interaction) -> None:
        if self.db.get_battletag(interaction.user.id) is None:
            await interaction.response.send_message("Tu n'as pas enregistré de BattleTag.", ephemeral=True)
            return
        self.db.set_battletag(interaction.user.id, None)
        await interaction.response.send_message("🗑️ BattleTag retiré.", ephemeral=True)

    async def list_tags(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        tags = self.db.battletags(interaction.guild.id)
        if not tags:
            await interaction.response.send_message(
                "Personne n'a encore enregistré son BattleTag (`/ajouter battletag`).", ephemeral=True
            )
            return
        lines = [f"<@{user_id}> · `{tag}`" for user_id, tag in tags]
        embed = discord.Embed(
            title=f"🎮 BattleTag — {len(tags)} joueur(s)", description="\n".join(lines)[:4096], color=0x3498DB
        )
        embed.set_footer(text="Pour ajouter le tien : /ajouter battletag")
        await interaction.response.send_message(embed=embed, ephemeral=True)
