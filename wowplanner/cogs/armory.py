"""Armurerie WoW Forever : synchro des persos (métiers, recettes, équipement, talents) pour le site.

Ce module fait les appels ; c'est cogs/sync.py qui les lance (synchro de nuit et /admin sync).

Facultatif : sans BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET, tout ceci est désactivé et le
reste du bot marche normalement. L'API n'étant pas officielle pour Forever, chaque appel
peut échouer : on dégrade toujours en douceur (message d'info, jamais d'erreur bloquante).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import aiohttp
from discord.ext import commands

from ..armory import (
    CACHE_SECONDS, ArmoryClient, ArmoryError, ArmorySheet, parse_item, parse_recipe, parse_talent_index,
    parse_talent_tree,
)
from ..db import Character
from ..gear import parse_equipment, parse_stats
from ..gamedata import class_label, race_label

if TYPE_CHECKING:
    from ..bot import WowPlannerBot

log = logging.getLogger(__name__)

# Pause entre deux persos pendant la synchro complète (on reste très loin des quotas Blizzard).
SYNC_PAUSE_SECONDS = 1.0
# Requêtes simultanées pour récupérer les composants des recettes.
RECIPE_FETCH_CONCURRENCY = 5
# Arbres de talents (données de jeu) : redemandés chaque semaine, au cas où un patch les change.
TALENT_TREES_MAX_AGE = 7 * 24 * 3600
TALENT_FETCH_PAUSE = 0.1

NOT_FOUND_HELP_SHORT = "il faut être niveau 10 et s'être déconnecté depuis"
NOT_FOUND_HELP = (
    "L'armurerie ne connaît que les persos **niveau 10 ou plus**, et seulement **après une déconnexion** "
    "(parfois avec quelques heures de retard). Vérifie aussi l'orthographe du nom (prénom et nom)."
)
FIX_HINT = "Si c'est une erreur, supprime le perso et recrée-le."
# Persos ajoutés depuis Discord et toujours introuvables : retirés par la synchro de nuit (voir cogs/sync.py).
PURGE_GRACE_DAYS = 2
PURGE_WARNING = (
    f"S'il n'est toujours pas dans l'armurerie dans {PURGE_GRACE_DAYS} jours, il sera retiré automatiquement."
)


@dataclass
class SyncResult:
    found: bool | None  # None : armurerie injoignable, on ne sait pas
    sheet: ArmorySheet | None = None
    professions_synced: bool = False
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Une ou deux lignes à ajouter au message de /ajouter perso."""
        if self.found is None:
            return "🔎 Armurerie injoignable pour l'instant, je réessaierai plus tard."
        if not self.found:
            return f"🔎 Pas (encore) trouvé dans l'armurerie. {NOT_FOUND_HELP}\n⚠️ {PURGE_WARNING}"
        sheet = self.sheet
        assert sheet is not None
        text = f"🔎 Trouvé dans l'armurerie : niveau {sheet.level}"
        if self.professions_synced:
            text += ", métiers synchronisés"
        return text + "." + "".join(f"\n⚠️ {w}" for w in self.warnings)


@dataclass
class FullSyncReport:
    """Bilan d'une synchro complète des persos (utilisé par /admin sync)."""
    characters: int = 0
    found: int = 0
    not_found: int = 0
    unreachable: int = 0
    # Persos que l'armurerie dit ne pas connaître (404), pour le nettoyage de nuit.
    missing: list[Character] = field(default_factory=list)


class ArmoryCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self.client: ArmoryClient | None = None
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

    # ================================================================== synchro

    def apply(self, character: Character, sheet: ArmorySheet) -> SyncResult:
        """Enregistre ce que l'armurerie nous apprend sur un perso déclaré."""
        result = SyncResult(found=True, sheet=sheet)
        self.db.set_armory_look(
            character.id, sheet.level, sheet.avatar_url, sheet.render_url, sheet.talents,
            parse_stats(sheet.statistics), parse_equipment(sheet.equipment),
        )
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
                f"{class_label(character.wow_class)}. {FIX_HINT}"
            )
        if sheet.race_key and sheet.race_key != character.race:
            result.warnings.append(
                f"L'armurerie indique **{race_label(sheet.race_key)}**, tu as déclaré "
                f"{race_label(character.race)}. {FIX_HINT}"
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
        result = self.apply(character, sheet)
        await self.fetch_item_icons({i["id"] for i in parse_equipment(sheet.equipment) or []})
        return result

    async def fetch_item_icons(self, item_ids: set[int]) -> None:
        """Icônes des objets portés pas encore connues (une seule demande par objet, jamais redemandée)."""
        if self.client is None:
            return
        missing = sorted(i for i in item_ids if isinstance(i, int) and i not in self.db.item_icons(item_ids))
        if not missing:
            return
        client = self.client
        semaphore = asyncio.Semaphore(RECIPE_FETCH_CONCURRENCY)

        async def one(item_id: int) -> tuple[int, str | None] | None:
            async with semaphore:
                try:
                    return item_id, await client.icon("item", item_id)
                except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    log.info("Icône de l'objet %s : %s", item_id, exc)
                    return None

        found = [r for r in await asyncio.gather(*(one(i) for i in missing)) if r]
        if found:
            self.db.set_item_icons(dict(found))

    async def sync_all(self) -> FullSyncReport:
        """Resynchronise tous les persos déclarés, sans cache (synchro de nuit et /admin sync)."""
        characters = self.db.all_characters()
        report = FullSyncReport(characters=len(characters))
        for character in characters:
            try:
                result = await self.sync(character, max_age=0)
            except Exception:
                log.exception("Synchro armurerie impossible pour %s", character.name)
                result = None
            if result is None or result.found is None:
                report.unreachable += 1
            elif result.found:
                report.found += 1
            else:
                report.not_found += 1
                report.missing.append(character)
            await asyncio.sleep(SYNC_PAUSE_SECONDS)
        return report

    async def lookup(self, name: str) -> tuple[ArmorySheet | None, bool | None]:
        """Fiche seule (une requête, sans cache) : le perso existe-t-il ? Pour la vérification au fil de la frappe
        sur le site. (fiche, trouvé ?) — trouvé vaut None si l'armurerie est désactivée ou injoignable."""
        if self.client is None:
            return None, None
        try:
            return ArmorySheet(await self.client.character(name)), True
        except ArmoryError as exc:
            if exc.status == 404:
                return None, False
            log.warning("Armurerie : %s", exc)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Armurerie injoignable : %s", exc)
        return None, None

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


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(ArmoryCog(bot))
