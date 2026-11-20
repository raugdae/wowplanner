"""Hôtel des ventes de WoW Forever : agrégation des annonces, prix, base locale des objets (sans Discord ni web).

Chaque relecture (toutes les heures environ chez Blizzard) donne, par objet : le prix le plus bas, le prix médian
(pondéré par la quantité en vente), la quantité disponible et le nombre d'annonces. Ces relevés sont gardés heure
par heure pendant 7 jours, puis un par jour pendant 90 jours (voir Database.compact_auction_prices).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .recipes import normalize

# Historique : un relevé par heure pendant 7 jours, puis un par jour, effacé après 90 jours.
HOURLY_DAYS = 7
KEEP_DAYS = 90


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
        bool(data.get("is_stackable")),
    )


def parse_item_detail(data: dict[str, Any]) -> ItemRecord | None:
    """/data/wow/item/{id} (noms déjà dans la langue demandée) → ItemRecord : objets absents de la recherche."""
    return parse_search_item(data)
