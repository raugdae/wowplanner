"""Hôtel des ventes de WoW Forever : agrégation des annonces, prix, base locale des objets (sans Discord ni web).

Chaque relecture (toutes les heures environ chez Blizzard) donne, par objet : le prix le plus bas, le prix médian
(pondéré par la quantité en vente), la quantité disponible et le nombre d'annonces. Ces relevés sont gardés heure
par heure pendant 7 jours, puis un par jour pendant 90 jours (voir Database.compact_auction_prices).

Ventes estimées : l'API ne donne pas les ventes, mais chaque annonce a un identifiant et un temps restant
(SHORT < 30 min, MEDIUM 30 min à 2 h, LONG 2 à 12 h, VERY_LONG 12 à 48 h). Une annonce LONG ou VERY_LONG qui a disparu
au relevé suivant (moins de 2 h plus tard) n'a pas pu expirer : elle a été achetée (ou, plus rarement, annulée). Les
annonces SHORT et MEDIUM qui disparaissent sont ignorées (expiration possible) : l'estimation est plutôt basse.
"""
from __future__ import annotations

import os
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .recipes import normalize

# Historique : un relevé par heure pendant 7 jours, puis un par jour, effacé après 90 jours.
HOURLY_DAYS = 7
KEEP_DAYS = 90
# Temps restant qui garantit qu'une annonce ne peut pas expirer avant le relevé suivant (au moins 2 h).
SURE_TIME_LEFT = frozenset({"LONG", "VERY_LONG"})
SALES_MAX_GAP = 2 * 3600  # au-delà, des annonces LONG ont pu expirer : pas d'estimation


@dataclass(frozen=True)
class PricePoint:
    min_price: int  # en pièces de cuivre, à l'unité
    median_price: int
    quantity: int
    listings: int


def _weighted_median(prices: list[tuple[int, int]]) -> int:
    """Médiane de (prix, quantité) pondérée par la quantité."""
    prices = sorted(prices)
    total = sum(q for _, q in prices)
    half, seen = total / 2, 0
    for price, quantity in prices:
        seen += quantity
        if seen >= half:
            return price
    return prices[-1][0]


def aggregate(auctions: list[dict[str, Any]]) -> dict[int, PricePoint]:
    """Annonces brutes de l'API (objets uniques : « buyout » ; ressources : « unit_price ») → relevé par objet.
    Les annonces sans prix d'achat immédiat (enchère seule) sont ignorées."""
    by_item: dict[int, list[tuple[int, int]]] = {}
    for a in auctions:
        item_id = (a.get("item") or {}).get("id")
        quantity = a.get("quantity") or 1
        if not isinstance(item_id, int) or not isinstance(quantity, int) or quantity <= 0:
            continue
        unit = a.get("unit_price")
        if not isinstance(unit, int):
            buyout = a.get("buyout")
            if not isinstance(buyout, int) or buyout <= 0:
                continue
            unit = buyout // quantity
        by_item.setdefault(item_id, []).append((unit, quantity))
    return {
        item_id: PricePoint(min(p for p, _ in prices), _weighted_median(prices), sum(q for _, q in prices), len(prices))
        for item_id, prices in by_item.items()
    }


@dataclass(frozen=True)
class ListingState:
    """Annonces d'un relevé, compactes (quelques Mo pour 300 000 annonces), triées par identifiant."""
    ts: float  # date des données chez Blizzard
    ids: array
    items: array
    quantities: array
    sure: bytes  # 1 : l'annonce ne peut pas expirer avant le relevé suivant


def listing_state(auctions: list[dict[str, Any]], ts: float) -> ListingState:
    rows = []
    for a in auctions:
        auction_id, item_id, quantity = a.get("id"), (a.get("item") or {}).get("id"), a.get("quantity") or 1
        if isinstance(auction_id, int) and isinstance(item_id, int) and isinstance(quantity, int) and quantity > 0:
            rows.append((auction_id, item_id, quantity, a.get("time_left") in SURE_TIME_LEFT))
    rows.sort()
    return ListingState(
        ts, array("q", (r[0] for r in rows)), array("i", (r[1] for r in rows)), array("i", (r[2] for r in rows)),
        bytes(r[3] for r in rows),
    )


# Fichier du dernier relevé (data/ah_listing.bin) : en-tête (format, date, nombre d'annonces), puis les colonnes.
_LISTING_HEADER = struct.Struct("<4sdq")
_LISTING_MAGIC = b"AHL1"


def save_listing(state: ListingState, path: Path) -> None:
    """Écrit le relevé (quelques Mo) d'un coup : un fichier à moitié écrit n'est jamais relu."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(_LISTING_HEADER.pack(_LISTING_MAGIC, state.ts, len(state.ids)))
        for column in (state.ids, state.items, state.quantities):
            column.tofile(f)
        f.write(state.sure)
    os.replace(tmp, path)


def load_listing(path: Path) -> ListingState | None:
    """Relevé enregistré par save_listing ; None si absent ou illisible."""
    try:
        with open(path, "rb") as f:
            magic, ts, n = _LISTING_HEADER.unpack(f.read(_LISTING_HEADER.size))
            if magic != _LISTING_MAGIC or n < 0:
                return None
            ids, items, quantities = array("q"), array("i"), array("i")
            for column in (ids, items, quantities):
                column.fromfile(f, n)
            sure = f.read(n)
    except (OSError, EOFError, struct.error):
        return None
    return ListingState(ts, ids, items, quantities, sure) if len(sure) == n else None


def estimate_sales(before: ListingState, after: ListingState) -> dict[int, int]:
    """Quantités vendues par objet entre deux relevés : annonces sûres disparues, et ventes partielles (quantité
    d'une même annonce en baisse)."""
    sold: dict[int, int] = {}
    ids, j, n = after.ids, 0, len(after.ids)
    for i, auction_id in enumerate(before.ids):
        while j < n and ids[j] < auction_id:
            j += 1
        if j < n and ids[j] == auction_id:
            gone = before.quantities[i] - after.quantities[j]
        else:
            gone = before.quantities[i] if before.sure[i] else 0
        if gone > 0:
            item_id = before.items[i]
            sold[item_id] = sold.get(item_id, 0) + gone
    return sold


def money_parts(copper: int) -> tuple[int, int, int]:
    """1234567 → (123, 45, 67) : pièces d'or, d'argent, de cuivre."""
    copper = max(int(copper), 0)
    return copper // 10000, copper // 100 % 100, copper % 100


def money_text(copper: int) -> str:
    """1234567 → « 123 po 45 pa 67 pc » (sans les zéros de tête)."""
    gold, silver, cop = money_parts(copper)
    parts = []
    if gold:
        parts.append(f"{gold:,} po".replace(",", " "))
    if silver:
        parts.append(f"{silver} pa")
    if cop or not parts:
        parts.append(f"{cop} pc")
    return " ".join(parts)


@dataclass(frozen=True)
class ItemRecord:
    """Un objet de la base locale (recherche d'objets de l'API, données statiques de Forever)."""
    id: int
    name: str
    quality: str | None
    class_id: int | None
    class_name: str | None
    subclass_id: int | None
    subclass_name: str | None
    level: int | None
    required_level: int | None
    sell_price: int | None
    stackable: bool
    # Prix d'achat chez un marchand (pour `purchase_quantity` objets). Blizzard le donne aussi pour des objets
    # qu'aucun marchand ne vend : voir profit.VENDOR_REAGENTS.
    purchase_price: int | None = None
    purchase_quantity: int = 1

    @property
    def search(self) -> str:
        return normalize(self.name)


def _localized(value: Any, locale: str) -> str | None:
    if isinstance(value, dict):
        return value.get(locale) or value.get("en_US") or next((v for v in value.values() if isinstance(v, str)), None)
    return value if isinstance(value, str) else None


def parse_search_item(data: dict[str, Any], locale: str = "fr_FR") -> ItemRecord | None:
    """Un résultat de /data/wow/search/item (noms dans toutes les langues) → ItemRecord, None s'il est inutilisable."""
    item_id = data.get("id")
    name = _localized(data.get("name"), locale)
    if not isinstance(item_id, int) or not name:
        return None
    item_class = data.get("item_class") or {}
    subclass = data.get("item_subclass") or {}
    number = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None  # noqa: E731
    return ItemRecord(
        item_id, name, (data.get("quality") or {}).get("type"),
        number(item_class.get("id")), _localized(item_class.get("name"), locale),
        number(subclass.get("id")), _localized(subclass.get("name"), locale),
        number(data.get("level")), number(data.get("required_level")), number(data.get("sell_price")),
        bool(data.get("is_stackable")), number(data.get("purchase_price")), number(data.get("purchase_quantity")) or 1,
    )


def parse_item_detail(data: dict[str, Any]) -> ItemRecord | None:
    """/data/wow/item/{id} (noms déjà dans la langue demandée) → ItemRecord : objets absents de la recherche."""
    return parse_search_item(data)
