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

# Ressources sans nœud à elles : obtenues parfois en bonus en récoltant autre chose (chance de loot).
BONUS_LOOT: dict[int, str] = {
    2452: "en cueillant du Mage royal ou de l'Églantine",  # Chardonnier
    8153: "en cueillant certaines herbes de haut niveau",  # Vignesang
    774: "en minant certains filons", 818: "en minant certains filons", 1210: "en minant certains filons",
    1705: "en minant certains filons", 1206: "en minant certains filons", 1529: "en minant certains filons",
    7909: "en minant certains filons", 3864: "en minant certains filons", 7910: "en minant certains filons",
    12361: "en minant certains filons", 12799: "en minant certains filons", 12364: "en minant certains filons",
    12800: "en minant certains filons", 11382: "en minant du sombrefer",  # gemmes, Sang de la montagne
}

# Métier de récolte → (sous-type « Artisanat » des ressources, niveaux connus, libellé).
GATHERING: dict[str, tuple[int, dict[int, int], str]] = {
    "herboristerie": (9, HERB_SKILL, "Herbes"),
    "minage": (7, MINING_SKILL, "Minerais, pierres et barres"),
    "depecage": (6, SKINNING_SKILL, "Cuirs et peaux"),
    "peche": (8, {}, "Poissons et viandes"),
}


def gather_requirement(item_id: int) -> tuple[str, int] | None:
    """(métier de récolte, niveau requis) d'une ressource connue, sinon None."""
    for profession, (_, skills, _) in GATHERING.items():
        if item_id in skills:
            return profession, skills[item_id]
    return None


def out_of_reach(item_id: int, professions: dict[str, int | None]) -> bool:
    """Ressource que le perso ne peut pas récolter lui-même : métier absent, ou niveau trop bas. Une ressource
    inconnue des tables (ou un niveau de métier inconnu) n'est jamais « hors compétence »."""
    requirement = gather_requirement(item_id)
    if requirement is None:
        return False
    profession, level = requirement
    if profession not in professions:
        return True
    skill = professions[profession]
    return skill is not None and level > skill


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


@dataclass(frozen=True)
class GatheredValue:
    """Ce que rapporte une ressource récoltée (rien à payer : la comparaison se fait avec le marchand)."""
    net: int | None  # vente à l'HdV, commission déduite
    vendor: int | None  # revente au marchand

    @property
    def gain(self) -> int | None:
        """Ce que l'HdV rapporte de plus que le marchand (négatif : mieux vaut vendre au marchand)."""
        return None if self.net is None else self.net - (self.vendor or 0)

    @property
    def margin(self) -> float | None:
        gain = self.gain
        return None if gain is None or not self.vendor else gain / self.vendor * 100


def gathered_value(row: Any) -> GatheredValue:
    net = int(row["min_price"] * (1 - AH_CUT)) if row["min_price"] else None
    return GatheredValue(net, row["sell_price"] or None)


# ===================================================================== calculatrice


def raw_unit(row: Any) -> int:
    """Meilleure vente « brute » d'un objet, à l'unité : HdV (commission déduite) ou marchand. 0 si aucun prix."""
    if row is None:
        return 0
    net = int(row["min_price"] * (1 - AH_CUT)) if row["min_price"] else 0
    return max(net, row["sell_price"] or 0)


def best_channel(row: Any) -> str | None:
    """Où l'objet se vend le mieux : « hdv » (commission déduite) ou « marchand » ; None sans aucun prix."""
    if row is None or raw_unit(row) == 0:
        return None
    net = int(row["min_price"] * (1 - AH_CUT)) if row["min_price"] else 0
    return "hdv" if net >= (row["sell_price"] or 0) else "marchand"


@dataclass
class CraftStep:
    """Fabriquer `crafts` fois une recette avec son stock : ce que ça rapporte face à la vente brute du stock utilisé."""
    recipe_id: int
    name: str
    product_id: int
    product: Any
    crafts: int
    product_value: int  # vente des objets fabriqués (meilleure vente : HdV net ou marchand)
    buy_cost: int  # composants achetés au marchand (fioles…)
    used_value: int  # ce qu'aurait rapporté la vente brute du stock utilisé

    @property
    def channel(self) -> str | None:
        """Où vendre les objets fabriqués : « hdv » ou « marchand » (voir best_channel)."""
        return best_channel(self.product)

    @property
    def gain(self) -> int:
        return self.product_value - self.buy_cost - self.used_value


@dataclass
class CraftPlan:
    raw_total: int  # tout le stock vendu brut
    steps: list[CraftStep]  # plan conseillé (recettes rentables, la plus rentable d'abord)
    leftovers: dict[int, int]  # stock restant après le plan, vendu brut
    leftover_value: int
    options: list[CraftStep]  # chaque recette seule, avec tout le stock
    unpriced: set[int]  # objets du stock sans aucun prix (comptés à 0)

    @property
    def total(self) -> int:
        return sum(s.product_value - s.buy_cost for s in self.steps) + self.leftover_value

    @property
    def gain(self) -> int:
        return self.total - self.raw_total


def _recipe_needs(recipe: Any) -> tuple[dict[int, int], dict[int, int]] | None:
    """(stock nécessaire par fabrication, achats au marchand par fabrication), None si un composant est inconnu."""
    stock: dict[int, int] = {}
    bought: dict[int, int] = {}
    if recipe.reagents is None:
        return None
    for quantity, _, item_id in recipe.reagents:
        if not isinstance(item_id, int):
            return None
        target = bought if item_id in VENDOR_REAGENTS else stock
        target[item_id] = target.get(item_id, 0) + quantity
    return stock, bought


def _step(recipe: Any, crafts: int, stock: dict[int, int], bought: dict[int, int], items: dict[int, Any]) -> CraftStep:
    product = items.get(recipe.crafted_item_id)
    product_value = int(raw_unit(product) * (recipe.crafted_quantity or 1.0) * crafts)
    buy_cost = sum((reagent_price(i, items)[0] or 0) * q for i, q in bought.items()) * crafts
    used_value = sum(raw_unit(items.get(i)) * q for i, q in stock.items()) * crafts
    return CraftStep(recipe.id, recipe.name, recipe.crafted_item_id, product, crafts, product_value, buy_cost,
                     used_value)


def craft_plan(inventory: dict[int, int], recipes: list, items: dict[int, Any]) -> CraftPlan:
    """Que faire de son stock : tout vendre brut, ou fabriquer ? Plan glouton : la recette qui rapporte le plus par
    fabrication d'abord, autant de fois que le stock le permet, puis la suivante ; le reste est vendu brut.
    Les composants vendus par les marchands sont achetés, les autres doivent être dans le stock."""
    inventory = {i: q for i, q in inventory.items() if q > 0}
    raw_total = sum(raw_unit(items.get(i)) * q for i, q in inventory.items())
    unpriced = {i for i in inventory if raw_unit(items.get(i)) == 0}

    usable = []
    for recipe in recipes:
        product = items.get(recipe.crafted_item_id) if recipe.crafted_item_id else None
        needs = _recipe_needs(recipe)
        if product is None or needs is None or raw_unit(product) == 0 or not needs[0]:
            continue
        stock, bought = needs
        alone = min(inventory.get(i, 0) // q for i, q in stock.items())
        if alone > 0:
            usable.append((recipe, stock, bought, _step(recipe, 1, stock, bought, items).gain, alone))

    options = sorted(
        (_step(r, alone, stock, bought, items) for r, stock, bought, _, alone in usable), key=lambda s: -s.gain
    )
    left = dict(inventory)
    steps = []
    for recipe, stock, bought, per_craft, _ in sorted(usable, key=lambda u: -u[3]):
        if per_craft <= 0:
            break
        crafts = min(left.get(i, 0) // q for i, q in stock.items())
        if crafts <= 0:
            continue
        for i, q in stock.items():
            left[i] -= q * crafts
        steps.append(_step(recipe, crafts, stock, bought, items))
    leftovers = {i: q for i, q in left.items() if q > 0}
    leftover_value = sum(raw_unit(items.get(i)) * q for i, q in leftovers.items())
    return CraftPlan(raw_total, steps, leftovers, leftover_value, options, unpriced)


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
