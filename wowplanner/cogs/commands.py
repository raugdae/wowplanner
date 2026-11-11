"""Toutes les commandes slash, organisées « verbe + catégorie » :

    /ajouter   event | perso | metier | battletag
    /modifier  perso | metier | instances
    /supprimer event | inscrit | perso | metier | battletag
    /liste     events | persos | metier | battletags | instances

Ce fichier ne fait que déclarer les commandes et leurs options ; la logique est dans
events.py (sorties), characters.py (persos, métiers), players.py (BattleTag) et instances.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..gamedata import CLASSES, MAX_PROFESSION_SKILL, PROFESSIONS, RACES
from ..roles import LABELS, ROLES
from .characters import CharacterCommands
from .players import PlayerCommands

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .events import EventsCog
    from .instances import InstancesCog

CLASS_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in CLASSES.items()]
RACE_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in RACES.items()]
ROLE_CHOICES = [app_commands.Choice(name=LABELS[r], value=r) for r in ROLES]
ROLE_OR_NONE_CHOICES = [*ROLE_CHOICES, app_commands.Choice(name="Aucun", value="aucun")]
PROFESSION_CHOICES = [
    app_commands.Choice(name=label if primary else f"{label} (secondaire)", value=key)
    for key, (label, primary) in PROFESSIONS.items()
]

Skill = app_commands.Range[int, 1, MAX_PROFESSION_SKILL]
SKILL_HELP = f"Niveau de compétence (1 à {MAX_PROFESSION_SKILL})"


def _value(choice: app_commands.Choice[str] | None) -> str | None:
    return choice.value if choice else None


class CommandsCog(commands.Cog):
    ajouter = app_commands.Group(
        name="ajouter", description="Ajouter : sortie, perso, métier, BattleTag", guild_only=True
    )
    modifier = app_commands.Group(name="modifier", description="Modifier : perso, métier", guild_only=True)
    supprimer = app_commands.Group(
        name="supprimer", description="Supprimer : sortie, inscrit, perso, métier, BattleTag", guild_only=True
    )
    liste = app_commands.Group(
        name="liste", description="Voir : sorties, persos, métier, BattleTags, instances", guild_only=True
    )

    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.chars = CharacterCommands(bot)
        self.players = PlayerCommands(bot)

    @property
    def events(self) -> EventsCog:
        return self.bot.get_cog("EventsCog")  # type: ignore[return-value]

    @property
    def instances(self) -> InstancesCog:
        return self.bot.get_cog("InstancesCog")  # type: ignore[return-value]

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

    @ajouter.command(name="perso", description="Déclarer un de tes personnages")
    @app_commands.describe(
        nom="Nom du perso en jeu, prénom et nom séparés par un espace (ex. : Grommash Hurlenfer)",
        classe="Classe",
        race="Race",
        role_prefere="Ton rôle préféré avec ce perso (s'il peut en jouer plusieurs)",
    )
    @app_commands.choices(classe=CLASS_CHOICES, race=RACE_CHOICES, role_prefere=ROLE_CHOICES)
    async def ajouter_perso(
        self,
        interaction: discord.Interaction,
        nom: app_commands.Range[str, 2, 32],
        classe: app_commands.Choice[str],
        race: app_commands.Choice[str],
        role_prefere: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await self.chars.add(interaction, nom, classe.value, race.value, _value(role_prefere))

    @ajouter.command(name="metier", description="Ajouter un métier à un de tes persos")
    @app_commands.describe(perso="Le perso", metier="Le métier", niveau=SKILL_HELP)
    @app_commands.choices(metier=PROFESSION_CHOICES)
    async def ajouter_metier(
        self,
        interaction: discord.Interaction,
        perso: str,
        metier: app_commands.Choice[str],
        niveau: Optional[Skill] = None,
    ) -> None:
        await self.chars.add_profession(interaction, perso, metier.value, niveau)

    @ajouter.command(name="battletag", description="Enregistrer ton BattleTag (ex. : Raug#2134)")
    @app_commands.describe(tag="Ton BattleTag, avec le # et les chiffres")
    async def ajouter_battletag(self, interaction: discord.Interaction, tag: app_commands.Range[str, 5, 20]) -> None:
        await self.players.set_tag(interaction, tag)

    # =============================================================== /modifier

    @modifier.command(name="perso", description="Modifier un de tes persos : nom, classe, race ou rôle préféré")
    @app_commands.describe(
        perso="Le perso à modifier",
        nom="Nouveau nom",
        classe="Nouvelle classe",
        race="Nouvelle race",
        role_prefere="Rôle préféré (« Aucun » pour le retirer)",
    )
    @app_commands.choices(classe=CLASS_CHOICES, race=RACE_CHOICES, role_prefere=ROLE_OR_NONE_CHOICES)
    async def modifier_perso(
        self,
        interaction: discord.Interaction,
        perso: str,
        nom: Optional[app_commands.Range[str, 2, 32]] = None,
        classe: Optional[app_commands.Choice[str]] = None,
        race: Optional[app_commands.Choice[str]] = None,
        role_prefere: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        await self.chars.modify(interaction, perso, nom, _value(classe), _value(race), _value(role_prefere))

    @modifier.command(name="metier", description="Changer le niveau d'un métier")
    @app_commands.describe(perso="Le perso", metier="Le métier", niveau=SKILL_HELP)
    @app_commands.choices(metier=PROFESSION_CHOICES)
    async def modifier_metier(
        self, interaction: discord.Interaction, perso: str, metier: app_commands.Choice[str], niveau: Skill
    ) -> None:
        await self.chars.modify_profession(interaction, perso, metier.value, niveau)

    @modifier.command(name="instances", description="Recharger la liste des donjons/raids depuis le wiki (modos)")
    async def modifier_instances(self, interaction: discord.Interaction) -> None:
        await self.instances.refresh_now(interaction)

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

    @supprimer.command(name="metier", description="Retirer un métier d'un de tes persos")
    @app_commands.describe(perso="Le perso", metier="Le métier")
    @app_commands.choices(metier=PROFESSION_CHOICES)
    async def supprimer_metier(
        self, interaction: discord.Interaction, perso: str, metier: app_commands.Choice[str]
    ) -> None:
        await self.chars.delete_profession(interaction, perso, metier.value)

    @supprimer.command(name="battletag", description="Retirer ton BattleTag")
    async def supprimer_battletag(self, interaction: discord.Interaction) -> None:
        await self.players.delete_tag(interaction)

    # ================================================================== /liste

    @liste.command(name="events", description="Les prochaines sorties du serveur")
    async def liste_events(self, interaction: discord.Interaction) -> None:
        await self.events.list_events(interaction)

    @liste.command(name="persos", description="Tes persos (ou ceux d'un autre joueur)")
    @app_commands.describe(joueur="Joueur dont tu veux voir les persos (toi par défaut)")
    async def liste_persos(self, interaction: discord.Interaction, joueur: Optional[discord.User] = None) -> None:
        await self.chars.list(interaction, joueur)

    @liste.command(name="metier", description="Qui a ce métier sur le serveur ?")
    @app_commands.describe(metier="Le métier recherché")
    @app_commands.choices(metier=PROFESSION_CHOICES)
    async def liste_metier(self, interaction: discord.Interaction, metier: app_commands.Choice[str]) -> None:
        await self.chars.search_profession(interaction, metier.value)

    @liste.command(name="battletags", description="Les BattleTag des joueurs du serveur")
    async def liste_battletags(self, interaction: discord.Interaction) -> None:
        await self.players.list_tags(interaction)

    @liste.command(name="instances", description="Les donjons et raids de WoW Forever")
    @app_commands.describe(type="Filtrer par type")
    async def liste_instances(
        self, interaction: discord.Interaction, type: Optional[Literal["donjons", "raids"]] = None
    ) -> None:
        await self.instances.list_instances(interaction, type)

    # ========================================================= autocomplétion

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

    @ajouter_metier.autocomplete("perso")
    @modifier_perso.autocomplete("perso")
    @modifier_metier.autocomplete("perso")
    @supprimer_perso.autocomplete("perso")
    @supprimer_metier.autocomplete("perso")
    async def _character_autocomplete(self, interaction: discord.Interaction, current: str):
        return self.chars.character_choices(interaction, current)


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(CommandsCog(bot))
