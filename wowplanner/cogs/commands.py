"""Toutes les commandes slash, organisées « verbe + catégorie » :

    /ajouter   event | perso | battletag
    /supprimer event | inscrit | perso | battletag
    /liste     events | battletags
    /admin     ajouter perso | supprimer perso | atelier | sync   (« Gérer le serveur »)
    /commander objet          (raccourci de l'atelier ; sinon tout passe par les boutons du panneau)

Le reste (persos, métiers, recettes, donjons) se consulte sur le site web.

Ce fichier ne fait que déclarer les commandes et leurs options ; la logique est dans
events.py (sorties), characters.py (persos), players.py (BattleTag), orders.py (atelier)
et sync.py (/admin sync).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..gamedata import CLASSES, RACES
from ..roles import LABELS, ROLES
from .characters import CharacterCommands
from .players import PlayerCommands

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .events import EventsCog
    from .orders import OrdersCog
    from .sync import SyncCog

CLASS_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in CLASSES.items()]
RACE_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in RACES.items()]
ROLE_CHOICES = [app_commands.Choice(name=LABELS[r], value=r) for r in ROLES]

PERSO_ADD_HELP = {
    "nom": "Nom du perso en jeu, prénom et nom séparés par un espace (ex. : Grommash Hurlenfer)",
    "classe": "Facultatif si le perso est dans l'armurerie (niveau 10+)",
    "race": "Facultatif si le perso est dans l'armurerie (niveau 10+)",
    "role_prefere": "Ton rôle préféré avec ce perso (s'il peut en jouer plusieurs)",
}


def _value(choice: app_commands.Choice[str] | None) -> str | None:
    return choice.value if choice else None


class CommandsCog(commands.Cog):
    ajouter = app_commands.Group(name="ajouter", description="Ajouter : sortie, perso, BattleTag", guild_only=True)
    supprimer = app_commands.Group(
        name="supprimer", description="Supprimer : sortie, inscrit, perso, BattleTag", guild_only=True
    )
    liste = app_commands.Group(name="liste", description="Voir : sorties, BattleTags", guild_only=True)
    # Réservé à « Gérer le serveur » : les autres membres ne voient pas /admin (réglable dans
    # Paramètres du serveur → Intégrations). Discord ne permet ce réglage que sur un verbe entier.
    admin = app_commands.Group(
        name="admin",
        description="Administration : persos des membres, atelier, synchro",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )
    admin_ajouter = app_commands.Group(name="ajouter", description="Ajouter pour un membre", parent=admin)
    admin_supprimer = app_commands.Group(name="supprimer", description="Supprimer pour un membre", parent=admin)

    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.chars = CharacterCommands(bot)
        self.players = PlayerCommands(bot)

    @property
    def events(self) -> EventsCog:
        return self.bot.get_cog("EventsCog")  # type: ignore[return-value]

    @property
    def orders(self) -> OrdersCog:
        return self.bot.get_cog("OrdersCog")  # type: ignore[return-value]

    @property
    def synchro(self) -> SyncCog:
        return self.bot.get_cog("SyncCog")  # type: ignore[return-value]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Retient que ce joueur est sur ce serveur (les listes sont limitées aux membres du serveur).
        if interaction.guild is not None:
            self.db.touch_member(interaction.guild.id, interaction.user.id)
        return True

    # ================================================================ /ajouter

    @ajouter.command(name="event", description="Créer une sortie donjon/raid avec inscription par boutons")
    @app_commands.describe(
        instance="Donjon ou raid (tape pour chercher, ou saisis un nom libre)",
        date="JJ/MM/AAAA, JJ/MM, « aujourd'hui » ou « demain »",
        heure="Heure de rendez-vous : 21:00, 21h30, 21h…",
        joueurs="Nombre total de joueurs (par défaut : taille de l'instance)",
        tanks="Nombre de places Tank",
        heals="Nombre de places Heal",
        dps="Nombre de places DPS",
        description="Infos complémentaires (stuff requis, point de RDV…)",
    )
    async def ajouter_event(
        self,
        interaction: discord.Interaction,
        instance: app_commands.Range[str, 1, 100],
        date: str,
        heure: str,
        joueurs: Optional[app_commands.Range[int, 1, 40]] = None,
        tanks: Optional[app_commands.Range[int, 0, 40]] = None,
        heals: Optional[app_commands.Range[int, 0, 40]] = None,
        dps: Optional[app_commands.Range[int, 0, 40]] = None,
        description: Optional[app_commands.Range[str, 1, 500]] = None,
    ) -> None:
        await self.events.create(interaction, instance, date, heure, joueurs, tanks, heals, dps, description)

    @ajouter.command(name="perso", description="Déclarer un de tes personnages (classe et race lues dans l'armurerie)")
    @app_commands.describe(**PERSO_ADD_HELP)
    @app_commands.choices(classe=CLASS_CHOICES, race=RACE_CHOICES, role_prefere=ROLE_CHOICES)
    async def ajouter_perso(
        self,
        interaction: discord.Interaction,
        nom: app_commands.Range[str, 2, 32],
        classe: Optional[app_commands.Choice[str]] = None,
        race: Optional[app_commands.Choice[str]] = None,
        role_prefere: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await self.chars.add(interaction, nom, _value(classe), _value(race), _value(role_prefere))

    @ajouter.command(name="battletag", description="Enregistrer ton BattleTag (ex. : Raug#2134)")
    @app_commands.describe(tag="Ton BattleTag, avec le # et les chiffres")
    async def ajouter_battletag(self, interaction: discord.Interaction, tag: app_commands.Range[str, 5, 20]) -> None:
        await self.players.set_tag(interaction, tag)

    # ============================================================== /supprimer

    @supprimer.command(name="event", description="Annuler une sortie et prévenir les inscrits (organisateur ou modo)")
    @app_commands.describe(sortie="La sortie à annuler")
    async def supprimer_event(self, interaction: discord.Interaction, sortie: str) -> None:
        await self.events.cancel(interaction, sortie)

    @supprimer.command(name="inscrit", description="Désinscrire un joueur d'une sortie (organisateur ou modo)")
    @app_commands.describe(
        sortie="La sortie concernée (à choisir en premier)",
        joueur="Le joueur à désinscrire (seuls les inscrits de cette sortie sont proposés)",
    )
    async def supprimer_inscrit(self, interaction: discord.Interaction, sortie: str, joueur: str) -> None:
        await self.events.kick(interaction, sortie, joueur)

    @supprimer.command(name="perso", description="Supprimer un de tes persos (et ses métiers)")
    @app_commands.describe(perso="Le perso à supprimer")
    async def supprimer_perso(self, interaction: discord.Interaction, perso: str) -> None:
        await self.chars.delete(interaction, perso)

    @supprimer.command(name="battletag", description="Retirer ton BattleTag")
    async def supprimer_battletag(self, interaction: discord.Interaction) -> None:
        await self.players.delete_tag(interaction)

    # ================================================================== /liste

    @liste.command(name="events", description="Les prochaines sorties du serveur")
    async def liste_events(self, interaction: discord.Interaction) -> None:
        await self.events.list_events(interaction)

    @liste.command(name="battletags", description="Les BattleTag des joueurs du serveur")
    async def liste_battletags(self, interaction: discord.Interaction) -> None:
        await self.players.list_tags(interaction)

    # ============================================================== /commander

    @app_commands.command(name="commander", description="Commander un objet à fabriquer à un perso du serveur")
    @app_commands.guild_only()
    @app_commands.describe(
        objet="L'objet (tape pour chercher parmi les recettes connues sur le serveur)",
        quantite="Combien (1 par défaut)",
        note="Un mot pour l'artisan (ex. : j'ai les composants)",
    )
    async def commander(
        self,
        interaction: discord.Interaction,
        objet: app_commands.Range[str, 2, 100],
        quantite: Optional[app_commands.Range[int, 1, 100]] = None,
        note: Optional[app_commands.Range[str, 1, 300]] = None,
    ) -> None:
        await self.orders.start(interaction, objet, quantite or 1, note)

    @commander.autocomplete("objet")
    async def _order_autocomplete(self, interaction: discord.Interaction, current: str):
        return self.orders.recipe_choices(interaction, current)

    # ================================================================== /admin

    @staticmethod
    async def _is_admin(interaction: discord.Interaction) -> bool:
        """Double vérification : Discord masque déjà /admin, mais un réglage serveur trop large reste possible."""
        if interaction.permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "Réservé aux membres qui ont la permission « Gérer le serveur ».", ephemeral=True
        )
        return False

    @admin_ajouter.command(name="perso", description="Ajouter un perso à un membre")
    @app_commands.describe(joueur="Le membre à qui appartient le perso", **PERSO_ADD_HELP)
    @app_commands.choices(classe=CLASS_CHOICES, race=RACE_CHOICES, role_prefere=ROLE_CHOICES)
    async def admin_ajouter_perso(
        self,
        interaction: discord.Interaction,
        joueur: discord.Member,
        nom: app_commands.Range[str, 2, 32],
        classe: Optional[app_commands.Choice[str]] = None,
        race: Optional[app_commands.Choice[str]] = None,
        role_prefere: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        if await self._is_admin(interaction):
            await self.chars.add(interaction, nom, _value(classe), _value(race), _value(role_prefere), owner=joueur)

    @admin_supprimer.command(name="perso", description="Supprimer un perso d'un membre")
    @app_commands.describe(joueur="Le membre (à choisir en premier)", perso="Son perso")
    async def admin_supprimer_perso(self, interaction: discord.Interaction, joueur: discord.Member, perso: str) -> None:
        if await self._is_admin(interaction):
            await self.chars.delete(interaction, perso, owner=joueur)

    @admin.command(name="atelier", description="Poster (et épingler) le panneau de l'atelier dans ce salon")
    async def admin_atelier(self, interaction: discord.Interaction) -> None:
        if await self._is_admin(interaction):
            await self.orders.post_panel(interaction)

    @admin.command(
        name="sync",
        description="Tout relire maintenant (sinon fait chaque nuit) : donjons, stats, talents, persos, recettes",
    )
    async def admin_sync(self, interaction: discord.Interaction) -> None:
        if await self._is_admin(interaction):
            await self.synchro.run(interaction)

    # ========================================================= autocomplétion

    @admin_supprimer_perso.autocomplete("perso")
    async def _admin_character_autocomplete(self, interaction: discord.Interaction, current: str):
        # Persos du membre déjà choisi dans le champ « joueur ».
        joueur = getattr(interaction.namespace, "joueur", None)
        owner_id = getattr(joueur, "id", None)
        if owner_id is None:
            return []
        return self.chars.character_choices(interaction, current, owner_id)

    @ajouter_event.autocomplete("instance")
    async def _instance_autocomplete(self, interaction: discord.Interaction, current: str):
        return self.events.instance_choices(current)

    @supprimer_event.autocomplete("sortie")
    @supprimer_inscrit.autocomplete("sortie")
    async def _event_autocomplete(self, interaction: discord.Interaction, current: str):
        return self.events.event_choices(interaction, current)

    @supprimer_inscrit.autocomplete("joueur")
    async def _signup_autocomplete(self, interaction: discord.Interaction, current: str):
        # Ne propose que les inscrits de la sortie déjà choisie dans le champ « sortie ».
        return self.events.signup_choices(getattr(interaction.namespace, "sortie", None), current)

    @supprimer_perso.autocomplete("perso")
    async def _character_autocomplete(self, interaction: discord.Interaction, current: str):
        return self.chars.character_choices(interaction, current)


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(CommandsCog(bot))
