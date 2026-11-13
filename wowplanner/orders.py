"""Commandes entre persos : logique sans Discord (recherche, composants, droits sur les commandes).

Seules les recettes débloquées par les persos du serveur (vues dans l'armurerie) peuvent être
commandées, et jamais à ses propres persos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .db import Crafter, GuildRecipe, Order
from .recipes import CraftedBy, filter_recipes, normalize, reagent_lines

MAX_QUANTITY = 100

STATUS_LABELS = {
    "pending": "⏳ En attente de réponse",
    "accepted": "🔨 Acceptée, en préparation",
    "done": "✅ Prête",
    "refused": "❌ Refusée",
    "cancelled": "🚫 Annulée",
}
STATUS_COLORS = {
    "pending": 0xF2C75C, "accepted": 0x3A8EF0, "done": 0x43B581, "refused": 0xE74C3C, "cancelled": 0x7F8C8D,
}


@dataclass(frozen=True)
class Transition:
    who: str  # "crafter" | "requester"
    from_status: tuple[str, ...]
    to_status: str
    label: str
    emoji: str


# Boutons proposés selon l'état de la commande et qui regarde.
TRANSITIONS = {
    "accept": Transition("crafter", ("pending",), "accepted", "Accepter", "👍"),
    "refuse": Transition("crafter", ("pending",), "refused", "Refuser", "✖️"),
    "done": Transition("crafter", ("accepted",), "done", "C'est prêt", "✅"),
    "drop": Transition("crafter", ("accepted",), "refused", "Abandonner", "✖️"),
    "cancel": Transition("requester", ("pending", "accepted"), "cancelled", "Annuler ma commande", "🚫"),
}


def allowed_actions(order: Order, user_id: int) -> list[str]:
    roles = set()
    if user_id == order.crafter_user_id:
        roles.add("crafter")
    if user_id == order.requester_id:
        roles.add("requester")
    return [name for name, t in TRANSITIONS.items() if t.who in roles and order.status in t.from_status]


def parse_quantity(text: str | None) -> int | None:
    """« 5 », «  », « x3 » → 5, 1, 3 ; None si invalide."""
    cleaned = (text or "").strip().lower().lstrip("x×").strip()
    if not cleaned:
        return 1
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if 1 <= value <= MAX_QUANTITY else None


@dataclass
class Candidate:
    recipe: GuildRecipe
    crafters: list[Crafter]  # sans les persos du demandeur


def orderable(
    recipes: list[GuildRecipe], crafters: dict[int, list[Crafter]], requester_id: int
) -> list[Candidate]:
    """Recettes que le demandeur peut commander : connues d'au moins un perso d'un autre joueur."""
    result = []
    for recipe in recipes:
        others = [c for c in crafters.get(recipe.id, []) if c.user_id != requester_id]
        if others:
            result.append(Candidate(recipe, others))
    return result


def search(candidates: list[Candidate], query: str) -> list[Candidate]:
    """Recettes dont le nom contient la recherche ; un nom exact l'emporte sur le reste."""
    by_id = {c.recipe.id: c for c in candidates}
    matched = [by_id[r.id] for r in filter_recipes([c.recipe for c in candidates], query)]
    exact = [c for c in matched if normalize(c.recipe.name) == normalize(query.strip())]
    return exact or matched


def scaled_reagents(recipe: GuildRecipe, quantity: int, crafted_by: CraftedBy) -> str:
    """Composants pour `quantity` objets (sous-recettes dépliées), en texte Discord."""
    if recipe.reagents is None:
        return "❔ composants inconnus pour l'instant"
    if not recipe.reagents:
        return "aucun composant"
    crafts = math.ceil(quantity / (recipe.crafted_quantity or 1))
    scaled = [(qty * crafts, name, item_id) for qty, name, item_id in recipe.reagents]
    return "\n".join(reagent_lines(scaled, crafted_by, seen=frozenset({recipe.id})))[:1000]
