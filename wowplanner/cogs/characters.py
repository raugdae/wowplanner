"""Logique des commandes sur les persos et les métiers (déclarées dans cogs/commands.py)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..db import Character
from .armory import NOT_FOUND_HELP_SHORT, SyncResult
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
# Lettres uniquement (accents compris), en un ou deux mots (prénom nom, comme dans WoW Forever)
# séparés par un seul espace. Chaque mot fait au moins 2 lettres.
NAME_RE = re.compile(r"^[^\W\d_]{2,}( [^\W\d_]{2,})?$")
NAME_MAX = 32
NAME_ERROR = (
    f"⚠️ Le nom ne doit contenir que des lettres ({NAME_MAX} max), en un ou deux mots "
    "séparés par **un seul** espace (ex. : `Grommash` ou `Grommash Hurlenfer`)."
)


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
    if c.armory_synced_at:
        text += f"\n  🔎 synchronisé avec l'armurerie <t:{c.armory_synced_at}:R>"
    return text


ARMORY_OVERWRITE_NOTE = (
    "\n💡 Ce perso est synchronisé avec l'armurerie : ses métiers y seront relus "
    "(et remplacés) à la prochaine synchro."
)


def normalize_name(name: str) -> str | None:
    """« grommash hurlenfer » → « Grommash Hurlenfer », comme en jeu. None si le nom n'est pas valide."""
    name = name.strip()
    if len(name) > NAME_MAX or not NAME_RE.match(name):
        return None
    return " ".join(part[0].upper() + part[1:].lower() for part in name.split(" "))


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
        if interaction.response.is_done():  # réponse différée (vérification armurerie en cours)
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def _armory_check(self, interaction: discord.Interaction, character: Character) -> tuple[str, bool]:
        """Cherche le perso dans l'armurerie (si activée). Renvoie (ligne à afficher, métiers synchronisés ?)."""
        armory = self.bot.get_cog("ArmoryCog")
        if armory is None or not armory.available:
            return "", False
        if not interaction.response.is_done():
            # L'appel peut dépasser les 3 s que Discord laisse pour répondre.
            await interaction.response.defer(ephemeral=True, thinking=True)
        result = await armory.sync(character, max_age=0)
        if result is None:
            return "", False
        return "\n" + result.summary(), result.professions_synced

    async def _refresh_events(self, message_ids: list[int]) -> None:
        events = self.bot.get_cog("EventsCog")
        if events is not None:
            for message_id in message_ids:
                await events.refresh_event(message_id)

    # ================================================================== persos

    def _armory(self):
        armory = self.bot.get_cog("ArmoryCog")
        return armory if armory is not None and armory.available else None

    async def _notify_owner(self, interaction: discord.Interaction, owner: discord.abc.User, text: str) -> None:
        """MP au joueur quand un admin touche à ses persos (silencieux si ses MP sont fermés)."""
        try:
            await owner.send(f"🛠️ **{interaction.user.display_name}** {text}")
        except discord.HTTPException:
            pass

    async def add(
        self,
        interaction: discord.Interaction,
        nom: str,
        classe: str | None,
        race: str | None,
        role_prefere: str | None,
        owner: discord.abc.User | None = None,
    ) -> None:
        """Ajoute un perso. Classe et race facultatives : reprises de l'armurerie si absentes.

        `owner` : membre à qui appartient le perso (commandes /admin) ; par défaut, l'auteur.
        """
        owner = owner or interaction.user
        by_admin = owner.id != interaction.user.id
        has = f"{owner.mention} a" if by_admin else "Tu as"

        name = normalize_name(nom)
        if name is None:
            return await self._send(interaction, NAME_ERROR)
        existing = self.db.get_characters(owner.id)
        if len(existing) >= MAX_CHARACTERS:
            return await self._send(interaction, f"⚠️ {has} déjà {MAX_CHARACTERS} persos (maximum).")
        if any(c.name.lower() == name.lower() for c in existing):
            return await self._send(interaction, f"⚠️ {has} déjà un perso nommé **{name}**.")

        # Armurerie : une seule recherche, qui sert à compléter classe/race puis à synchroniser.
        armory = self._armory()
        sheet, found = None, None
        if armory is not None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            sheet, found = await armory.fetch(name, max_age=0)

        from_armory = []
        if classe is None or race is None:
            if sheet is None:
                if armory is None:
                    why = "L'armurerie n'est pas activée"
                elif found is False:
                    why = f"Je n'ai pas trouvé **{name}** dans l'armurerie ({NOT_FOUND_HELP_SHORT})"
                else:
                    why = "L'armurerie ne répond pas pour l'instant"
                return await self._send(interaction, f"⚠️ {why} : précise la **classe** et la **race**.")
            if classe is None and sheet.class_key:
                classe = sheet.class_key
                from_armory.append("classe")
            if race is None and sheet.race_key:
                race = sheet.race_key
                from_armory.append("race")
            if classe is None or race is None:
                return await self._send(
                    interaction, "⚠️ Classe ou race inconnue dans l'armurerie : précise-les à la main."
                )

        # Classe ET race lues dans l'armurerie : Blizzard fait foi, même si notre table des
        # combinaisons (gamedata) est en retard sur le jeu.
        if len(from_armory) < 2 and not race_allows(race, classe):
            return await self._send(interaction, race_refusal(race, classe))
        if role_prefere and role_prefere not in roles_for(classe):
            return await self._send(interaction, role_refusal(classe, role_prefere))
        try:
            character = self.db.add_character(owner.id, name, classe, race, role_prefere)
        except sqlite3.IntegrityError:
            return await self._send(interaction, f"⚠️ {has} déjà un perso nommé **{name}**.")
        if interaction.guild is not None:
            self.db.touch_member(interaction.guild.id, owner.id)

        armory_line, professions_synced = "", False
        if armory is not None:
            result = armory.apply(character, sheet) if sheet is not None else SyncResult(found=found)
            armory_line, professions_synced = "\n" + result.summary(), result.professions_synced
        if from_armory:
            armory_line += f"\n🔎 {' et '.join(from_armory).capitalize()} reprise(s) de l'armurerie."

        whose = f" pour {owner.mention}" if by_admin else ""
        tips = []
        if not by_admin:
            if role_prefere is None and len(roles_for(classe)) > 1:
                tips.append("Indique ton rôle préféré avec `/modifier perso`.")
            if not professions_synced:
                tips.append("Ajoute ses métiers avec `/ajouter metier`.")
        await self._send(
            interaction,
            f"✅ **{name}** ({class_label(classe)} {race_label(race)}) ajouté{whose}. "
            f"Rôles possibles : {roles_text(character)}.{armory_line}" + "".join(f"\n💡 {t}" for t in tips),
        )
        if by_admin:
            await self._notify_owner(
                interaction, owner,
                f"a ajouté ton perso **{name}** ({class_label(classe)} {race_label(race)}) sur le bot. "
                "Tu peux le voir avec `/liste persos` et le modifier avec `/modifier perso`.",
            )

    async def modify(
        self,
        interaction: discord.Interaction,
        perso: str,
        nom: str | None,
        classe: str | None,
        race: str | None,
        role_prefere: str | None,
        owner: discord.abc.User | None = None,
    ) -> None:
        owner = owner or interaction.user
        has = f"{owner.mention} a" if owner.id != interaction.user.id else "Tu as"
        character = await self.own_character(interaction, perso, owner.id)
        if character is None:
            return
        if not any((nom, classe, race, role_prefere)):
            return await self._send(interaction, "Indique au moins une chose à modifier (nom, classe, race ou rôle).")

        updated = replace(character)
        notes = []
        if nom:
            name = normalize_name(nom)
            if name is None:
                return await self._send(interaction, NAME_ERROR)
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
            return await self._send(interaction, f"⚠️ {has} déjà un perso nommé **{updated.name}**.")

        armory_line = ""
        if updated.name != character.name:  # nouveau nom : on revérifie dans l'armurerie
            armory_line, _ = await self._armory_check(interaction, updated)
            updated = self.db.get_character(updated.id) or updated  # métiers éventuellement synchronisés

        await self._send(
            interaction,
            f"✅ Perso modifié : {character_block(updated)}{armory_line}" + "".join(f"\n💡 {n}" for n in notes),
        )
        await self._refresh_events(self.db.character_events(character.id))

    async def delete(
        self, interaction: discord.Interaction, perso: str, owner: discord.abc.User | None = None
    ) -> None:
        owner = owner or interaction.user
        by_admin = owner.id != interaction.user.id
        character = await self.own_character(interaction, perso, owner.id)
        if character is None:
            return
        affected = self.db.delete_character(owner.id, character.id)
        whose = f" (perso de {owner.mention})" if by_admin else ""
        await self._send(interaction, f"🗑️ **{character.name}**{whose} supprimé, avec ses métiers.")
        # Les sorties où il était inscrit affichent désormais le pseudo à la place.
        await self._refresh_events(affected)
        if by_admin:
            await self._notify_owner(interaction, owner, f"a supprimé ton perso **{character.name}** du bot.")

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
        note = ARMORY_OVERWRITE_NOTE if character.armory_synced_at else ""
        await self._send(interaction, f"✅ **{character.name}** : {label}{lvl}.{note}")

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
        note = ARMORY_OVERWRITE_NOTE if character.armory_synced_at else ""
        await self._send(interaction, f"✅ **{character.name}** : {label} ({niveau}).{note}")

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

    def character_choices(
        self, interaction: discord.Interaction, current: str, owner_id: int | None = None
    ) -> list[app_commands.Choice[str]]:
        """Persos du joueur (ou de `owner_id` pour les commandes /admin) contenant le texte tapé."""
        q = current.lower()
        return [
            app_commands.Choice(name=f"{c.name} — {class_label(c.wow_class)} {race_label(c.race)}"[:100], value=str(c.id))
            for c in self.db.get_characters(owner_id or interaction.user.id)
            if q in c.name.lower()
        ][:25]

    async def own_character(
        self, interaction: discord.Interaction, value: str, owner_id: int | None = None
    ) -> Character | None:
        """Retrouve un perso du joueur (ID venant de l'autocomplétion, ou nom tapé à la main)."""
        owner_id = owner_id or interaction.user.id
        character = self.db.get_character(int(value)) if value.isdigit() else None
        if character is None or character.user_id != owner_id:
            character = next(
                (c for c in self.db.get_characters(owner_id) if c.name.lower() == value.strip().lower()),
                None,
            )
        if character is None:
            if owner_id == interaction.user.id:
                text = "Perso introuvable. Tes persos : `/liste persos`, pour en ajouter : `/ajouter perso`."
            else:
                text = f"Perso introuvable chez <@{owner_id}> (voir `/liste persos joueur:`)."
            await self._send(interaction, text)
        return character
