"""Logique des commandes sur les persos et les métiers (déclarées dans cogs/commands.py)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..db import Character
from ..gamedata import (
    MAX_PRIMARY_PROFESSIONS,
    RACES,
    class_label,
    is_primary,
    profession_label,
    race_allows,
    race_label,
    roles_for,
)
from ..roles import LABELS

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

# Le menu de choix du perso est limité à 25 options par Discord.
MAX_CHARACTERS = 25
# Lettres uniquement (accents compris), comme les noms de personnage en jeu.
NAME_RE = re.compile(r"^[^\W\d_]{2,24}$")


def roles_text(c: Character) -> str:
    """« Tank ⭐, DPS » : rôles possibles, le préféré marqué d'une étoile."""
    return ", ".join(f"{LABELS[r]} ⭐" if r == c.preferred_role else LABELS[r] for r in roles_for(c.wow_class))


def professions_text(c: Character) -> str:
    return ", ".join(
        f"{profession_label(p)} ({skill})" if skill is not None else profession_label(p)
        for p, skill in sorted(c.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
    )


def character_block(c: Character) -> str:
    text = f"• **{c.name}** — {class_label(c.wow_class)} {race_label(c.race)} · {roles_text(c)}"
    if c.professions:
        text += f"\n  ⚒️ {professions_text(c)}"
    return text


def normalize_name(name: str) -> str | None:
    """« grommash » → « Grommash », comme en jeu. None si le nom n'est pas valide."""
    name = name.strip()
    if not NAME_RE.match(name):
        return None
    return name[0].upper() + name[1:].lower()


def role_refusal(wow_class: str, role: str) -> str:
    possible = ", ".join(LABELS[r] for r in roles_for(wow_class))
    return f"⚠️ Un {class_label(wow_class)} ne peut pas être {LABELS[role]}. Rôles possibles : {possible}."


def race_refusal(race: str, wow_class: str) -> str:
    possible = ", ".join(sorted(class_label(c) for c in RACES[race][1]))
    return (
        f"⚠️ Un {race_label(race)} ne peut pas être {class_label(wow_class)} dans WoW Forever.\n"
        f"Classes possibles pour {race_label(race)} : {possible}."
    )


class CharacterCommands:
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db

    async def _send(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)

    async def _refresh_events(self, message_ids: list[int]) -> None:
        events = self.bot.get_cog("EventsCog")
        if events is not None:
            for message_id in message_ids:
                await events.refresh_event(message_id)

    # ================================================================== persos

    async def add(
        self, interaction: discord.Interaction, nom: str, classe: str, race: str, role_prefere: str | None
    ) -> None:
        name = normalize_name(nom)
        if name is None:
            return await self._send(interaction, "⚠️ Le nom ne doit contenir que des lettres (2 à 24).")
        if not race_allows(race, classe):
            return await self._send(interaction, race_refusal(race, classe))
        if role_prefere and role_prefere not in roles_for(classe):
            return await self._send(interaction, role_refusal(classe, role_prefere))
        if len(self.db.get_characters(interaction.user.id)) >= MAX_CHARACTERS:
            return await self._send(
                interaction, f"⚠️ Tu as déjà {MAX_CHARACTERS} persos. Supprimes-en un avec `/supprimer perso`."
            )
        try:
            character = self.db.add_character(interaction.user.id, name, classe, race, role_prefere)
        except sqlite3.IntegrityError:
            return await self._send(interaction, f"⚠️ Tu as déjà un perso nommé **{name}**.")

        tips = []
        if role_prefere is None and len(roles_for(classe)) > 1:
            tips.append("Indique ton rôle préféré avec `/modifier perso`.")
        tips.append("Ajoute ses métiers avec `/ajouter metier`.")
        await self._send(
            interaction,
            f"✅ **{name}** ({class_label(classe)} {race_label(race)}) ajouté. "
            f"Rôles possibles : {roles_text(character)}.\n" + "\n".join(f"💡 {t}" for t in tips),
        )

    async def modify(
        self,
        interaction: discord.Interaction,
        perso: str,
        nom: str | None,
        classe: str | None,
        race: str | None,
        role_prefere: str | None,
    ) -> None:
        character = await self.own_character(interaction, perso)
        if character is None:
            return
        if not any((nom, classe, race, role_prefere)):
            return await self._send(interaction, "Indique au moins une chose à modifier (nom, classe, race ou rôle).")

        updated = replace(character)
        notes = []
        if nom:
            name = normalize_name(nom)
            if name is None:
                return await self._send(interaction, "⚠️ Le nom ne doit contenir que des lettres (2 à 24).")
            updated.name = name
        updated.wow_class = classe or character.wow_class
        updated.race = race or character.race
        if not race_allows(updated.race, updated.wow_class):
            return await self._send(interaction, race_refusal(updated.race, updated.wow_class))

        if role_prefere == "aucun":
            updated.preferred_role = None
        elif role_prefere:
            if role_prefere not in roles_for(updated.wow_class):
                return await self._send(interaction, role_refusal(updated.wow_class, role_prefere))
            updated.preferred_role = role_prefere
        elif updated.preferred_role and updated.preferred_role not in roles_for(updated.wow_class):
            notes.append(f"Rôle préféré {LABELS[updated.preferred_role]} retiré : impossible avec cette classe.")
            updated.preferred_role = None

        try:
            self.db.update_character(updated)
        except sqlite3.IntegrityError:
            return await self._send(interaction, f"⚠️ Tu as déjà un perso nommé **{updated.name}**.")

        await self._send(
            interaction,
            f"✅ Perso modifié : {character_block(updated)}" + "".join(f"\n💡 {n}" for n in notes),
        )
        await self._refresh_events(self.db.character_events(character.id))

    async def delete(self, interaction: discord.Interaction, perso: str) -> None:
        character = await self.own_character(interaction, perso)
        if character is None:
            return
        affected = self.db.delete_character(interaction.user.id, character.id)
        await self._send(interaction, f"🗑️ **{character.name}** supprimé, avec ses métiers.")
        # Les sorties où il était inscrit affichent désormais le pseudo à la place.
        await self._refresh_events(affected)

    async def list(self, interaction: discord.Interaction, joueur: discord.abc.User | None) -> None:
        target = joueur or interaction.user
        characters = self.db.get_characters(target.id)
        battletag = self.db.get_battletag(target.id)
        if not characters and not battletag:
            who = "Tu n'as" if target.id == interaction.user.id else f"{target.mention} n'a"
            return await self._send(interaction, f"{who} aucun perso déclaré. Ça se fait avec `/ajouter perso`.")
        lines = []
        if battletag:
            lines += [f"🎮 BattleTag : `{battletag}`", ""]
        lines += [character_block(c) for c in characters] or ["*Aucun perso déclaré.*"]
        embed = discord.Embed(
            title=f"Persos de {target.display_name}", description="\n".join(lines)[:4096], color=0x3498DB
        )
        embed.set_footer(text="⭐ rôle préféré")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ================================================================= métiers

    async def add_profession(self, interaction: discord.Interaction, perso: str, metier: str, niveau: int | None) -> None:
        character = await self.own_character(interaction, perso)
        if character is None:
            return
        label = profession_label(metier)
        if metier in character.professions:
            return await self._send(
                interaction, f"**{character.name}** a déjà {label}. Pour changer le niveau : `/modifier metier`."
            )
        if is_primary(metier):
            primaries = [p for p in character.professions if is_primary(p)]
            if len(primaries) >= MAX_PRIMARY_PROFESSIONS:
                current = ", ".join(profession_label(p) for p in primaries)
                return await self._send(
                    interaction,
                    f"⚠️ **{character.name}** a déjà {MAX_PRIMARY_PROFESSIONS} métiers principaux ({current}). "
                    "Retires-en un avec `/supprimer metier`.",
                )
        self.db.set_profession(character.id, metier, niveau)
        lvl = f" ({niveau})" if niveau is not None else ""
        await self._send(interaction, f"✅ **{character.name}** : {label}{lvl}.")

    async def modify_profession(self, interaction: discord.Interaction, perso: str, metier: str, niveau: int) -> None:
        character = await self.own_character(interaction, perso)
        if character is None:
            return
        label = profession_label(metier)
        if metier not in character.professions:
            return await self._send(
                interaction, f"**{character.name}** n'a pas {label}. Pour l'ajouter : `/ajouter metier`."
            )
        self.db.set_profession(character.id, metier, niveau)
        await self._send(interaction, f"✅ **{character.name}** : {label} ({niveau}).")

    async def delete_profession(self, interaction: discord.Interaction, perso: str, metier: str) -> None:
        character = await self.own_character(interaction, perso)
        if character is None:
            return
        label = profession_label(metier)
        if self.db.remove_profession(character.id, metier):
            await self._send(interaction, f"🗑️ **{character.name}** : {label} retiré.")
        else:
            await self._send(interaction, f"**{character.name}** n'a pas {label}.")

    async def search_profession(self, interaction: discord.Interaction, metier: str) -> None:
        assert interaction.guild is not None
        label = profession_label(metier)
        found = self.db.characters_with_profession(interaction.guild.id, metier)
        if not found:
            return await self._send(interaction, f"Personne n'a déclaré **{label}** pour l'instant (`/ajouter metier`).")
        lines = [
            f"`{skill if skill is not None else '?':>3}` **{c.name}** ({class_label(c.wow_class)}) · <@{c.user_id}>"
            for c, skill in found
        ]
        embed = discord.Embed(
            title=f"⚒️ {label} — {len(found)} perso(s)", description="\n".join(lines)[:4096], color=0x3498DB
        )
        embed.set_footer(text="Classés par niveau de compétence · ? = niveau non renseigné")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ============================================================== interne

    def character_choices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        q = current.lower()
        return [
            app_commands.Choice(name=f"{c.name} — {class_label(c.wow_class)} {race_label(c.race)}"[:100], value=str(c.id))
            for c in self.db.get_characters(interaction.user.id)
            if q in c.name.lower()
        ][:25]

    async def own_character(self, interaction: discord.Interaction, value: str) -> Character | None:
        """Retrouve un perso du joueur (ID venant de l'autocomplétion, ou nom tapé à la main)."""
        character = self.db.get_character(int(value)) if value.isdigit() else None
        if character is None or character.user_id != interaction.user.id:
            character = next(
                (c for c in self.db.get_characters(interaction.user.id) if c.name.lower() == value.strip().lower()),
                None,
            )
        if character is None:
            await self._send(
                interaction, "Perso introuvable. Tes persos : `/liste persos`, pour en ajouter : `/ajouter perso`."
            )
        return character
