"""Hôtel des ventes : relève les prix de l'hôtel des ventes AUCTION_HOUSE_ID pour la page du site.

- Toutes les 20 minutes, on demande les deux listes de Blizzard (objets uniques et ressources, ~1 Mo chacune) ;
  si elles ont changé depuis le dernier relevé (Blizzard les met à jour environ toutes les heures), on enregistre un
  relevé par objet (voir auctions.aggregate). Si l'API ne répond pas, le site garde les derniers prix connus.
- Base locale des objets : tout le catalogue de Forever (noms, types, qualité, prix chez le marchand) récupéré par la
  recherche d'objets de l'API (1000 objets par requête), puis complété objet par objet pour les nouveautés.
- Icônes : demandées petit à petit (une requête par objet), les plus vendus d'abord.
- Une fois par jour : l'historique au-delà de 7 jours est réduit à un relevé par jour, et effacé après 90 jours.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import aiohttp
from discord.ext import commands, tasks

from ..armory import ArmoryError
from ..auctions import HOURLY_DAYS, KEEP_DAYS, aggregate, parse_item_detail, parse_search_item

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .armory import ArmoryCog

log = logging.getLogger(__name__)

POLL_MINUTES = 20
# Catalogue complet des objets : relu chaque semaine (nouveaux objets des patchs).
CATALOG_MAX_AGE = 7 * 24 * 3600
CATALOG_MAX_PAGES = 200  # garde-fou : 200 000 objets
# Par relevé : objets inconnus demandés un par un, et icônes.
UNKNOWN_PER_RUN = 100
ICONS_PER_RUN = 300
COMPACT_EVERY = 24 * 3600


class AuctionCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self._lock = asyncio.Lock()

    @property
    def armory(self) -> ArmoryCog | None:
        cog = self.bot.get_cog("ArmoryCog")
        return cog if cog is not None and cog.available else None  # type: ignore[return-value]

    @property
    def enabled(self) -> bool:
        return bool(self.bot.config.auction_house_id)

    async def cog_load(self) -> None:
        if self.enabled:
            self.poll.start()
        else:
            log.info("Hôtel des ventes désactivé (AUCTION_HOUSE_ID non renseigné)")

    async def cog_unload(self) -> None:
        self.poll.cancel()

    @tasks.loop(minutes=POLL_MINUTES)
    async def poll(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            try:
                await self.refresh()
            except Exception:
                log.exception("Hôtel des ventes : relevé en échec")

    @poll.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    # ================================================================ relevé

    async def refresh(self) -> str:
        """Un passage complet ; renvoie un bilan d'une ligne (pour les logs et l'administration)."""
        armory = self.armory
        if armory is None or armory.client is None:
            return "armurerie non configurée (clés Blizzard absentes)"
        client = armory.client
        cfg = self.bot.config
        text = await self._snapshot(client, cfg.auction_ruleset, cfg.auction_house_id)
        await self._catalog(client)
        await self._unknown_items(client)
        icons = self.db.ah_missing_icons(ICONS_PER_RUN)
        if icons:
            await armory.fetch_item_icons(set(icons))
        self._compact()
        return text

    async def _snapshot(self, client, ruleset: int, house: int) -> str:
        try:
            items, items_date = await client.auctions(ruleset, house, commodities=False)
            goods, goods_date = await client.auctions(ruleset, house, commodities=True)
        except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Hôtel des ventes injoignable : %s (on garde les derniers prix)", exc)
            return "injoignable, derniers prix gardés"
        dates = [d for d in (items_date, goods_date) if d]
        stamp = max(dates) if dates else time.time()  # date des données chez Blizzard
        key = f"{int(items_date or 0)}:{int(goods_date or 0)}"
        if items_date and goods_date and self.db.get_setting("ah_data_version") == key:
            return "pas de nouvelles données"
        points = aggregate([*(items.get("auctions") or []), *(goods.get("auctions") or [])])
        if not points:
            log.warning("Hôtel des ventes %s : aucune annonce reçue, derniers prix gardés", house)
            return "aucune annonce reçue, derniers prix gardés"
        ts = int(stamp) // 3600 * 3600  # un relevé par heure au plus
        self.db.store_ah_snapshot(ts, points)
        self.db.set_setting("ah_data_version", key)
        log.info("Hôtel des ventes %s : %d objets relevés", house, len(points))
        return f"{len(points)} objets relevés"

    async def _catalog(self, client) -> None:
        """Catalogue complet des objets de Forever, une fois au départ puis chaque semaine."""
        last = float(self.db.get_setting("ah_catalog_at") or 0)
        if self.db.ah_item_count() and time.time() - last < CATALOG_MAX_AGE:
            return
        from_id, total = 1, 0
        for _ in range(CATALOG_MAX_PAGES):
            try:
                page = await client.search_items(from_id)
            except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.warning("Catalogue des objets interrompu à l'objet %s : %s", from_id, exc)
                return  # repris au prochain relevé
            records = [r for r in (parse_search_item(d, client.locale) for d in page) if r]
            self.db.upsert_ah_items(records)
            total += len(records)
            ids = [d.get("id") for d in page if isinstance(d.get("id"), int)]
            if len(page) < 1000 or not ids:
                break
            from_id = max(ids) + 1
            await asyncio.sleep(0.2)
        self.db.set_setting("ah_catalog_at", str(int(time.time())))
        log.info("Catalogue des objets de Forever : %d objets", total)

    async def _unknown_items(self, client) -> None:
        """Objets en vente absents du catalogue (ajoutés depuis la dernière lecture), demandés un par un."""
        missing = self.db.ah_unknown_items(UNKNOWN_PER_RUN)
        records = []
        for item_id in missing:
            try:
                record = parse_item_detail(await client.item(item_id))
            except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.info("Objet %s : %s", item_id, exc)
                continue
            if record:
                records.append(record)
            await asyncio.sleep(0.05)
        if records:
            self.db.upsert_ah_items(records)

    def _compact(self) -> None:
        last = float(self.db.get_setting("ah_compact_at") or 0)
        now = int(time.time())
        if now - last < COMPACT_EVERY:
            return
        self.db.compact_ah_prices(now, HOURLY_DAYS, KEEP_DAYS)
        self.db.set_setting("ah_compact_at", str(now))


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(AuctionCog(bot))
