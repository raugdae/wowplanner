"""Rentabilité des métiers d'un perso, d'après les prix de l'hôtel des ventes (page « Rentabilité » du site).

- Métiers de fabrication : pour chaque recette connue, ce que rapporte l'objet vendu à l'HdV (prix le plus bas,
  commission de 5 % déduite), face au coût des composants (prix le plus bas de l'HdV, ou prix du marchand pour ceux
  que les marchands vendent : fioles, fils, teintures…), et face à la revente directe au marchand.
- Métiers de récolte (herboristerie, minage, dépeçage, pêche) : ce que valent les ressources récoltables à son niveau.

Blizzard donne un prix d'achat « marchand » pour presque tous les objets, même ceux qu'aucun marchand ne vend : seuls
les composants de VENDOR_REAGENTS sont comptés au prix du marchand. Niveaux de récolte : ceux de Classic, que Forever
reprend pour ces ressources (les ressources propres à Forever apparaissent avec un niveau « ? »).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AH_CUT = 0.05  # commission de l'hôtel des ventes sur une vente

# Composants vendus par les marchands (prix d'achat marchand).
VENDOR_REAGENTS = frozenset({
    3371, 3372, 8925, 18256,  # fioles : vide, plombée, de cristal, imprégnée
    2320, 2321, 4291, 8343, 14341,  # fils : grossier, fin, de soie, de soie épais, runique
    2324, 2325, 2604, 2605, 4340, 4341, 4342, 6260, 6261, 10290,  # décolorant et teintures
    2880, 3466, 3857,  # flux faible, flux puissant, charbon
    4289, 2678, 2692, 3713, 159, 1179,  # sel, épices douces / fortes / apaisantes, eau de source, lait glacé
    6217, 4470,  # bâtonnet en cuivre (enchantement), bois simple
})

# Niveau de métier pour récolter (herbes, minerais, pierres) ou fabriquer les barres (fonte).
HERB_SKILL = {
    2447: 1, 765: 1, 2449: 15, 785: 50, 2452: 50, 2450: 70, 3820: 85, 2453: 100, 3355: 115, 3369: 120, 3356: 125,
    3357: 150, 3818: 160, 3821: 170, 3358: 185, 3819: 195, 4625: 205, 8831: 210, 8153: 210, 8836: 220, 8838: 230,
    8839: 235, 8845: 245, 8846: 250, 13464: 260, 13463: 270, 13465: 280, 13466: 285, 13467: 290, 13468: 300,
}
MINING_SKILL = {
    2770: 1, 2835: 1, 2840: 1, 2771: 65, 2836: 65, 3576: 65, 2841: 65, 2775: 75, 2842: 75, 2772: 125, 2838: 125,
    3575: 125, 2776: 155, 3577: 155, 3859: 165, 3858: 175, 7912: 175, 3860: 175, 7911: 230, 6037: 230, 11370: 230,
    11371: 230, 10620: 245, 12365: 245, 12359: 250,
}
SKINNING_SKILL = {
    2934: 1, 2318: 1, 783: 1, 2319: 100, 4232: 100, 4234: 150, 4235: 150, 4304: 200, 8169: 200, 8170: 250, 8171: 250,
}

# Métier de récolte → (sous-type « Artisanat » des ressources, niveaux connus, libellé).
GATHERING: dict[str, tuple[int, dict[int, int], str]] = {
    "herboristerie": (9, HERB_SKILL, "Herbes"),
    "minage": (7, MINING_SKILL, "Minerais, pierres et barres"),
    "depecage": (6, SKINNING_SKILL, "Cuirs et peaux"),
    "peche": (8, {}, "Poissons et viandes (le niveau de pêche n'est pas connu par ressource)"),
}


@dataclass
class ReagentCost:
    quantity: int
    name: str
    item_id: int | None
    unit: int | None  # prix à l'unité (pc), None si inconnu
    source: str | None  # "hdv" | "marchand" | None

    @property
    def total(self) -> int | None:
        return None if self.unit is None else self.unit * self.quantity


@dataclass
class RecipeProfit:
    recipe_id: int
    name: str
    product_id: int
    product: Any  # ligne du catalogue (ah_items_map), None si inconnu
    crafted_quantity: float
    revenue: int | None  # vente à l'HdV, commission déduite
    vendor_value: int | None  # revente au marchand
    cost: int  # composants dont le prix est connu
    missing: int  # composants sans prix
    reagents: list[ReagentCost] = field(default_factory=list)

    @property
    def profit(self) -> int | None:
        if self.revenue is None or self.missing:
            return None
        return self.revenue - self.cost

    @property
    def margin(self) -> float | None:
        profit = self.profit
        return None if profit is None or not self.cost else profit / self.cost * 100

    @property
    def available(self) -> int | None:
        return self.product["quantity"] if self.product is not None else None


def reagent_price(item_id: int | None, items: dict[int, Any]) -> tuple[int | None, str | None]:
    """(prix à l'unité, source) d'un composant : marchand s'il en vend, sinon prix le plus bas de l'HdV."""
    row = items.get(item_id) if item_id is not None else None
    if row is None:
        return None, None
    if item_id in VENDOR_REAGENTS and row["purchase_price"]:
        return -(-row["purchase_price"] // max(row["purchase_quantity"] or 1, 1)), "marchand"
    if row["min_price"]:
        return row["min_price"], "hdv"
    return None, None


def recipe_profits(recipes: list, items: dict[int, Any]) -> tuple[list[RecipeProfit], int]:
    """Rentabilité des recettes (db.GuildRecipe) qui fabriquent un objet, la plus rentable d'abord.
    Renvoie aussi le nombre de recettes sans objet (enchantements…), qui ne se vendent pas à l'HdV."""
    results, without_item = [], 0
    for recipe in recipes:
        if not recipe.crafted_item_id:
            without_item += 1
            continue
        product = items.get(recipe.crafted_item_id)
        qty = recipe.crafted_quantity or 1.0
        revenue = vendor = None
        if product is not None and product["min_price"]:
            revenue = int(product["min_price"] * qty * (1 - AH_CUT))
        if product is not None and product["sell_price"]:
            vendor = int(product["sell_price"] * qty)
        reagents = []
        for quantity, name, item_id in recipe.reagents or []:
            unit, source = reagent_price(item_id, items)
            reagents.append(ReagentCost(quantity, name, item_id, unit, source))
        known = [r.total for r in reagents if r.total is not None]
        missing = len(reagents) - len(known) + (1 if recipe.reagents is None else 0)
        results.append(RecipeProfit(
            recipe.id, recipe.name, recipe.crafted_item_id, product, qty, revenue, vendor, sum(known), missing, reagents,
        ))
    results.sort(key=lambda r: (r.profit is None, -(r.profit or 0), -(r.revenue or 0)))
    return results, without_item


def gathering_rows(rows: list, skills: dict[int, int], skill: int | None) -> list[tuple[Any, int | None, bool]]:
    """Ressources en vente (ah_tradeskill_on_sale) → [(ligne, niveau requis, récoltable maintenant)], les récoltables
    d'abord, puis par prix décroissant. Un niveau inconnu compte comme récoltable."""
    result = []
    for row in rows:
        required = skills.get(row["item_id"])
        reachable = required is None or skill is None or required <= skill
        result.append((row, required, reachable))
    result.sort(key=lambda r: (not r[2], -(r[0]["min_price"] or 0)))
    return result
