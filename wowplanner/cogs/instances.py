"""Commandes /instances et mise à jour automatique de la liste depuis le wiki."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..instances import WIKI_URL

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)


class InstancesCog(commands.Cog):
    instances_group = app_commands.Group(name="instances", description="Donjons et raids de WoW Forever")

    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.registry = bot.instances
        if bot.config.instances_refresh_hours > 0:
            self.refresh_loop.change_interval(hours=bot.config.instances_refresh_hours)

    async def cog_load(self) -> None:
        if self.bot.config.instances_refresh_hours > 0:
            self.refresh_loop.start()

    async def cog_unload(self) -> None:
        self.refresh_loop.cancel()

    @tasks.loop(hours=24)
    async def refresh_loop(self) -> None:
        age = self.registry.cache_age_hours()
        if age is not None and age < self.bot.config.instances_refresh_hours * 0.9:
            return  # cache encore frais (ex. : redémarrage rapproché)
        try:
            count = await self.registry.refresh(self.bot.http_session)
            log.info("Liste des instances mise à jour depuis le wiki : %d entrées", count)
        except Exception as exc:  # le bot doit continuer à tourner quoi qu'il arrive
            log.warning("Mise à jour des instances impossible, on garde la liste actuelle : %s", exc)

    @refresh_loop.before_loop
    async def _before_refresh(self) -> None:
        await self.bot.wait_until_ready()

    @instances_group.command(name="liste", description="Afficher les donjons et raids disponibles")
    @app_commands.describe(type="Filtrer par type")
    async def list_instances(
        self, interaction: discord.Interaction, type: Optional[Literal["donjons", "raids"]] = None
    ) -> None:
        embed = discord.Embed(title="WoW Forever — Donjons & Raids", url=WIKI_URL, color=0x3498DB)
        dungeons = [i for i in self.registry.all if not i.is_raid]
        raids = [i for i in self.registry.all if i.is_raid]

        parts = []
        if type in (None, "donjons"):
            parts.append("**🗝️ Donjons (5 joueurs)**")
            parts += [
                f"`{i.levels or '?':>5}` {i.name}" + (f" ({i.abbr})" if i.abbr else "") + (" 🆕" if i.new else "")
                for i in dungeons
            ]
        if type in (None, "raids"):
            parts.append("\n**🏰 Raids**")
            parts += [f"`{i.size:>2} j.` {i.name}" + (" 🆕" if i.new else "") for i in raids]
        embed.description = "\n".join(parts)[:4096]

        updated = self.registry.updated_at.strftime("%d/%m/%Y") if self.registry.updated_at else "?"
        embed.set_footer(text=f"Source : warcraft.wiki.gg · {self.registry.source} · maj {updated}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @instances_group.command(name="maj", description="Recharger la liste depuis le wiki maintenant")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            count = await self.registry.refresh(self.bot.http_session)
        except Exception as exc:
            await interaction.followup.send(f"⚠️ Échec de la mise à jour : {exc}", ephemeral=True)
            return
        await interaction.followup.send(f"✅ {count} instances chargées depuis le wiki.", ephemeral=True)


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(InstancesCog(bot))
