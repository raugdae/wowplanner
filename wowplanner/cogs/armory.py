"""Armurerie WoW Forever : fiche d'un perso en MP, synchro des métiers, vérification des persos.

Facultatif : sans BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET, tout ceci est désactivé et le
reste du bot marche normalement. L'API n'étant pas officielle pour Forever, chaque appel
peut échouer : on dégrade toujours en douceur (message d'info, jamais d'erreur bloquante).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..armory import (
    CACHE_SECONDS, ArmoryClient, ArmoryError, ArmorySheet, parse_item, parse_recipe, parse_talent_index,
    parse_talent_tree,
)
from ..db import Character
from ..gamedata import class_label, profession_label, race_label
from ..recipes import Field, build_pages, crafted_by_map, filter_recipes

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

# Pause entre deux persos pendant la synchro quotidienne (on reste très loin des quotas Blizzard).
SYNC_PAUSE_SECONDS = 1.0
# Requêtes simultanées pour récupérer les composants des recettes.
RECIPE_FETCH_CONCURRENCY = 5
# /modifier armurerie : une demande par minute et par joueur ; petite pause entre deux persos.
REFRESH_COOLDOWN_SECONDS = 60
REFRESH_PAUSE_SECONDS = 0.3
# Arbres de talents (données de jeu) : redemandés chaque semaine, au cas où un patch les change.
TALENT_TREES_MAX_AGE = 7 * 24 * 3600
TALENT_FETCH_PAUSE = 0.1
# Caractères max par message de recettes (limite Discord : 6000 pour toutes les fiches du message).
RECIPE_MESSAGE_CHARS = 5200

CLASS_COLORS = {
    "guerrier": 0xC79C6E, "paladin": 0xF58CBA, "chasseur": 0xABD473, "voleur": 0xFFF569, "pretre": 0xFFFFFF,
    "chaman": 0x0070DE, "mage": 0x69CCF0, "demoniste": 0x9482C9, "druide": 0xFF7D0A,
}
NOT_FOUND_HELP_SHORT = "il faut être niveau 10 et s'être déconnecté depuis"
NOT_FOUND_HELP = (
    "L'armurerie ne connaît que les persos **niveau 10 ou plus**, et seulement **après une déconnexion** "
    "(parfois avec quelques heures de retard). Vérifie aussi l'orthographe du nom (prénom et nom)."
)


@dataclass
class SyncResult:
    found: bool | None  # None : armurerie injoignable, on ne sait pas
    sheet: ArmorySheet | None = None
    professions_synced: bool = False
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Une ou deux lignes à ajouter aux messages de /ajouter perso, /modifier perso."""
        if self.found is None:
            return "🔎 Armurerie injoignable pour l'instant, je réessaierai plus tard."
        if not self.found:
            return f"🔎 Pas (encore) trouvé dans l'armurerie. {NOT_FOUND_HELP}"
        sheet = self.sheet
        assert sheet is not None
        text = f"🔎 Trouvé dans l'armurerie : niveau {sheet.level}"
        if self.professions_synced:
            text += ", métiers synchronisés"
        return text + "." + "".join(f"\n⚠️ {w}" for w in self.warnings)


def _num(value: Any) -> float | None:
    """Les stats arrivent en nombre, en {base, effective} ou en {value, …}."""
    if isinstance(value, dict):
        value = value.get("effective", value.get("value"))
    return value if isinstance(value, (int, float)) else None


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "?"
    if pct:
        return f"{value:.1f} %".replace(".", ",")
    return f"{int(round(value))}"


# Disposition de la fiche de perso en jeu : colonne gauche, colonne droite, armes en bas.
LEFT_SLOTS = (
    ("HEAD", "Tête"), ("NECK", "Cou"), ("SHOULDER", "Épaules"), ("BACK", "Dos"),
    ("CHEST", "Torse"), ("SHIRT", "Chemise"), ("TABARD", "Tabard"), ("WRIST", "Poignets"),
)
RIGHT_SLOTS = (
    ("HANDS", "Mains"), ("WAIST", "Taille"), ("LEGS", "Jambes"), ("FEET", "Pieds"),
    ("FINGER_1", "Anneau 1"), ("FINGER_2", "Anneau 2"), ("TRINKET_1", "Bijou 1"), ("TRINKET_2", "Bijou 2"),
)
WEAPON_SLOTS = (("MAIN_HAND", "Main droite"), ("OFF_HAND", "Main gauche"), ("RANGED", "À distance"))
# Largeur des noms d'objets dans les colonnes côte à côte (au-delà : coupé avec « … »).
ITEM_NAME_WIDTH = 14

# Qualité des objets. Chaque ligne commence par un emoji (➖ pour un emplacement vide) :
# un emoji est plus large qu'une lettre, mais s'il y en a un sur chaque ligne, les colonnes restent alignées.
QUALITY_ICONS = {
    "POOR": "⚫", "COMMON": "⚪", "UNCOMMON": "🟢", "RARE": "🔵", "EPIC": "🟣", "LEGENDARY": "🟠",
    "ARTIFACT": "🟡", "HEIRLOOM": "🟡",
}
EMPTY_SLOT_ICON = "➖"
QUALITY_LEGEND = "⚪ commun · 🟢 inhabituel · 🔵 rare · 🟣 épique · 🟠 légendaire"


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _table(rows: list[tuple[str, ...]], align_right: tuple[int, ...] = ()) -> str:
    """Tableau aligné dans un bloc de code (Discord n'affiche pas les tableaux Markdown « | »)."""
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = [c.rjust(w) if i in align_right else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))]
        lines.append("  ".join(cells).rstrip())
    return "```\n" + "\n".join(lines) + "\n```"


def _slot_table(items_by_slot: dict[str, dict[str, Any]], slots: tuple[tuple[str, str], ...], width: int) -> str:
    rows = []
    for slot_type, label in slots:
        item = items_by_slot.get(slot_type)
        if item is None:
            rows.append((EMPTY_SLOT_ICON, label, "—", ""))
            continue
        icon = QUALITY_ICONS.get((item.get("quality") or {}).get("type"), "⚪")
        ilvl = (item.get("level") or {}).get("value")
        rows.append((icon, label, _cut(item.get("name", "?"), width), str(ilvl) if ilvl is not None else ""))
    return _table(rows, align_right=(3,))


def build_armory_embed(sheet: ArmorySheet, owners: list[int]) -> discord.Embed:
    p = sheet.profile
    faction = sheet.label("faction")
    lines = [
        f"Niveau **{sheet.level}** · {sheet.label('character_class') or '?'} {sheet.label('race') or ''}"
        + (f" · {faction}" if faction else ""),
    ]
    if p.get("guild"):
        lines.append(f"Guilde : **{p['guild'].get('name')}**")
    spec = sheet.active_spec
    if spec:
        lines.append(f"Spé : **{spec[0]}** ({spec[1]} pts)")
    if p.get("equipped_item_level") is not None:
        lines.append(f"Item level : **{p.get('equipped_item_level')}**")
    if owners:
        lines.append("Joueur : " + ", ".join(f"<@{uid}>" for uid in owners))

    embed = discord.Embed(
        title=sheet.full_name or "?",
        description="\n".join(lines),
        color=CLASS_COLORS.get(sheet.class_key or "", 0x3498DB),
    )

    s = sheet.statistics
    if s:
        power_type = (s.get("power_type") or {}).get("name") or "Ressource"
        rows = [
            ("Vie", _fmt(_num(s.get("health"))), power_type, _fmt(_num(s.get("power")))),
            ("Force", _fmt(_num(s.get("strength"))), "Agilité", _fmt(_num(s.get("agility")))),
            ("Intelligence", _fmt(_num(s.get("intellect"))), "Endurance", _fmt(_num(s.get("stamina")))),
            ("Esprit", _fmt(_num(s.get("spirit"))), "Armure", _fmt(_num(s.get("armor")))),
            ("Crit mêlée", _fmt(_num(s.get("melee_crit")), True), "Crit sorts", _fmt(_num(s.get("spell_crit")), True)),
            ("Crit distance", _fmt(_num(s.get("ranged_crit")), True), "Esquive", _fmt(_num(s.get("dodge")), True)),
            ("Puiss. attaque", _fmt(_num(s.get("attack_power"))), "Puiss. sorts", _fmt(_num(s.get("spell_power")))),
        ]
        embed.add_field(name="📊 Stats", value=_table(rows, align_right=(1, 3)), inline=False)

    skills = sheet.profession_skills()
    if skills:
        rows = [("Métier", "Niveau")] + [
            (profession_label(k), f"{skill}/{maxi}" if maxi else str(skill)) for k, (skill, maxi) in skills.items()
        ]
        embed.add_field(name="⚒️ Métiers", value=_table(rows, align_right=(1,)), inline=False)

    items = (sheet.equipment or {}).get("equipped_items", [])
    if items:
        by_slot = {(i.get("slot") or {}).get("type"): i for i in items}
        embed.add_field(name="🛡️ Équipement", value=_slot_table(by_slot, LEFT_SLOTS, ITEM_NAME_WIDTH), inline=True)
        embed.add_field(name="​", value=_slot_table(by_slot, RIGHT_SLOTS, ITEM_NAME_WIDTH), inline=True)
        embed.add_field(name="⚔️ Armes", value=_slot_table(by_slot, WEAPON_SLOTS, 32), inline=False)

    footer = "Armurerie Blizzard · mise à jour à chaque déconnexion du perso"
    embed.set_footer(text=f"{QUALITY_LEGEND}\n{footer}" if items else footer)
    return embed


def recipe_messages(field_pages: list[list[Field]], title: str) -> list[list[discord.Embed]]:
    """Regroupe les fiches (≤ 25 champs chacune) en messages : jusqu'à 10 fiches et 6000 caractères par message.

    Titre sur la première fiche du message, numéro de page sur la dernière.
    """
    groups: list[list[list[Field]]] = []
    current: list[list[Field]] = []
    size = 0
    for fields in field_pages:
        chars = sum(len(f.name) + len(f.value) for f in fields)
        if current and (size + chars > RECIPE_MESSAGE_CHARS or len(current) >= 10):
            groups.append(current)
            current, size = [], 0
        current.append(fields)
        size += chars
    if current:
        groups.append(current)

    messages = []
    for n, group in enumerate(groups, 1):
        embeds = []
        for i, fields in enumerate(group):
            embed = discord.Embed(title=title if i == 0 else None, color=0x3498DB)
            for f in fields:
                embed.add_field(name=f.name, value=f.value, inline=f.inline)
            embeds.append(embed)
        embeds[-1].set_footer(
            text=f"Page {n}/{len(groups)} · 👥 = persos du serveur qui la connaissent · armurerie Blizzard"
        )
        messages.append(embeds)
    return messages


def profession_url(site: str, profession: str, search: str | None = None) -> str:
    """Page d'un métier sur le site, avec la recherche pré-remplie."""
    url = f"{site}/metier/{profession}"
    return url + (f"?q={quote(search.strip())}" if search and search.strip() else "")


class RecipePagesView(discord.ui.View):
    """Boutons ◀ ▶ pour feuilleter les pages de recettes (actifs une heure).

    Une page = un message pouvant contenir plusieurs fiches (embeds).
    """

    def __init__(self, pages: list[list[discord.Embed]]):
        super().__init__(timeout=3600)
        self.pages = pages
        self.index = 0
        self.message: discord.Message | None = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1

    async def _show(self, interaction: discord.Interaction, delta: int) -> None:
        self.index = max(0, min(len(self.pages) - 1, self.index + delta))
        self._sync_buttons()
        await interaction.response.edit_message(embeds=self.pages[self.index], view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, -1)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show(interaction, +1)

    async def on_timeout(self) -> None:
        # Après une heure, on retire les boutons (la page affichée reste lisible).
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class ArmoryCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.client: ArmoryClient | None = None
        self._last_refresh: dict[int, float] = {}
        self._talents_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.client is not None

    async def cog_load(self) -> None:
        cfg = self.bot.config
        if not (cfg.blizzard_client_id and cfg.blizzard_client_secret):
            log.info("Armurerie désactivée (BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET non renseignés)")
            return
        self.client = ArmoryClient(
            self.bot.http_session, cfg.blizzard_client_id, cfg.blizzard_client_secret, cfg.blizzard_region
        )
        self.daily_sync.start()

    async def cog_unload(self) -> None:
        self.daily_sync.cancel()

    # ================================================================== synchro

    def apply(self, character: Character, sheet: ArmorySheet) -> SyncResult:
        """Enregistre ce que l'armurerie nous apprend sur un perso déclaré."""
        result = SyncResult(found=True, sheet=sheet)
        self.db.set_armory_look(character.id, sheet.level, sheet.avatar_url, sheet.render_url, sheet.talents)
        skills = sheet.profession_skills()
        if skills is not None:
            self.db.replace_professions(character.id, {k: skill for k, (skill, _) in skills.items()})
            result.professions_synced = True
        known = sheet.known_recipes()
        if known is not None:
            self.db.replace_character_recipes(character.id, known)
        if sheet.class_key and sheet.class_key != character.wow_class:
            result.warnings.append(
                f"L'armurerie indique **{class_label(sheet.class_key)}**, tu as déclaré "
                f"{class_label(character.wow_class)}. Corrige avec `/modifier perso` si besoin."
            )
        if sheet.race_key and sheet.race_key != character.race:
            result.warnings.append(
                f"L'armurerie indique **{race_label(sheet.race_key)}**, tu as déclaré "
                f"{race_label(character.race)}. Corrige avec `/modifier perso` si besoin."
            )
        return result

    async def fetch(self, name: str, max_age: float = CACHE_SECONDS) -> tuple[ArmorySheet | None, bool | None]:
        """(fiche, trouvé ?) — trouvé vaut None si l'armurerie est désactivée ou injoignable."""
        if self.client is None:
            return None, None
        try:
            return await self.client.sheet(name, max_age=max_age), True
        except ArmoryError as exc:
            if exc.status == 404:
                return None, False
            log.warning("Armurerie : %s", exc)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Armurerie injoignable : %s", exc)
        return None, None

    async def sync(self, character: Character, max_age: float = CACHE_SECONDS) -> SyncResult | None:
        """Cherche le perso dans l'armurerie et synchronise ses métiers. None si armurerie désactivée."""
        if self.client is None:
            return None
        sheet, found = await self.fetch(character.name, max_age=max_age)
        if sheet is None:
            return SyncResult(found=found)
        return self.apply(character, sheet)

    async def refresh(
        self, interaction: discord.Interaction, characters: list[Character], title: str, cooldown: bool
    ) -> None:
        """/modifier armurerie et /admin modifier armurerie : resynchronise des persos sans cache."""
        if self.client is None:
            await interaction.response.send_message(
                "L'armurerie n'est pas activée sur ce bot (clés Blizzard non configurées).", ephemeral=True
            )
            return
        if not characters:
            await interaction.response.send_message("Aucun perso à mettre à jour.", ephemeral=True)
            return
        if cooldown:
            now = time.monotonic()
            last = self._last_refresh.get(interaction.user.id, 0.0)
            if now - last < REFRESH_COOLDOWN_SECONDS:
                wait = int(REFRESH_COOLDOWN_SECONDS - (now - last)) + 1
                await interaction.response.send_message(
                    f"⏳ Doucement : réessaie dans {wait} s (une mise à jour par minute).", ephemeral=True
                )
                return
            self._last_refresh[interaction.user.id] = now

        await interaction.response.defer(ephemeral=True, thinking=True)
        lines = []
        for character in characters:
            result = await self.sync(character, max_age=0)
            if result is None or result.found is None:
                lines.append(f"⚠️ **{character.name}** : armurerie injoignable, réessaie plus tard")
            elif not result.found:
                lines.append(f"🔎 **{character.name}** : pas trouvé (niveau < 10, pas déconnecté depuis, ou faute de nom ?)")
            else:
                sheet = result.sheet
                assert sheet is not None
                professions = len(sheet.profession_skills() or {})
                recipes = sum(len(v) for v in (sheet.known_recipes() or {}).values())
                lines.append(
                    f"✅ **{character.name}** : niveau {sheet.level} · {professions} métier(s) · {recipes} recette(s)"
                    + "".join(f"\n  ⚠️ {w}" for w in result.warnings)
                )
            await asyncio.sleep(REFRESH_PAUSE_SECONDS)
        await self.fetch_recipe_details(self.db.recipes_missing_details())

        description = "\n".join(lines)
        if len(description) > 4000:
            description = description[:3990] + "\n…"
        embed = discord.Embed(title=title, description=description, color=0x3498DB)
        embed.set_footer(text="L'armurerie se met à jour à la déconnexion du perso, parfois avec du retard.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tasks.loop(hours=24)
    async def daily_sync(self) -> None:
        await self.fetch_talent_trees()
        characters = self.db.all_characters()
        found = 0
        for character in characters:
            try:
                result = await self.sync(character, max_age=0)
                found += bool(result and result.found)
            except Exception:
                log.exception("Synchro armurerie impossible pour %s", character.name)
            await asyncio.sleep(SYNC_PAUSE_SECONDS)
        log.info("Synchro armurerie : %d/%d perso(s) trouvé(s)", found, len(characters))
        fetched = await self.fetch_recipe_details(self.db.recipes_missing_details())
        if fetched:
            log.info("Synchro armurerie : composants de %d nouvelle(s) recette(s) récupérés", fetched)

    async def fetch_recipe_details(self, recipe_ids: list[int]) -> int:
        """Récupère nom français, composants et objet fabriqué (stats, effets) des recettes, une seule fois par
        recette. Renvoie le nombre obtenu."""
        if self.client is None or not recipe_ids:
            return 0
        client = self.client
        semaphore = asyncio.Semaphore(RECIPE_FETCH_CONCURRENCY)
        done = 0

        async def one(recipe_id: int) -> None:
            nonlocal done
            async with semaphore:
                try:
                    details = parse_recipe(await client.recipe(recipe_id))
                except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    log.warning("Recette %s : %s", recipe_id, exc)
                    return
                item_info = None
                if details.crafted_item_id:
                    try:
                        item_info = parse_item(await client.item(details.crafted_item_id))
                    except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        log.info("Objet %s (recette %s) : %s", details.crafted_item_id, recipe_id, exc)
            self.db.set_recipe_details(
                recipe_id, details.name, details.reagents, details.crafted_item_id, details.crafted_quantity,
                details.description, item_info,
            )
            done += 1

        await asyncio.gather(*(one(rid) for rid in recipe_ids))
        return done

    async def fetch_talent_trees(self, force: bool = False) -> int:
        """Arbres de talents et leurs icônes, pour le site. Ne refait rien s'ils ont moins d'une semaine."""
        if self.client is None:
            return 0
        age = self.db.talent_trees_age()
        if not force and age is not None and age < TALENT_TREES_MAX_AGE:
            return 0
        async with self._talents_lock:
            client = self.client
            semaphore = asyncio.Semaphore(RECIPE_FETCH_CONCURRENCY)

            async def guarded(coro):
                async with semaphore:
                    try:
                        result = await coro
                        await asyncio.sleep(TALENT_FETCH_PAUSE)  # quelques centaines d'icônes : sans se presser
                        return result
                    except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        log.info("Talents : %s", exc)
                        return None

            index = await guarded(client.talent_tree_index())
            if not index:
                return 0
            pairs = parse_talent_index(index)
            raw = await asyncio.gather(*(guarded(client.talent_tree(t, s)) for t, s in pairs))
            trees = [parse_talent_tree(d) for d in raw if d]
            spells = {n["spell"] for t in trees for n in t["nodes"] if n["spell"]}
            spell_ids = sorted(spells)
            icons = dict(zip(spell_ids, await asyncio.gather(*(guarded(client.icon("spell", s)) for s in spell_ids))))
            spec_icons = await asyncio.gather(
                *(guarded(client.icon("playable-specialization", t["spec_id"])) for t in trees)
            )
            for tree, spec_icon in zip(trees, spec_icons):
                tree["icon"] = spec_icon
                for node in tree["nodes"]:
                    node["icon"] = icons.get(node["spell"])
            if trees:
                self.db.replace_talent_trees(trees)
                log.info("Talents : %d arbre(s), %d icône(s)", len(trees), sum(1 for v in icons.values() if v))
            return len(trees)

    @daily_sync.before_loop
    async def _before_daily_sync(self) -> None:
        await self.bot.wait_until_ready()

    # ============================================================ fiche en MP

    async def show(self, interaction: discord.Interaction, perso: str) -> None:
        if self.client is None:
            await interaction.response.send_message(
                "L'armurerie n'est pas activée sur ce bot (clés Blizzard non configurées).", ephemeral=True
            )
            return
        name = perso.strip()
        if name.isdigit():  # valeur venant de l'autocomplétion
            character = self.db.get_character(int(name))
            name = character.name if character else name

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            sheet = await self.client.sheet(name)
        except ArmoryError as exc:
            if exc.status == 404:
                text = f"🔎 **{name}** introuvable dans l'armurerie.\n{NOT_FOUND_HELP}"
            else:
                log.warning("Armurerie : %s", exc)
                text = "⚠️ L'armurerie ne répond pas correctement pour l'instant, réessaie plus tard."
            await interaction.followup.send(text, ephemeral=True)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await interaction.followup.send("⚠️ L'armurerie est injoignable pour l'instant.", ephemeral=True)
            return

        # Au passage, on met à jour les métiers des persos déclarés sous ce nom.
        declared = self.db.characters_named(sheet.full_name or name)
        for character in declared:
            self.apply(character, sheet)

        embed = build_armory_embed(sheet, sorted({c.user_id for c in declared}))
        try:
            await interaction.user.send(embed=embed)
        except discord.HTTPException:
            await interaction.followup.send(
                "Je n'ai pas pu t'envoyer de MP (ils sont peut-être fermés), la voici ici :", embed=embed, ephemeral=True
            )
            return
        await interaction.followup.send(f"📬 Fiche de **{sheet.full_name or name}** envoyée en MP.", ephemeral=True)

    # ============================================================ recettes en MP

    async def show_recipes(self, interaction: discord.Interaction, profession: str, search: str | None) -> None:
        label = profession_label(profession)
        if self.client is None:
            await interaction.response.send_message(
                "L'armurerie n'est pas activée sur ce bot (clés Blizzard non configurées).", ephemeral=True
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser sur le serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        # Composants des recettes jamais vues : récupérés une fois pour toutes. Tous métiers, car une
        # sous-recette peut venir d'un autre métier (ex. : barres du Minage pour la Forge).
        await self.fetch_recipe_details(self.db.recipes_missing_details())

        known = self.db.guild_recipes(interaction.guild.id, profession)
        if not known:
            await interaction.followup.send(
                f"Aucun perso du serveur n'a de recette de **{label}** dans l'armurerie. Seuls les persos "
                "trouvés dans l'armurerie (niveau 10 ou plus) sont pris en compte.",
                ephemeral=True,
            )
            return
        matched = filter_recipes(known, search)
        if not matched:
            # Rien à envoyer : réponse privée dans le salon, pas de MP.
            await interaction.followup.send(
                f"Aucune recette de **{label}** ne contient « {search} » "
                f"({len(known)} recette(s) connue(s) sur le serveur).",
                ephemeral=True,
            )
            return

        site = getattr(self.bot.config, "web_url", "")
        if site:
            # Le site montre tout (composants, infobulles, artisans) : un lien plutôt qu'un pavé en MP.
            url = profession_url(site, profession, search)
            what = f"{len(matched)} recette(s) de **{label}**" + (f" contenant « {search} »" if search else "")
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label=f"Voir les recettes de {label}", emoji="🌐", url=url))
            await interaction.followup.send(f"⚒️ {what} : composants, effets et artisans sur le site.", view=view, ephemeral=True)
            return

        title = f"⚒️ {label} — {len(matched)} recette(s)" + (f" · « {search} »" if search else "")
        crafted_by = crafted_by_map(self.db.guild_recipes(interaction.guild.id))
        pages = recipe_messages(build_pages(matched, crafted_by), title)
        view = RecipePagesView(pages) if len(pages) > 1 else None
        extra = {"view": view} if view else {}

        try:
            message = await interaction.user.send(embeds=pages[0], **extra)
        except discord.HTTPException:
            message = await interaction.followup.send(
                "Je n'ai pas pu t'envoyer de MP (ils sont peut-être fermés), les voici ici :",
                embeds=pages[0], ephemeral=True, wait=True, **extra,
            )
            if view:
                view.message = message
            return
        if view:
            view.message = message
        pages_text = f" ({len(pages)} pages)" if len(pages) > 1 else ""
        await interaction.followup.send(
            f"📬 {len(matched)} recette(s) de **{label}** envoyée(s) en MP{pages_text}.", ephemeral=True
        )

    def character_choices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Tes persos d'abord, puis ceux des autres joueurs du serveur. Un nom libre reste possible."""
        q = current.lower()
        mine = self.db.get_characters(interaction.user.id)
        others = self.db.guild_characters(interaction.guild.id) if interaction.guild else []
        seen: set[int] = set()
        choices = []
        for c in [*mine, *others]:
            if c.id in seen or q not in c.name.lower():
                continue
            seen.add(c.id)
            choices.append(app_commands.Choice(name=f"{c.name} — {class_label(c.wow_class)}"[:100], value=c.name))
        return choices[:25]


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(ArmoryCog(bot))
