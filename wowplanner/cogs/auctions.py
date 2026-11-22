"""Hôtel des ventes : relève les prix de l'hôtel des ventes AUCTION_HOUSE_ID pour la page du site.

- Toutes les 20 minutes, on demande les deux listes de Blizzard (objets uniques et ressources, ~1 Mo chacune) ;
  si elles ont changé depuis le dernier relevé (Blizzard les met à jour environ toutes les heures), on enregistre un
  relevé par objet (voir auctions.aggregate). Si l'API ne répond pas, le site garde les derniers prix connus.
- Base locale des objets : tout le catalogue de Forever (noms, types, qualité, prix chez le marchand) récupéré par la
  recherche d'objets de l'API (1000 objets par requête), puis complété objet par objet pour les nouveautés.
- Icônes : demandées petit à petit (une requête par objet), les plus vendus d'abord.
- Ventes estimées : à chaque nouveau relevé, comparaison des annonces avec le relevé précédent (gardé en mémoire et
  dans data/ah_listing.bin, relu au redémarrage : un redémarrage ne fait pas perdre d'heure). Voir
  auctions.estimate_sales.
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
from ..auctions import (
    HOURLY_DAYS, KEEP_DAYS, SALES_MAX_GAP, ListingState, aggregate, estimate_sales, listing_state, load_listing,
    parse_item_detail, parse_search_item, save_listing,
)

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .armory import ArmoryCog

log = logging.getLogger(__name__)

POLL_MINUTES = 20
# Catalogue complet des objets : relu chaque semaine (nouveaux objets des patchs).
CATALOG_MAX_AGE = 7 * 24 * 3600
CATALOG_MAX_PAGES = 200  # garde-fou : 200 000 objets
# Contenu du catalogue ; un nouveau numéro fait tout relire au prochain relevé. 2 : prix d'achat marchand.
CATALOG_VERSION = "2"
# Par relevé : objets inconnus demandés un par un, et icônes.
UNKNOWN_PER_RUN = 100
ICONS_PER_RUN = 300
COMPACT_EVERY = 24 * 3600


class AuctionCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db
        self._lock = asyncio.Lock()
        self._listing: ListingState | None = None  # annonces du dernier relevé, pour estimer les ventes
        # Objets en vente que Blizzard ne connaît pas (404) : plus redemandés jusqu'au prochain démarrage.
        self._not_found: set[int] = set()
        data_dir = getattr(bot.config, "data_dir", None)
        self._listing_path = data_dir / "ah_listing.bin" if data_dir else None
        if self._listing_path is not None:
            self._listing = load_listing(self._listing_path)

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
        fresh = not (items_date and goods_date and self.db.get_setting("ah_data_version") == key)
        if not fresh and self._listing is not None:
            return "pas de nouvelles données"
        auctions = [*(items.get("auctions") or []), *(goods.get("auctions") or [])]
        sales = await self._estimate_sales(listing_state(auctions, stamp)) if auctions else ""
        if not fresh:  # premier passage après un redémarrage : sert de point de départ aux ventes
            return "pas de nouvelles données"
        points = aggregate(auctions)
        if not points:
            log.warning("Hôtel des ventes %s : aucune annonce reçue, derniers prix gardés", house)
            return "aucune annonce reçue, derniers prix gardés"
        ts = int(stamp) // 3600 * 3600  # un relevé par heure au plus
        self.db.store_ah_snapshot(ts, points)
        self.db.set_setting("ah_data_version", key)
        log.info("Hôtel des ventes %s : %d objets relevés%s", house, len(points), sales)
        return f"{len(points)} objets relevés{sales}"

    async def _estimate_sales(self, state: ListingState) -> str:
        """Ventes depuis le relevé précédent, rangées dans l'heure du milieu de l'intervalle."""
        before, self._listing = self._listing, state
        if self._listing_path is not None and (before is None or state.ts != before.ts):
            try:
                await asyncio.to_thread(save_listing, state, self._listing_path)
            except OSError as exc:
                log.warning("Relevé de l'hôtel des ventes non enregistré : %s", exc)
        if before is None or not 0 < state.ts - before.ts <= SALES_MAX_GAP:
            return ""
        sold = estimate_sales(before, state)
        self.db.store_ah_sales(int((before.ts + state.ts) / 2) // 3600 * 3600, sold)
        return f", {sum(sold.values())} ventes estimées"

    async def _catalog(self, client) -> None:
        """Catalogue complet des objets de Forever, une fois au départ puis chaque semaine."""
        last = float(self.db.get_setting("ah_catalog_at") or 0)
        current = self.db.get_setting("ah_catalog_version") == CATALOG_VERSION
        if current and self.db.ah_item_count() and time.time() - last < CATALOG_MAX_AGE:
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
        self.db.set_setting("ah_catalog_version", CATALOG_VERSION)
        log.info("Catalogue des objets de Forever : %d objets", total)

    async def _unknown_items(self, client) -> None:
        """Objets en vente absents du catalogue (ajoutés depuis la dernière lecture), demandés un par un."""
        candidates = self.db.ah_unknown_items(UNKNOWN_PER_RUN + len(self._not_found))
        missing = [i for i in candidates if i not in self._not_found][:UNKNOWN_PER_RUN]
        records = []
        for item_id in missing:
            try:
                record = parse_item_detail(await client.item(item_id))
            except (ArmoryError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if isinstance(exc, ArmoryError) and exc.status == 404:
                    self._not_found.add(item_id)
                # Niveau debug : ces objets inconnus noyaient les logs (à remettre en info au besoin).
                log.debug("Objet %s : %s", item_id, exc)
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
        self.db.compact_ah_sales(now, HOURLY_DAYS, KEEP_DAYS)
        self.db.set_setting("ah_compact_at", str(now))


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(AuctionCog(bot))
