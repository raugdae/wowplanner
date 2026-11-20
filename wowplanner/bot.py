from __future__ import annotations

import logging
import time

import aiohttp
import discord
from discord.ext import commands

from . import __version__
from .config import Config
from .db import Database
from .ephemeral import EphemeralCleaner
from .instances import InstanceRegistry
from .web import WebSite
from .webauth import DiscordOAuth, load_secret
from .roles import RoleEmojis

log = logging.getLogger(__name__)

# Appartenance au serveur (connexion au site) : un « oui » est gardé 10 minutes.
MEMBER_CACHE_SECONDS = 600

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
        self.website = WebSite(self.db, lambda: self.config.guild_id)
        self.website.auction_house = config.auction_house_id
        self._member_cache: dict[int, tuple[float, bool]] = {}

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        self.instances.load()

        await self.load_extension("wowplanner.cogs.events")
        await self.load_extension("wowplanner.cogs.armory")
        await self.load_extension("wowplanner.cogs.orders")
        await self.load_extension("wowplanner.cogs.statsync")
        await self.load_extension("wowplanner.cogs.sync")
        await self.load_extension("wowplanner.cogs.commands")  # après events et instances, qu'il appelle
        await self.load_extension("wowplanner.cogs.schedule")
        await self.load_extension("wowplanner.cogs.webbridge")  # actions du site (sorties, persos)
        await self.load_extension("wowplanner.cogs.auctions")  # prix de l'hôtel des ventes (AUCTION_HOUSE_ID)

        if self.config.web_port:
            if self._setup_web_auth():
                await self.website.start(self.config.web_host, self.config.web_port)

        if self.config.guild_id:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("%d commandes synchronisées sur le serveur %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("%d commandes globales synchronisées (jusqu'à 1 h pour apparaître)", len(synced))

    def _setup_web_auth(self) -> bool:
        """Active la connexion Discord du site si DISCORD_CLIENT_SECRET est renseigné.

        Renvoie False (site non démarré) si la connexion est demandée mais mal configurée : mieux vaut pas de
        site qu'un site ouvert par erreur.
        """
        cfg = self.config
        if not cfg.discord_client_secret:
            log.warning("Site web OUVERT À TOUS : renseigne DISCORD_CLIENT_SECRET pour le réserver aux membres")
            return True
        if not cfg.web_url:
            log.error(
                "Connexion Discord impossible sans adresse publique du site (WEB_URL ou WEB_DOMAIN) : site non démarré"
            )
            return False
        client_id = cfg.discord_client_id or str(self.application_id or "")
        if not client_id:
            log.error("Identifiant de l'application Discord inconnu (DISCORD_CLIENT_ID) : site non démarré")
            return False
        oauth = DiscordOAuth(self.http_session, client_id, cfg.discord_client_secret, f"{cfg.web_url}/auth/callback")
        self.website.enable_auth(
            oauth, load_secret(cfg.data_dir / "session_secret"), self.is_guild_member,
            secure_cookies=cfg.web_url.startswith("https://"),
        )
        log.info("Site réservé aux membres du serveur (connexion Discord, retour sur %s)", oauth.redirect_uri)
        return True

    async def is_guild_member(self, user_id: int) -> bool | None:
        """Membre du serveur du site ? None si on ne peut pas le savoir (serveur inconnu, Discord injoignable).

        Appel direct à l'API (pas besoin de l'intent « membres ») ; un « oui » est gardé 10 minutes.
        """
        cached = self._member_cache.get(user_id)
        if cached and time.monotonic() - cached[0] < MEMBER_CACHE_SECONDS:
            return cached[1]
        guild_id = self.website.guild_id()
        if guild_id is None:
            return None
        try:
            await self.http.get_member(guild_id, user_id)
        except discord.NotFound:
            # Pas mis en cache : quelqu'un qui rejoint le serveur peut se reconnecter tout de suite.
            self._member_cache.pop(user_id, None)
            return False
        except discord.HTTPException as exc:
            log.warning("Vérification de membre impossible : %s", exc)
            return None
        self._member_cache[user_id] = (time.monotonic(), True)
        return True

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s (%s)", self.user, self.user.id if self.user else "?")
        await self.change_presence(activity=discord.Game("/ajouter event"))

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        # Simple écoute : le traitement des commandes et des boutons se fait ailleurs, en parallèle.
        await self.ephemeral.on_interaction(interaction)

    async def close(self) -> None:
        if getattr(self, "http_session", None):
            await self.http_session.close()
        await self.website.stop()
        await super().close()
        self.db.close()
