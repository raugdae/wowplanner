from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

from . import __version__
from .config import Config
from .db import Database
from .ephemeral import EphemeralCleaner
from .instances import InstanceRegistry
from .roles import RoleEmojis

log = logging.getLogger(__name__)

USER_AGENT = f"wowplanner-discord-bot/{__version__} (bot Discord d'organisation de groupes)"


class WowPlannerBot(commands.Bot):
    http_session: aiohttp.ClientSession

    def __init__(self, config: Config):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True  # détection des messages de sortie supprimés
        intents.voice_states = True  # savoir si un salon vocal de sortie est vide avant de le supprimer
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)

        self.config = config
        self.db = Database(config.db_path)
        self.instances = InstanceRegistry(config.instances_cache_path)
        self.role_emojis = RoleEmojis(
            {"tank": config.emoji_tank, "heal": config.emoji_heal, "dps": config.emoji_dps}
        )
        self.ephemeral = EphemeralCleaner()

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        self.instances.load()

        await self.load_extension("wowplanner.cogs.instances")
        await self.load_extension("wowplanner.cogs.events")
        await self.load_extension("wowplanner.cogs.commands")  # après events et instances, qu'il appelle
        await self.load_extension("wowplanner.cogs.schedule")

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("%d commandes synchronisées sur le serveur %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("%d commandes globales synchronisées (jusqu'à 1 h pour apparaître)", len(synced))

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s (%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game("/ajouter event"))

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        # Simple écoute : le traitement des commandes et des boutons se fait ailleurs, en parallèle.
        await self.ephemeral.on_interaction(interaction)

    async def close(self) -> None:
        if getattr(self, "http_session", None):
            await self.http_session.close()
        await super().close()
        self.db.close()
